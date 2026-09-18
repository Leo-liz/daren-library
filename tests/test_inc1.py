from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from db import UNPERIODIZED_DATE, UNPERIODIZED_SOURCE, connect
from importer import HEADERS, import_xlsx, read_xlsx_rows
from metrics import recompute_metrics
from web import (
    _list_rows,
    export_creator_csv,
    load_creator_profile,
    render_creator_detail,
    render_creator_list,
    render_dashboard,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class Inc1DataFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary_directory.name) / "test.db"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _connection(self):
        return connect(self.db_path)

    def test_ac01_all_valid_rows_import_and_special_values_parse(self) -> None:
        cases = (
            ("creator", "creator_good.xlsx", "raw_creator", 2, 0),
            ("video", "video_good.xlsx", "raw_video", 3, 1),
            ("live", "live_good.xlsx", "raw_live", 2, 1),
        )
        for source_type, filename, table, expected_rows, header_position in cases:
            source_rows = read_xlsx_rows(FIXTURES / filename)
            nonblank_source_rows = [
                row for _, row in source_rows[header_position + 1:]
                if any(value not in (None, "") for value in row)
            ]
            self.assertEqual(expected_rows, len(nonblank_source_rows))
            result = import_xlsx(self.db_path, FIXTURES / filename, source_type)
            self.assertEqual(expected_rows, result.accepted_rows)
            self.assertEqual(0, result.overwritten_rows)
            self.assertEqual(0, result.rejected_rows)
            self.assertEqual(
                result.total_rows,
                result.accepted_rows + result.overwritten_rows + result.rejected_rows,
            )
            with self._connection() as connection:
                self.assertEqual(expected_rows, connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        with self._connection() as connection:
            creator = connection.execute(
                "SELECT * FROM raw_creator WHERE creator_key='username:lananh.vn'"
            ).fetchone()
            self.assertEqual(1_000_000, creator["alliance_gmv_vnd"])
            self.assertEqual(200_000, creator["estimated_commission_vnd"])
            self.assertIsNone(creator["public_gmv_vnd"])
            self.assertAlmostEqual(0.125, creator["click_rate"])
            self.assertIn("lananh.vn", creator["raw_json"])
            live = connection.execute(
                "SELECT * FROM raw_live WHERE started_at='2026/08/15/ 20:00'"
            ).fetchone()
            self.assertAlmostEqual(0.025, live["conversion_rate"])
            self.assertIn("Lan Anh 蓝安", live["raw_json"])

    def test_ac01_duplicate_import_overwrites_and_records_latest_batch(self) -> None:
        first = import_xlsx(self.db_path, FIXTURES / "creator_good.xlsx", "creator")
        second = import_xlsx(self.db_path, FIXTURES / "creator_good.xlsx", "creator")
        self.assertNotEqual(first.batch_id, second.batch_id)
        self.assertEqual(0, first.overwritten_rows)
        self.assertEqual(0, second.accepted_rows)
        self.assertEqual(2, second.overwritten_rows)
        self.assertEqual(2, second.to_dict()["overwritten_rows"])
        self.assertEqual(
            second.total_rows,
            second.accepted_rows + second.overwritten_rows + second.rejected_rows,
        )
        with self._connection() as connection:
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM raw_creator").fetchone()[0])
            self.assertEqual(
                {second.batch_id},
                {row[0] for row in connection.execute("SELECT DISTINCT import_batch_id FROM raw_creator")},
            )
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0])

    def test_ac01_cross_day_duplicate_import_uses_one_stable_period_and_latest_batch(self) -> None:
        first_time = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)
        second_time = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)
        with patch("importer.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = first_time
            first = import_xlsx(self.db_path, FIXTURES / "creator_good.xlsx", "creator")
        with self._connection() as connection:
            first_rating = dict(connection.execute(
                "SELECT grade, score, evidence_json FROM ratings WHERE creator_key='username:lananh.vn'"
            ).fetchone())

        with patch("importer.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = second_time
            second = import_xlsx(self.db_path, FIXTURES / "creator_good.xlsx", "creator")

        self.assertNotEqual(first.batch_id, second.batch_id)
        self.assertEqual(0, second.accepted_rows)
        self.assertEqual(2, second.overwritten_rows)
        with self._connection() as connection:
            periods = connection.execute(
                "SELECT * FROM raw_creator_periods WHERE creator_key='username:lananh.vn'"
            ).fetchall()
            self.assertEqual(1, len(periods))
            self.assertEqual(
                (UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE),
                (periods[0]["period_start"], periods[0]["period_end"], periods[0]["period_source"]),
            )
            self.assertEqual(second.batch_id, periods[0]["import_batch_id"])
            batches = connection.execute(
                "SELECT batch_id, imported_at FROM import_batches WHERE source_type='creator' ORDER BY imported_at"
            ).fetchall()
            self.assertEqual(
                [(first.batch_id, first_time.isoformat()), (second.batch_id, second_time.isoformat())],
                [(row["batch_id"], row["imported_at"]) for row in batches],
            )
            metrics = {
                row["metric_name"]: row
                for row in connection.execute(
                    "SELECT * FROM metrics WHERE creator_key='username:lananh.vn'"
                ).fetchall()
            }
            expected_dashboard_total = connection.execute(
                "SELECT SUM(alliance_gmv_vnd) FROM raw_creator_periods"
            ).fetchone()[0]

        self.assertEqual(1_000_000, metrics["historical_gmv"]["metric_value"])
        self.assertEqual(25, metrics["sold_items"]["metric_value"])
        self.assertEqual([second.batch_id], json.loads(metrics["historical_gmv"]["source_batches"]))
        total_row = next(
            row for row in _list_rows(self.db_path, {"period": ["total"]})
            if row["creator_key"] == "username:lananh.vn"
        )
        self.assertEqual(1_000_000, total_row["historical_gmv"])
        self.assertEqual(25, total_row["sold_items"])
        self.assertIn(f"{expected_dashboard_total:,} ₫", render_dashboard(
            self.db_path, {"period": ["total"], "grain": ["total"]}
        ))

        with self._connection() as connection:
            second_rating = dict(connection.execute(
                "SELECT grade, score, evidence_json FROM ratings WHERE creator_key='username:lananh.vn'"
            ).fetchone())
        self.assertEqual((first_rating["grade"], first_rating["score"]),
                         (second_rating["grade"], second_rating["score"]))
        evidence_values = {
            item["metric"]: item["value"]
            for item in json.loads(second_rating["evidence_json"])["participating_metrics"]
        }
        self.assertEqual(1_000_000, evidence_values["historical_gmv"])
        self.assertEqual(25, evidence_values["sold_items"])

    def test_ac03_detail_list_and_export_use_spec_metric_names(self) -> None:
        import_xlsx(self.db_path, FIXTURES / "creator_good.xlsx", "creator")
        profile = load_creator_profile(self.db_path, "username:lananh.vn")
        self.assertIsNotNone(profile)
        assert profile is not None
        detail = render_creator_detail(profile)
        self.assertIn("历史 GMV（达人总 GMV（联盟））", detail)
        self.assertIn('<span class="label">历史出单件数</span>', detail)

        creator_list = render_creator_list(self.db_path, {})
        self.assertIn("<th>历史 GMV</th><th>历史出单件数</th>", creator_list)
        csv_header = export_creator_csv(self.db_path, {}).decode("utf-8-sig").splitlines()[0]
        self.assertEqual("达人,达人ID,评级,标签,备注,历史 GMV（VND）,历史出单件数", csv_header)

    def test_live_composite_key_keeps_sessions_and_duplicate_import_overwrites(self) -> None:
        first = import_xlsx(self.db_path, FIXTURES / "live_good.xlsx", "live")
        self.assertEqual(2, first.accepted_rows)
        self.assertEqual(0, first.overwritten_rows)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT source_record_key, creator_key, started_at FROM raw_live ORDER BY event_at_utc7"
            ).fetchall()
            self.assertEqual(2, len(rows))
            self.assertEqual({"username:lananh.vn"}, {row["creator_key"] for row in rows})
            self.assertEqual(
                ["2026/08/15/ 20:00", "2026-08-16 19:30"],
                [row["started_at"] for row in rows],
            )
            self.assertEqual(
                [
                    '["username:lananh.vn","2026/08/15/ 20:00"]',
                    '["username:lananh.vn","2026-08-16 19:30"]',
                ],
                [row["source_record_key"] for row in rows],
            )

        second = import_xlsx(self.db_path, FIXTURES / "live_good.xlsx", "live")
        self.assertEqual(0, second.accepted_rows)
        self.assertEqual(2, second.overwritten_rows)
        with self._connection() as connection:
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM raw_live").fetchone()[0])
            self.assertEqual(
                {second.batch_id},
                {row[0] for row in connection.execute("SELECT DISTINCT import_batch_id FROM raw_live")},
            )

    def test_ac02_bad_rows_are_isolated_with_excel_row_and_reason(self) -> None:
        result = import_xlsx(self.db_path, FIXTURES / "creator_bad_rows.xlsx", "creator")
        self.assertEqual(3, result.total_rows)
        self.assertEqual(1, result.accepted_rows)
        self.assertEqual(2, result.rejected_rows)
        self.assertEqual([3, 4], [error.row_number for error in result.errors])
        self.assertIn("主键缺失", result.errors[0].reason)
        self.assertIn("数值非法", result.errors[1].reason)
        with self._connection() as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM raw_creator").fetchone()[0])

    def test_ac04_metrics_match_manual_calculation_and_keep_lineage(self) -> None:
        creator_batch = import_xlsx(self.db_path, FIXTURES / "creator_good.xlsx", "creator").batch_id
        video_batch = import_xlsx(self.db_path, FIXTURES / "video_good.xlsx", "video").batch_id
        live_batch = import_xlsx(self.db_path, FIXTURES / "live_good.xlsx", "live").batch_id
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO costs(platform, creator_key, quote_vnd, collaboration_cost_vnd, updated_at)
                VALUES ('tiktok_shop_vn', 'username:lananh.vn', NULL, 100000, '2026-09-10T00:00:00Z')
                """
            )
        self.assertEqual(2, recompute_metrics(self.db_path))

        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM metrics WHERE platform='tiktok_shop_vn' AND creator_key='username:lananh.vn'"
            ).fetchall()
            metrics = {row["metric_name"]: row for row in rows}
            self.assertEqual(1_000_000, metrics["historical_gmv"]["metric_value"])
            self.assertEqual(25, metrics["sold_items"]["metric_value"])
            self.assertEqual(750_000, metrics["post_collaboration_gmv"]["metric_value"])
            self.assertEqual(500_000, metrics["video_attributed_gmv"]["metric_value"])
            self.assertEqual(1_000_000, metrics["live_attributed_gmv"]["metric_value"])
            self.assertEqual(2.0, metrics["historical_roi"]["metric_value"])
            self.assertEqual(7.5, metrics["cost_ratio_roi"]["metric_value"])
            self.assertEqual("raw_video", metrics["video_attributed_gmv"]["source_table"])
            self.assertEqual("attributed_gmv_vnd", metrics["video_attributed_gmv"]["source_field"])
            self.assertEqual([video_batch], json.loads(metrics["video_attributed_gmv"]["source_batches"]))
            self.assertEqual([live_batch], json.loads(metrics["live_attributed_gmv"]["source_batches"]))
            self.assertEqual([creator_batch], json.loads(metrics["historical_gmv"]["source_batches"]))

            bob = connection.execute(
                """
                SELECT metric_name, metric_value FROM metrics
                WHERE platform='tiktok_shop_vn' AND creator_key='username:minhanh.vn'
                  AND metric_name IN ('historical_roi', 'cost_ratio_roi')
                ORDER BY metric_name
                """
            ).fetchall()
            self.assertEqual(2, len(bob))
            self.assertTrue(all(row["metric_value"] is None for row in bob))

    def test_import_then_recompute_populates_metrics_and_lineage(self) -> None:
        for source_type in ("creator", "video", "live"):
            import_xlsx(self.db_path, FIXTURES / f"{source_type}_good.xlsx", source_type)
        self.assertGreater(recompute_metrics(self.db_path), 0)

        with self._connection() as connection:
            metrics = connection.execute(
                """
                SELECT source_table, source_field, source_batches
                FROM metrics
                WHERE metric_value IS NOT NULL
                """
            ).fetchall()
        self.assertGreater(len(metrics), 0)
        for metric in metrics:
            self.assertTrue(metric["source_table"])
            self.assertTrue(metric["source_field"])
            self.assertTrue(json.loads(metric["source_batches"]))

    def test_declared_fixture_widths_match_inc1_mapping(self) -> None:
        self.assertEqual(24, len(HEADERS["creator"]))
        self.assertEqual(31, len(HEADERS["video"]))
        self.assertEqual(28, len(HEADERS["live"]))
        self.assertNotIn("直播ID", HEADERS["live"])


if __name__ == "__main__":
    unittest.main()

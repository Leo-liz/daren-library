from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from analytics import (
    aggregate_content,
    assign_tag,
    content_items_with_roi,
    create_tag,
    creator_annotations,
    creator_period_metrics,
    delete_followup,
    delete_tag,
    list_business_periods,
    list_followups,
    product_breakdown,
    rename_tag,
    save_commissions,
    save_followup,
    save_note,
    save_target_cost,
    unassign_tag,
)
from config_admin import config_change_log, update_config
from db import UNPERIODIZED_DATE, UNPERIODIZED_SOURCE, connect
from importer import import_xlsx
from metrics import recompute_metrics
from rating import DEFAULT_CONFIG_PATH
from web import create_server, export_creator_csv, load_creator_profile, render_creator_list


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
CREATOR_KEY = "username:lananh.vn"


class Inc3AnalyticsAndOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.db_path = self.temp_path / "test.db"
        self.config_path = self.temp_path / "rules.json"
        shutil.copyfile(DEFAULT_CONFIG_PATH, self.config_path)
        for source_type in ("creator", "video", "live"):
            import_xlsx(self.db_path, FIXTURES / f"{source_type}_good.xlsx", source_type)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_period_metadata_and_total_consistency(self) -> None:
        with connect(self.db_path) as connection:
            batches = connection.execute(
                "SELECT source_type, period_start, period_end, period_source FROM import_batches"
            ).fetchall()
            creator_batch = next(row for row in batches if row["source_type"] == "creator")
            self.assertEqual(
                (UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE),
                (creator_batch["period_start"], creator_batch["period_end"], creator_batch["period_source"]),
            )
            for source_type in ("video", "live"):
                batch = next(row for row in batches if row["source_type"] == source_type)
                self.assertEqual(("2026-08-01", "2026-08-31", "banner"),
                                 (batch["period_start"], batch["period_end"], batch["period_source"]))
            connection.execute(
                """INSERT INTO import_batches(
                       batch_id, source_type, source_name, platform, imported_at,
                       period_start, period_end, period_source
                   ) VALUES ('synthetic-july', 'creator', 'synthetic.xlsx', 'tiktok_shop_vn',
                             '2026-09-14T00:00:00Z', '2026-07-01', '2026-07-31', 'banner')"""
            )
            connection.execute(
                """INSERT INTO raw_creator_periods(
                       platform, creator_key, period_start, period_end, period_source,
                       alliance_gmv_vnd, alliance_items, estimated_commission_vnd,
                       targeted_gmv_vnd, import_batch_id, updated_at
                   ) VALUES ('tiktok_shop_vn', ?, '2026-07-01', '2026-07-31', 'banner',
                             100000, 4, 10000, 50000, ?, '2026-09-14T00:00:00Z')""",
                (CREATOR_KEY, "synthetic-july"),
            )
        first = creator_period_metrics(self.db_path, CREATOR_KEY, "2026-07-01|2026-07-31")
        periods = list_business_periods(self.db_path, "creator")
        per_period = [creator_period_metrics(self.db_path, CREATOR_KEY, item["token"]) for item in periods]
        total = creator_period_metrics(self.db_path, CREATOR_KEY, "total")
        self.assertEqual(100_000, first["historical_gmv"])
        self.assertEqual(sum(item["historical_gmv"] or 0 for item in per_period), total["historical_gmv"])
        self.assertEqual(sum(item["sold_items"] or 0 for item in per_period), total["sold_items"])

        for source_type in ("video", "live"):
            daily = aggregate_content(self.db_path, source_type, CREATOR_KEY, "day")
            overall = aggregate_content(self.db_path, source_type, CREATOR_KEY, "total")
            self.assertEqual(sum(row["attributed_gmv_vnd"] for row in daily), overall[0]["attributed_gmv_vnd"])
            self.assertTrue(all("+07:00" in row["published_at" if source_type == "video" else "event_at_utc7"]
                                for row in self._content_rows(source_type)))

    def _content_rows(self, source_type: str):
        field = "published_at" if source_type == "video" else "event_at_utc7"
        with connect(self.db_path) as connection:
            return connection.execute(
                f"SELECT {field} FROM raw_{source_type} WHERE creator_key=?", (CREATOR_KEY,)
            ).fetchall()

    def test_product_and_interaction_aggregation_matches_manual_values(self) -> None:
        products = product_breakdown(self.db_path, CREATOR_KEY)
        self.assertEqual(1, len(products))
        self.assertEqual("合成口红A", products[0]["product_name"])
        self.assertEqual(18_000, products[0]["vv"])
        self.assertEqual(500_000, products[0]["attributed_gmv_vnd"])
        self.assertEqual(5, products[0]["attributed_items"])

        video = aggregate_content(self.db_path, "video", CREATOR_KEY, "total")[0]
        self.assertEqual((18_000, 180, 18, 9, 3),
                         tuple(video[key] for key in ("views", "likes", "comments", "shares", "new_followers")))
        live = aggregate_content(self.db_path, "live", CREATOR_KEY, "total")[0]
        self.assertEqual((5_500, 8_000, 75, 30, 1_300),
                         tuple(live[key] for key in ("viewers", "view_count", "comments", "shares", "likes")))
        with connect(self.db_path) as connection:
            self.assertTrue(all(row[0] is None for row in connection.execute("SELECT favorites FROM raw_video")))
            self.assertTrue(all(row[0] is None for row in connection.execute("SELECT favorites FROM raw_live")))

    def test_multilevel_roi_manual_calculation_and_null_semantics(self) -> None:
        recompute_metrics(self.db_path, config_path=self.config_path)
        with connect(self.db_path) as connection:
            before = dict(connection.execute(
                "SELECT metric_name, metric_value FROM metrics WHERE creator_key=? AND metric_name IN ('video_total_roi','live_total_roi')",
                (CREATOR_KEY,),
            ).fetchall())
        self.assertIsNone(before["video_total_roi"])
        self.assertIsNone(before["live_total_roi"])
        self.assertTrue(all(item["roi"] is None for item in content_items_with_roi(
            self.db_path, CREATOR_KEY, "video", self.config_path
        )))

        save_target_cost(self.db_path, CREATOR_KEY, "video", "v-001", 100_000)
        save_target_cost(self.db_path, CREATOR_KEY, "video", "v-002", 100_000)
        with connect(self.db_path) as connection:
            live_ids = [row[0] for row in connection.execute(
                "SELECT source_record_key FROM raw_live WHERE creator_key=? ORDER BY event_at_utc7", (CREATOR_KEY,)
            )]
        save_target_cost(self.db_path, CREATOR_KEY, "live", live_ids[0], 200_000)
        save_target_cost(self.db_path, CREATOR_KEY, "live", live_ids[1], 300_000)
        recompute_metrics(self.db_path, config_path=self.config_path)
        with connect(self.db_path) as connection:
            after = dict(connection.execute(
                "SELECT metric_name, metric_value FROM metrics WHERE creator_key=? AND metric_name IN ('video_total_roi','live_total_roi')",
                (CREATOR_KEY,),
            ).fetchall())
        self.assertEqual(2.5, after["video_total_roi"])
        self.assertEqual(2.0, after["live_total_roi"])
        self.assertEqual([3.0, 2.0], [item["roi"] for item in content_items_with_roi(
            self.db_path, CREATOR_KEY, "video", self.config_path
        )])
        self.assertEqual([2.0, 2.0], [item["roi"] for item in content_items_with_roi(
            self.db_path, CREATOR_KEY, "live", self.config_path
        )])

    def test_followups_tags_notes_and_commissions_crud(self) -> None:
        followup_id = save_followup(self.db_path, CREATOR_KEY, "2026-09-14", "合成BD", "首次沟通", "寄样")
        self.assertEqual("首次沟通", list_followups(self.db_path, CREATOR_KEY)[0]["content"])
        save_followup(self.db_path, CREATOR_KEY, "2026-09-15", "合成BD", "已寄样", "待反馈", followup_id)
        self.assertEqual("已寄样", list_followups(self.db_path, CREATOR_KEY)[0]["content"])
        delete_followup(self.db_path, CREATOR_KEY, followup_id)
        self.assertEqual([], list_followups(self.db_path, CREATOR_KEY))

        tag_id = create_tag(self.db_path, "合成标签")
        rename_tag(self.db_path, tag_id, "合成标签2")
        assign_tag(self.db_path, CREATOR_KEY, tag_id)
        save_note(self.db_path, CREATOR_KEY, "仅用于合成测试")
        annotation = creator_annotations(self.db_path, [CREATOR_KEY])[CREATOR_KEY]
        self.assertIn("合成标签2", annotation["tags"])
        self.assertEqual("仅用于合成测试", annotation["note"])
        unassign_tag(self.db_path, CREATOR_KEY, tag_id)
        delete_tag(self.db_path, tag_id)
        save_note(self.db_path, CREATOR_KEY, "")
        self.assertEqual({"note": "", "tags": ""}, creator_annotations(self.db_path, [CREATOR_KEY])[CREATOR_KEY])

        save_commissions(self.db_path, CREATOR_KEY, "2026-08-01", "2026-08-31", 10_000, 20_000)
        with connect(self.db_path) as connection:
            row = connection.execute("SELECT organic_commission_vnd, paid_commission_vnd FROM commissions").fetchone()
        self.assertEqual((10_000, 20_000), tuple(row))

    def test_config_update_recomputes_and_records_each_changed_key(self) -> None:
        for video_id in ("v-001", "v-002"):
            save_target_cost(self.db_path, CREATOR_KEY, "video", video_id, 100_000)
        recompute_metrics(self.db_path, config_path=self.config_path)
        changes = update_config(self.db_path, self.config_path, {
            "weights.historical_gmv": "0.5",
            "roi_formulas.video_total.multiplier": "2",
            "roi_formulas.video_total.expression": "(Σ视频归因 GMV / Σ视频坑位费) × 2",
        })
        self.assertEqual(3, len(changes))
        with connect(self.db_path) as connection:
            value = connection.execute(
                "SELECT metric_value FROM metrics WHERE creator_key=? AND metric_name='video_total_roi'",
                (CREATOR_KEY,),
            ).fetchone()[0]
        self.assertEqual(5.0, value)
        keys = {row["config_key"] for row in config_change_log(self.db_path)}
        self.assertTrue({item["key"] for item in changes}.issubset(keys))

    def test_list_csv_and_new_routes_include_rating_tags_and_note(self) -> None:
        preset = None
        with connect(self.db_path) as connection:
            preset = connection.execute("SELECT tag_id FROM tags WHERE name='xx计划'").fetchone()[0]
        assign_tag(self.db_path, CREATOR_KEY, preset)
        save_note(self.db_path, CREATOR_KEY, "合成备注")
        html = render_creator_list(self.db_path, {})
        self.assertIn("评级", html)
        self.assertIn("xx计划", html)
        self.assertIn("合成备注", html)
        exported = export_creator_csv(self.db_path, {}).decode("utf-8-sig")
        self.assertIn("评级,标签,备注", exported)
        self.assertIn("xx计划,合成备注", exported)

        server = create_server(self.db_path, self.config_path, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            routes = (
                "/dashboard?grain=day", "/config", "/export.csv",
                "/creator/" + quote(CREATOR_KEY, safe="") + "?grain=week",
                "/compare?" + urlencode({"ids": [CREATOR_KEY, "username:minhanh.vn"]}, doseq=True),
            )
            for route in routes:
                with self.subTest(route=route), urlopen(base + route, timeout=5) as response:
                    self.assertEqual(200, response.status)
            encoded_key = quote(CREATOR_KEY, safe="")
            post_cases = (
                (f"/followup/{encoded_key}", {"action": "save", "followed_at": "2026-09-14", "bd_name": "合成BD", "content": "HTTP跟进"}),
                (f"/annotation/{encoded_key}", {"action": "note", "note": "HTTP备注"}),
                (f"/commission/{encoded_key}", {"period_start": "2026-08-01", "period_end": "2026-08-31", "organic_vnd": "1", "paid_vnd": "2"}),
                (f"/target-cost/{encoded_key}", {"target_type": "video", "target_id": "v-001", "slot_fee_vnd": "100000"}),
            )
            for route, fields in post_cases:
                request = Request(base + route, data=urlencode(fields).encode(), method="POST")
                with self.subTest(route=route), urlopen(request, timeout=5) as response:
                    self.assertEqual(200, response.status)
            body = urlencode({"weights.historical_gmv": "0.55"}).encode()
            request = Request(base + "/config", data=body, method="POST")
            with urlopen(request, timeout=5) as response:
                self.assertEqual(200, response.status)
                self.assertIn("已保存 1 项配置变更并重算", response.read().decode("utf-8"))
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()

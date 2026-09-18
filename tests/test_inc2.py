from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from db import connect, initialize_database
from importer import import_xlsx
from rating import (
    DEFAULT_CONFIG_PATH,
    RatingConfigError,
    ensure_ratings_current,
    load_rating_config,
    recompute_ratings,
)
from web import create_server, load_creator_profile, render_creator_detail, save_cost


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class Inc2RatingAndProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.db_path = self.temp_path / "test.db"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _import_fixture_profiles(self) -> None:
        import_xlsx(self.db_path, FIXTURES / "creator_good.xlsx", "creator")
        import_xlsx(self.db_path, FIXTURES / "video_good.xlsx", "video")
        import_xlsx(self.db_path, FIXTURES / "live_good.xlsx", "live")

    def _write_config(self, config: dict, name: str = "rules.json") -> Path:
        path = self.temp_path / name
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _seed_five_grade_population(self) -> None:
        initialize_database(self.db_path)
        fixture = json.loads((FIXTURES / "rating_profiles.json").read_text(encoding="utf-8"))
        now = "2026-09-11T00:00:00+00:00"
        with connect(self.db_path) as connection:
            for profile in fixture["profiles"]:
                name = profile["name"]
                creator_key = f"username:{name}.example"
                connection.execute(
                    """
                    INSERT INTO creators(platform, creator_key, creator_username, created_at, updated_at)
                    VALUES ('tiktok_shop_vn', ?, ?, ?, ?)
                    """,
                    (creator_key, f"{name}.example", now, now),
                )
                for metric_name in ("historical_gmv", "sold_items", "post_collaboration_gmv"):
                    connection.execute(
                        """
                        INSERT INTO metrics(
                            platform, creator_key, metric_name, metric_value,
                            source_table, source_field, source_batches, computed_at
                        ) VALUES ('tiktok_shop_vn', ?, ?, ?, 'synthetic', 'test', '[]', ?)
                        """,
                        (creator_key, metric_name, profile[metric_name], now),
                    )

    def test_ac03_detail_has_all_core_fields_and_null_pending_labels(self) -> None:
        self._import_fixture_profiles()
        profile = load_creator_profile(self.db_path, "username:lananh.vn")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertIsNone(profile["quote_vnd"])
        self.assertIsNone(profile["metrics"]["historical_roi"])
        self.assertIsNone(profile["metrics"]["cost_ratio_roi"])
        self.assertIsNotNone(profile["rating"], "导入完成后应自动生成评级")

        html = render_creator_detail(profile)
        for label in (
            "内容质量", "历史出单件数", "历史 GMV", "报价", "历史 ROI",
            "合作后 GMV", "费比 ROI", "等级", "规则依据",
        ):
            self.assertIn(label, html)
        self.assertGreaterEqual(html.count("null <small>待补录</small>"), 4)

    def test_ac05_default_rules_produce_all_five_grades_and_evidence(self) -> None:
        self._seed_five_grade_population()
        self.assertEqual(5, recompute_ratings(self.db_path))
        with connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT creator_key, grade, score, evidence_json FROM ratings ORDER BY creator_key"
            ).fetchall()
        grades = {row["grade"] for row in rows}
        self.assertEqual({"S", "A", "B", "C", "D"}, grades)
        gamma = next(row for row in rows if row["creator_key"] == "username:gamma.example")
        self.assertEqual("B", gamma["grade"])
        evidence = json.loads(gamma["evidence_json"])
        self.assertEqual(3, len(evidence["participating_metrics"]))
        self.assertEqual("B", evidence["matched_interval"]["grade"])
        self.assertEqual("暂定", evidence["status"])

    def test_ac05_config_change_triggers_recompute_and_updates_grade_and_evidence(self) -> None:
        self._seed_five_grade_population()
        recompute_ratings(self.db_path)
        with connect(self.db_path) as connection:
            before = connection.execute(
                "SELECT grade, rules_hash, evidence_json FROM ratings WHERE creator_key='username:gamma.example'"
            ).fetchone()

        changed = copy.deepcopy(load_rating_config(DEFAULT_CONFIG_PATH))
        changed["weights"]["historical_gmv"]["value"] = 0
        changed["weights"]["sold_items"]["value"] = 0.5
        changed["weights"]["post_collaboration_gmv"]["value"] = 0.5
        changed["tiers"][0]["min_score"] = 90
        changed["tiers"][1]["max_score"] = 90
        changed["tiers"][1]["min_score"] = 70
        changed["tiers"][2]["max_score"] = 70
        changed["tiers"][2]["min_score"] = 50
        changed["tiers"][3]["max_score"] = 50
        changed["tiers"][3]["min_score"] = 30
        changed["tiers"][4]["max_score"] = 30
        changed_path = self._write_config(changed)

        self.assertTrue(ensure_ratings_current(self.db_path, changed_path))
        self.assertFalse(ensure_ratings_current(self.db_path, changed_path))
        with connect(self.db_path) as connection:
            after = connection.execute(
                "SELECT grade, rules_hash, evidence_json FROM ratings WHERE creator_key='username:gamma.example'"
            ).fetchone()
        self.assertEqual("B", before["grade"])
        self.assertEqual("D", after["grade"])
        self.assertNotEqual(before["rules_hash"], after["rules_hash"])
        before_evidence = json.loads(before["evidence_json"])
        after_evidence = json.loads(after["evidence_json"])
        self.assertNotEqual(before_evidence["matched_interval"], after_evidence["matched_interval"])
        self.assertEqual(
            {"sold_items", "post_collaboration_gmv"},
            {item["metric"] for item in after_evidence["participating_metrics"]},
        )

    def test_ac08_cost_post_changes_roi_from_null_and_recomputes_rating(self) -> None:
        self._import_fixture_profiles()
        creator_key = "username:lananh.vn"
        before = load_creator_profile(self.db_path, creator_key)
        assert before is not None and before["rating"] is not None
        before_rating_time = before["rating"]["computed_at"]

        server = create_server(self.db_path, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            encoded_key = quote(creator_key, safe="")
            base_url = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base_url + "/", timeout=5) as response:
                self.assertEqual(200, response.status)
                self.assertIn("达人列表", response.read().decode("utf-8"))
            with urlopen(base_url + f"/cost/{encoded_key}", timeout=5) as response:
                self.assertEqual(200, response.status)
                self.assertIn("成本与报价补录", response.read().decode("utf-8"))
            with urlopen(base_url + "/recompute", timeout=5) as response:
                self.assertEqual(200, response.status)
                self.assertIn("已重算", response.read().decode("utf-8"))
            detail_url = f"http://127.0.0.1:{server.server_port}/creator/{encoded_key}"
            with urlopen(detail_url, timeout=5) as response:
                self.assertEqual(200, response.status)
                self.assertIn("待补录", response.read().decode("utf-8"))
            body = urlencode({"quote_vnd": "150000", "collaboration_cost_vnd": "100000"}).encode()
            request = Request(
                f"http://127.0.0.1:{server.server_port}/cost/{encoded_key}",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                self.assertEqual(200, response.status)
                returned_html = response.read().decode("utf-8")
                self.assertIn("150,000 ₫", returned_html)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        after = load_creator_profile(self.db_path, creator_key)
        assert after is not None and after["rating"] is not None
        self.assertEqual(150_000, after["quote_vnd"])
        self.assertEqual(100_000, after["collaboration_cost_vnd"])
        self.assertEqual(2.0, after["metrics"]["historical_roi"])
        self.assertEqual(7.5, after["metrics"]["cost_ratio_roi"])
        self.assertNotEqual(before_rating_time, after["rating"]["computed_at"])

    def test_cost_validation_rejects_zero_and_non_integer_collaboration_cost(self) -> None:
        self._import_fixture_profiles()
        for value in ("0", "1.5", "abc", "-1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "合作成本"):
                    save_cost(self.db_path, "username:lananh.vn", "", value)

    def test_illegal_or_missing_rating_config_has_readable_error(self) -> None:
        missing = copy.deepcopy(load_rating_config(DEFAULT_CONFIG_PATH))
        del missing["weights"]
        with self.assertRaisesRegex(RatingConfigError, "缺少字段: weights"):
            load_rating_config(self._write_config(missing, "missing.json"))

        illegal = copy.deepcopy(load_rating_config(DEFAULT_CONFIG_PATH))
        illegal["weights"]["historical_gmv"]["value"] = -1
        with self.assertRaisesRegex(RatingConfigError, "不得为负数"):
            load_rating_config(self._write_config(illegal, "illegal.json"))

        with self.assertRaisesRegex(RatingConfigError, "不存在"):
            load_rating_config(self.temp_path / "does-not-exist.json")


if __name__ == "__main__":
    unittest.main()

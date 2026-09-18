from __future__ import annotations

import csv
import io
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from adapters import DataAdapter, ShopeeAdapter, TikTokManualImportAdapter
from analytics import assign_tag, list_business_periods, save_note
from calculator import CalculatorInput, PLACEHOLDER_MESSAGE, calculate
from db import connect
from importer import import_xlsx
from metrics import enqueue_recompute, queued_recompute_creators, recompute_incremental
from rating import DEFAULT_CONFIG_PATH
from web import (
    _list_rows,
    create_server,
    export_creator_csv,
    render_calculator_page,
    render_compare,
    render_creator_list,
    render_dashboard,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class Inc4DiscoveryDashboardAndInterfacesTests(unittest.TestCase):
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

    def test_ac06_search_filter_sort_compare_and_csv_match_display_rows(self) -> None:
        creator_key = "username:lananh.vn"
        with connect(self.db_path) as connection:
            grade = connection.execute(
                "SELECT grade FROM ratings WHERE creator_key=?", (creator_key,)
            ).fetchone()[0]
            tag_id = connection.execute("SELECT tag_id FROM tags WHERE name='xx计划'").fetchone()[0]
        assign_tag(self.db_path, creator_key, tag_id)
        save_note(self.db_path, creator_key, "合成 Việt 备注")

        search_rows = _list_rows(self.db_path, {"q": ["lananh"], "period": ["total"]})
        self.assertEqual([creator_key], [row["creator_key"] for row in search_rows])
        grade_rows = _list_rows(self.db_path, {"grade": [grade], "period": ["total"]})
        self.assertIn(creator_key, {row["creator_key"] for row in grade_rows})
        ranged = _list_rows(self.db_path, {
            "period": ["total"], "gmv_min": ["900000"], "gmv_max": ["1100000"],
        })
        self.assertEqual([creator_key], [row["creator_key"] for row in ranged])
        descending = _list_rows(self.db_path, {"period": ["total"], "sort": ["items_desc"]})
        ascending = _list_rows(self.db_path, {"period": ["total"], "sort": ["items_asc"]})
        self.assertEqual(list(reversed([row["creator_key"] for row in descending])),
                         [row["creator_key"] for row in ascending])

        query = {"q": ["lananh"], "period": ["total"], "sort": ["gmv_desc"]}
        html = render_creator_list(self.db_path, query)
        payload = export_creator_csv(self.db_path, query)
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        csv_rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
        self.assertEqual(1, len(csv_rows))
        self.assertIn("Lan Anh 蓝安", html)
        self.assertEqual("Lan Anh 蓝安", csv_rows[0]["达人"].split(" [评级:", 1)[0])
        self.assertEqual(grade, csv_rows[0]["评级"])
        self.assertEqual("xx计划", csv_rows[0]["标签"])
        self.assertEqual("合成 Việt 备注", csv_rows[0]["备注"])

        keys = [row["creator_key"] for row in _list_rows(self.db_path, {"period": ["total"]})[:2]]
        compared = render_compare(self.db_path, {"ids": keys, "period": ["total"]}, self.config_path)
        self.assertIn("达人对比", compared)
        with self.assertRaisesRegex(ValueError, "至少选择 2 位"):
            render_compare(self.db_path, {"ids": keys[:1]}, self.config_path)

    def test_ac07_dashboard_totals_distribution_and_dual_top_match_database(self) -> None:
        with connect(self.db_path) as connection:
            creator_count = connection.execute("SELECT COUNT(*) FROM creators").fetchone()[0]
            historical_gmv = connection.execute(
                "SELECT SUM(alliance_gmv_vnd) FROM raw_creator_periods"
            ).fetchone()[0]
            video_gmv = connection.execute("SELECT SUM(attributed_gmv_vnd) FROM raw_video").fetchone()[0]
            live_gmv = connection.execute("SELECT SUM(attributed_gmv_vnd) FROM raw_live").fetchone()[0]
            grade_counts = dict(connection.execute("SELECT grade, COUNT(*) FROM ratings GROUP BY grade"))
        html = render_dashboard(self.db_path, {"period": ["total"], "grain": ["total"]})
        for value in (creator_count, historical_gmv, video_gmv, live_gmv):
            self.assertIn(f"{value:,}", html)
        for grade in "SABCD":
            self.assertIn(f"{grade}:{grade_counts.get(grade, 0)}", html)
        self.assertIn("TOP 10（GMV）", html)
        self.assertIn("TOP 10（出单件数）", html)
        period = list_business_periods(self.db_path, "video")[0]["token"]
        period_html = render_dashboard(self.db_path, {"period": [period], "grain": ["day"]})
        self.assertIn(period.replace("|", ""), period_html.replace(" 至 ", ""))

    def test_calculator_contract_and_page_remain_deliberate_placeholder(self) -> None:
        inputs = CalculatorInput(120, 50_000, 1_000_000, 0.12)
        result = calculate(inputs, self.config_path)
        self.assertFalse(result.available)
        self.assertIsNone(result.formula)
        self.assertIsNone(result.value)
        self.assertEqual(PLACEHOLDER_MESSAGE, result.message)
        html = render_calculator_page(self.config_path)
        self.assertIn(PLACEHOLDER_MESSAGE, html)
        self.assertIn("calculator_formula", html)
        self.assertIn("不连接 TikTok、FastMoss", html)
        with self.assertRaises(ValueError):
            CalculatorInput(-1, 1, 1, 0.1)

    def test_ac09_adapter_contract_manual_tiktok_and_shopee_placeholder(self) -> None:
        adapter = TikTokManualImportAdapter()
        self.assertIsInstance(adapter, DataAdapter)
        imported_db = self.temp_path / "adapter.db"
        result = adapter.import_data(imported_db, "creator", FIXTURES / "creator_good.xlsx")
        self.assertEqual(2, result.accepted_rows)
        with self.assertRaisesRegex(NotImplementedError, "只支持授权后台导出"):
            adapter.fetch({})
        shopee = ShopeeAdapter()
        with self.assertRaisesRegex(NotImplementedError, "仅占位"):
            shopee.fetch({})
        with self.assertRaisesRegex(NotImplementedError, "尚未实现"):
            shopee.import_data(imported_db, "creator", FIXTURES / "creator_good.xlsx")

    def test_incremental_recompute_updates_only_queued_creator_and_routes_are_reachable(self) -> None:
        self.assertEqual([], queued_recompute_creators(self.db_path))
        target = "username:lananh.vn"
        untouched = "username:minhanh.vn"
        with connect(self.db_path) as connection:
            before_target = connection.execute(
                "SELECT metric_value, computed_at FROM metrics WHERE creator_key=? AND metric_name='historical_gmv'",
                (target,),
            ).fetchone()
            before_untouched = connection.execute(
                "SELECT metric_value, computed_at FROM metrics WHERE creator_key=? AND metric_name='historical_gmv'",
                (untouched,),
            ).fetchone()
            connection.execute(
                "UPDATE raw_creator_periods SET alliance_gmv_vnd=alliance_gmv_vnd+123 WHERE creator_key=?",
                (target,),
            )
        enqueue_recompute(self.db_path, [target], "import")
        self.assertEqual(1, recompute_incremental(self.db_path, self.config_path))
        self.assertEqual([], queued_recompute_creators(self.db_path))
        with connect(self.db_path) as connection:
            after_target = connection.execute(
                "SELECT metric_value, computed_at FROM metrics WHERE creator_key=? AND metric_name='historical_gmv'",
                (target,),
            ).fetchone()
            after_untouched = connection.execute(
                "SELECT metric_value, computed_at FROM metrics WHERE creator_key=? AND metric_name='historical_gmv'",
                (untouched,),
            ).fetchone()
        self.assertEqual(before_target["metric_value"] + 123, after_target["metric_value"])
        self.assertNotEqual(before_target["computed_at"], after_target["computed_at"])
        self.assertEqual(tuple(before_untouched), tuple(after_untouched))

        server = create_server(self.db_path, self.config_path, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            creators = [row["creator_key"] for row in _list_rows(self.db_path, {"period": ["total"]})[:2]]
            routes = (
                "/", "/dashboard?grain=total", "/calculator", "/config", "/export.csv",
                "/recompute", "/recompute?full=1",
                "/creator/" + quote(creators[0], safe=""),
                "/cost/" + quote(creators[0], safe=""),
                "/compare?" + urlencode({"ids": creators}, doseq=True),
            )
            for route in routes:
                with self.subTest(route=route), urlopen(base + route, timeout=10) as response:
                    self.assertEqual(200, response.status)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()

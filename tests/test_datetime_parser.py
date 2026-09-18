from __future__ import annotations

import unittest

from importer import _parse_business_datetime


class BusinessDatetimeParserTests(unittest.TestCase):
    def test_ceo_smoke_video_samples(self) -> None:
        samples = (
            "2026/07/07 16:40:33",
            "2026/05/27 05:14:30",
            "2026/08/12 12:15:07",
            "2026/08/13 11:03:38",
            "2026/07/10 18:30:00",
            "2026/05/05 11:15:09",
            "2026/07/11 23:20:49",
        )
        for value in samples:
            with self.subTest(value=value):
                self.assertEqual(
                    value[:10].replace("/", "-") + "T" + value[11:] + "+07:00",
                    _parse_business_datetime(value, "发布时间", required=True),
                )

    def test_ceo_smoke_live_samples(self) -> None:
        samples = (
            "2026/08/09/ 08:56",
            "2026/08/30/ 19:58",
            "2026/08/29/ 19:33",
            "2026/08/31/ 11:49",
            "2026/08/12/ 20:45",
            "2026/08/11/ 16:39",
        )
        for value in samples:
            with self.subTest(value=value):
                expected = value.replace("/", "-", 2).replace("/ ", "T") + ":00+07:00"
                self.assertEqual(expected, _parse_business_datetime(value, "开播时间", required=True))

    def test_defensive_live_variant_with_seconds(self) -> None:
        self.assertEqual(
            "2026-08-31T23:49:07+07:00",
            _parse_business_datetime("2026/08/31/ 23:49:07", "开播时间", required=True),
        )

    def test_existing_patterns_remain_supported(self) -> None:
        cases = {
            "2026/08/31 23:49": "2026-08-31T23:49:00+07:00",
            "2026-08-31 23:49:07": "2026-08-31T23:49:07+07:00",
            "2026/08/31": "2026-08-31T00:00:00+07:00",
            "2026-08-31": "2026-08-31T00:00:00+07:00",
            "2026-08-31T16:49:07Z": "2026-08-31T23:49:07+07:00",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(expected, _parse_business_datetime(value, "时间", required=True))

    def test_excel_serial_fallback_remains_supported(self) -> None:
        self.assertEqual(
            "1899-12-31T00:00:00+07:00",
            _parse_business_datetime("1", "时间", required=True),
        )

    def test_invalid_values_are_rejected_with_contract_message(self) -> None:
        for value in ("abc", "2026-13-45"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    rf"^字段 发布时间 日期时间非法: {value}$",
                ):
                    _parse_business_datetime(value, "发布时间", required=True)


if __name__ == "__main__":
    unittest.main()

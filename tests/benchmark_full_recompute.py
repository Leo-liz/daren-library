"""Cold-start full metric recompute benchmark for 5,000 synthetic creators."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import UNPERIODIZED_DATE, UNPERIODIZED_SOURCE, connect, initialize_database  # noqa: E402
from metrics import recompute_metrics  # noqa: E402


LIMIT_SECONDS = 120.0
MATERIALIZED_METRICS_PER_CREATOR = 21


def _seed(db_path: Path, creators: int) -> None:
    initialize_database(db_path)
    now = "2026-09-17T00:00:00+00:00"
    batches = (
        ("bench-creator", "creator", "creator-5000.xlsx", UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE),
        ("bench-video", "video", "video-5000.xlsx", "2026-08-01", "2026-08-31", "banner"),
        ("bench-live", "live", "live-5000.xlsx", "2026-08-01", "2026-08-31", "banner"),
    )
    with connect(db_path) as connection:
        connection.executemany(
            """INSERT INTO import_batches(
                   batch_id, source_type, source_name, platform, imported_at,
                   period_start, period_end, period_source,
                   total_rows, accepted_rows, rejected_rows
               ) VALUES (?, ?, ?, 'tiktok_shop_vn', ?, ?, ?, ?, ?, ?, 0)""",
            ((batch, source_type, source_name, now, start, end, period_source, creators, creators)
             for batch, source_type, source_name, start, end, period_source in batches),
        )
        connection.executemany(
            """INSERT INTO creators(
                   platform, creator_key, creator_username, created_at, updated_at
               ) VALUES ('tiktok_shop_vn', ?, ?, ?, ?)""",
            ((f"id:{index}", f"benchmark-{index}", now, now) for index in range(creators)),
        )
        connection.executemany(
            """INSERT INTO raw_creator_periods(
                   platform, creator_key, period_start, period_end, period_source,
                   alliance_gmv_vnd, alliance_items, estimated_commission_vnd,
                   targeted_gmv_vnd, import_batch_id, updated_at
               ) VALUES ('tiktok_shop_vn', ?, ?, ?, ?, ?, ?, ?, ?, 'bench-creator', ?)""",
            ((f"id:{index}", UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE,
              1_000_000 + index, 10 + index % 50, 100_000 + index, 500_000 + index, now)
             for index in range(creators)),
        )
        connection.executemany(
            """INSERT INTO raw_video(
                   platform, source_record_key, creator_key, video_id, published_at,
                   attributed_gmv_vnd, attributed_items, views, likes, comments, shares,
                   new_followers, source_row_number, import_batch_id, raw_json
               ) VALUES ('tiktok_shop_vn', ?, ?, ?, '2026-08-01T00:00:00+07:00',
                         ?, ?, ?, ?, ?, ?, ?, ?, 'bench-video', '{}')""",
            ((f"video-{index}", f"id:{index}", f"video-{index}", 100_000 + index,
              1 + index % 5, 1_000 + index, 100 + index % 50, 10 + index % 20,
              5 + index % 10, index % 8, index + 3)
             for index in range(creators)),
        )
        connection.executemany(
            """INSERT INTO raw_live(
                   platform, source_record_key, creator_key, live_id, started_at, event_at_utc7,
                   attributed_gmv_vnd, attributed_items, viewers, view_count, comments, shares,
                   likes, source_row_number, import_batch_id, raw_json
               ) VALUES ('tiktok_shop_vn', ?, ?, ?, '2026/08/01/ 20:00',
                         '2026-08-01T20:00:00+07:00', ?, ?, ?, ?, ?, ?, ?, ?, 'bench-live', '{}')""",
            ((f"live-{index}", f"id:{index}", f"live-{index}", 200_000 + index,
              2 + index % 5, 2_000 + index, 3_000 + index, 20 + index % 20,
              8 + index % 10, 200 + index % 50, index + 3)
             for index in range(creators)),
        )
        connection.executemany(
            """INSERT INTO costs(
                   platform, creator_key, target_type, target_id,
                   collaboration_cost_vnd, slot_fee_vnd, updated_at
               ) VALUES ('tiktok_shop_vn', ?, ?, ?, ?, ?, ?)""",
            (
                row
                for index in range(creators)
                for row in (
                    (f"id:{index}", "creator", "", 100_000, None, now),
                    (f"id:{index}", "video", f"video-{index}", None, 50_000, now),
                    (f"id:{index}", "live", f"live-{index}", None, 100_000, now),
                )
            ),
        )


def run(creators: int = 5_000) -> dict[str, int | float]:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "full-recompute.db"
        _seed(db_path, creators)
        started = time.perf_counter()
        recomputed = recompute_metrics(db_path)
        elapsed = time.perf_counter() - started
        with connect(db_path) as connection:
            metric_rows = connection.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        return {
            "creators_recomputed": recomputed,
            "metric_rows": metric_rows,
            "metrics_per_creator": metric_rows // creators,
            "elapsed_seconds": round(elapsed, 3),
        }


@unittest.skipUnless(os.environ.get("RUN_BENCHMARKS") == "1", "set RUN_BENCHMARKS=1")
class FullRecomputeBenchmarkTests(unittest.TestCase):
    def test_5000_creator_full_recompute_meets_limit(self) -> None:
        result = run()
        print(json.dumps(result, ensure_ascii=False))
        self.assertEqual(5_000, result["creators_recomputed"])
        self.assertEqual(5_000 * MATERIALIZED_METRICS_PER_CREATOR, result["metric_rows"])
        self.assertLessEqual(result["elapsed_seconds"], LIMIT_SECONDS)


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if (
        result["creators_recomputed"] == 5_000
        and result["metric_rows"] == 5_000 * MATERIALIZED_METRICS_PER_CREATOR
        and result["elapsed_seconds"] <= LIMIT_SECONDS
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

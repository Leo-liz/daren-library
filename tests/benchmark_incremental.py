"""Synthetic real-scale benchmark for the incremental recompute path."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import UNPERIODIZED_DATE, UNPERIODIZED_SOURCE, connect, initialize_database
from metrics import enqueue_recompute, recompute_incremental
from rating import DEFAULT_CONFIG_PATH


def run(creators: int = 80_000, metrics_per_creator: int = 7) -> dict[str, int | float]:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "scale.db"
        initialize_database(db_path)
        now = "2026-09-14T00:00:00+00:00"
        with connect(db_path) as connection:
            connection.execute(
                """INSERT INTO import_batches(
                       batch_id, source_type, source_name, platform, imported_at,
                       period_start, period_end, period_source,
                       total_rows, accepted_rows, rejected_rows
                   ) VALUES ('scale', 'creator', 'synthetic-scale.xlsx', 'tiktok_shop_vn', ?,
                             ?, ?, ?, ?, ?, 0)""",
                (now, UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE,
                 creators, creators),
            )
            connection.executemany(
                """INSERT INTO creators(
                       platform, creator_key, creator_username, created_at, updated_at
                   ) VALUES ('tiktok_shop_vn', ?, ?, ?, ?)""",
                ((f"id:{index}", f"synthetic-{index}", now, now) for index in range(creators)),
            )
            metric_names = (
                "historical_gmv", "sold_items", "post_collaboration_gmv",
                "historical_roi", "cost_ratio_roi", "video_attributed_gmv", "live_attributed_gmv",
            )[:metrics_per_creator]
            connection.executemany(
                """INSERT INTO metrics(
                       platform, creator_key, metric_name, metric_value,
                       source_table, source_field, source_batches, computed_at
                   ) VALUES ('tiktok_shop_vn', ?, ?, ?, ?, ?, '[\"scale\"]', ?)""",
                (
                    (f"id:{index}", name, float(index % 1000 + offset), "synthetic", name, now)
                    for index in range(creators)
                    for offset, name in enumerate(metric_names)
                ),
            )
            target = f"id:{creators - 1}"
            connection.execute(
                """INSERT INTO raw_creator_periods(
                       platform, creator_key, period_start, period_end, period_source,
                       alliance_gmv_vnd, alliance_items, estimated_commission_vnd,
                       targeted_gmv_vnd, import_batch_id, updated_at
                   ) VALUES ('tiktok_shop_vn', ?, ?, ?, ?,
                             999999, 123, 456789, 888888, 'scale', ?)""",
                (target, UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE, now),
            )
        seeded_metrics = creators * len(metric_names)
        enqueue_recompute(db_path, [target], "import")
        started = time.perf_counter()
        recomputed = recompute_incremental(db_path, DEFAULT_CONFIG_PATH)
        elapsed = time.perf_counter() - started
        with connect(db_path) as connection:
            target_gmv = connection.execute(
                "SELECT metric_value FROM metrics WHERE creator_key=? AND metric_name='historical_gmv'",
                (target,),
            ).fetchone()[0]
            queue_remaining = connection.execute("SELECT COUNT(*) FROM recompute_queue").fetchone()[0]
        return {
            "creators": creators,
            "seeded_metrics": seeded_metrics,
            "recomputed_creators": recomputed,
            "elapsed_seconds": round(elapsed, 3),
            "target_gmv": int(target_gmv),
            "queue_remaining": queue_remaining,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-seconds", type=float, default=5.0)
    arguments = parser.parse_args()
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["elapsed_seconds"] <= arguments.max_seconds else 1


if __name__ == "__main__":
    raise SystemExit(main())

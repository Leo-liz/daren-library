"""5,000-row synthetic import benchmark for creator and video workbooks."""

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

from fixtures.generate_fixtures import generate_benchmark  # noqa: E402
from importer import import_xlsx  # noqa: E402


CREATOR_LIMIT_SECONDS = 60.0
VIDEO_LIMIT_SECONDS = 90.0


def run(row_count: int = 5_000) -> dict[str, int | float]:
    with tempfile.TemporaryDirectory() as directory:
        temp_path = Path(directory)
        creator_path, video_path = generate_benchmark(temp_path, row_count)
        db_path = temp_path / "benchmark.db"

        started = time.perf_counter()
        creator_result = import_xlsx(db_path, creator_path, "creator")
        creator_seconds = time.perf_counter() - started

        started = time.perf_counter()
        video_result = import_xlsx(db_path, video_path, "video")
        video_seconds = time.perf_counter() - started

        return {
            "rows": row_count,
            "creator_accepted": creator_result.accepted_rows,
            "creator_rejected": creator_result.rejected_rows,
            "creator_seconds": round(creator_seconds, 3),
            "video_accepted": video_result.accepted_rows,
            "video_rejected": video_result.rejected_rows,
            "video_seconds": round(video_seconds, 3),
        }


@unittest.skipUnless(os.environ.get("RUN_BENCHMARKS") == "1", "set RUN_BENCHMARKS=1")
class ImportBenchmarkTests(unittest.TestCase):
    def test_5000_row_imports_meet_limits(self) -> None:
        result = run()
        print(json.dumps(result, ensure_ascii=False))
        self.assertEqual(5_000, result["creator_accepted"])
        self.assertEqual(0, result["creator_rejected"])
        self.assertLessEqual(result["creator_seconds"], CREATOR_LIMIT_SECONDS)
        self.assertEqual(5_000, result["video_accepted"])
        self.assertEqual(0, result["video_rejected"])
        self.assertLessEqual(result["video_seconds"], VIDEO_LIMIT_SECONDS)


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if (
        result["creator_accepted"] == 5_000
        and result["creator_rejected"] == 0
        and result["creator_seconds"] <= CREATOR_LIMIT_SECONDS
        and result["video_accepted"] == 5_000
        and result["video_rejected"] == 0
        and result["video_seconds"] <= VIDEO_LIMIT_SECONDS
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

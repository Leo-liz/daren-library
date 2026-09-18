from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "fixtures"


class CliStdoutEncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _run_cli(self, script_name: str, *arguments: object) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "gbk:strict"
        environment["PYTHONUTF8"] = "0"
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / script_name), *(str(item) for item in arguments)],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _json_stdout(self, completed: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
        return json.loads(completed.stdout.decode("utf-8"))

    def test_importer_bad_rows_pipe_returns_2_with_complete_json(self) -> None:
        completed = self._run_cli(
            "importer.py",
            "creator",
            FIXTURES / "creator_bad_rows.xlsx",
            "--db",
            self.temp_path / "bad.db",
        )

        self.assertEqual(2, completed.returncode, completed.stderr.decode("utf-8", errors="replace"))
        payload = self._json_stdout(completed)
        errors = payload["errors"]
        self.assertEqual([3, 4], [item["row_number"] for item in errors])
        self.assertIn("主键缺失", errors[0]["reason"])
        self.assertIn("数值非法", errors[1]["reason"])
        self.assertIn("không hợp lệ", errors[1]["reason"])

    def test_metrics_pipe_emits_parseable_json(self) -> None:
        db_path = self.temp_path / "metrics.db"
        imported = self._run_cli(
            "importer.py", "creator", FIXTURES / "creator_good.xlsx", "--db", db_path
        )
        self.assertEqual(0, imported.returncode, imported.stderr.decode("utf-8", errors="replace"))

        completed = self._run_cli("metrics.py", "--db", db_path)

        self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8", errors="replace"))
        payload = self._json_stdout(completed)
        self.assertEqual(2, payload["creators_recomputed"])

    def test_importer_good_rows_pipe_returns_0_with_parseable_json(self) -> None:
        completed = self._run_cli(
            "importer.py",
            "creator",
            FIXTURES / "creator_good.xlsx",
            "--db",
            self.temp_path / "good.db",
        )

        self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8", errors="replace"))
        payload = self._json_stdout(completed)
        self.assertEqual(0, payload["rejected_rows"])
        self.assertEqual([], payload["errors"])


if __name__ == "__main__":
    unittest.main()

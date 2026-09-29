import json
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# The CLI dependency is irrelevant to direct GolfRunner tests and is not
# installed in every lightweight test environment.
sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda _: None))

from scripts.run_golf import GolfRunner  # noqa: E402
from scripts.task import GolfTaskResult  # noqa: E402


class GolfRunnerResumeTest(unittest.TestCase):
    def test_existing_output_runs_only_failed_and_incomplete_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "project"
            output_dir = root / "results"
            project_root.mkdir()

            entries = []
            for name in ("successful", "failed", "incomplete"):
                source_file = project_root / f"{name}.lean"
                src = f"theorem {name} : True := by trivial"
                source_file.write_text(src + "\n", encoding="utf-8")
                entries.append(
                    {
                        "name": name,
                        "path": source_file.name,
                        "proof_length": 5,
                        "src": src,
                        "signature": f"theorem {name} : True",
                        "contexts": [],
                    }
                )

            eval_file = root / "eval.jsonl"
            eval_file.write_text(
                "".join(json.dumps(entry) + "\n" for entry in entries),
                encoding="utf-8",
            )

            successful_dir = output_dir / "successful"
            successful_dir.mkdir(parents=True)
            successful_result = {
                "success": True,
                "name": "successful",
                "initial_length": 5,
                "final_length": 3,
                "attempts": 2,
            }
            (successful_dir / "result.json").write_text(
                json.dumps(successful_result), encoding="utf-8"
            )
            successful_marker = successful_dir / "preserved.txt"
            successful_marker.write_text("keep", encoding="utf-8")

            failed_dir = output_dir / "failed"
            failed_dir.mkdir()
            (failed_dir / "result.json").write_text(
                json.dumps({"success": False, "error_message": "crashed"}),
                encoding="utf-8",
            )
            (failed_dir / "stale.txt").write_text("remove", encoding="utf-8")

            incomplete_dir = output_dir / "incomplete"
            incomplete_dir.mkdir()
            (incomplete_dir / "claude_raw.jsonl").write_text(
                "partial", encoding="utf-8"
            )

            old_summary = output_dir / "summary.json"
            old_summary.write_text('{"stale": true}', encoding="utf-8")

            def fake_run(tasks, parallel, max_workers):
                self.assertEqual(["failed", "incomplete"], [task.name for task in tasks])
                self.assertTrue(successful_marker.exists())
                self.assertFalse((failed_dir / "stale.txt").exists())
                self.assertFalse((incomplete_dir / "claude_raw.jsonl").exists())
                self.assertFalse(old_summary.exists())

                now = datetime.now()
                return [
                    GolfTaskResult(
                        task_id=task.task_id,
                        name=task.name,
                        success=True,
                        initial_length=task.initial_proof_length,
                        final_length=4,
                        attempts=1,
                        start_time=now,
                        end_time=now,
                    )
                    for task in tasks
                ]

            with patch("scripts.run_golf.run_golf_tasks", side_effect=fake_run):
                return_code = GolfRunner().run(
                    project_root=str(project_root),
                    jsonl_file=str(eval_file),
                    output_dir=str(output_dir),
                    cleanup=False,
                )

            self.assertEqual(0, return_code)
            self.assertEqual("keep", successful_marker.read_text(encoding="utf-8"))
            summary = json.loads(old_summary.read_text(encoding="utf-8"))
            self.assertEqual(3, summary["total_tasks"])
            self.assertEqual(3, summary["improved"])
            self.assertEqual(
                ["successful", "failed", "incomplete"],
                [result["name"] for result in summary["results"]],
            )


if __name__ == "__main__":
    unittest.main()

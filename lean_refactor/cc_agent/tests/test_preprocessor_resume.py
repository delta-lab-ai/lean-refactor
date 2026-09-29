import json
import tempfile
import unittest
from pathlib import Path

from scripts.preprocessor import prepare_tasks_for_resume
from scripts.task import GolfTaskMetadata


class PrepareTasksForResumeTest(unittest.TestCase):
    def make_task(self, root: Path, name: str) -> GolfTaskMetadata:
        project_root = root / "project"
        original_path = project_root / f"{name}.lean"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_text(f"theorem {name} : True := by trivial\n", encoding="utf-8")

        task_dir = root / "results" / name
        return GolfTaskMetadata(
            name=name,
            original_path=original_path,
            initial_proof_length=5,
            src=f"theorem {name} : True := by trivial",
            signature=f"theorem {name} : True",
            contexts=[],
            temp_file_path=project_root / f"{name}_{name}.lean",
            best_proof_file=task_dir / "best_proof.txt",
            current_proof_file=task_dir / "current_proof.txt",
            progress_file=task_dir / "progress.jsonl",
            project_root=project_root,
        )

    def test_skips_success_and_resets_failed_and_incomplete_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            successful = self.make_task(root, "successful")
            failed = self.make_task(root, "failed")
            incomplete = self.make_task(root, "incomplete")

            successful_dir = successful.progress_file.parent
            successful_dir.mkdir(parents=True)
            (successful_dir / "result.json").write_text(
                json.dumps({"success": True, "name": successful.name}),
                encoding="utf-8",
            )
            successful_marker = successful_dir / "keep-me.txt"
            successful_marker.write_text("preserved", encoding="utf-8")

            failed_dir = failed.progress_file.parent
            failed_dir.mkdir(parents=True)
            (failed_dir / "result.json").write_text(
                json.dumps(
                    {
                        "success": False,
                        "error_message": "previous process failed",
                    }
                ),
                encoding="utf-8",
            )
            (failed_dir / "old-artifact.txt").write_text("stale", encoding="utf-8")
            failed.temp_file_path.write_text("stale temp file", encoding="utf-8")

            incomplete_dir = incomplete.progress_file.parent
            incomplete_dir.mkdir(parents=True)
            (incomplete_dir / "claude_raw.jsonl").write_text("partial", encoding="utf-8")

            tasks_to_run, successful_tasks = prepare_tasks_for_resume(
                [successful, failed, incomplete]
            )

            self.assertEqual([failed, incomplete], tasks_to_run)
            self.assertEqual([successful], [task for task, _ in successful_tasks])
            self.assertEqual("preserved", successful_marker.read_text(encoding="utf-8"))

            for task in (failed, incomplete):
                task_dir = task.progress_file.parent
                self.assertFalse((task_dir / "result.json").exists())
                self.assertFalse((task_dir / "old-artifact.txt").exists())
                self.assertFalse((task_dir / "claude_raw.jsonl").exists())
                self.assertEqual(task.src, task.best_proof_file.read_text(encoding="utf-8"))
                self.assertEqual(task.src, task.current_proof_file.read_text(encoding="utf-8"))
                progress = [
                    json.loads(line)
                    for line in task.progress_file.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(1, len(progress))
                self.assertEqual(0, progress[0]["attempt"])
                self.assertEqual(
                    task.original_path.read_text(encoding="utf-8"),
                    task.temp_file_path.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()

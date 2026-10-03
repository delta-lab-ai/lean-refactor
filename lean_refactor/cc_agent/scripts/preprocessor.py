"""
JSONL reader and temp file creator for proof golfing tasks.
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .task import GolfTaskMetadata


def sanitize_name(name: str) -> str:
    """Convert theorem name to filesystem-safe string."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def load_tasks(
    jsonl_path: str,
    project_root: str,
    output_dir: str,
    max_turns: int = 40,
    timeout_minutes: Optional[float] = 60,
    filter_name: Optional[str] = None,
    max_tasks: Optional[int] = None,
    model: Optional[str] = None,
    effort: Optional[str] = None,
) -> list[GolfTaskMetadata]:
    """
    Read JSONL input and create GolfTaskMetadata objects with temp files.

    Each JSONL line has: name, path, proof_length, src, signature, contexts.
    For each entry:
    - Creates a temp .lean file (copy of original) in the same directory
    - Creates a best_proof.txt with the initial src
    - Creates an empty progress.jsonl

    Args:
        jsonl_path: Path to input JSONL file
        project_root: Lean project root directory
        output_dir: Directory for output files (best_proof, progress)
        max_turns: Max turns for each Claude session
        filter_name: If set, only process this specific theorem
        max_tasks: If set, limit number of tasks

    Returns:
        List of GolfTaskMetadata objects
    """
    jsonl_path = Path(jsonl_path).resolve()
    project_root = Path(project_root).resolve()
    output_dir = Path(output_dir).resolve()

    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")
    if not project_root.exists():
        raise FileNotFoundError(f"Project root not found: {project_root}")

    tasks = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[warn] Skipping malformed JSON at line {line_num}: {e}")
                continue

            name = entry["name"]
            rel_path = entry["path"]
            proof_length = entry["proof_length"]
            src = entry["src"]
            signature = entry.get("signature", "")
            contexts = entry.get("contexts", [])

            # Apply filter
            if filter_name and name != filter_name:
                print(f"[info] Skipping '{name}' due to filter (looking for '{filter_name}')")
                continue

            # Compute paths
            original_path = project_root / rel_path
            if not original_path.exists():
                print(f"[warn] Original file not found, skipping: {original_path}")
                continue

            sanitized = sanitize_name(name)
            temp_file_path = original_path.parent / f"{original_path.stem}_{sanitized}.lean"
            best_proof_file = output_dir / sanitized / "best_proof.txt"
            current_proof_file = output_dir / sanitized / "current_proof.txt"
            progress_file = output_dir / sanitized / "progress.jsonl"

            task = GolfTaskMetadata(
                name=name,
                original_path=original_path,
                initial_proof_length=proof_length,
                src=src,
                signature=signature,
                contexts=contexts,
                temp_file_path=temp_file_path,
                best_proof_file=best_proof_file,
                current_proof_file=current_proof_file,
                progress_file=progress_file,
                project_root=project_root,
                max_turns=max_turns,
                timeout_minutes=timeout_minutes,
                model=model,
                effort=effort,
            )
            tasks.append(task)

            if max_tasks and len(tasks) >= max_tasks:
                break

    print(f"[info] Loaded {len(tasks)} tasks from {jsonl_path}")
    return tasks


def prepare_task_files(task: GolfTaskMetadata) -> None:
    """
    Create temp file and output files for a single task.

    - Copies the entire original .lean file to the temp file path
    - Writes the initial src to best_proof.txt
    - Creates empty progress.jsonl
    """
    # Copy entire original file to temp file
    original_content = task.original_path.read_text(encoding="utf-8")
    task.temp_file_path.parent.mkdir(parents=True, exist_ok=True)
    task.temp_file_path.write_text(original_content, encoding="utf-8")

    # Write initial proof to best_proof file and current_proof file
    task.best_proof_file.parent.mkdir(parents=True, exist_ok=True)
    task.best_proof_file.write_text(task.src, encoding="utf-8")
    task.current_proof_file.write_text(task.src, encoding="utf-8")

    # Multi-objective settings read by check_proof.py
    if task.objective is not None:
        objective_file = task.progress_file.parent / "objective.json"
        objective_file.write_text(json.dumps(task.objective, indent=2, ensure_ascii=False), encoding="utf-8")

    # Seed progress file with attempt=0 (the original proof)
    task.progress_file.parent.mkdir(parents=True, exist_ok=True)
    if not task.progress_file.exists():
        seed_record = {
            "attempt": 0,
            "proof_text": task.src,
            "length": task.initial_proof_length,
            "best_length": task.initial_proof_length,
            "improved": False,
            "timestamp": datetime.now().isoformat(),
        }
        with open(task.progress_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(seed_record, ensure_ascii=False) + "\n")

    print(f"[info] Prepared task '{task.name}': temp={task.temp_file_path}")


def prepare_all_tasks(tasks: list[GolfTaskMetadata]) -> None:
    """Prepare temp files and output directories for all tasks."""
    for task in tasks:
        prepare_task_files(task)


def prepare_tasks_for_resume(
    tasks: list[GolfTaskMetadata],
) -> tuple[list[GolfTaskMetadata], list[tuple[GolfTaskMetadata, dict]]]:
    """
    Select and freshly prepare the tasks that need to run.

    A task is complete only when its result.json contains ``success: true``.
    Successful task directories are left untouched. Failed tasks, interrupted
    tasks without a result.json, and tasks with an unreadable result.json have
    their task directory removed before being prepared from the original input.

    Returns:
        (tasks_to_run, successful_tasks_with_result_data)
    """
    tasks_to_run: list[GolfTaskMetadata] = []
    successful_tasks: list[tuple[GolfTaskMetadata, dict]] = []

    for task in tasks:
        task_dir = task.progress_file.parent
        expected_dir_name = sanitize_name(task.name)
        artifact_paths = (
            task.best_proof_file,
            task.current_proof_file,
            task.progress_file,
        )
        if (
            not expected_dir_name
            or task_dir.name != expected_dir_name
            or any(path.parent != task_dir for path in artifact_paths)
        ):
            raise ValueError(
                f"Refusing to reset unsafe task directory for '{task.name}': {task_dir}"
            )

        result_file = task_dir / "result.json"
        retry_reason = "no result.json (incomplete previous run)"

        if result_file.exists():
            try:
                loaded = json.loads(result_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    if loaded.get("success") is True:
                        successful_tasks.append((task, loaded))
                        print(f"[info] Skipping already successful task: {task.name}")
                        continue

                    error_message = loaded.get("error_message")
                    retry_reason = "previous result was not successful"
                    if error_message:
                        retry_reason += f": {error_message}"
                else:
                    retry_reason = "result.json does not contain a JSON object"
            except (OSError, json.JSONDecodeError) as exc:
                retry_reason = f"could not read result.json: {exc}"

        print(f"[info] Resetting task '{task.name}' ({retry_reason})")

        # The task directory contains only run artifacts for this task:
        # result.json, proof snapshots, progress, and raw logs.
        if task_dir.exists():
            shutil.rmtree(task_dir)

        # An interrupted run may also leave its generated Lean file behind.
        if task.temp_file_path.exists():
            task.temp_file_path.unlink()

        prepare_task_files(task)
        tasks_to_run.append(task)

    print(
        f"[info] Resume scan: {len(successful_tasks)} successful task(s) skipped, "
        f"{len(tasks_to_run)} task(s) prepared to run"
    )
    return tasks_to_run, successful_tasks


def cleanup_temp_files(tasks: list[GolfTaskMetadata]) -> int:
    """Remove temp .lean files created during preprocessing. Returns count removed."""
    removed = 0
    for task in tasks:
        if task.temp_file_path.exists():
            task.temp_file_path.unlink()
            removed += 1
    print(f"[info] Cleaned up {removed} temp files")
    return removed


def cleanup_temp_files_by_pattern(project_root: str) -> int:
    """Remove temp .lean files matching the naming pattern from a project directory."""
    project_root = Path(project_root).resolve()
    removed = 0
    # Temp files match: *_<sanitized_name>.lean where sanitized_name contains underscores
    # More precisely, they have the pattern: originalStem_theoremName.lean
    # We look for .lean files that aren't imported by any other file
    for lean_file in project_root.rglob("*.lean"):
        # Heuristic: temp files contain at least one underscore after the stem
        # and their stem is longer than typical file names
        stem = lean_file.stem
        # Check if this looks like a temp file (original_sanitizedName pattern)
        if "_" in stem and len(stem) > 30:
            lean_file.unlink()
            removed += 1
            print(f"[info] Removed temp file: {lean_file}")
    print(f"[info] Cleaned up {removed} temp files by pattern")
    return removed

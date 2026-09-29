import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from lean_worker.verifier_lean_client import LeanClientScheduler


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_no}: {exc}") from exc
    return rows


def _read_last_improved_jsonl_row(path: Path) -> dict[str, Any]:
    last_improved_row: dict[str, Any] | None = None
    first_row: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_no}: {exc}") from exc

            if first_row is None:
                first_row = row

            if row.get("improved") is True:
                last_improved_row = row

    if first_row is None:
        raise ValueError(f"File is empty: {path}")

    if last_improved_row is None:
        return first_row

    return last_improved_row


def _build_problem_lookup(problems_jsonl: Path) -> dict[str, dict[str, Any]]:
    """Returns dict keyed by sanitized name (matching result subdir names)."""
    rows = _read_jsonl(problems_jsonl)
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"Missing/invalid 'name' in problems file row: {row}")
        sanitized = _sanitize_name(name)
        if sanitized in lookup:
            raise ValueError(f"Duplicate sanitized problem name in problems jsonl: {sanitized} (from '{name}')")
        lookup[sanitized] = row
    return lookup


def collect_tasks(results_dir: Path, problems_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for subdir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        sanitized_name = subdir.name
        if sanitized_name not in problems_lookup:
            raise KeyError(
                f"Problem '{sanitized_name}' from result subdir {subdir} not found in problems jsonl"
            )

        progress_path = subdir / "progress.jsonl"
        if not progress_path.exists():
            raise FileNotFoundError(f"Missing progress.jsonl: {progress_path}")

        last_row = _read_last_improved_jsonl_row(progress_path)
        proof_text = last_row.get("proof_text")
        if not isinstance(proof_text, str) or not proof_text.strip():
            raise ValueError(
                f"Missing/invalid proof_text in last improved=true row of {progress_path}: {last_row}"
            )

        problem = problems_lookup[sanitized_name]
        original_name = problem["name"]

        relative_path = problem.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError(
                f"Missing/invalid 'path' for problem '{original_name}' in problems jsonl"
            )

        src = problem.get("src")
        if not isinstance(src, str) or not src.strip():
            raise ValueError(
                f"Missing/invalid 'src' for problem '{original_name}' in problems jsonl"
            )

        tasks.append(
            {
                "name": original_name,
                "result_dir": str(subdir),
                "progress_jsonl": str(progress_path),
                "old_code": src,
                "new_code": proof_text,
                "relative_path": relative_path,
            }
        )
    return tasks


def verify_tasks(
    tasks: list[dict[str, Any]],
    workspace_path: str,
    timeout: int,
    max_concurrent_requests: int,
) -> list[dict[str, Any]]:
    scheduler = LeanClientScheduler(
        workspace_path=workspace_path,
        max_concurrent_requests=max_concurrent_requests,
        timeout=timeout,
        name="lean_client_verify",
    )
    try:
        request_payloads = [
            {
                "old_code": task["old_code"],
                "new_code": task["new_code"],
                "relative_path": task["relative_path"],
                "timeout": timeout,
            }
            for task in tasks
        ]
        request_ids = scheduler.submit_all_request(request_payloads)
        raw_outputs = scheduler.get_all_request_outputs(request_ids)
    finally:
        scheduler.close()

    results: list[dict[str, Any]] = []
    for task, output in zip(tasks, raw_outputs):
        passed = bool(output.get("pass", False))
        error_occurred = bool(output.get("error_occurred", False))
        is_correct = passed and not error_occurred
        result = {
            "name": task["name"],
            "pass": passed,
            "error_occurred": error_occurred,
            "is_correct": is_correct,
            "diagnostics": output.get("diagnostics", []),
        }
        print(
            f"[{result['name']}] is_correct={result['is_correct']} "
            f"pass={result['pass']} error_occurred={result['error_occurred']}"
        )
        results.append(result)
    return results


def _to_serializable(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if hasattr(obj, "_asdict"):
        return _to_serializable(obj._asdict())
    if hasattr(obj, "__dict__"):
        return _to_serializable(vars(obj))
    try:
        return [_to_serializable(item) for item in obj]
    except TypeError:
        return str(obj)


def write_output(results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(_to_serializable(row), ensure_ascii=False) + "\n")
    print(f"Wrote {len(results)} verification rows to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify result subdirectories using LeanClientScheduler (LSP-based). "
            "Combines problem src (old_code) + latest proof_text (new_code) for replacement verification."
        )
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        required=True,
        help="Directory that contains one subdirectory per problem, each with progress.jsonl",
    )
    parser.add_argument(
        "--problems-jsonl",
        type=Path,
        required=True,
        help="Problems jsonl containing at least fields: name, path, src",
    )
    parser.add_argument(
        "--workspace-path",
        type=str,
        required=True,
        help="Lean project root directory (where lakefile.lean lives)",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        required=True,
        help="Where to write verification output jsonl",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Verification timeout per proof (seconds)",
    )
    parser.add_argument(
        "--max-concurrent-requests",
        type=int,
        default=5,
        help="Number of LeanClient worker processes",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.results_dir.exists() or not args.results_dir.is_dir():
        raise NotADirectoryError(f"Invalid --results-dir: {args.results_dir}")
    if not args.problems_jsonl.exists() or not args.problems_jsonl.is_file():
        raise FileNotFoundError(f"Invalid --problems-jsonl: {args.problems_jsonl}")
    workspace = Path(args.workspace_path)
    if not workspace.exists() or not workspace.is_dir():
        raise NotADirectoryError(f"Invalid --workspace-path: {args.workspace_path}")

    problems_lookup = _build_problem_lookup(args.problems_jsonl)
    tasks = collect_tasks(args.results_dir, problems_lookup)

    print(f"Loaded {len(tasks)} tasks from {args.results_dir}")
    results = verify_tasks(
        tasks=tasks,
        workspace_path=args.workspace_path,
        timeout=args.timeout,
        max_concurrent_requests=args.max_concurrent_requests,
    )
    write_output(results, args.output_path)


if __name__ == "__main__":
    main()

import argparse
import json
from pathlib import Path
from typing import Any

from lean_worker.verifier_slow import Lean4ServerScheduler


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
    rows = _read_jsonl(problems_jsonl)
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"Missing/invalid 'name' in problems file row: {row}")
        if name in lookup:
            raise ValueError(f"Duplicate problem name in problems jsonl: {name}")
        lookup[name] = row
    return lookup


def collect_tasks(results_dir: Path, problems_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for subdir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        problem_name = subdir.name
        if problem_name not in problems_lookup:
            raise KeyError(
                f"Problem '{problem_name}' from result subdir {subdir} not found in problems jsonl"
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

        header = problems_lookup[problem_name].get("header")
        if not isinstance(header, str):
            raise ValueError(
                f"Missing/invalid header for problem '{problem_name}' in problems jsonl"
            )

        combined_code = f"{header}{proof_text}" if header.endswith("\n") else f"{header}\n{proof_text}"

        tasks.append(
            {
                "name": problem_name,
                "result_dir": str(subdir),
                "progress_jsonl": str(progress_path),
                "code": combined_code,
            }
        )
    return tasks


def verify_tasks(
    tasks: list[dict[str, Any]],
    timeout: int,
    max_concurrent_requests: int,
) -> list[dict[str, Any]]:
    scheduler = Lean4ServerScheduler(
        max_concurrent_requests=max_concurrent_requests,
        timeout=timeout,
        name="putnam_verify",
    )
    try:
        request_payloads = [
            {
                "code": task["code"],
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
        complete = bool(output.get("complete", False))
        is_correct = passed and complete
        result = {
            "name": task["name"],
            "result_dir": task["result_dir"],
            "progress_jsonl": task["progress_jsonl"],
            "pass": passed,
            "complete": complete,
            "is_correct": is_correct,
            "verify_time": output.get("verify_time"),
            "errors": output.get("errors", []),
            "warnings": output.get("warnings", []),
            "system_errors": output.get("system_errors"),
            "system_messages": output.get("system_messages", ""),
        }
        print(
            f"[{result['name']}] is_correct={result['is_correct']} "
            f"pass={result['pass']} complete={result['complete']} "
            f"verify_time={result['verify_time']}"
        )
        results.append(result)
    return results


def write_output(results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(results)} verification rows to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Putnam result subdirectories by combining problem header + latest proof_text "
            "and running Lean verification."
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
        help="Problems jsonl containing at least fields: name, header",
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
        default=2400,
        help="Verification timeout per proof (seconds)",
    )
    parser.add_argument(
        "--max-concurrent-requests",
        type=int,
        default=30,
        help="Number of Lean verifier worker processes",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.results_dir.exists() or not args.results_dir.is_dir():
        raise NotADirectoryError(f"Invalid --results-dir: {args.results_dir}")
    if not args.problems_jsonl.exists() or not args.problems_jsonl.is_file():
        raise FileNotFoundError(f"Invalid --problems-jsonl: {args.problems_jsonl}")

    problems_lookup = _build_problem_lookup(args.problems_jsonl)
    tasks = collect_tasks(args.results_dir, problems_lookup)

    print(f"Loaded {len(tasks)} tasks from {args.results_dir}")
    results = verify_tasks(
        tasks=tasks,
        timeout=args.timeout,
        max_concurrent_requests=args.max_concurrent_requests,
    )
    write_output(results, args.output_path)


if __name__ == "__main__":
    main()

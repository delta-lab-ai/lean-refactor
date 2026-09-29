"""Verify the shortest proof of every result subdir and repair records that don't compile.

For each result subdirectory (one per problem, containing progress.jsonl):
  1. Collect candidate proofs from progress.jsonl that are shorter than the
     initial proof, deduplicated by proof_text, sorted shortest-first.
  2. Verify the shortest candidate via LeanClientScheduler (old_code=src from
     the problems jsonl, new_code=candidate proof_text, replacement mode).
  3. If it fails to compile, drop every progress.jsonl line with that
     proof_text and try the next-shortest candidate, until one passes or
     candidates are exhausted (final falls back to the initial proof).
  4. Rewrite progress.jsonl (recomputing best_length/improved on the kept
     rows), update the subdir's result.json and best_proof.txt, and fix the
     matching entry plus aggregate stats in summary.json.

Files are backed up to *.bak before the first modification. Verifier
infrastructure errors (error_occurred=True) are inconclusive: the task is
reported but nothing is modified for it.

Usage:
  .venv/bin/python -m scripts.verify_and_fix_results \
    --results-dir results/analysis_golf \
    --problems-jsonl workspace/analysis/eval/eval_analysis.jsonl \
    --workspace-path workspace/analysis \
    --output-path results/analysis_golf/verify_fix_report.jsonl \
    --max-concurrent-requests 5
"""

import argparse
import json
import re
import shutil
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


def _backup_once(path: Path) -> None:
    if path.exists():
        bak = path.with_name(path.name + ".bak")
        if not bak.exists():
            shutil.copy2(path, bak)


class TaskState:
    def __init__(self, subdir: Path, problem: dict[str, Any]):
        self.subdir = subdir
        self.name: str = problem["name"]
        self.src: str = problem["src"]
        self.relative_path: str = problem["path"]
        self.rows = _read_jsonl(subdir / "progress.jsonl")
        if not self.rows:
            raise ValueError(f"Empty progress.jsonl in {subdir}")
        self.initial_length: int = self.rows[0]["length"]

        # Unique candidate proofs strictly shorter than the initial proof,
        # shortest first (ties broken by earliest attempt).
        seen: dict[str, tuple[int, int]] = {}
        for row in self.rows:
            text = row.get("proof_text")
            length = row.get("length")
            if not isinstance(text, str) or not isinstance(length, int):
                continue
            if length >= self.initial_length:
                continue
            if text not in seen:
                seen[text] = (length, row.get("attempt", 0))
        self.candidates: list[tuple[int, int, str]] = sorted(
            (length, attempt, text) for text, (length, attempt) in seen.items()
        )
        self.candidate_idx = 0
        self.error_retries = 0
        self.failed_texts: list[str] = []
        self.failed_lengths: list[int] = []
        self.last_failure_diagnostics: list[Any] = []
        self.verified_length: int | None = None
        self.verified_text: str | None = None
        # no_improvement | pending | verified | exhausted | verifier_error
        self.status = "no_improvement" if not self.candidates else "pending"

    def current_candidate(self) -> tuple[int, int, str]:
        return self.candidates[self.candidate_idx]

    @property
    def final_length(self) -> int:
        if self.status == "verified":
            return self.verified_length
        return self.initial_length


def run_verification_rounds(
    tasks: list[TaskState],
    workspace_path: str,
    timeout: int,
    max_concurrent_requests: int,
    max_error_retries: int = 2,
) -> None:
    pending = [t for t in tasks if t.status == "pending"]
    if not pending:
        print("No tasks with improved proofs to verify.")
        return

    scheduler = LeanClientScheduler(
        workspace_path=workspace_path,
        max_concurrent_requests=max_concurrent_requests,
        timeout=timeout,
        name="verify_fix",
    )
    try:
        round_no = 0
        while pending:
            round_no += 1
            print(f"\n=== Round {round_no}: verifying {len(pending)} candidate proof(s) ===", flush=True)
            payloads = []
            for task in pending:
                length, attempt, text = task.current_candidate()
                print(f"  [{task.name}] length={length} (attempt {attempt}, candidate {task.candidate_idx + 1}/{len(task.candidates)})", flush=True)
                payloads.append(
                    {
                        "old_code": task.src,
                        "new_code": text,
                        "relative_path": task.relative_path,
                        "timeout": timeout,
                    }
                )
            request_ids = scheduler.submit_all_request(payloads)
            outputs = scheduler.get_all_request_outputs(request_ids)

            next_pending: list[TaskState] = []
            for task, output in zip(pending, outputs):
                length, attempt, text = task.current_candidate()
                passed = bool(output.get("pass", False))
                error_occurred = bool(output.get("error_occurred", False))
                if error_occurred:
                    task.last_failure_diagnostics = output.get("diagnostics", [])
                    if task.error_retries < max_error_retries:
                        task.error_retries += 1
                        print(f"  [{task.name}] VERIFIER ERROR at length={length} — retrying same candidate ({task.error_retries}/{max_error_retries})", flush=True)
                        next_pending.append(task)
                    else:
                        task.status = "verifier_error"
                        print(f"  [{task.name}] VERIFIER ERROR at length={length} — retries exhausted, leaving files untouched", flush=True)
                elif passed:
                    task.status = "verified"
                    task.verified_length = length
                    task.verified_text = text
                    print(f"  [{task.name}] PASS at length={length}", flush=True)
                else:
                    task.failed_texts.append(text)
                    task.failed_lengths.append(length)
                    task.last_failure_diagnostics = output.get("diagnostics", [])
                    task.candidate_idx += 1
                    if task.candidate_idx < len(task.candidates):
                        next_len = task.candidates[task.candidate_idx][0]
                        print(f"  [{task.name}] FAIL at length={length} — will try next shortest ({next_len})", flush=True)
                        next_pending.append(task)
                    else:
                        task.status = "exhausted"
                        print(f"  [{task.name}] FAIL at length={length} — no candidates left, falling back to initial ({task.initial_length})", flush=True)
            pending = next_pending
    finally:
        scheduler.close()


def rewrite_progress(task: TaskState) -> int:
    """Drop rows with failed proof_texts, recompute best_length/improved. Returns rows removed."""
    failed = set(task.failed_texts)
    kept = [row for row in task.rows if row.get("proof_text") not in failed]
    removed = len(task.rows) - len(kept)
    if removed == 0:
        return 0

    best = task.initial_length
    for i, row in enumerate(kept):
        length = row.get("length")
        if i == 0 or not isinstance(length, int):
            row["improved"] = False if i == 0 else row.get("improved", False)
            row["best_length"] = best
            continue
        row["improved"] = length < best
        best = min(best, length)
        row["best_length"] = best

    progress_path = task.subdir / "progress.jsonl"
    _backup_once(progress_path)
    with progress_path.open("w", encoding="utf-8") as f:
        for row in kept:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return removed


def update_result_json(task: TaskState) -> None:
    result_path = task.subdir / "result.json"
    if not result_path.exists():
        return
    with result_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    initial = data.get("initial_length", task.initial_length)
    final = task.final_length
    data["final_length"] = final
    data["tokens_saved"] = initial - final
    data["reduction_pct"] = round(100.0 * (initial - final) / initial, 2) if initial > 0 else 0.0
    data["success"] = final < initial
    _backup_once(result_path)
    with result_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_best_proof(task: TaskState) -> None:
    best_proof_path = task.subdir / "best_proof.txt"
    text = task.verified_text if task.status == "verified" else task.src
    if best_proof_path.exists() and best_proof_path.read_text(encoding="utf-8") == text:
        return
    _backup_once(best_proof_path)
    best_proof_path.write_text(text, encoding="utf-8")


def update_summary(summary_path: Path, tasks: list[TaskState]) -> None:
    if not summary_path.exists():
        print(f"[warn] No summary.json at {summary_path}; skipping summary update")
        return
    with summary_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)

    finals = {t.name: t for t in tasks if t.status in ("verified", "exhausted")}
    results = summary.get("results", [])
    changed = False
    for entry in results:
        task = finals.get(entry.get("name"))
        if task is None:
            continue
        initial = entry.get("initial_length", task.initial_length)
        final = task.final_length
        if entry.get("final_length") == final:
            continue
        entry["final_length"] = final
        entry["tokens_saved"] = initial - final
        entry["reduction_pct"] = round(100.0 * (initial - final) / initial, 2) if initial > 0 else 0.0
        entry["success"] = final < initial
        changed = True

    if not changed:
        print("summary.json already consistent; no update needed")
        return

    # Recompute aggregates the same way run_golf.py does.
    summary["total_tasks"] = len(results)
    summary["improved"] = sum(1 for r in results if r.get("success"))
    summary["total_initial_tokens"] = sum(r.get("initial_length", 0) for r in results)
    summary["total_final_tokens"] = sum(r.get("final_length", 0) for r in results)
    summary["total_tokens_saved"] = sum(max(0, r.get("tokens_saved", 0)) for r in results)
    summary["avg_reduction_percentage"] = (
        round(sum(r.get("reduction_pct", 0.0) for r in results) / len(results), 2) if results else 0.0
    )

    _backup_once(summary_path)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Updated {summary_path}")


def write_report(tasks: list[TaskState], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for task in tasks:
            row = {
                "name": task.name,
                "status": task.status,
                "initial_length": task.initial_length,
                "final_length": task.final_length,
                "num_candidates": len(task.candidates),
                "failed_lengths": task.failed_lengths,
                "verified_length": task.verified_length,
                "last_failure_diagnostics": task.last_failure_diagnostics,
            }
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(f"Wrote {len(tasks)} report rows to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify shortest proofs from progress.jsonl; drop non-compiling ones and fix result/summary files."
    )
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--problems-jsonl", type=Path, required=True)
    parser.add_argument("--workspace-path", type=str, required=True)
    parser.add_argument("--output-path", type=Path, required=True, help="Verification report jsonl")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-concurrent-requests", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true", help="Verify only; do not modify any files")
    parser.add_argument(
        "--filter-name",
        type=str,
        default=None,
        help="Comma-separated task names (original or sanitized); only these subdirs are processed",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.results_dir.is_dir():
        raise NotADirectoryError(f"Invalid --results-dir: {args.results_dir}")
    if not args.problems_jsonl.is_file():
        raise FileNotFoundError(f"Invalid --problems-jsonl: {args.problems_jsonl}")
    if not Path(args.workspace_path).is_dir():
        raise NotADirectoryError(f"Invalid --workspace-path: {args.workspace_path}")

    problems_lookup = _build_problem_lookup(args.problems_jsonl)

    name_filter: set[str] | None = None
    if args.filter_name:
        name_filter = {_sanitize_name(n.strip()) for n in args.filter_name.split(",") if n.strip()}

    tasks: list[TaskState] = []
    for subdir in sorted(p for p in args.results_dir.iterdir() if p.is_dir()):
        if name_filter is not None and subdir.name not in name_filter:
            continue
        if not (subdir / "progress.jsonl").exists():
            print(f"[warn] Skipping {subdir.name}: no progress.jsonl")
            continue
        if subdir.name not in problems_lookup:
            raise KeyError(f"Result subdir '{subdir.name}' not found in problems jsonl")
        tasks.append(TaskState(subdir, problems_lookup[subdir.name]))

    n_pending = sum(1 for t in tasks if t.status == "pending")
    print(f"Loaded {len(tasks)} tasks; {n_pending} have improved proofs to verify")

    run_verification_rounds(
        tasks=tasks,
        workspace_path=args.workspace_path,
        timeout=args.timeout,
        max_concurrent_requests=args.max_concurrent_requests,
    )

    print("\n=== Applying fixes ===")
    any_failed = False
    for task in tasks:
        if task.status in ("no_improvement", "verifier_error", "pending"):
            continue
        if task.failed_texts:
            any_failed = True
            if args.dry_run:
                print(f"[dry-run] [{task.name}] would remove {len(task.failed_texts)} proof(s) {task.failed_lengths}, final_length -> {task.final_length}")
                continue
            removed = rewrite_progress(task)
            update_result_json(task)
            update_best_proof(task)
            print(f"[{task.name}] removed {removed} progress line(s) for {len(task.failed_texts)} bad proof(s) {task.failed_lengths}; final_length -> {task.final_length}")
    if not any_failed:
        print("All shortest proofs compiled; no files needed fixing.")

    if not args.dry_run:
        update_summary(args.results_dir / "summary.json", tasks)

    write_report(tasks, args.output_path)

    print("\n=== Final status ===")
    for status in ("verified", "exhausted", "verifier_error", "no_improvement"):
        names = [t.name for t in tasks if t.status == status]
        if names:
            print(f"{status} ({len(names)}): " + ", ".join(names))


if __name__ == "__main__":
    main()

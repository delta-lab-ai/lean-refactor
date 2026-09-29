#!/usr/bin/env python3
"""
CLI for running proof golfing tasks with Claude Code.

Usage:
    python -m scripts.run_golf run --project-root <path> [--jsonl-file <path>] [options]
    python -m scripts.run_golf setup-project [--workspace-dir <path>]
    python -m scripts.run_golf cleanup --project-root <path>
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import fire

from .preprocessor import (
    cleanup_temp_files,
    cleanup_temp_files_by_pattern,
    load_tasks,
    prepare_tasks_for_resume,
)
from . import runner as runner_mod
from .runner import run_golf_tasks, print_summary
from .setup_project import setup_lean_project
from .task import GolfTaskMetadata, GolfTaskResult


def _find_eval_jsonl(project_root: Path) -> Path:
    """
    Find the eval JSONL file under project_root/eval/.

    Expected path: eval/eval_{folder_name}.jsonl where folder_name is
    the project root directory name (e.g. PutnamBench -> eval/eval_PutnamBench.jsonl).

    Raises FileNotFoundError if the expected file does not exist.
    """
    eval_dir = project_root / "eval"
    if not eval_dir.is_dir():
        raise FileNotFoundError(
            f"No eval/ directory found under project root: {project_root}"
        )

    folder_name = project_root.name
    expected = eval_dir / f"eval_{folder_name}.jsonl"
    if not expected.exists():
        raise FileNotFoundError(
            f"Expected eval file not found: {expected}\n"
            f"The file must be named eval_{{project_folder}}.jsonl "
            f"(e.g. eval_{folder_name}.jsonl)"
        )
    return expected


def _load_price_map(price_jsonl: Path) -> dict[str, float]:
    """Load per-task price caps from JSONL with keys: name, total_cost."""
    if not price_jsonl.exists():
        raise FileNotFoundError(f"Price JSONL file not found: {price_jsonl}")

    price_map: dict[str, float] = {}
    with open(price_jsonl, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"[warn] Skipping malformed price JSON at line {line_num} in {price_jsonl}: {exc}",
                    file=sys.stderr,
                )
                continue

            name = rec.get("name")
            if not isinstance(name, str) or not name.strip():
                print(
                    f"[warn] Skipping price record with missing/invalid 'name' at line {line_num} in {price_jsonl}",
                    file=sys.stderr,
                )
                continue

            try:
                raw_cost = float(rec.get("total_cost", 0.0))
            except (TypeError, ValueError):
                print(
                    f"[warn] Invalid 'total_cost' for '{name}' at line {line_num} in {price_jsonl}; using 0.30",
                    file=sys.stderr,
                )
                raw_cost = 0.30

            cost = math.floor(raw_cost * 100) / 100

            if cost < 0:
                print(
                    f"[warn] Negative 'total_cost' for '{name}' at line {line_num} in {price_jsonl}; using 0.30",
                    file=sys.stderr,
                )
                cost = 0.30

            price_map[name] = cost

    print(f"[info] Loaded {len(price_map)} price records from {price_jsonl}")
    return price_map


def _result_from_json(task: GolfTaskMetadata, data: dict) -> GolfTaskResult:
    """Reconstruct a successful prior result for the aggregate summary."""

    def parse_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def parse_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def parse_time(value: object) -> datetime:
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now()

    start_time = parse_time(data.get("start_time"))
    end_time = parse_time(data.get("end_time"))
    return GolfTaskResult(
        task_id=str(data.get("task_id") or task.task_id),
        name=task.name,
        success=True,
        initial_length=parse_int(
            data.get("initial_length"), task.initial_proof_length
        ),
        final_length=parse_int(data.get("final_length"), task.initial_proof_length),
        attempts=parse_int(data.get("attempts")),
        start_time=start_time,
        end_time=end_time,
        error_message=data.get("error_message"),
        terminal_reason=data.get("terminal_reason"),
        model=data.get("model") or task.model,
        cost_usd=parse_float(data.get("cost_usd")),
        input_tokens=parse_int(data.get("input_tokens")),
        output_tokens=parse_int(data.get("output_tokens")),
        cache_read_tokens=parse_int(data.get("cache_read_tokens")),
        cache_creation_tokens=parse_int(data.get("cache_creation_tokens")),
    )


class GolfRunner:
    """Proof golfing CLI (Claude Code)."""

    DEFAULT_SETUP_REPO_URL = "https://github.com/mikeljl/lean-projects-data"
    DEFAULT_SETUP_WORKSPACE_DIR = "workspace"

    @staticmethod
    def _print_kill_hint():
        pid = os.getpid()
        print(f"[info] Runner pid={pid}, stop command: kill -TERM {pid}")

    def run(
        self,
        project_root: str,
        jsonl_file: Optional[str] = None,
        price_jsonl: Optional[str] = None,
        output_dir: str = "results/golf",
        max_turns: int = 20,
        timeout_minutes: float = 120,
        parallel: bool = False,
        max_workers: int = 1,
        filter_name: Optional[str] = None,
        max_tasks: Optional[int] = None,
        cleanup: bool = True,
        model: Optional[str] = None,
        effort: Optional[str] = None,
    ) -> int:
        """
        Run proof optimization.

        By default, auto-discovers the eval JSONL file from
        <project_root>/eval/eval*.jsonl. Use --jsonl-file to override.

        Args:
            project_root: Lean project root directory
            jsonl_file: (optional) Path to input JSONL file; if omitted,
                        auto-discovered from eval/eval*.jsonl under project_root
            price_jsonl: (optional) Path to price JSONL with fields {name, total_cost};
                         when provided, sets a per-task budget passed to Claude Code as
                         --max-budget-usd
            output_dir: Directory for output files (default: results/golf)
            max_turns: Max turns per Claude session (default: 40)
            parallel: Whether to run tasks in parallel
            max_workers: Number of parallel Claude instances
            filter_name: Only optimize this specific theorem
            max_tasks: Limit number of tasks to process
            cleanup: Whether to remove temp files after completion (default: True)
            model: Model alias or full ID: "opus", "sonnet", "haiku", a full model ID, or
                   "deepseekv4pro" to route Claude Code at DeepSeek V4 Pro (needs
                   $DEEPSEEK_API_KEY; sets ANTHROPIC_BASE_URL/ANTHROPIC_MODEL and friends
                   per task instead of --model/--effort)
            effort: Thinking effort level ("low", "medium", "high", "max")
            timeout_minutes: Per-task wall-clock timeout in minutes; 0 = no limit (default: 60)

        Returns:
            0 on success, 1 on error
        """
        self._print_kill_hint()

        if runner_mod.is_deepseek_model(model):
            if not runner_mod.deepseek_token():
                print(
                    "[error] --model deepseekv4pro needs an API token. Export it first:\n"
                    "  export DEEPSEEK_API_KEY=sk-...\n"
                    "(ANTHROPIC_AUTH_TOKEN is also accepted.)",
                    file=sys.stderr,
                )
                return 1
            cfg = runner_mod.DEEPSEEK_V4_PRO
            print(
                f"[info] Routing Claude Code to {cfg['base_url']} — {cfg['primary']} "
                f"(fast model {cfg['fast']}), effort {effort or cfg['default_effort']}"
            )
            if price_jsonl:
                print(
                    "[info] Budgets are enforced at real DeepSeek rates by the runner "
                    "(cache-hit $0.003625 / cache-miss $0.435 / output $0.87 per Mtok for pro). "
                    "--max-budget-usd is NOT passed to Claude Code, which would price the cap "
                    "with its Anthropic rate table. cost_usd in result.json is re-priced too."
                )
            print(
                "[info] Prompt caching works on this endpoint and is reported in cache_read_tokens "
                "(measured ~75% of input on a 4-turn session). Caching is per-session, so it only "
                "kicks in from the second turn onward; cache_creation_tokens is always 0 here."
            )

        project_root_path = Path(project_root).resolve()
        output_path = Path(output_dir).resolve()
        price_path: Optional[Path] = None
        price_map: dict[str, float] = {}

        # Resolve JSONL path: auto-discover or use explicit override
        if jsonl_file is None:
            jsonl_path = _find_eval_jsonl(project_root_path)
            print(f"[info] Auto-discovered eval file: {jsonl_path}")
        else:
            jsonl_path = Path(jsonl_file)
            if not jsonl_path.is_absolute():
                candidate = project_root_path / jsonl_file
                if candidate.exists():
                    jsonl_path = candidate

        if price_jsonl:
            price_path = Path(price_jsonl)
            if not price_path.is_absolute():
                candidate = project_root_path / price_jsonl
                if candidate.exists():
                    price_path = candidate
            price_path = price_path.resolve()
            try:
                price_map = _load_price_map(price_path)
            except FileNotFoundError as e:
                print(f"[error] {e}", file=sys.stderr)
                return 1

        try:
            # Load and prepare tasks
            tasks = load_tasks(
                jsonl_path=str(jsonl_path),
                project_root=project_root,
                output_dir=output_dir,
                max_turns=max_turns,
                timeout_minutes=timeout_minutes if timeout_minutes > 0 else None,
                filter_name=filter_name,
                max_tasks=max_tasks,
                model=model,
                effort=effort,
            )

            if not tasks:
                print("[warn] No tasks to run.")
                return 0

            tasks_to_run, successful_tasks = prepare_tasks_for_resume(tasks)

            if not tasks_to_run:
                print("[info] All selected tasks already completed successfully.")
                return 0

            # The aggregate summary is stale as soon as any task is retried. It
            # will be recreated from successful prior results and fresh results.
            summary_file = output_path / "summary.json"
            if summary_file.exists():
                summary_file.unlink()

            if price_path is not None:
                default_budget = 0.30
                for task in tasks_to_run:
                    if task.name in price_map:
                        task.max_budget_usd = price_map[task.name]
                    else:
                        print(
                            f"[warn] Task '{task.name}' not found in price JSONL; using default budget ${default_budget:.2f}",
                            file=sys.stderr,
                        )
                        task.max_budget_usd = default_budget
                    print(f"[info] Budget for task '{task.name}': ${task.max_budget_usd:.2f}")

            # Run tasks
            fresh_results = run_golf_tasks(
                tasks=tasks_to_run,
                parallel=parallel,
                max_workers=max_workers,
            )
            fresh_results_by_name = {result.name: result for result in fresh_results}
            successful_results_by_name = {
                task.name: _result_from_json(task, result_data)
                for task, result_data in successful_tasks
            }
            results = [
                fresh_results_by_name.get(task.name)
                or successful_results_by_name[task.name]
                for task in tasks
            ]

            # Print summary
            print_summary(results)

            # Save aggregate results
            output_path.mkdir(parents=True, exist_ok=True)
            total_initial_tokens = sum(r.initial_length for r in results)
            total_final_tokens = sum(r.final_length for r in results)
            avg_reduction_percentage = (
                sum(r.reduction_pct for r in results) / len(results)
                if results else 0.0
            )
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "total_tasks": len(results),
                        "improved": sum(1 for r in results if r.success),
                        "total_initial_tokens": total_initial_tokens,
                        "total_final_tokens": total_final_tokens,
                        "total_tokens_saved": sum(max(0, r.tokens_saved) for r in results),
                        "avg_reduction_percentage": round(avg_reduction_percentage, 2),
                        "total_cost_usd": sum(r.cost_usd for r in results),
                        "usage": {
                            "input_tokens": sum(r.input_tokens for r in results),
                            "output_tokens": sum(r.output_tokens for r in results),
                            "cache_read_tokens": sum(r.cache_read_tokens for r in results),
                            "cache_creation_tokens": sum(r.cache_creation_tokens for r in results),
                        },
                        "results": [r.to_dict() for r in results],
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"[info] Summary saved to {summary_file}")

            # Cleanup temp files
            if cleanup:
                print("[info] Cleaning up temp files...")
                cleanup_temp_files(tasks_to_run)

            return 0

        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def setup_project(
        self,
        workspace_dir: str = DEFAULT_SETUP_WORKSPACE_DIR,
    ) -> int:
        """
        Build Lean projects that already exist under workspace_dir.

        Args:
            workspace_dir: Parent directory containing Lean projects (default: ./workspace)

        Returns:
            0 on success, 1 on error
        """
        try:
            setup_lean_project(workspace_dir)
            return 0
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1

    def cleanup(
        self,
        project_root: str,
    ) -> int:
        """
        Remove temp .lean files from a previous run.

        Args:
            project_root: Lean project root directory

        Returns:
            0 on success
        """
        cleanup_temp_files_by_pattern(project_root)
        return 0


def main():
    fire.Fire(GolfRunner)


if __name__ == "__main__":
    main()

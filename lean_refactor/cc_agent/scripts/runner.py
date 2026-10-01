"""
Core runner functions for executing Claude Code (`claude -p`) on proof golfing tasks.

Adapted from numina-lean-agent/scripts/runner.py.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import deepseek_endpoint
from .task import GolfTaskMetadata, GolfTaskResult

# Enable line buffering for real-time output when redirecting to file
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Global registry of active Claude subprocesses for clean shutdown on Ctrl+C
_active_procs: set[subprocess.Popen] = set()
_active_procs_lock = threading.Lock()


def _register_proc(proc: subprocess.Popen) -> None:
    with _active_procs_lock:
        _active_procs.add(proc)


def _unregister_proc(proc: subprocess.Popen) -> None:
    with _active_procs_lock:
        _active_procs.discard(proc)


def _kill_all_procs(signum, frame) -> None:
    with _active_procs_lock:
        procs = list(_active_procs)
    if procs:
        print(f"\n[info] Killing {len(procs)} active agent process(es)...", file=sys.stderr)
        for proc in procs:
            try:
                proc.kill()
            except OSError:
                pass
    sys.exit(1)


signal.signal(signal.SIGINT, _kill_all_procs)
signal.signal(signal.SIGTERM, _kill_all_procs)

# Absolute path to the prompt template and check_proof tool
PROJECT_DIR = Path(__file__).resolve().parent.parent
PROMPT_TEMPLATE_PATH = PROJECT_DIR / "prompts" / "prompt_golf.txt"
CHECK_PROOF_PATH = PROJECT_DIR / "tools" / "check_proof.py"

MODEL_ALIASES = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-4-5-20251001",
}

# Claude Code can be pointed at any Anthropic-compatible endpoint. These --model values
# select a third-party provider: the model and endpoint are set through environment
# variables rather than --model/--effort, which the proxy does not understand.
DEEPSEEK_V4_PRO = {
    "aliases": ("deepseekv4pro", "deepseek-v4-pro", "deepseek"),
    "base_url": "https://api.deepseek.com/anthropic",
    "primary": "deepseek-v4-pro[1m]",   # opus/sonnet slots
    "fast": "deepseek-v4-flash",        # haiku slot + subagents
    "default_effort": "max",
}

# Env var holding the endpoint token, checked in this order.
DEEPSEEK_TOKEN_ENV_VARS = ("DEEPSEEK_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def is_deepseek_model(model: Optional[str]) -> bool:
    return bool(model) and model.strip().lower() in DEEPSEEK_V4_PRO["aliases"]


def deepseek_token() -> Optional[str]:
    for var in DEEPSEEK_TOKEN_ENV_VARS:
        token = os.environ.get(var)
        if token:
            return token
    return None


def deepseek_env_overrides(effort: Optional[str]) -> dict[str, str]:
    """
    Environment for routing Claude Code to DeepSeek V4 Pro.

    The token is read from $DEEPSEEK_API_KEY (or $ANTHROPIC_AUTH_TOKEN) so it never has to
    live in the repo. Model and effort are set here rather than on the command line: the
    endpoint does not accept Anthropic model IDs, so `--model`/`--effort` are omitted from
    argv when this provider is selected.
    """
    token = deepseek_token()
    if not token:
        raise RuntimeError(
            "DeepSeek endpoint selected but no API token found. Export it first:\n"
            "  export DEEPSEEK_API_KEY=sk-..."
        )
    cfg = DEEPSEEK_V4_PRO
    return {
        "ANTHROPIC_BASE_URL": cfg["base_url"],
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_MODEL": cfg["primary"],
        "ANTHROPIC_DEFAULT_OPUS_MODEL": cfg["primary"],
        "ANTHROPIC_DEFAULT_SONNET_MODEL": cfg["primary"],
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": cfg["fast"],
        "CLAUDE_CODE_SUBAGENT_MODEL": cfg["fast"],
        "CLAUDE_CODE_EFFORT_LEVEL": effort or cfg["default_effort"],
    }


def build_prompt(task: GolfTaskMetadata) -> str:
    """Build the full prompt for a golfing task by interpolating the template."""
    template_path = PROMPT_TEMPLATE_PATH
    template = template_path.read_text(encoding="utf-8")
    print(f"[info] Using prompt template from path: {str(template_path)}")

    # Format contexts (limit to most relevant ones to save prompt space)
    formatted_contexts = ""
    if task.contexts:
        # Include up to 10 context entries
        for ctx in task.contexts[:10]:
            ctx_name = ctx.get("name", "unknown")
            ctx_kind = ctx.get("kind", "")
            ctx_sig = ctx.get("signature", "")
            formatted_contexts += f"### `{ctx_name}` ({ctx_kind})\n```lean4\n{ctx_sig}\n```\n\n"

    if not formatted_contexts:
        formatted_contexts = "(No additional context provided)\n"

    # task_dir is the parent of progress_file (e.g. output_dir/sanitized_name/)
    task_dir = str(task.progress_file.parent)

    prompt = template.format(
        name=task.name,
        temp_file_path=str(task.temp_file_path),
        proof_length=task.initial_proof_length,
        signature=task.signature,
        check_proof_path=str(CHECK_PROOF_PATH),
        progress_file=str(task.progress_file),
        best_proof_file=str(task.best_proof_file),
        current_proof_file=str(task.current_proof_file),
        task_dir=task_dir,
        formatted_contexts=formatted_contexts,
    )
    return prompt


def run_claude_once(
    args: list[str],
    env: Optional[dict] = None,
    cwd: Optional[Path] = None,
    json_save_path: Optional[Path] = None,
    timeout_seconds: Optional[float] = None,
    deepseek_budget_usd: Optional[float] = None,
    task_name: str = "",
) -> tuple[int, Optional[dict], bool, bool]:
    """
    Execute a single claude command with stream-json output.

    Args:
        args: Claude command arguments list
        env: Environment variables
        cwd: Working directory
        json_save_path: Path to save the raw NDJSON stream
        timeout_seconds: If set, kill the process after this many seconds
        deepseek_budget_usd: If set, enforce this cap using real DeepSeek prices by tailing
            the stream (used instead of --max-budget-usd, which prices at Anthropic rates)
        task_name: Task name, for budget log lines

    Returns:
        (returncode, claude_result, timed_out, budget_exceeded)
        claude_result: Parsed dict from the final type:"result" JSON line, or None
        timed_out: True if the process was killed due to timeout
        budget_exceeded: True if the DeepSeek budget watcher killed the process
    """
    if json_save_path is None:
        tmp_name = f"claude_golf_{uuid.uuid4().hex[:8]}.jsonl"
        json_save_path = Path(tempfile.gettempdir()) / tmp_name

    json_save_path.parent.mkdir(parents=True, exist_ok=True)

    current_pid = os.getpid()
    print(f"[info] Launching Claude: cwd={cwd}")
    print(f"[info] Runner pid={current_pid}")
    if timeout_seconds is not None:
        print(f"[info] Task timeout: {timeout_seconds:.0f}s ({timeout_seconds / 60:.1f}m)")

    timed_out = False
    watcher: Optional[deepseek_endpoint.BudgetWatcher] = None
    with open(json_save_path, "w", encoding="utf-8") as stdout_target:
        proc = subprocess.Popen(
            args,
            stdout=stdout_target,
            stderr=subprocess.STDOUT,
            text=True,
            env=env or None,
            cwd=str(cwd) if cwd else None,
        )
        _register_proc(proc)
        try:
            if deepseek_budget_usd is not None:
                watcher = deepseek_endpoint.BudgetWatcher(
                    proc=proc,
                    stream_path=json_save_path,
                    budget_usd=deepseek_budget_usd,
                    task_name=task_name,
                )
                watcher.start()
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            print(
                f"[warn] Claude pid={proc.pid} exceeded timeout of {timeout_seconds:.0f}s, killing...",
                file=sys.stderr,
            )
            proc.kill()
            proc.wait()
        finally:
            _unregister_proc(proc)

    budget_exceeded = bool(watcher and watcher.triggered)
    if watcher is not None:
        watcher.join(timeout=10.0)

    if timed_out:
        print(f"[warn] Claude pid={proc.pid} killed after timeout (exit code {proc.returncode})")
    elif budget_exceeded:
        print(f"[warn] Claude pid={proc.pid} killed after exceeding DeepSeek budget "
              f"(exit code {proc.returncode})")
    else:
        print(f"[info] Claude pid={proc.pid} exited with code {proc.returncode}")

    # Parse the result line from the NDJSON stream (search backward)
    claude_result = None
    try:
        lines = []
        with open(json_save_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip()]

        for line in reversed(lines):
            try:
                parsed = json.loads(line)
                if parsed.get("type") == "result":
                    claude_result = parsed
                    result_text = parsed.get("result", "")
                    if len(result_text) > 500:
                        print(f"[info] Claude result (truncated): {result_text[:500]}...")
                    else:
                        print(f"[info] Claude result: {result_text}")
                    break
            except json.JSONDecodeError:
                continue
    except OSError:
        pass

    if claude_result is None:
        print(f"[warn] No type='result' line found in {json_save_path}", file=sys.stderr)

    return proc.returncode, claude_result, timed_out, budget_exceeded


def extract_usage_cost(claude_result: Optional[dict]) -> float:
    """Extract total cost from claude result dict."""
    if not claude_result:
        return 0.0
    try:
        return claude_result.get("total_cost_usd", 0.0) or 0.0
    except (AttributeError, TypeError):
        return 0.0


def extract_usage_tokens(claude_result: Optional[dict]) -> tuple[int, int, int, int]:
    """
    Extract token usage from claude result dict.

    Returns:
        (input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens)
        output_tokens includes thinking tokens when --effort is set.
    """
    if not claude_result:
        return 0, 0, 0, 0
    try:
        usage = claude_result.get("usage") or {}
        return (
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
            int(usage.get("cache_read_input_tokens", 0) or 0),
            int(usage.get("cache_creation_input_tokens", 0) or 0),
        )
    except (AttributeError, TypeError, ValueError):
        return 0, 0, 0, 0


def read_progress(progress_file: Path) -> tuple[int, int]:
    """
    Read progress file to get attempt count and best length.

    Returns:
        (attempt_count, best_length)
    """
    if not progress_file.exists():
        return 0, 0

    attempt_count = 0
    best_length = 10**9
    with open(progress_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                attempt_count += 1
                length = record.get("length", 10**9)
                if record.get("improved", False):
                    best_length = min(best_length, length)
                # Track the running best from the best_length field
                rec_best = record.get("best_length", 10**9)
                best_length = min(best_length, rec_best)
            except json.JSONDecodeError:
                continue

    return attempt_count, best_length


def run_golf_task(task: GolfTaskMetadata) -> GolfTaskResult:
    """Execute a single proof golfing task."""
    start_time = datetime.now()
    error_message = None

    try:
        # Build prompt
        prompt = build_prompt(task)

        is_deepseek = is_deepseek_model(task.model)
        if is_deepseek:
            resolved_model = DEEPSEEK_V4_PRO["primary"]
        else:
            resolved_model = MODEL_ALIASES.get(task.model, task.model) if task.model else None

        print(f"\n{'=' * 60}")
        print(f"[info] Starting task: {task.name}")
        if resolved_model:
            print(f"[info] Model: {resolved_model}")
        if is_deepseek:
            print(f"[info] Endpoint: {DEEPSEEK_V4_PRO['base_url']} (model/effort set via environment)")
        if task.effort:
            print(f"[info] Effort: {task.effort}")
        elif is_deepseek:
            print(f"[info] Effort: {DEEPSEEK_V4_PRO['default_effort']} (default for this endpoint)")
        print(f"[info] Initial proof length: {task.initial_proof_length} tokens")
        print(f"[info] Temp file: {task.temp_file_path}")
        print(f"[info] Max turns: {task.max_turns}")
        if task.max_budget_usd is not None:
            print(f"[info] Max budget: ${task.max_budget_usd:.2f}")
        print(f"{'=' * 60}\n")

        # Build environment
        env = os.environ.copy()

        result_dir = task.progress_file.parent
        result_dir.mkdir(parents=True, exist_ok=True)
        timeout_seconds = task.timeout_minutes * 60 if task.timeout_minutes else None

        cmd = [
            "claude",
            "-p",
            "--verbose",
            "--output-format", "stream-json",
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(task.max_turns),
        ]

        if is_deepseek:
            # The endpoint rejects Anthropic model IDs, so model and effort are passed
            # through the environment instead of --model/--effort.
            env.update(deepseek_env_overrides(task.effort))
        else:
            if resolved_model:
                cmd += ["--model", resolved_model]

            if task.effort:
                cmd += ["--effort", task.effort]

        # Claude Code prices every model with its own Anthropic rate table, so on the
        # DeepSeek endpoint --max-budget-usd would cap Opus-equivalent dollars. Enforce
        # the cap ourselves from the stream, at real DeepSeek prices, instead.
        deepseek_budget = task.max_budget_usd if (is_deepseek and task.max_budget_usd) else None
        if task.max_budget_usd is not None and not is_deepseek:
            cmd += ["--max-budget-usd", f"{task.max_budget_usd:.2f}"]

        cmd.append(prompt)

        json_save_path = result_dir / "claude_raw.jsonl"

        returncode, claude_result, timed_out, budget_exceeded = run_claude_once(
            cmd,
            env=env,
            cwd=task.project_root,
            json_save_path=json_save_path,
            timeout_seconds=timeout_seconds,
            deepseek_budget_usd=deepseek_budget,
            task_name=task.name,
        )

        # Check for process failure vs expected termination
        terminal_reason = claude_result.get("terminal_reason") if claude_result else None
        if timed_out:
            terminal_reason = "timeout"
            error_message = f"Claude killed after {timeout_seconds:.0f}s timeout"
            print(f"[warn] {error_message}", file=sys.stderr)
        elif budget_exceeded:
            terminal_reason = "budget_exceeded"
            error_message = f"Claude killed after exceeding ${task.max_budget_usd:.2f} DeepSeek budget"
            print(f"[warn] {error_message}", file=sys.stderr)
        elif claude_result is None:
            error_message = f"Claude process exited with code {returncode}, no result produced (possible crash)"
            print(f"[warn] {error_message}", file=sys.stderr)
        elif terminal_reason == "max_turns":
            print(f"[info] Claude reached max turns ({task.max_turns})")
        elif returncode != 0:
            error_message = f"Claude process exited with code {returncode} (terminal_reason={terminal_reason})"
            print(f"[warn] {error_message}", file=sys.stderr)

        cost = extract_usage_cost(claude_result)
        input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens = extract_usage_tokens(claude_result)
        if is_deepseek:
            if claude_result is not None:
                reported = cost
                cost = deepseek_endpoint.estimate_cost_usd(claude_result)
                print(
                    f"[info] Re-priced at DeepSeek rates: ${cost:.6f} "
                    f"(Claude Code reported ${reported:.4f} using its Anthropic rate table)"
                )
            else:
                # Killed before the final result line (budget/timeout): recover usage
                # from the per-turn assistant events instead of reporting zeros.
                totals = deepseek_endpoint.stream_totals(json_save_path)
                cost = totals["cost_usd"]
                input_tokens = totals["input_tokens"]
                cache_read_tokens = totals["cache_read_tokens"]
                output_tokens = totals["output_tokens"]
                cache_creation_tokens = 0
                print(
                    f"[info] No result line (session was killed); recovered usage from the "
                    f"stream: ${cost:.6f} at DeepSeek rates"
                )

        # Read progress to determine outcome
        attempts, best_length = read_progress(task.progress_file)

        if best_length >= 10**9:
            # No successful check_proof calls — use initial length
            best_length = task.initial_proof_length

        success = best_length < task.initial_proof_length

    except Exception as e:
        error_message = str(e)
        terminal_reason = "exception"
        attempts = 0
        best_length = task.initial_proof_length
        success = False
        cost = 0.0
        resolved_model = task.model
        input_tokens = output_tokens = cache_read_tokens = cache_creation_tokens = 0
        print(f"[error] Task {task.name} failed: {e}", file=sys.stderr)

    end_time = datetime.now()

    result = GolfTaskResult(
        task_id=task.task_id,
        name=task.name,
        success=success,
        initial_length=task.initial_proof_length,
        final_length=best_length,
        attempts=attempts,
        start_time=start_time,
        end_time=end_time,
        error_message=error_message,
        terminal_reason=terminal_reason,
        model=resolved_model,
        cost_usd=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )

    print(f"\n[info] Task {task.name} completed:")
    print(f"  Success: {result.success}")
    print(f"  Initial length: {result.initial_length}")
    print(f"  Final length: {result.final_length}")
    print(f"  Tokens saved: {result.tokens_saved}")
    print(f"  Attempts: {result.attempts}")
    print(f"  Duration: {result.duration_seconds:.1f}s")
    if cost > 0:
        print(f"  Cost: ${cost:.4f}")
    if input_tokens or output_tokens or cache_read_tokens or cache_creation_tokens:
        total_input = input_tokens + cache_read_tokens + cache_creation_tokens
        print(f"  Total input tokens: {total_input:,}  Output tokens: {output_tokens:,}")
        print(f"    (fresh={input_tokens:,}  cache_read={cache_read_tokens:,}  cache_write={cache_creation_tokens:,})")

    # Save result JSON
    result_file = task.progress_file.parent / "result.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

    return result


def run_golf_tasks(
    tasks: list[GolfTaskMetadata],
    parallel: bool = False,
    max_workers: int = 1,
) -> list[GolfTaskResult]:
    """
    Execute multiple golfing tasks, optionally in parallel.

    Args:
        tasks: List of task metadata
        parallel: Whether to run in parallel
        max_workers: Maximum parallel workers

    Returns:
        List of results (in same order as tasks)
    """
    if not tasks:
        return []

    if not parallel or max_workers <= 1:
        results = []
        for i, task in enumerate(tasks, 1):
            print(f"\n[{i}/{len(tasks)}] Running task: {task.name}")
            result = run_golf_task(task)
            results.append(result)
        return results

    # Parallel execution
    print(f"\n[info] Running {len(tasks)} tasks in parallel (max_workers={max_workers})")
    results = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(run_golf_task, task): idx
            for idx, task in enumerate(tasks)
        }

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                task = tasks[idx]
                results[idx] = GolfTaskResult(
                    task_id=task.task_id,
                    name=task.name,
                    success=False,
                    initial_length=task.initial_proof_length,
                    final_length=task.initial_proof_length,
                    attempts=0,
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    error_message=str(e),
                    terminal_reason="exception",
                )
                print(f"[error] Task {task.name} raised exception: {e}", file=sys.stderr)

    return results


def print_summary(results: list[GolfTaskResult]) -> None:
    """Print a summary table of all results."""
    W = 90
    print(f"\n{'=' * W}")
    print(f"{'PROOF GOLFING SUMMARY':^{W}}")
    print(f"{'=' * W}")
    print(f"{'Name':<40} {'Init':>6} {'Final':>6} {'Saved':>6} {'Reduc%':>7} {'Attempts':>8} {'Time':>8}")
    print(f"{'-' * W}")

    total_saved = 0
    total_improved = 0
    total_time = 0.0
    total_cost = 0.0
    total_initial = 0
    total_final = 0

    for r in results:
        saved = r.tokens_saved
        total_saved += max(0, saved)
        total_initial += r.initial_length
        total_final += r.final_length
        if r.success:
            total_improved += 1
        total_time += r.duration_seconds
        total_cost += r.cost_usd

        marker = "+" if r.success else " "
        print(
            f"{marker}{r.name:<39} {r.initial_length:>6} {r.final_length:>6} "
            f"{saved:>6} {r.reduction_pct:>6.2f}% {r.attempts:>8} {r.duration_seconds:>7.0f}s"
        )

    print(f"{'-' * W}")
    avg_reduction_pct = sum(r.reduction_pct for r in results) / len(results) if results else 0.0
    print(f"Total: {total_improved}/{len(results)} improved, {total_saved} tokens saved, "
        f"{avg_reduction_pct:.2f}% avg reduction, {total_time:.0f}s elapsed, ${total_cost:.4f} cost")
    print(f"{'=' * W}")

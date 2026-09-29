"""
Real cost accounting for Claude Code runs routed at DeepSeek.

Claude Code prices every response with its own Anthropic rate table, so a DeepSeek run is
reported at Claude Opus 5 rates ($5/$25 per Mtok — verified empirically). That overstates
spend by more than an order of magnitude and makes `--max-budget-usd` fire far too early.

This module fixes both halves:

* `estimate_cost_usd()` re-prices a run from its token counts using DeepSeek's published
  rates, per model (pro and flash are billed very differently).
* `BudgetWatcher` tails the `claude_raw.jsonl` stream, which carries per-request usage on
  every `assistant` event, and kills the session when *real* DeepSeek cost reaches the cap.
  The runner therefore does not pass `--max-budget-usd` on this path.

Prompt caching works per session on this endpoint and cache reads are billed at ~1/120th of
fresh input, so the cache split dominates the arithmetic — pricing without it is meaningless.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# USD per 1M tokens (deepseek.ai published rates, checked 2026-08-07).
# `cache_hit` applies to cache_read_input_tokens, `cache_miss` to fresh input.
MODEL_PRICES: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {"cache_hit": 0.003625, "cache_miss": 0.435, "output": 0.87},
    "deepseek-v4-flash": {"cache_hit": 0.0028, "cache_miss": 0.14, "output": 0.28},
}
FALLBACK_PRICE = MODEL_PRICES["deepseek-v4-pro"]

_warned: set[str] = set()
_warned_lock = threading.Lock()


def load_price_overrides(path: Optional[str] = None) -> None:
    """Merge per-model price overrides from a JSON file into MODEL_PRICES."""
    path = path or os.environ.get("DEEPSEEK_PRICES_JSON")
    if not path:
        return
    price_path = Path(path).expanduser()
    if not price_path.exists():
        raise FileNotFoundError(f"DeepSeek prices JSON not found: {price_path}")
    data = json.loads(price_path.read_text(encoding="utf-8"))
    for slug, rates in data.items():
        entry = dict(MODEL_PRICES.get(_normalize_model(slug), FALLBACK_PRICE))
        for key in ("cache_hit", "cache_miss", "output"):
            if key in rates:
                entry[key] = float(rates[key])
        MODEL_PRICES[_normalize_model(slug)] = entry
    print(f"[info] Loaded DeepSeek price overrides for {len(data)} model(s) from {price_path}")


def _normalize_model(model: Optional[str]) -> str:
    """Strip context-window suffixes: 'deepseek-v4-pro[1m]' -> 'deepseek-v4-pro'."""
    if not model:
        return "deepseek-v4-pro"
    return model.split("[", 1)[0].strip()


def _prices_for(model: Optional[str]) -> dict[str, float]:
    key = _normalize_model(model)
    if key in MODEL_PRICES:
        return MODEL_PRICES[key]
    with _warned_lock:
        if key not in _warned:
            _warned.add(key)
            print(
                f"[warn] No DeepSeek price table for '{key}'; using deepseek-v4-pro rates.",
                file=sys.stderr,
            )
    return FALLBACK_PRICE


def cost_for_usage(model: Optional[str], fresh_input: int, cache_read: int, output: int) -> float:
    rates = _prices_for(model)
    return (
        max(0, fresh_input) * rates["cache_miss"]
        + max(0, cache_read) * rates["cache_hit"]
        + max(0, output) * rates["output"]
    ) / 1_000_000.0


def estimate_cost_usd(claude_result: Optional[dict]) -> float:
    """
    Re-price a finished run at DeepSeek rates.

    Prefers the per-model `modelUsage` breakdown on the result line (pro and flash differ by
    ~3x), falling back to the flat `usage` block priced as pro.
    """
    if not claude_result:
        return 0.0

    model_usage = claude_result.get("modelUsage") or {}
    if model_usage:
        total = 0.0
        for model, u in model_usage.items():
            total += cost_for_usage(
                model,
                int(u.get("inputTokens", 0) or 0),
                int(u.get("cacheReadInputTokens", 0) or 0),
                int(u.get("outputTokens", 0) or 0),
            )
        return round(total, 8)

    u = claude_result.get("usage") or {}
    return round(
        cost_for_usage(
            None,
            int(u.get("input_tokens", 0) or 0),
            int(u.get("cache_read_input_tokens", 0) or 0),
            int(u.get("output_tokens", 0) or 0),
        ),
        8,
    )


# ── Live budget enforcement ─────────────────────────────────────────────────


class _StreamCostReader:
    """
    Incrementally tail claude_raw.jsonl, accumulating real DeepSeek cost.

    Every `assistant` event carries the usage of the request that produced it. The same
    message is emitted once per content block, so usage is counted once per message id.

    Limitation: this endpoint reports `output_tokens: 0` on live events — output is only
    finalized on the closing `result` line. Live cost therefore tracks input (fresh +
    cached) exactly but omits output, so the cap fires slightly late. Input dominates by
    orders of magnitude in this workload (tens of thousands of input tokens per turn vs
    hundreds of output), and the figure written to result.json is the complete one.
    """

    def __init__(self, path: Path):
        self.path = path
        self._offset = 0
        self._buffer = ""
        self._seen_messages: set[str] = set()
        self.cost = 0.0
        self.input_tokens = 0
        self.cache_read_tokens = 0
        self.output_tokens = 0

    def poll(self) -> float:
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                chunk = f.read()
                self._offset = f.tell()
        except OSError:
            return self.cost

        if not chunk:
            return self.cost

        self._buffer += chunk
        lines = self._buffer.split("\n")
        self._buffer = lines.pop()

        for line in lines:
            line = line.strip()
            if not line.startswith("{") or '"assistant"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "assistant":
                continue
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            if not usage:
                continue
            msg_id = message.get("id") or ""
            if msg_id and msg_id in self._seen_messages:
                continue
            if msg_id:
                self._seen_messages.add(msg_id)
            fresh = int(usage.get("input_tokens", 0) or 0)
            cached = int(usage.get("cache_read_input_tokens", 0) or 0)
            out = int(usage.get("output_tokens", 0) or 0)
            self.input_tokens += fresh
            self.cache_read_tokens += cached
            self.output_tokens += out
            self.cost += cost_for_usage(message.get("model"), fresh, cached, out)
        return self.cost


def stream_totals(stream_path: Path) -> dict:
    """
    Recover usage from a `claude_raw.jsonl` that has no final `result` line.

    A session killed by the budget watcher or the timeout never emits `type: "result"`, so
    the per-turn `assistant` events are the only record of what it spent.
    """
    reader = _StreamCostReader(stream_path)
    reader.poll()
    return {
        "input_tokens": reader.input_tokens,
        "cache_read_tokens": reader.cache_read_tokens,
        "output_tokens": reader.output_tokens,
        "cost_usd": round(reader.cost, 8),
    }


class BudgetWatcher(threading.Thread):
    """Kill a `claude -p` session once its real DeepSeek cost reaches `budget_usd`."""

    def __init__(
        self,
        proc: subprocess.Popen,
        stream_path: Path,
        budget_usd: float,
        task_name: str,
        poll_interval: float = 5.0,
    ):
        super().__init__(daemon=True)
        self.proc = proc
        self.stream_path = stream_path
        self.budget_usd = budget_usd
        self.task_name = task_name
        self.poll_interval = poll_interval
        self.triggered = False
        self.cost = 0.0

    def run(self) -> None:
        reader = _StreamCostReader(self.stream_path)
        while self.proc.poll() is None:
            self.cost = reader.poll()
            if self.cost >= self.budget_usd:
                self.triggered = True
                print(
                    f"[warn] Task {self.task_name}: DeepSeek cost ${self.cost:.4f} reached budget "
                    f"${self.budget_usd:.2f}, killing Claude pid={self.proc.pid}...",
                    file=sys.stderr,
                )
                try:
                    self.proc.kill()
                except OSError:
                    pass
                return
            time.sleep(self.poll_interval)
        self.cost = reader.poll()

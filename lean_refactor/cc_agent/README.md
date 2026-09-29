# cc_agent

Claude Code agent for Lean 4 proof optimization (proof golfing). It reads a JSONL of theorems,
creates one isolated temp `.lean` file per theorem (parallel-safe), and launches a `claude -p`
session per theorem that iteratively shortens the proof while keeping the file compiling.
Results, per-attempt progress, and cost/token usage are recorded per task.

All commands below are run from this directory (`lean_refactor/cc_agent`). It has its own Python
environment, separate from the top-level `lean-refactor` one.

## Setup

Requirements: [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) (logged in, or
`ANTHROPIC_API_KEY` set), [`uv`/`uvx`](https://docs.astral.sh/uv/), Python ≥ 3.10, and
[elan](https://github.com/leanprover/elan) (`lake`).

```bash
cd lean_refactor/cc_agent

# 1) One-time: installs the lean4-skills plugin (project scope), registers the lean-lsp MCP
#    server in .mcp.json, and runs `uv sync`
bash setup.sh
source .venv/bin/activate

# 2) Build every Lean project under ./workspace (lake exe cache get + lake build)
python -m scripts.run_golf setup-project
```

`workspace/analysis` is bundled as an example project (Mathlib `v4.24.0`), with a 10-theorem
eval file at `workspace/analysis/eval/eval_analysis.jsonl` and matching per-task budgets in
`workspace/analysis/price.jsonl`.

### Adding your own project

Each project must be a direct child of `./workspace` and contain
`eval/eval_<project_folder_name>.jsonl`. Produce that file with the extraction pipeline in
`data_extraction/` at the repository root (see the top-level README, section 3.1), then copy the
extracted project in and build it:

```bash
rsync -av --exclude='.lake' /path/to/extracted-project/ ./workspace/<project_name>/
python -m scripts.run_golf setup-project
```

## How to run

Run on the bundled example with Haiku, 5 parallel workers, and per-task budgets:

```bash
python -m scripts.run_golf run \
  --project-root workspace/analysis \
  --output-dir results/analysis_golf \
  --price-jsonl workspace/analysis/price.jsonl \
  --model haiku \
  --parallel \
  --max-workers 5 \
  2>&1 | tee analysis_golf.log
```

The eval JSONL is auto-discovered at `<project-root>/eval/eval_<project_folder_name>.jsonl`
(override with `--jsonl-file`). To try a single theorem first, add
`--filter-name "Chapter5.Sequence.equiv_example"`.

### Options (`run`)

| Option | Default | Meaning |
| --- | --- | --- |
| `--project-root` | (required) | Lean project root; also the cwd for each `claude` process |
| `--jsonl-file` | auto-discovered | Explicit eval JSONL override |
| `--output-dir` | `results/golf` | Per-task artifacts + `summary.json` |
| `--max-turns` | `20` | Max turns per Claude session |
| `--timeout-minutes` | `120` | Per-task wall-clock limit; `0` = no limit |
| `--parallel` / `--max-workers` | `False` / `1` | `ThreadPoolExecutor` fan-out, one temp file per task |
| `--model` | CLI default | `opus`→`claude-opus-5`, `sonnet`→`claude-sonnet-5`, `haiku`→`claude-haiku-4-5-20251001`, or a full model ID |
| `--effort` | CLI default | `low` \| `medium` \| `high` \| `max` |
| `--price-jsonl` | none | Per-task `--max-budget-usd` caps |
| `--filter-name` / `--max-tasks` | none | Run one theorem / cap task count |
| `--cleanup` | `True` | Remove temp `.lean` files after the run |

Other commands:

```bash
python -m scripts.run_golf setup-project [--workspace-dir workspace]
python -m scripts.run_golf cleanup --project-root workspace/analysis   # remove leftover temp .lean files
python -m unittest discover tests                                      # resume-logic tests
```

### Agent tools

The agent follows `prompts/prompt_golf.txt`. It can use the lean4-skills slash commands
`/lean4:golf` and `/lean4:refactor`, plus the lean-lsp MCP tools (`lean_diagnostic_messages`,
`lean_goal`, `lean_multi_attempt`, lemma search, ...). Both are installed by `setup.sh`.

### DeepSeek endpoint

`--model deepseekv4pro` points Claude Code at DeepSeek V4 Pro's Anthropic-compatible endpoint.
Export `DEEPSEEK_API_KEY` first. Cost is re-priced at DeepSeek rates, and budgets are enforced by
the runner rather than passed as `--max-budget-usd`.

### Budget caps (`--price-jsonl`)

JSONL with `{"name": ..., "total_cost": ...}` per line (`name` must match the eval JSONL).
`total_cost` is floored to 2 decimals and passed as `--max-budget-usd`. Names missing from the
price file fall back to `$0.30` with a warning. Each task's budget is logged before it starts.

### Resume behavior

Re-running with the same `--output-dir` skips any task whose `result.json` has `success: true`.
Every other task dir (failed, interrupted, unreadable) is deleted and re-prepared from the original
source, and `summary.json` is rebuilt from surviving and fresh results.

## Output layout

```
results/<run>/
  summary.json                     # totals: improved count, tokens saved, avg reduction, cost, usage, per-task results
  <sanitized_theorem_name>/
    result.json                    # success, initial/final length, tokens_saved, reduction_pct, attempts, cost, tokens
    progress.jsonl                 # one row per check_proof call (attempt 0 = original proof)
    best_proof.txt                 # shortest verified-shorter proof so far
    current_proof.txt              # proof the agent last submitted
    claude_raw.jsonl               # raw stream-json transcript of the Claude session
```

## Post-run verification

`check_proof.py` trusts the agent's `lean_diagnostic_messages` check, so re-verify final proofs
independently:

```bash
# Recompile each task's latest improved proof via the Lean LSP and write a report (no files modified)
python -m scripts.verify_lean_client_results \
  --results-dir results/analysis_golf \
  --problems-jsonl workspace/analysis/eval/eval_analysis.jsonl \
  --workspace-path workspace/analysis \
  --output-path results/analysis_golf/verify_report.jsonl \
  --max-concurrent-requests 5
```

`scripts.verify_and_fix_results` takes the same arguments, but also repairs records whose shortest
proof fails to compile by falling back to the next-shortest candidate (files are backed up to
`*.bak` first). `scripts/verify_putnam_results.py` verifies via the REPL-based verifier (problem
header + proof); set `DEFAULT_LEAN_WORKSPACE` to the Lean workspace it should use.

## Key files

| Path | Role |
| --- | --- |
| `scripts/run_golf.py` | Fire CLI (`run`, `setup-project`, `cleanup`): path resolution, price map, resume, summary writing |
| `scripts/runner.py` | Builds prompts, launches `claude -p --output-format stream-json`, parses cost/tokens, parallel executor, summary table |
| `scripts/deepseek_endpoint.py` | DeepSeek price tables, cost re-pricing, budget enforcement |
| `scripts/preprocessor.py` | Loads eval JSONL, creates temp `.lean` + task artifacts, resume selection, temp-file cleanup |
| `scripts/task.py` | `GolfTaskMetadata` / `GolfTaskResult` dataclasses |
| `scripts/setup_project.py` | `lake exe cache get` + `lake build` for each project under `workspace/` |
| `scripts/verify_lean_client_results.py`, `verify_and_fix_results.py`, `verify_putnam_results.py` | Post-run verification (LSP-based / LSP-based with repair / REPL-based) |
| `scripts/proof_utils.py` | `proof_length()` tokenizer (from goedels-poetry) |
| `tools/check_proof.py` | Agent-called tool: validates statement + file integrity, computes length, updates `best_proof.txt` and `progress.jsonl` |
| `lean_worker/` | leanclient LSP wrapper, multi-process LSP verifier, REPL verifier, scheduler base |
| `prompts/prompt_golf.txt` | Prompt template |
| `setup.sh` | One-time plugin/MCP/venv setup |
| `tests/` | `unittest` coverage of resume logic |

## Input JSONL format

One object per line: `{"name", "path", "proof_length", "src", "signature", "contexts": [...]}`.
`path` is relative to the project root, `src` is the full statement + proof, and `contexts` are
related declarations (the first 10 are injected into the prompt).

## Key constraints

- The agent may only edit the target proof body. The statement, other declarations, and imports
  must stay byte-identical (`check_proof.py` enforces both and prints the original to revert to).
- `check_proof.py` rejects any attempt containing `sorry`/`admit`/`sorryAx`.
- No helper lemmas or new declarations: optimization must be self-contained.
- Compilation is checked with `lean_diagnostic_messages` (severity 1), not `lake build`.
- Proof length is the custom tokenizer in `check_proof.py` / `scripts/proof_utils.py`.

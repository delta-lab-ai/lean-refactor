# Task: collect the initial heartbeats for a Lean project

You are preparing the heartbeats file for the proof-optimization agent in `lean_refactor/cc_agent`,
used when it runs in multi-objective mode (`--multi_objective --heartbeat_weight ...`). For every
theorem in the project's eval JSONL, record how many Lean heartbeats its ORIGINAL proof uses. The
agent scores every new proof relative to this number.

## Inputs (fill these in)

- **Project folder**: `lean_refactor/cc_agent/workspace/<PROJECT>` — must be a direct child of `workspace/`.

The eval file `workspace/<PROJECT>/eval/eval_<PROJECT>.jsonl` must already exist (see
`prompts/build_eval_jsonl.md`), and the project must be built (`python -m scripts.run_golf setup-project`).

## Output file — the name and location are mandatory

```
lean_refactor/cc_agent/workspace/<PROJECT>/eval/heartbeats_<PROJECT>.jsonl
```

The runner looks for exactly this path. One JSON object per line:

```json
{"name": "...", "path": "...", "proof_length": 0, "heartbeat": 1234}
```

`heartbeat` is an `int`, or `null` with an extra `"error"` key when the measurement failed.

## How to measure — use the provided script, do not count heartbeats yourself

Heartbeats must be measured exactly the way `tools/check_proof.py` measures them during the run,
otherwise every score is skewed. Run, from `lean_refactor/cc_agent`:

```bash
python3 tools/heartbeat.py --project-root workspace/<PROJECT> --jobs 4
```

It reads the eval JSONL and writes the output file above. For each theorem it copies the theorem's
file, adds `import Mathlib.Util.CountHeartbeats` after the imports (unless the file already has
`import Mathlib` or that import), inserts `set_option Elab.async false in` and `#count_heartbeats in`
right before the declaration (before its doc comment and attributes), runs `lake env lean` from the
project root, and parses the `Used N heartbeats` message. Useful options: `--filter-name <name>` to
measure one theorem, `--timeout <seconds>` (default 540), `--jobs <n>` (each job is a full Lean
process; lower it if memory is tight).

Do not edit `tools/heartbeat.py` or the project's `.lean` files. The script writes temporary
`*_hb_*.lean` files next to the originals and always deletes them.

## Handling failures

The script exits with code 1 if any theorem has `"heartbeat": null`. For each failure, read its
`error`:
- `lake binary not found` or an `incompatible header` / toolchain download error: the Lean
  environment is broken (wrong toolchain, project not built). Fix the environment, then re-run
  the whole script. Do not work around it.
- `timeout`: re-run that theorem alone with a larger `--timeout`. If it still times out, leave it as
  `null`.
- `src not found`: the eval JSONL's `src` is not an exact substring of the file. Report it; do not
  edit the eval file here.
- Lean errors (`lean exited with code 1: ...`): the file does not compile as-is. Report it and leave
  it as `null`.

Rows left as `null` are measured again by `check_proof.py` on that theorem's first call during the
run, which is slower but works.

To re-measure only some theorems, run the script with `--filter-name` and `--output` pointing to a
scratch file, then replace the corresponding lines in the output file. Keep one line per eval
theorem, in the eval file's order.

## Validation (run before finishing)

Write and run a short script that asserts:
1. The output file has exactly one line per line of the eval JSONL, with the same `name`s in the
   same order.
2. Every line is valid JSON with keys `name`, `path`, `proof_length`, `heartbeat` (and `error` only
   when `heartbeat` is `null`), and `heartbeat` is a positive `int` or `null`.

When finished, report: the output path, how many theorems were measured, and every theorem left as
`null` with its error.

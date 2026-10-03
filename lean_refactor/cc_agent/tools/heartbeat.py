#!/usr/bin/env python3
"""
Lean heartbeat measurement for proofs inside a Lean project (standard library only).

A declaration's heartbeats are measured in its real file context:

1. Take the project file containing the declaration, optionally with the
   declaration `src` replaced by a new version.
2. Insert, right before the declaration (before its doc comment/attributes):

       set_option Elab.async false in
       #count_heartbeats in

3. Add `import Mathlib.Util.CountHeartbeats` (where `#count_heartbeats` is
   defined) after the file's imports, unless the file already imports it or
   the whole of Mathlib (`import Mathlib`).
4. Rewrite `set_option maxHeartbeats 0` to a finite cap: with an unlimited
   ambient maximum, `#count_heartbeats` never terminates.
5. Write the result to a temp `.lean` file next to the original, run
   `lake env lean <temp-file>` from the project root, and parse
   `Used N heartbeats` from the output. The temp file is always removed.

A nonzero exit code means the file has errors; the count is then not trusted.

Library use (from tools/check_proof.py):

    from heartbeat import count_heartbeats_for_src
    heartbeats, error = count_heartbeats_for_src(project_root, file_path, src, new_src)

CLI use, to collect the original proofs' heartbeats for an eval set:

    python3 tools/heartbeat.py --project-root workspace/<PROJECT>

reads `<PROJECT>/eval/eval_<PROJECT>.jsonl` and writes
`<PROJECT>/eval/heartbeats_<PROJECT>.jsonl` with one
`{"name", "path", "proof_length", "heartbeat"}` row per theorem (plus
`"error"` when the measurement failed, in which case `heartbeat` is null).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_HEARTBEAT_TIMEOUT = 540.0

COUNT_HEARTBEATS_PREFIX = "set_option Elab.async false in\n#count_heartbeats in\n"
COUNT_HEARTBEATS_MODULE = "Mathlib.Util.CountHeartbeats"
_HEARTBEAT_RE = re.compile(r"Used (\d+) heartbeats")
# Matches one import line, e.g. `import Mathlib.Data.Nat`, `public import Foo`, `public meta import Bar`.
_IMPORT_RE = re.compile(r"^(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([^\s-]+)")
# `#count_heartbeats` loops forever when the ambient `maxHeartbeats` is 0 (unlimited).
_MAX_HEARTBEATS_ZERO_RE = re.compile(r"set_option\s+maxHeartbeats\s+0\b")
_MAX_HEARTBEATS_REPLACEMENT = "set_option maxHeartbeats 400000000"
_ERR_TAIL = 2000


def ensure_count_heartbeats_import(content: str) -> str:
    """
    Add `import Mathlib.Util.CountHeartbeats` after the file's last import, unless
    the file already imports that module or the whole of Mathlib (`import Mathlib`).
    """
    lines = content.split("\n")
    insert_at = 0  # line index right after the header (last import / `module` / `prelude`)
    comment_depth = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if comment_depth > 0 or stripped.startswith("/-"):
            comment_depth = max(0, comment_depth + stripped.count("/-") - stripped.count("-/"))
            continue
        if not stripped or stripped.startswith("--"):
            continue
        match = _IMPORT_RE.match(stripped)
        if match:
            if match.group(1) in ("Mathlib", COUNT_HEARTBEATS_MODULE):
                return content
            insert_at = i + 1
            continue
        if stripped in ("module", "prelude"):
            insert_at = i + 1
            continue
        # First command after the header: imports cannot appear past this point.
        break
    lines.insert(insert_at, f"import {COUNT_HEARTBEATS_MODULE}")
    return "\n".join(lines)


def instrument_for_heartbeats(content: str, decl_start: int) -> str:
    """Instrument a Lean file so compiling it reports the heartbeats of the declaration at `decl_start`."""
    content = content[:decl_start] + COUNT_HEARTBEATS_PREFIX + content[decl_start:]
    content = ensure_count_heartbeats_import(content)
    return _MAX_HEARTBEATS_ZERO_RE.sub(_MAX_HEARTBEATS_REPLACEMENT, content)


def count_heartbeats(
    project_root: str | Path,
    file_path: str | Path,
    content: str,
    decl_start: int,
    timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
) -> tuple[int | None, str | None]:
    """
    Measure the heartbeats of the declaration starting at `decl_start` in `content`.

    `content` is compiled as if it were `file_path` (the temp file is written next to it).

    Returns
    -------
    (heartbeats, None) on success, (None, error message) on failure.
    """
    root = Path(project_root).resolve()
    file_path = root / file_path  # absolute file_path stays as is
    temp_file = file_path.parent / f"{file_path.stem}_hb_{uuid.uuid4().hex[:8]}.lean"

    try:
        try:
            temp_file.write_text(instrument_for_heartbeats(content, decl_start), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return None, f"failed to write temp file: {e}"

        try:
            proc = subprocess.run(
                ["lake", "env", "lean", str(temp_file)],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None, f"timeout after {timeout:.0f}s"
        except FileNotFoundError:
            return None, "lake binary not found on PATH"
        except Exception as e:  # noqa: BLE001
            return None, f"subprocess failed: {e}"

        combined = (proc.stdout or "") + (proc.stderr or "")
        # A nonzero exit means the file has errors. #count_heartbeats still
        # prints "Used N heartbeats" for a failing declaration, but that count
        # can reflect an aborted elaboration, so it must not be trusted.
        if proc.returncode != 0:
            snippet = combined[-_ERR_TAIL:].strip() or "no output"
            return None, f"lean exited with code {proc.returncode}: {snippet}"
        match = _HEARTBEAT_RE.search(combined)
        if match:
            return int(match.group(1)), None
        snippet = combined[-_ERR_TAIL:].strip() or "no output"
        return None, f"no heartbeat count in output: {snippet}"
    finally:
        temp_file.unlink(missing_ok=True)


def count_heartbeats_for_src(
    project_root: str | Path,
    file_path: str | Path,
    src: str,
    new_src: str | None = None,
    timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
) -> tuple[int | None, str | None]:
    """
    Measure the heartbeats of a declaration of a project file.

    Parameters
    ----------
    project_root : str | Path
        Lean project root (contains the lakefile; must be built).
    file_path : str | Path
        The declaration's file, relative to `project_root` or absolute.
    src : str
        The declaration exactly as it appears in the file, starting at its doc
        comment/attributes (the eval JSONL `src`).
    new_src : str | None
        Replacement for `src` to measure instead (e.g. an optimized proof).
        None measures the declaration as it is in the file.
    timeout : float
        Timeout for `lake env lean` in seconds.

    Returns
    -------
    (heartbeats, None) on success, (None, error message) on failure.
    """
    path = Path(project_root).resolve() / file_path
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return None, f"failed to read {path}: {e}"
    pos = content.find(src)
    if pos == -1:
        return None, f"src not found in {path}"
    if new_src is not None:
        content = content[:pos] + new_src + content[pos + len(src) :]
    return count_heartbeats(project_root, path, content, pos, timeout=timeout)


def main() -> int:
    """Collect the heartbeats of every original proof in an eval JSONL."""
    ap = argparse.ArgumentParser(description="Measure Lean #count_heartbeats for every theorem of an eval JSONL.")
    ap.add_argument("--project-root", required=True, help="Lean project root, e.g. workspace/analysis (must be built).")
    ap.add_argument("--eval-jsonl", default=None, help="Eval JSONL (default: <project>/eval/eval_<project>.jsonl).")
    ap.add_argument("--output", default=None, help="Output JSONL (default: <project>/eval/heartbeats_<project>.jsonl).")
    ap.add_argument("--jobs", type=int, default=4, help="Parallel measurements (default 4).")
    ap.add_argument("--timeout", type=float, default=DEFAULT_HEARTBEAT_TIMEOUT, help="Per-theorem timeout in seconds.")
    ap.add_argument("--filter-name", default=None, help="Only measure this theorem.")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    eval_jsonl = Path(args.eval_jsonl) if args.eval_jsonl else root / "eval" / f"eval_{root.name}.jsonl"
    output = Path(args.output) if args.output else root / "eval" / f"heartbeats_{root.name}.jsonl"

    records = []
    with eval_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if args.filter_name is None or rec["name"] == args.filter_name:
                    records.append(rec)
    print(f"Measuring {len(records)} theorem(s) from {eval_jsonl} in {root}", flush=True)

    def measure(rec: dict) -> dict:
        heartbeat, error = count_heartbeats_for_src(root, rec["path"], rec["src"], timeout=args.timeout)
        row = {"name": rec["name"], "path": rec["path"], "proof_length": rec.get("proof_length"), "heartbeat": heartbeat}
        if error is not None:
            row["error"] = error
        status = f"heartbeat={heartbeat}" if heartbeat is not None else f"ERROR: {error[:200]}"
        print(f"  {rec['name']}: {status}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        rows = list(ex.map(measure, records))

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    measured = sum(1 for row in rows if row["heartbeat"] is not None)
    print(f"Wrote {output} ({measured}/{len(rows)} measured)")
    return 0 if measured == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())

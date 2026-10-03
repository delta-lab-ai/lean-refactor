"""
Multi-objective acceptance for Lean 4 proofs.

A compiled candidate proof is scored with a weighted scalarization of
proof length (f1) and compilation cost in Lean heartbeats (f2), each
normalized by the original proof's value:

    F_hat(proof) = length_weight * f1(proof) / f1(original)
                 + heartbeat_weight * f2(proof) / f2(original)

and accepted iff it improves the best score achieved so far:

    if verified(candidate) and F_hat(candidate) < best_score:
        best_proof, best_score = candidate, F_hat(candidate)

With (length_weight, heartbeat_weight) = (1, 0) this is the length-only
rule; with (0, 1) a longer-but-faster proof is accepted.

Heartbeats are measured by inserting ``#count_heartbeats in`` before the
declaration in a copy of its project file and running ``lake env lean``.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

COUNT_HEARTBEATS_MODULE = "Mathlib.Util.CountHeartbeats"
_HEARTBEAT_RE = re.compile(r"Used (\d+) heartbeats")
_IMPORT_RE = re.compile(r"^(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([^\s-]+)")
# `#count_heartbeats` never terminates when the ambient `maxHeartbeats` is 0 (unlimited).
_MAX_HEARTBEATS_ZERO_RE = re.compile(r"set_option\s+maxHeartbeats\s+0\b")


def ensure_count_heartbeats_import(content: str) -> str:
    """Add `import Mathlib.Util.CountHeartbeats` unless the file already imports it or all of Mathlib."""
    lines = content.split("\n")
    insert_at = 0
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
        break
    lines.insert(insert_at, f"import {COUNT_HEARTBEATS_MODULE}")
    return "\n".join(lines)


def count_heartbeats(
    project_root: str,
    relative_path: str,
    original_proof: str,
    new_proof: str,
    original_src: str | None = None,
    timeout: float = 600.0,
) -> int | None:
    """
    Heartbeats used to elaborate ``new_proof`` in place of ``original_proof`` inside its project file.

    ``original_src`` is the declaration as it appears in the file (with doc comment and
    attributes), used to insert ``#count_heartbeats in`` before them. Returns None on failure.
    """
    root = Path(project_root)
    content = (root / relative_path).read_text(encoding="utf-8")
    proof_pos = content.find(original_proof)
    if proof_pos == -1:
        return None
    src_pos = content.find(original_src) if original_src else -1
    decl_start = src_pos if src_pos != -1 and src_pos <= proof_pos else proof_pos

    content = content[:proof_pos] + new_proof + content[proof_pos + len(original_proof) :]
    content = content[:decl_start] + "set_option Elab.async false in\n#count_heartbeats in\n" + content[decl_start:]
    content = ensure_count_heartbeats_import(content)
    content = _MAX_HEARTBEATS_ZERO_RE.sub("set_option maxHeartbeats 400000000", content)

    rel = Path(relative_path)
    temp_rel = (rel.parent / f"temp_hb_{uuid.uuid4().hex[:8]}_{rel.name}").as_posix()
    try:
        (root / temp_rel).write_text(content, encoding="utf-8")
        proc = subprocess.run(
            ["lake", "env", "lean", temp_rel], cwd=root, capture_output=True, text=True, timeout=timeout
        )
    except Exception:  # noqa: BLE001
        return None
    finally:
        (root / temp_rel).unlink(missing_ok=True)
    match = _HEARTBEAT_RE.search(proc.stdout + proc.stderr)
    return int(match.group(1)) if proc.returncode == 0 and match else None


def evaluate_multi_objective_acceptance(opt_state, proof_state: dict, candidate: str, new_length: int) -> bool:
    """
    Accept ``candidate`` iff its scalarized score F_hat improves the best score so far.

    ``opt_state`` (a PlannerOptimizerState) holds the weights, the original proof's length and
    heartbeats, and ``best_score``; the original proof scores ``length_weight + heartbeat_weight``.
    """

    def measure(proof: str) -> int | None:
        return count_heartbeats(
            opt_state.heartbeat_project_root,
            proof_state["relative_path"],
            proof_state["original_proof"],
            proof,
            original_src=opt_state.original_src,
        )

    f_hat = opt_state.length_weight * new_length / opt_state.initial_proof_length
    if opt_state.heartbeat_weight != 0:
        if opt_state.initial_heartbeat is None:
            opt_state.initial_heartbeat = measure(proof_state["original_proof"])
        heartbeat = measure(candidate)
        if not opt_state.initial_heartbeat or heartbeat is None:
            return False
        f_hat += opt_state.heartbeat_weight * heartbeat / opt_state.initial_heartbeat

    if f_hat < opt_state.best_score:
        opt_state.best_score = f_hat
        return True
    return False

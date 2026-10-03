#!/usr/bin/env python3
"""
Standalone tool for checking and recording proof optimization attempts.

Called by the agent after each successful compilation.
Reads the current proof from current_proof.txt (written by the agent),
rejects incomplete proofs (`sorry`/`admit`), validates the theorem statement and file
context haven't changed, computes proof length, compares against the current best, and
records progress.

By default a proof is an improvement iff it is shorter than the best proof. If the task
directory contains objective.json (written by the runner in multi-objective mode), the
proof's Lean heartbeats are also measured (see heartbeat.py) and it is an improvement iff
it lowers the weighted score

    score = length_weight * length / initial_length + heartbeat_weight * heartbeats / initial_heartbeats

below the best score so far (the original proof scores length_weight + heartbeat_weight).

Only requires --proof-name, --temp-file-path, and --task-dir.
All other paths are derived:
  - original file: derived from temp file path by reversing the naming convention
  - current_proof.txt, best_proof.txt, progress.jsonl: under task-dir

Usage:
    python3 check_proof.py \
        --proof-name "IsElementary.measure_le_cover_sum" \
        --temp-file-path "/path/to/temp.lean" \
        --task-dir "/path/to/output/sanitized_name"
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from heartbeat import DEFAULT_HEARTBEAT_TIMEOUT, count_heartbeats_for_src


# ── Inlined proof utilities (from goedels-poetry/utils.py) ──────────────────


def _remove_comments(text: str) -> str:
    text = re.sub(r"/-.*?-/", "", text, flags=re.DOTALL)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        cleaned_line = line.split("--", 1)[0]
        if cleaned_line.strip() == "":
            continue
        cleaned_lines.append(cleaned_line)
    return "\n".join(cleaned_lines).strip()


def _parse_single_attribute(text: str, start: int):
    n = len(text)
    assert text[start] == "@" and start + 1 < n and text[start + 1] == "["
    i = start + 2
    depth = 1
    while i < n:
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _extract_and_remove_attributes(text: str):
    n = len(text)
    if n == 0:
        return "", text
    pos = 0
    while pos < n and text[pos].isspace():
        pos += 1
    if not (pos + 1 < n and text[pos] == "@" and text[pos + 1] == "["):
        return "", text
    attr_block_start = 0
    attr_block_end = attr_block_start
    cur = pos
    first_attr_start = pos
    while cur < n and text[cur] == "@" and cur + 1 < n and text[cur + 1] == "[":
        attr_end = _parse_single_attribute(text, cur)
        if attr_end is None:
            return "", text
        attr_block_end = attr_end
        while attr_block_end < n and text[attr_block_end].isspace():
            attr_block_end += 1
        cur = attr_block_end
        if not (cur + 1 < n and text[cur] == "@" and text[cur + 1] == "["):
            break
    if attr_block_end <= first_attr_start:
        return "", text
    return text[attr_block_start:attr_block_end], text[attr_block_end:]


def _return_theorem_to_prove_mathlib_style(text: str):
    MODIFIERS = {"private", "protected", "noncomputable", "nonrec", "unsafe", "partial", "scoped", "local"}
    mods_pattern = "|".join(MODIFIERS)
    start_pattern = (
        r"\s*(?:(?:" + mods_pattern + r")\s+)*\s*(?:theorem|lemma)\b"
    )
    start_match = re.search(start_pattern, text, re.DOTALL)
    if start_match:
        start_index = start_match.start()
        current_index = start_match.end()
        bracket_stack = []
        brackets_map = {")": "(", "]": "[", "}": "{"}
        open_brackets = set(brackets_map.values())
        close_brackets = set(brackets_map.keys())
        text_len = len(text)
        while current_index < text_len:
            char = text[current_index]
            if len(bracket_stack) == 0:
                if current_index + 1 < text_len and text[current_index:current_index + 2] == ":=":
                    return (start_index, current_index + 2)
            if char in open_brackets:
                bracket_stack.append(char)
            elif char in close_brackets:
                if bracket_stack and bracket_stack[-1] == brackets_map[char]:
                    bracket_stack.pop()
            current_index += 1
    prefix = r"\s*(?:(?:" + mods_pattern + r")\s+)*\s*(?:theorem|lemma).*?"
    pattern_match = r"(" + prefix + r"\s*\|)"
    match = re.search(pattern_match, text, re.DOTALL)
    if match:
        return match.span()
    return None


def _proof_length(statement_and_proof: str) -> int:
    lean_operators = [
        ":=", "!=", "&&", "-.", "->", "←", "..", "...", "::", ":>",
        "<;>", ";;", "==", "||", "=>", "<=", ">=", "⁻¹", "?_",
    ]
    lean_operators_spaced = [" ".join(conn) for conn in lean_operators]
    lean_operators_dict = dict(zip(lean_operators_spaced, lean_operators, strict=False))

    def lexer(lean_snippet):
        tokenized_lines = []
        for line in lean_snippet.splitlines():
            tokens = []
            token = ""
            for ch in line:
                if ch == " ":
                    if token:
                        tokens.append(token)
                        token = ""
                elif str.isalnum(ch) or (ch in "._'"):
                    token += ch
                else:
                    if token:
                        tokens.append(token)
                        token = ""
                    tokens.append(ch)
            if token:
                tokens.append(token)
            tokenized_line = " ".join(tokens)
            for conn in lean_operators_spaced:
                if conn in tokenized_line:
                    tokenized_line = tokenized_line.replace(conn, lean_operators_dict[conn])
            tokenized_lines.append(tokenized_line)
        return "\n".join(tokenized_lines)

    try:
        statement_and_proof = _remove_comments(statement_and_proof)
        _, statement_and_proof = _extract_and_remove_attributes(statement_and_proof)
        decl_start, decl_end = _return_theorem_to_prove_mathlib_style(statement_and_proof)
        proof = statement_and_proof[decl_end:]
        proof_tokenized = lexer(proof)
        return sum([len(l.split(" ")) for l in proof_tokenized.splitlines()])
    except Exception:
        return 10**9


# ── Path derivation ─────────────────────────────────────────────────────────


def _sanitize_name(name: str) -> str:
    """Same sanitization as preprocessor.py."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _derive_original_file(temp_file_path: Path, proof_name: str) -> Path:
    """Derive the original .lean file path from the temp file path.

    Temp files are named: {original_stem}_{sanitized_name}.lean
    Original files are: {original_stem}.lean in the same directory.
    """
    sanitized = _sanitize_name(proof_name)
    suffix = f"_{sanitized}"
    temp_stem = temp_file_path.stem
    if temp_stem.endswith(suffix):
        original_stem = temp_stem[: -len(suffix)]
    else:
        original_stem = temp_stem
    return temp_file_path.parent / f"{original_stem}.lean"


# ── Statement extraction for comparison ─────────────────────────────────────


def _find_incomplete_tactics(text: str) -> list[str]:
    """
    Return the proof-hole tactics used in `text` (comments stripped).

    `sorry` and `admit` only raise a severity-2 warning ("declaration uses 'sorry'"), so a
    file containing them still looks clean to `lean_diagnostic_messages` with severity=1.
    They are not proofs and must never be recorded as an improvement.
    """
    cleaned = _remove_comments(text)
    found = []
    for tactic in ("sorry", "admit", "sorryAx"):
        if re.search(rf"\b{tactic}\b", cleaned):
            found.append(tactic)
    return found


def _extract_statement(text: str) -> str | None:
    """Extract the theorem statement (without attributes/comments/proof) for comparison."""
    cleaned = _remove_comments(text)
    _, without_attrs = _extract_and_remove_attributes(cleaned)
    result = _return_theorem_to_prove_mathlib_style(without_attrs)
    if result is None:
        return None
    start, end = result
    return without_attrs[start:end]


# ── Multi-objective acceptance ──────────────────────────────────────────────


def _best_score_so_far(progress_file: Path, objective: dict) -> tuple[float, int | None]:
    """Score and heartbeats of the current best proof: the last improved attempt, else the original."""
    best_score = objective["length_weight"] + objective["heartbeat_weight"]
    best_heartbeat = objective.get("initial_heartbeat")
    with open(progress_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("improved") and "score" in record:
                best_score = record["score"]
                best_heartbeat = record.get("heartbeat")
    return best_score, best_heartbeat


def _check_multi_objective(
    objective: dict,
    objective_file: Path,
    original_file: Path,
    original_proof_text: str,
    current_proof_text: str,
    new_length: int,
    progress_file: Path,
) -> tuple[dict, float] | None:
    """
    Measure the current proof's heartbeats and score it.

    Returns the fields to add to the progress record (heartbeat, score, best_score,
    improved) and the previous best score, or None after printing HEARTBEAT_ERROR
    when the measurement failed.
    """
    length_weight = objective["length_weight"]
    heartbeat_weight = objective["heartbeat_weight"]
    initial_length = objective["initial_length"]
    project_root = objective["project_root"]
    timeout = objective.get("heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)

    heartbeat = None
    if heartbeat_weight != 0:
        if objective.get("initial_heartbeat") is None:
            initial_heartbeat, error = count_heartbeats_for_src(
                project_root, original_file, original_proof_text, timeout=timeout
            )
            if initial_heartbeat is None:
                print("HEARTBEAT_ERROR: Could not measure the heartbeats of the ORIGINAL proof, so no attempt "
                      "can be scored. This is an environment problem, not a problem with your proof. Stop.")
                print(f"Details: {error}")
                return None
            objective["initial_heartbeat"] = initial_heartbeat
            objective_file.write_text(json.dumps(objective, indent=2, ensure_ascii=False), encoding="utf-8")

        heartbeat, error = count_heartbeats_for_src(
            project_root, original_file, original_proof_text, new_src=current_proof_text, timeout=timeout
        )
        if heartbeat is None:
            print("HEARTBEAT_ERROR: Measuring the heartbeats of your proof failed, so nothing was recorded.")
            print("If the details below show Lean errors, your proof does not compile in the full file: fix it "
                  "and check again. If it is a timeout, your proof is too expensive: revert to the best proof.")
            print(f"Details: {error}")
            return None

    score = length_weight * new_length / initial_length
    if heartbeat_weight != 0:
        score += heartbeat_weight * heartbeat / objective["initial_heartbeat"]
    best_score, best_heartbeat = _best_score_so_far(progress_file, objective)
    improved = score < best_score
    fields = {
        "heartbeat": heartbeat,
        "best_heartbeat": heartbeat if improved else best_heartbeat,
        "initial_heartbeat": objective.get("initial_heartbeat"),
        "score": round(score, 6),
        "best_score": round(score if improved else best_score, 6),
        "improved": improved,
    }
    return fields, best_score


# ── Main logic ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Check and record a proof optimization attempt.")
    parser.add_argument("--proof-name", required=True, help="Name of the theorem/lemma")
    parser.add_argument("--temp-file-path", required=True, help="Path to the temp Lean file")
    parser.add_argument("--task-dir", required=True,
                        help="Task output directory containing current_proof.txt, best_proof.txt, progress.jsonl")
    args = parser.parse_args()

    temp_file = Path(args.temp_file_path).resolve()
    task_dir = Path(args.task_dir).resolve()

    # ── Derive all paths ─────────────────────────────────────────────────

    current_proof_file = task_dir / "current_proof.txt"
    best_proof_file = task_dir / "best_proof.txt"
    progress_file = task_dir / "progress.jsonl"
    original_file = _derive_original_file(temp_file, args.proof_name)

    # ── Validate task-dir files exist ────────────────────────────────────

    missing = []
    if not current_proof_file.exists():
        missing.append(f"current_proof.txt (expected at {current_proof_file})")
    if not best_proof_file.exists():
        missing.append(f"best_proof.txt (expected at {best_proof_file})")
    if not progress_file.exists():
        missing.append(f"progress.jsonl (expected at {progress_file})")

    if missing:
        print(f"MISSING_FILES: Required files not found under task directory {task_dir}:")
        for m in missing:
            print(f"  - {m}")
        print(f"\nMake sure you are calling check_proof.py with the correct --proof-name and --task-dir.")
        print(f"Expected command:")
        print(f"  python3 <check_proof_path> --proof-name \"{args.proof_name}\" "
              f"--temp-file-path \"{args.temp_file_path}\" --task-dir \"{args.task_dir}\"")
        sys.exit(0)

    # ── Read current proof from current_proof.txt ────────────────────────

    current_proof_text = current_proof_file.read_text(encoding="utf-8").strip()
    if not current_proof_text:
        print("ERROR: current_proof.txt is empty. You MUST write the full theorem+proof "
              "(including attributes and comments) to this file before calling check_proof.")
        sys.exit(0)

    # ── Load original proof from progress.jsonl attempt=0 ────────────────

    original_proof_text = None
    with open(progress_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("attempt") == 0:
                    original_proof_text = record["proof_text"]
                    break
            except json.JSONDecodeError:
                continue

    if original_proof_text is None:
        print("ERROR: Could not find attempt=0 in progress.jsonl.", file=sys.stderr)
        sys.exit(1)

    # ── Check 1: Proof completeness (no sorry/admit) ─────────────────────

    holes = _find_incomplete_tactics(current_proof_text)
    if holes:
        best_text = best_proof_file.read_text(encoding="utf-8").strip()
        print(
            f"INCOMPLETE_PROOF: Your proof uses {', '.join('`' + h + '`' for h in holes)}, "
            f"which does not prove anything."
        )
        print(
            "`sorry`/`admit` only produce a severity-2 warning, so the file still shows no "
            "severity-1 errors — but the theorem is NOT proved and this attempt is rejected."
        )
        print("Nothing was recorded. Revert to the best proof below and shorten it for real:")
        print("---BEST_PROOF_START---")
        print(best_text)
        print("---BEST_PROOF_END---")
        sys.exit(0)

    # ── Check 2: Statement integrity ─────────────────────────────────────

    original_stmt = _extract_statement(original_proof_text)
    current_stmt = _extract_statement(current_proof_text)

    if original_stmt is None:
        print("WARNING: Could not parse theorem statement from original proof.", file=sys.stderr)
    elif current_stmt is None:
        print("ERROR: Could not parse theorem statement from current proof in current_proof.txt.")
        print("Make sure current_proof.txt contains the full theorem+proof (including the theorem/lemma keyword).")
        sys.exit(0)
    elif original_stmt != current_stmt:
        print("STATEMENT_MODIFIED: The theorem statement was changed! You must keep the original statement unchanged.")
        print(f"\nOriginal statement:\n{original_stmt}")
        print(f"\nYour statement:\n{current_stmt}")
        print(f"\nRevert to the original proof and redo without changing the statement:")
        print("---ORIGINAL_PROOF_START---")
        print(original_proof_text)
        print("---ORIGINAL_PROOF_END---")
        sys.exit(0)

    # ── Check 3: File context integrity ──────────────────────────────────

    if temp_file.exists() and original_file.exists():
        temp_content = temp_file.read_text(encoding="utf-8")
        original_content = original_file.read_text(encoding="utf-8")

        # Find current proof in temp file
        current_stripped = current_proof_text.strip()
        proof_pos = temp_content.find(current_stripped)

        if proof_pos == -1:
            print("WARNING: Could not locate the current_proof.txt content in the temp file. "
                  "Make sure what you wrote to current_proof.txt matches exactly what is in the temp file.")
        else:
            temp_before = temp_content[:proof_pos]
            temp_after = temp_content[proof_pos + len(current_stripped):]

            # Find original src in original file
            orig_stripped = original_proof_text.strip()
            orig_pos = original_content.find(orig_stripped)

            if orig_pos == -1:
                print("WARNING: Could not locate the original proof in the original file for context check.")
            else:
                orig_before = original_content[:orig_pos]
                orig_after = original_content[orig_pos + len(orig_stripped):]

                if temp_before != orig_before or temp_after != orig_after:
                    print("FILE_MODIFIED: You modified parts of the file OUTSIDE the target proof!")
                    print("Only the proof of the target theorem should be changed. "
                          "Revert ALL other changes in the temp file.")
                    print(f"\nRestore the proof to the original and redo:")
                    print("---ORIGINAL_PROOF_START---")
                    print(original_proof_text)
                    print("---ORIGINAL_PROOF_END---")
                    sys.exit(0)

    # ── Compute proof length ─────────────────────────────────────────────

    new_length = _proof_length(current_proof_text)

    if new_length >= 10**9:
        print(f"ERROR: Failed to parse proof for length computation. Text:\n{current_proof_text[:500]}",
              file=sys.stderr)
        sys.exit(1)

    # ── Read current best ────────────────────────────────────────────────

    best_text = best_proof_file.read_text(encoding="utf-8").strip()
    best_length = _proof_length(best_text)

    # ── Count attempts ───────────────────────────────────────────────────

    attempt_num = 0
    with open(progress_file, "r", encoding="utf-8") as f:
        attempt_num = sum(1 for line in f if line.strip())

    objective_file = task_dir / "objective.json"
    multi_obj = None
    if objective_file.exists():
        objective = json.loads(objective_file.read_text(encoding="utf-8"))
        checked = _check_multi_objective(
            objective, objective_file, original_file, original_proof_text, current_proof_text,
            new_length, progress_file,
        )
        if checked is None:
            sys.exit(0)
        multi_obj, previous_best_score = checked
        improved = multi_obj["improved"]
    else:
        improved = new_length < best_length

    # ── Record to progress file ──────────────────────────────────────────

    progress_record = {
        "attempt": attempt_num,
        "proof_text": current_proof_text,
        "length": new_length,
        "best_length": new_length if improved else best_length,
        "improved": improved,
        "timestamp": datetime.now().isoformat(),
    }
    if multi_obj is not None:
        progress_record.update(multi_obj)
    with open(progress_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(progress_record, ensure_ascii=False) + "\n")

    # ── Output result ────────────────────────────────────────────────────

    if multi_obj is not None:
        if improved:
            best_proof_file.write_text(current_proof_text, encoding="utf-8")
        hb_text = (
            f", heartbeats {multi_obj['heartbeat']} (best {multi_obj['best_heartbeat']}, "
            f"original {multi_obj['initial_heartbeat']})"
            if multi_obj["heartbeat"] is not None
            else ""
        )
        if improved:
            print(f"IMPROVED: score {multi_obj['score']:.4f} (lower is better; previous best "
                  f"{previous_best_score:.4f}). Length {new_length} tokens "
                  f"(previous best {best_length}){hb_text}.")
            print("Keep optimizing from this proof.")
        else:
            print(f"NOT_IMPROVED: score {multi_obj['score']:.4f} >= best {multi_obj['best_score']:.4f} "
                  f"(lower is better). Length {new_length} tokens (best {best_length}){hb_text}.")
            print(f"Read the best proof from {best_proof_file} and revert to it, then try a different approach:")
            print("---BEST_PROOF_START---")
            print(best_text)
            print("---BEST_PROOF_END---")
    elif improved:
        best_proof_file.write_text(current_proof_text, encoding="utf-8")
        diff = best_length - new_length
        print(f"IMPROVED: {new_length} tokens (was {best_length}, saved {diff} tokens)")
        print(f"Keep optimizing from this proof.")
    else:
        print(f"NOT_IMPROVED: {new_length} tokens >= best {best_length} tokens.")
        print(f"Read the best proof from {best_proof_file} and revert to it, then try a different approach:")
        print("---BEST_PROOF_START---")
        print(best_text)
        print("---BEST_PROOF_END---")


if __name__ == "__main__":
    main()

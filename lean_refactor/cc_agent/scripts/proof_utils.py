"""
Proof length computation utilities.

Functions copied from goedels-poetry/goedels_poetry/utils.py for self-contained use.
Only depends on re (stdlib).
"""

import re


def remove_comments(text: str) -> str:
    """Remove block comments (/- ... -/) and line comments (-- ...)."""
    # First remove all /- ... -/ blocks
    text = re.sub(r"/-.*?-/", "", text, flags=re.DOTALL)
    # Then remove -- comments from each line
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        cleaned_line = line.split("--", 1)[0]
        if cleaned_line.strip() == "":
            continue
        cleaned_lines.append(cleaned_line)
    cleaned_text = "\n".join(cleaned_lines)
    return cleaned_text.strip()


def _parse_single_attribute(text: str, start: int) -> int | None:
    """
    Given text and an index `start` where text[start:start+2] == '@[',
    return the index just *after* the matching closing ']' for this attribute.

    Uses bracket depth over '[' and ']'. Returns None if we hit EOF
    before closing.
    """
    n = len(text)
    assert text[start] == "@" and start + 1 < n and text[start + 1] == "["

    i = start + 2  # position after the initial '['
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


def extract_and_remove_attributes(text: str):
    """
    Extract a leading block of attribute(s) like @[simp], @[aesop ...], etc.
    Returns (attr_block, cleaned_text).
    """
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

    attr_block = text[attr_block_start:attr_block_end]
    cleaned_text = text[attr_block_end:]

    return attr_block, cleaned_text


def return_theorem_to_prove_mathlib_style(text: str):
    """
    Extracts the signature of a Mathlib theorem/lemma.
    Returns (start_index, end_index) where end_index is right after ':='.
    """
    MODIFIERS = {"private", "protected", "noncomputable", "nonrec", "unsafe", "partial", "scoped", "local"}
    mods_pattern = "|".join(MODIFIERS)

    start_pattern = (
        r"\s*"
        r"(?:(?:" + mods_pattern + r")\s+)*"
        r"\s*"
        r"(?:theorem|lemma)\b"
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
                if current_index + 1 < text_len:
                    if text[current_index: current_index + 2] == ":=":
                        return (start_index, current_index + 2)

            if char in open_brackets:
                bracket_stack.append(char)
            elif char in close_brackets:
                if bracket_stack and bracket_stack[-1] == brackets_map[char]:
                    bracket_stack.pop()

            current_index += 1

    # Fallback: pattern matching style with |
    prefix = (
        r"\s*"
        r"(?:(?:" + mods_pattern + r")\s+)*"
        r"\s*"
        r"(?:theorem|lemma)"
        r".*?"
    )

    pattern_match = r"(" + prefix + r"\s*\|)"
    match = re.search(pattern_match, text, re.DOTALL)
    if match:
        return match.span()

    return None


def proof_length(statement_and_proof: str) -> int:
    """
    Compute the token count of a proof from a full statement string.
    Extracts the proof by finding where the signature ends, then tokenizes and counts.
    Returns 10**9 on error.
    """
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
        statement_and_proof = remove_comments(statement_and_proof)
        _, statement_and_proof = extract_and_remove_attributes(statement_and_proof)
        decl_start, decl_end = return_theorem_to_prove_mathlib_style(statement_and_proof)
        proof = statement_and_proof[decl_end:]
        proof_tokenized = lexer(proof)
        return sum([len(l.split(" ")) for l in proof_tokenized.splitlines()])
    except Exception:
        return 10**9

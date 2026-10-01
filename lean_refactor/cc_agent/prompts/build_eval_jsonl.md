# Task: build the eval JSONL for a Lean project

You are preparing the input file for the proof-golfing agent in `lean_refactor/cc_agent`.
Each line of the file describes one theorem/lemma whose proof will be shortened.

## Inputs (fill these in)

- **Project folder**: `lean_refactor/cc_agent/workspace/<PROJECT>` — must be a direct child of `workspace/`.
- **Which theorems to include**: `<SELECTION CRITERIA, e.g. "the 20 longest proofs under Analysis/MeasureTheory/">`

## Output file — the name and location are mandatory

Write exactly one file:

```
lean_refactor/cc_agent/workspace/<PROJECT>/eval/eval_<PROJECT>.jsonl
```

`<PROJECT>` must be the project folder's name exactly, including case. The runner finds the file
by computing `project_root / "eval" / f"eval_{project_root.name}.jsonl"`. If the name is anything
else (`eval.jsonl`, `eval_<project>.json`, a different case), the run fails with
`FileNotFoundError`. Example: `workspace/analysis/eval/eval_analysis.jsonl`.

Create the `eval/` directory if it doesn't exist. Use UTF-8, one JSON object per line, and
no blank lines. Write with `json.dumps(obj, ensure_ascii=False)` so Lean Unicode (`ℝ`, `→`, `∀`)
stays readable.

## Line format

Write the keys in this order:

```json
{"name": "...", "path": "...", "proof_length": 0, "src": "...", "signature": "", "contexts": []}
```

### `name` (required)
The **fully qualified** declaration name, with every enclosing `namespace` prepended. Example:
`lemma nesting` inside `namespace DyadicCube` becomes `"DyadicCube.nesting"`.
- It must be unique **after sanitization**, where every character outside `[a-zA-Z0-9_]` becomes
  `_`. The sanitized name is used as the output directory name and in the temp file name
  `<stem>_<sanitized>.lean`. `Foo.bar` and `Foo_bar` would collide, so keep only one of them.
- It is also the key used by `price.jsonl` and the verify scripts, so don't rename later.

### `path` (required)
The `.lean` file containing the declaration, **relative to the project folder**. Use forward
slashes and no leading `./`, e.g. `"Analysis/MeasureTheory/Section_1_2_1.lean"`.
`<project>/<path>` must exist; otherwise the task is silently skipped.

### `src` (required — the most important field, get it exactly right)
The declaration's full text, copied **byte for byte** from the file:
- **Start** at the first line of the declaration block: its doc comment (`/-- ... -/`) if it has
  one, otherwise its `@[...]` attributes if it has any, otherwise the modifiers/keyword
  (`private`, `protected`, `theorem`, `lemma`).
- **End** at the last character of the proof. Do not include the next declaration, a following
  `end`, trailing blank lines, or comments that belong to the next item.
- Keep the original whitespace, indentation, line breaks, comments inside the proof, and Unicode.
  Do not reformat or normalize anything.

`check_proof.py` relies on this in two ways. It parses the statement from `src` to detect
statement changes. It also locates `src` in the original file with `str.find`, then compares
everything before and after it to detect edits outside the proof. If `src` is not an exact
substring, the second check is silently disabled.

Only include declarations that meet all of these:
- The keyword is `theorem` or `lemma`. `example`, `def`, `instance`, `abbrev` are not parsed.
- The proof starts with `:=` at bracket depth 0 (term-mode `:= ...` or `:= by ...`). Skip
  equation-compiler style proofs (`| 0 => ...` with no `:=`).
- The proof contains no `sorry`, `admit`, or `sorryAx`.
- Its exact `src` text appears **only once** in the file.
- The file currently compiles. Assume the project is built; skip files you know are broken.

### `proof_length` (required)
Compute it with the **same function the agent's checker uses**. Do not count tokens yourself:

```python
import sys; sys.path.insert(0, "lean_refactor/cc_agent/tools")
from check_proof import _proof_length
proof_length = _proof_length(src)
```

It must be an `int`. If the function returns `10**9`, it failed to parse `src`; drop that
declaration. Every improvement the agent makes is measured against this value, so a mismatched
count makes the results meaningless.

### `signature` (optional — leave empty)
Set it to `""`. It is only displayed in the agent's prompt.

### `contexts` (optional — leave empty)
Set it to `[]`. It is only used for prompt hints.

## Validation (run before finishing)

Write and run a short script that re-reads the output file and asserts, for every line:
1. It is valid JSON with exactly the six keys above, `signature == ""`, `contexts == []`.
2. `(project / path).is_file()`.
3. `src in (project / path).read_text(encoding="utf-8")`, and it occurs exactly once.
4. `_proof_length(src) == proof_length` and `proof_length < 10**9`.
5. `re.search(r"\b(theorem|lemma)\b", src)` matches, and `re.search(r"\b(sorry|admit|sorryAx)\b", src)` does not.
6. Sanitized names are unique across the file.

Also confirm the file path ends with `/<PROJECT>/eval/eval_<PROJECT>.jsonl`.

When finished, report: the output path, the number of lines written, and every declaration you
considered but skipped, with the reason (no `:=`, not unique, contains `sorry`, parse failure,
name collision, etc.).

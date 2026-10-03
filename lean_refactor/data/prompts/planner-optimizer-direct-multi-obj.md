You are given a correct Lean 4 proof of a mathematical theorem from a real library, its elaborated signature, and the dependencies used in the theorem. Your goal is to optimize the proof under the optimization objective below while ensuring it is still correct. Focus on structural optimization, and come up with smarter ways to write the proof.

{% include "_objective-multi-obj.md" %}

Here is the original theorem and proof:
```lean4
{{ current_proof }}
```

{% if signature %}
Theorem's elaborated signature:
{{ signature }}
{% endif %}

{% if informalization %}
Theorem's doc string:
{{ informalization }}
{% endif %}

{% if dependencies %}
Information about the dependencies used in the original proof. Note, the provided dependencies are from the same Lean 4 project that the current theorem is in. Mathlib 4 dependencies are not included for brevity.
{{ dependencies }}
{% endif %}

{% if use_tactic_style %}
## Tactic-Mode Constraint

**IMPORTANT:** The optimized proof **must** be written in **tactic mode**. In Lean 4, tactic-mode proofs begin with `:= by` after the theorem signature, followed by a sequence of tactic commands to incrementally transform and solve a goal state.

You **must not** convert the proof to term-mode. The proof body must start with `:= by`.
{% endif %}

Now, provide the complete code, including the original theorem statement (not the elaborated signature) and your optimized proof. Do NOT modify the original theorem statement. You must wrap the entire Lean 4 theorem and proof in tags like:

```lean4
<your optimized theorem and proof here>
```

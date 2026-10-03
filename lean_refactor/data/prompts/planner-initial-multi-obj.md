Your task is to analyze a given Lean 4 proof from a research level project and create a structured plan for optimizing it under the optimization objective below, while maintaining the correctness.

{% include "_objective-multi-obj.md" %}

## Instructions

Analyze the proof and identify regions that can be optimized under this objective. For each optimization opportunity:

{% if use_tactic_style %}
**Tactic-Mode Constraint:** The proof is written in Lean 4 **tactic mode** (the proof body starts with `:= by` followed by tactic commands). All optimization plans **must** preserve tactic-mode style. Do not propose converting the proof to term-mode.
{% endif %}

1. **Identify the line range** (1-indexed) of the region to optimize. The beginning of the theorem statement is line 1.
2. **Provide a title**: a short descriptive name that summarizes your strategy.
3. **Provide potential reduction**: state how much this strategy could improve the score (high, medium, or low)
4. **Determine an optimization strategy**: describe your detailed plan on how you can optimize the region, including descriptions of the code transformations you plan to do and the rationale behind the strategy (including how it trades off proof length against elaboration effort, given the weights above). You do not need to provide concrete code transformations, just a detailed plan is enough.

## Inputs

1. You will receive a correct Lean 4 statement and proof source code.
2. Its elaborated signature.
3. Its doc string from the source if it exists in the source.
4. All the dependencies used in the statement and proof from the same Lean 4 project it originated from. Mathlib 4 dependencies are not included for brevity. If there are no dependencies from the Lean 4 project that the proof comes from (this means the proof only depends on Mathlib 4), then no dependencies will be provided.

## Output Format

Output the plans using the following JSON format, wrapped in a single ```json ``` tags.
Ensure the output is valid JSON. Specifically, make sure to escape any double quotes or backslashes within the string values (e.g., use `\"` for quotes and `\\` for backslashes).

```json
[
  {
    "line_start": X,
    "line_end": Y,
    "title": "the strategy name",
    "reduction": "high, medium, or low",
    "description": "Detailed description of the optimization strategy to apply at this region of proof, describing the strategy, how to optimize the region under the weighted length/heartbeat objective, and the rationale behind the strategy."
  }
]
```

Rules about the ordering of the output plans:

1) Sort plans primarily from top to bottom of the proof (increasing line numbers).
2) Overlaps of optimization regions are allowed. If two plans overlap in location, put the plan with the MOST significant potential score improvement first.
3) If two plans have the same overlap + same potential impact, keep top-to-bottom ordering.

Here is the proof to optimize:
```lean4
{{ current_proof }}
```

{% if signature %}
Theorem's elaborated signature:
{{ signature }}
{% endif %}

{% if informalization %}
Theorem's documentation:
{{ informalization }}
{% endif %}

{% if dependencies %}
Information about dependencies used in the proof:
{{ dependencies }}
{% endif %}

Now analyze the proof and generate your optimization plans.

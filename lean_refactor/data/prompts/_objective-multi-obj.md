## Optimization Objective

The proof is optimized for two properties at once:

1. **Proof length**: the number of tokens in the proof.
2. **Heartbeats**: Lean's count of elaboration effort, a proxy for how much compute and time it takes to check the proof.

Every new proof that compiles is scored as (lower is better):

    score = {{ length_weight }} * (length / original length) + {{ heartbeat_weight }} * (heartbeats / original heartbeats)

A new proof is ACCEPTED only if its score is lower than the best score of any proof accepted so far.
{% if length_weight == 0 %}
Proof length has weight 0 here, so a LONGER proof is acceptable as long as it is cheaper to elaborate.
{% endif %}
{% if heartbeat_weight != 0 %}

Heavy automation (`simp` or `simp_all` with large lemma sets, `aesop`, `decide`, `norm_num` on large goals, `nlinarith`, `polyrith`, `continuity`) can make a proof shorter but much more expensive to elaborate. Cheaper, targeted alternatives include `simp only [...]` with a minimal lemma list and `rw`/`exact` with specific lemmas. A slightly longer proof that is much cheaper to elaborate can be a good trade when it lowers the score.
{% endif %}

# GEO Agent V1 single-decision protocol convergence

Date: 2026-10-20

## Scope and classification

This is an `IMPLEMENTATION_CHANGE`. It preserves the existing `TOOL_CALL |
FINAL_ARTIFACT | STOP` meanings, evidence grading, server qualification and formal V2 lane.
It changes only the Agent-specific DeepSeek request contract and its offline enforcement.

No DeepSeek request, sampling, fetch, publication or formal-result write was performed during
this work.

## Exact reconstruction of validation 5

The retained response envelope does not include the original `input` field, but the outbound
body can be reconstructed deterministically from the immutable Agent run, first-turn state,
persisted execution profile and then-current code. Canonicalizing that reconstructed body with
the same code used by the shared budget guard produces:

`1090a2d07cc514040e99471c0bfb1284e21886678013ab92ee56c06d140bd299`

This exactly matches the fifth run's persisted `provider_payload_hash`. The diagnosis below is
therefore based on the effective request, not inferred only from an output excerpt.

The effective outbound request had this complete top-level structure (values abbreviated, no
headers or credentials):

```json
{
  "model": "deepseek-flash",
  "instructions": "<business instruction bundle followed by the old loop footer>",
  "input": "<serialized geo.agent.loop-input.v2 object>",
  "temperature": 0.0,
  "max_output_tokens": 8192,
  "text": {
    "format": {
      "type": "json_schema",
      "name": "AgentDecision",
      "schema": "<AgentDecision JSON Schema>"
    }
  }
}
```

Confirmed properties:

- `/responses` and `instructions` were used; no `developer` message or chat `messages` array was
  constructed.
- `text.format.type=json_schema` and the actual `AgentDecision` Schema were sent.
- the Schema top level was one object with `additionalProperties=false`.
- only `action_type` and `reasoning` were required; action-specific fields were nullable defaults.
- `tool_name` was an unrestricted string in the provider Schema, although the server retained a
  separate allowlist.
- provider strict structured output was not requested. The response echoed
  `text.format.strict=null`.
- `parallel_tool_calls` and `max_tool_calls` were not sent. The response's values
  (`true` and `null`) were provider defaults and cannot be treated as single-step enforcement.

The response had `status=completed`, `incomplete_details=null`, a completed reasoning item and a
completed message item. It was not truncated. Its exact 1,449-character `output_text`, SHA-256
`f9083dad8a57d7d75684bbd854b7c16557e82ac63440128078b1fbcfcf3ebe62`, contains seven
`TOOL_CALL` objects and one `STOP` object separated by newlines.

## Root-cause classification

The fifth result must not be classified simply as model incapability or a provider violation:

1. **Request construction defect:** `strict_json=True` controlled local parsing but did not set
   provider `text.format.strict=true`.
2. **Schema under-specification:** the top-level object was closed, but four action fields were not
   required and `tool_name` did not expose the allowlist to the provider.
3. **Prompt granularity ambiguity:** the old prompt mentioned one action per round, but only after
   three long business documents. It did not lead with the distinction between the long-term GEO
   mission and the current call's single decision.
4. **Provider/model behavior:** the model ignored the natural-language single-action sentence and
   emitted a future plan without waiting for observations. Because provider strict mode was absent,
   validation 5 does not prove non-compliance under the corrected strict contract.

Neither workspace/project `AGENTS.md` nor an installed GEO skill directs the model to emit a full
tool plan. The frozen Agent instructions explicitly allow multi-turn adjustment and warn against a
fixed eight-step flow. `GEO_PLAYBOOK.md` contains optional analysis questions, but explicitly says
they are not a mandatory checklist. No instruction source tells the model that unexecuted tools have
already returned results.

## Implemented single-decision contract

The existing `text.format=json_schema` path remains the only active request protocol. Native
`function_call` is not enabled in parallel.

Changes:

- the Agent decision request alone now sends `text.format.strict=true`; generic DeepSeek/formal V2
  behavior remains unchanged by default;
- the system-level `instructions` now begin with a short current-call protocol: return exactly one
  top-level decision, no array, no newline-delimited decisions, no future action list and no assumed
  observations;
- `geo.agent.loop-input.v3` repeats this as a machine-readable `current_call_contract` and a direct
  current-call instruction;
- all six decision fields are required by the provider Schema; fields not applicable to the selected
  action must be explicit `null`;
- `tool_name` is limited in the Schema and Pydantic contract to the existing nine-tool allowlist;
- server validation rejects mixed actions such as `TOOL_CALL + stop_reason`, `STOP + tool_name` and
  `FINAL_ARTIFACT + arguments`;
- prompt, Schema, transport and execution identities were versioned so old cache entries or legacy
  execution profiles cannot silently cross the boundary.

Versions:

- prompt: `geo-agent-loop.v3`
- Schema: `geo.agent.decision.v2`
- transport: `geo.agent.deepseek.responses-json-schema.single-decision.v1`
- loop input: `geo.agent.loop-input.v3`
- execution profile: `geo.agent.execution.v3`

The same validation-5 frozen scope produces this offline post-change fingerprint (it was not sent):

`083e80a7210cb2d8a8e7c5344df85f1988b859fc1936610bdfa2efa3e40fd0b8`

Request-structure comparison:

| Dimension | Validation 5 request | Corrected Agent request |
| --- | --- | --- |
| provider strict mode | absent; echoed as `null` | `text.format.strict=true` |
| top-level Schema | object, `additionalProperties=false` | unchanged |
| required keys | `action_type`, `reasoning` | all six decision keys |
| tool name | nullable free string | nullable nine-value enum |
| action relationships | local minimum checks | mutually exclusive server checks |
| per-call instruction position | after long business bundle | first section of `instructions` |
| input call contract | prose only | explicit `decision_count=1`, no future list/assumptions |
| parallel/max tool parameters | not sent | still not sent or relied upon |
| prompt / Schema identity | `v2` / `v1` | `v3` / `v2` |

## Offline acceptance

The exact validation-5 output is retained as a non-secret fixture. The test verifies its SHA-256,
eight-line shape and complete rejection through the real adapter path. No first-object extraction or
batch execution is allowed.

Additional tests prove:

- one valid decision is accepted and serialized through the Agent request;
- the actual Agent request contains provider strict mode, the closed allowlisted Schema and the
  system-level single-call instruction;
- multiple decisions, ambiguous response items, malformed DSML, unknown tools and mixed actions are
  rejected;
- a prior tool result and observation catalog remain available to later turns, so dynamic selection
  is not replaced by a fixed workflow;
- strict-mode identity changes the derived call/cache identity;
- shared budget, accounting, formal automatic delivery and experimental persistence isolation remain
  intact.

Results:

- focused protocol/Agent/identity suite: `48 passed`
- combined shared-budget/formal-delivery/Agent regression: `83 passed`
- compile check: passed
- external model calls: `0`
- model cost: CNY `0`

## Architecture decision after this checkpoint

Offline controls can guarantee that the server executes at most one admitted decision; they cannot
prove that DeepSeek will obey the corrected request until a separately authorized real call occurs.
One further real validation is technically justified, but it must be treated as the final validation
of this loop protocol rather than another open-ended repair cycle.

If the model again emits multiple decisions with `strict=true`, do not add another permissive parser,
implicit retry or larger state machine. Choose one replacement direction instead:

1. replace (not run alongside) text output with one provider-native `AgentDecision` function call on
   a model/profile that reliably enforces it; or
2. prefer the simpler evidence-package Agent: proactively provide the minimal frozen Prompt, answer,
   citations, available source passages, Truth and brand context, let the model synthesize the full
   GEO artifact, and retain only bounded supplemental reads plus the existing server grading.

Given the accumulated implementation cost and absence of a successful real artifact, the evidence-
package Agent is the recommended fallback if the corrected single-step protocol fails once more.

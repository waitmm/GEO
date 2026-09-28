# Citation Contribution P1 Contract Audit

Status: IMPLEMENTATION_CHANGE / OFFLINE COMPLETE / CANARY NOT AUTHORIZED

## Frozen Failed Execution

- Contribution: `citation-contribution-76074b05-e357-41b0-b563-51bdf3dc720d`
- Plan: `citation-contribution-plan-1144c02d0a8eb1daf200`
- Result: `contribution-v1:b59cacd86f3b4f37`
- Outcome: 19/19 `FAILED_SCHEMA`; zero admitted evaluations or bindings.
- The plan, result and 19 mode-0600 response artifacts remain immutable.

## Root Cause Evidence

The production typed model required top-level `evaluations` and
`no_binding_reason`, but the request sent only Chat Completions
`response_format={"type":"json_object"}`. The provider received neither the
typed JSON Schema nor a concrete valid output example. The prompt described
business rules but did not specify every response field.

Observed complete-response shapes:

| Shape | Count |
| --- | ---: |
| `results + no_binding_reason` | 9 |
| `results` | 7 |
| `results + no_binding_reason + type` | 2 |
| `candidate_pairs` | 1 |

Repository audit found no Citation Contribution output example or production
template defining top-level `results`. It was model-generated under an
under-specified JSON Object contract. `candidate_pairs` existed only as the old
input key, and one response copied that input-oriented name into the output.
The final root cause is prompt/schema/transport drift, not generic model
instability.

## Recovered Contract

`CitationContributionResponse` is now the single structural source for:

- provider JSON Schema;
- the schema injected into the production system prompt;
- validated positive and legal-empty examples;
- strict local structural admission;
- contract fixtures.

The model returns only frozen indexes:

- `candidate_pair_index`
- `answer_unit_index`
- `citation_index`
- `passage_index`

Backend code validates the exact index tuple and then generates formal business
IDs from the frozen Plan. It also validates complete pair coverage, duplicate
pairs, AnswerUnit/source spans, relation consistency, negative span absence,
and top-level `evaluations/no_binding_reason` logic.

## Provider Transport

Final selection: `A. Responses API + json_schema`.

DeepSeek's current official Responses API documents
`text.format.type=json_schema`; its thinking-mode guide maps non-thinking
Responses calls to `reasoning.effort=none`:

- https://api-docs.deepseek.com/api/create-response/
- https://api-docs.deepseek.com/guides/thinking_mode/

The existing `DeepSeekClient` now has a default-off opt-in mode. Citation
Contribution uses `/responses` with the generated schema; Answer Semantic,
SourceClaim, Alignment, Strategy and legacy callers retain their existing Chat
Completions behavior.

## Versions And Identity

- Contract: `single_prompt_v2.citation_contribution.v2`
- Plan: `single_prompt_v2.citation_contribution_plan.p1.v4`
- Prompt: `single_prompt_v2.citation_contribution.p1.v2`
- Schema: `single_prompt_v2.citation_contribution.strict.v2`
- Transport: `semantic_llm.deepseek.responses_json_schema.v1`
- Implementation: `single_prompt_v2.citation_contribution.contract_recovery.v1`

These versions, plus schema and prompt hashes, enter Plan identity. Structured
output mode, schema hash and transport version enter cache identity. Old cache
entries therefore cannot be consumed by the recovered contract.

## Offline Gate

- All 19 old response-shape fixtures: rejected.
- Valid non-empty typed response: accepted.
- Valid explicit empty typed response: accepted at schema level.
- Unknown fields, missing fields, wrong types, invalid nullability and invalid
  cross-field states: rejected.
- Provider request test: `/responses` carries the exact generated JSON Schema.
- No external LLM call, sampling, source fetch, review or Strategy write was
  performed during this repair.

The next executable step is a newly frozen Plan with a deterministic first-two
Citation Canary. It requires separate exact authorization. A failed Canary must
stop the remaining 17 calls.

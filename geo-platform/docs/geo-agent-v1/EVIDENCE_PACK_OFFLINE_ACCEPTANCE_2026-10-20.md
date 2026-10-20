# GEO Agent V1 minimal frozen Evidence Pack — offline acceptance

Date: 2026-10-20

Branch: `experiment/geo-agent-v1`

Change classification: `IMPLEMENTATION_CHANGE`

## Decision and scope

The text-JSON single-step decision loop remains available only as a historical experimental
profile. The Optimize experiment entry now defaults to an independent `EVIDENCE_PACK` profile:

1. freeze the exact existing Project / Prompt / AnalysisContext / Run scope;
2. deterministically assemble the original answers, citation occurrences and statuses, all source
   dispositions, bounded whole source passages, Product Truth, brand context and Monitor metrics;
3. make at most one ordinary Markdown model request, with no tools and no repair retry;
4. validate exact required sections, evidence locators, draft completeness and delivery grade on
   the server;
5. persist only to `AgentExperimentRun` / `AgentResultVersion` and expose the result in the existing
   Optimize experiment panel.

This does not change the formal V2 Analysis, ResultVersion, Review, Truth or delivery gate. It adds
no sampler, crawler, source acquisition path, publishing permission, Agent framework or database
migration. Workflow result text is deliberately absent from the Evidence Pack.

## Frozen contracts

- execution: `geo.evidence-pack.execution.v1`
- pack: `geo.evidence-pack.v1`
- coverage: `geo.evidence-pack.coverage.v1`
- prompt: `geo-evidence-pack-synthesis.v1`
- result: `geo.evidence-pack.markdown-result.v1`
- transport: `geo.deepseek.responses-text.v1`
- validation: `geo.evidence-pack.validation.v1`

The execution profile freezes one model call, zero tool calls, zero repairs and automatic retry 0.
The pack uses stable ordering. It includes whole source passages until the text budget is reached;
every omitted passage remains visible by snapshot ID, passage ID, hash and `TEXT_BUDGET` reason.
If the non-passage core itself exceeds capacity, the run fails explicitly rather than truncating a
Run answer, Truth or identity object.

The model returns Markdown rather than an `AgentDecision`. Required level-two sections are:

- `GEO 诊断与依据`
- `品牌表现与证据缺口`
- `优化策略与渠道`
- `完整正文`
- `QA 与事实限制`
- `复测计划`

The server accepts only evidence locators that resolve to the frozen pack:

- `[[answer:RUN_ID:START:END]]`
- `[[citation:CITATION_OCCURRENCE_ID]]`
- `[[source:SNAPSHOT_ID:PASSAGE_ID]]`
- `[[truth:TRUTH_ID:VERSION]]`

Answer observations, citation relationships, source passages and target-brand Truth stay distinct.
Unknown locators, omitted passages, missing or duplicate sections, incomplete drafts, placeholders,
unsupported quantitative claims and unsafe L3 output fail validation. L2 remains `VERIFY_FIRST`;
L3 is `NOT_CONSUMABLE` and must state `VERIFY_FIRST`. With zero valid answers, the common L4 path
creates a recovery package with zero model calls.

## Provider and accounting correction

Both structured and plain-text DeepSeek transports now record a definite non-200 response before
business parsing. The audit event preserves HTTP status, a bounded provider error category, a hash
and the complete redacted response body in the existing restricted archive. API keys,
Authorization headers and sensitive-key values are not stored.

A non-200 response with no provider usage is counted as a real request, keeps its conservative
reservation, records zero *actual* tokens/cost and is not silently replayed. This fixes the earlier
state where a provider rejection could be missing from the Agent Run while present in the shared
ledger.

## Offline acceptance evidence

Focused Evidence Pack, provider and ledger suite:

```text
PYTHONPATH=. .../.venv/bin/pytest -q \
  tests/test_agent_experiment.py \
  tests/test_deepseek_generation_contract.py \
  tests/test_shared_model_budget.py
61 passed
```

Combined Agent / shared-budget / formal automatic-delivery / transport-identity regression:

```text
PYTHONPATH=. .../.venv/bin/pytest -q \
  tests/test_shared_model_budget.py \
  tests/test_agent_experiment.py \
  tests/test_automatic_delivery.py \
  tests/test_deepseek_generation_contract.py \
  tests/test_derived_model_call_identity.py
93 passed
```

Additional checks:

- Python compile check: passed.
- frontend client tests: `20 passed`.
- frontend production build: passed (existing large-chunk warning only).
- isolated browser acceptance: `PASS`, `external_calls=0`, desktop / expanded trace and comparison /
  mobile screenshots produced under
  `backend/artifacts/acceptance/agent-browser-20261020T050329Z/`.
- mobile browser assertion: no horizontal document overflow.
- formal release database SHA-256 before final commit:
  `e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`, unchanged from the prior
  strict-protocol acceptance.

The browser fixture records CNY `0.002` only as simulated UI usage. Real external requests in this
implementation and acceptance round: `0`; real incremental model cost: CNY `0`.

## Explicit stop and future authorization boundary

No real DeepSeek call was authorized or attempted. The original immutable shared ledger authorizes
only `RESPONSES_JSON_SCHEMA`; the new route correctly identifies itself as `RESPONSES_TEXT` and is
therefore rejected by that ledger before network I/O. A regression test proves the failure is
closed and consumes zero requests.

Consequently, a future paid Evidence Pack test needs a new explicit owner authorization and an
append-only budget-ledger authorization design that retains all historical usage. The old ledger
must not be reset or relabeled, and `RESPONSES_TEXT` must not be disguised as JSON Schema. Until
that work is explicitly authorized and tested, the route remains offline/cache-only for real
provider execution.

This acceptance proves the deterministic pack, one-call transport contract, server validation,
isolated persistence and UI flow. It does not prove DeepSeek output quality, a completed real GEO
delivery, stability, or superiority over Workflow. Those remain `NOT_MEASURABLE`.

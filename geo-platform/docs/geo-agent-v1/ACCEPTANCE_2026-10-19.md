# GEO Agent Experiment V1 / Release Acceptance

Date: 2026-10-19

Branch: `experiment/geo-agent-v1`

Baseline: `codex/geo-integration@d715964`

DB revision: `20261019_02`

Initial authority boundary: no real model, new sampling, public fetch or publication authorized.
The later controlled comparison addendum below supersedes only the real-model restriction;
new sampling, public fetch, publication and formal-lane writes remained prohibited.

## Outcome

The P0 engineering lane is implemented and accepted for offline isolated use. It is not a
claim that Agent output quality beats Workflow. A later explicit authorization supplied the
provider/model, request limit, token limit, CNY hard cap, conservative price, price source
and check date. The first controlled real-model experiment was executed and failed before
producing an Agent result; quality equivalence therefore remains unproven.

Formal V2 tables are read-only to this lane. Agent writes are limited to four new tables;
database triggers protect frozen run identity and make events, checkpoints and results
append-only. GET routes use the release read-only session.

## Acceptance traceability

| Test IDs | Requirement | Implementation | Status / evidence |
|---|---|---|---|
| A-01..A-03, A-06 | valid low-evidence answer, zero citation, no brand/knowledge | `scope.py`, `grading.py`, `runner.py` | PASS: `test_no_source_still_delivers_complete_l3_instruction_only_artifact` |
| A-04..A-05 | observed citation separate from unavailable/ready source | `scope.py`, `tools.py` | PASS in mixed READY/WAIVED source fixture; citation occurrence and disposition remain separate |
| A-07, A-16, A-20 | subject/relation/fact claims cannot self-upgrade | `contracts.py`, `grading.py` | PASS for server-owned pointer/type/read checks and L3 fact/readiness rejection; semantic quality remains part of real-model review |
| A-08..A-09 | wrong scope/version/hash blocks before model | `scope.py`, `service.py` | PASS: wrong manifest hash creates BLOCKED audit row, zero model/tool/result; scoped GET returns 404 |
| A-10..A-11 | idempotent retry and explicit regenerate identity | `service.py` unique request/execution keys | PASS in service tests; regenerate nonce changes execution identity and preserves the old row |
| A-12..A-14 | checkpoint, restart, budget and bounded repair | `runner.py`, `release_worker.py` | PASS for worker dispatch/checkpoint persistence/request reservation; invalid output is rejected with one bounded repair |
| A-15, A-28 | untrusted content/prompt injection | `runner.py::_system_prompt`, `tools.py` | PASS: shell request rejected by allowlist; tool material is labeled untrusted |
| A-17 | no valid answer | `runner.py::_save_l4_recovery` | PASS: NEEDS_INPUT, L4 recovery, zero model calls, no draft |
| A-18 | no fixed Project/Prompt/Run identity | all scoped services | PASS: generated IDs and ownership checks; no production Project #1 fallback |
| A-21 | cancellation | `service.py::cancel_agent_run`, runner turn guard | PASS by API/service behavior; no provider call was permitted in this acceptance |
| A-22 | refresh/GET/project switch isolation | API read-only session + keyed React state | PASS: API scoped read test and browser desktop/mobile/refresh/project-key path |
| A-23..A-24 | fair Workflow comparison or honest missing baseline | `compare_with_workflow`, UI comparison card | PASS in browser/API; equality requires exact run IDs and raw output hash |
| A-25 | formal lane regression | unchanged Workflow components + regression suite | PASS; commands below |
| A-26 | real provider autonomous path | `DeepSeekDecisionClient` | BLOCKED: no external authorization/budget; no call attempted |
| A-27 | bounded long input | 4,000-character paged tools, 12-observation context, checkpoint hashes | PASS at contract/unit level; real long-context quality NOT_RUN |
| A-29 | QA repair | bounded server rejection/feedback loop | PASS at runner contract level; real-model repair quality BLOCKED with A-26 |
| A-31 | qualification→plan→result exact binding | `_save_result`, append-only triggers | PASS: hashes are server-generated and returned in result view |
| A-19 | supplemental public web observation | P1 | OUT/P1, intentionally not implemented |
| A-30 | two-window post-publication retest | existing Monitor/Validate only | OUT/P1; no publication or new sampling authorized |

## Executed evidence

- Combined Agent + formal graded-delivery + release regression:
  `...pytest -q tests/test_agent_experiment.py tests/test_release_first_slice.py tests/test_graded_delivery.py tests/test_automatic_delivery.py`
  → `82 passed in 104.18s` (15 Agent-specific tests plus applicable formal-lane tests).
- Frontend: `npm run test:client`, `npm run test:startup`, `npm run build:release`
- Browser: `...python scripts/agent_experiment_browser_check.py`
- Migration: fresh isolated SQLite upgraded through `20261019_02`; application startup schema validation passed.

Latest retained browser report before final commit:
`backend/artifacts/acceptance/agent-browser-20261019T103613Z/report.json` with desktop,
trace/comparison and 390px mobile screenshots. It used the real local API, migrated isolated
database and built release UI; the decision client was scripted and external calls were 0.
The preceding `agent-browser-20261019T103518Z` attempt is retained as FAIL: its sole failure
was the acceptance locator still expecting the old short `L3` label after the implementation
adopted the frozen full enum; the assertion was updated, not weakened.

## Cost and comparison boundary

- The original offline P0 acceptance used 0 real provider/model calls and CNY 0.
- Scripted Agent fixture usage is synthetic and must not be treated as billing. The browser
  fixture displays CNY 0.0200 solely to verify cost rendering.
- One offline Agent result ID is in the browser report. Its hashes are stored in the isolated
  database and exposed by the read-only result endpoint.
- A fair Workflow result was not fabricated. The comparison view reports an empty or blocked
  baseline unless a formal task has the exact same Run set and raw-output hash.

## Controlled real-model comparison addendum

The owner subsequently authorized one isolated `deepseek-flash` comparison batch with a
shared ceiling of CNY 30, 3,000,000 tokens and 36 requests. The controller used one durable
SQLite ledger for Agent and Workflow lanes, single concurrency, no automatic retries, atomic
worst-case reservation and actual-usage settlement. Pricing was checked on 2026-10-19 and the
ledger conservatively accounts every token at CNY 10 per million.

The exact frozen comparison scope was Project 1 / Prompt 1 / Run 1, Analysis
`925ef2dc-605f-467d-a025-52033a574d92`, Context
`ctx-5407fb2f-acd5-41ac-8ac7-41713a08a5aa`, raw output hash
`11dca9e4438bdecf66a86472f2e8a498f6f7067c3bcc4f9f3cfd381d2c9ebccb` and run scope hash
`80126c460f0da4f588acab4dfe07f0a904ba86171be93ccbb8d81c97eeda4e67`.
The formal Workflow baseline was reused because its Diagnosis, Citation Contribution,
Strategy and Execution hashes all validated against this scope. No new Workflow request was
made and the formal database was not written.

Three manual Agent executions were retained under different run identities; these were not
transport retries. The first exposed wrapped non-JSON output, the second exposed a DeepSeek
DSML tool-call form, and bounded strict adapters were added with offline tests after each
failure. The final execution autonomously called `get_scope_summary`, `list_runs`,
`get_scope_summary`, `read_answer`, `get_scope_summary`, and `list_citations`. It correctly
observed one valid answer, 19 citations and zero target-brand mentions, but spent three of six
turns rereading the scope summary and then stopped at the run-local six-model-call ceiling.
It persisted `FAILED / AGENT_MODEL_CALL_BUDGET_EXHAUSTED`, produced no
`AgentResultVersion`, and therefore did not produce diagnosis, strategy, article or QA output.

Batch settlement is complete: 13 Agent requests, 77,011 input tokens, 2,730 output tokens,
79,741 total tokens, 45.982 seconds across the three executions, zero Workflow requests and
zero in-flight/unknown reservations. The conservative ledger charge is CNY 0.79741. Applying
the documented peak cache-miss input price and output price to recorded usage gives CNY
0.175862; the provider invoice was not independently queried. Remaining ceilings are CNY
29.20259, 2,920,259 tokens and 23 requests.

This is a valid real-runtime failure, not a completed quality comparison. The trace proves
that the model can choose allowed tools and use frozen observations, but the Agent delivered
nothing scoreable while the existing Workflow baseline contains an actionable discovery
diagnosis, a complete evidence-limited article and passing deterministic text QA. Stability,
draft quality and cost per successful Agent deliverable remain `NOT_MEASURABLE`. No second
Prompt/scenario was attempted.

Post-run targeted regression command:
`env PYTHONPATH=backend .../backend/.venv/bin/pytest -q backend/tests/test_shared_model_budget.py backend/tests/test_agent_experiment.py backend/tests/test_automatic_delivery.py backend/tests/test_deepseek_generation_contract.py backend/tests/test_derived_model_call_identity.py`
resulted in `62 passed`.

## Context-continuity repair and authorized rerun

The owner authorized one further run on the same exact frozen input, with a subordinate
ceiling of CNY 3, 300,000 tokens and 10 requests inside the original shared ledger. Inspection
confirmed that each prior implementation request already serialized recent decision and tool
result history into the stateless Responses `input`; the failure was therefore not total loss
of history. The model lacked an explicit progress inventory, normalized observation identity
and finalization phase.

The local repair added an audited `MODEL_INPUT_CONTEXT` manifest for every request, an
observation catalog with full recent tool results, checkpoint-safe summary replay, normalized
scope/tool/argument observation keys, duplicate-result reuse without re-executing the tool,
two-call finalization reservation, and safe rejection of exploration calls during
finalization. It did not add tools or GEO analysis steps. Offline transport tests inspect the
actual `/responses` body and prove that history and the observation catalog are serialized
into `input`; checkpoint, truncation, duplicate, finalization, budget and formal-lane tests
also pass.

The zero-call preflight first produced one preserved `BLOCKED / RUN_SNAPSHOT_DRIFT` row
because it was started outside the repository-relative monitoring artifact root, so two
semantic-region artifacts could not be projected. Running the new independent preflight from
the existing artifact root restored the exact frozen scope hash
`69a86f8ecdc574e5a7631d6982270e1a25e29485937df4c17d2205ed99a7b2c7` without copying,
refetching or changing evidence. It verified the prior ledger exactly at 13 requests, 79,741
tokens and CNY 0.79741 and created run
`agent-run-50a60949-2e4e-41d1-b486-7abd2016e7b2`.

The one authorized external execution then failed before any provider response with
`ConnectError`. Automatic retries remained zero. It produced no model decision, tool call or
Agent result, so real cross-turn continuity and delivery quality remain untested. The shared
guard conservatively retained this request as `DELIVERY_UNKNOWN`: one request, a 31,172-token
ceiling and CNY 0.31172. Provider usage and actual charge are unknown and must not be reported
as consumed tokens or billed cost. The cumulative conservative ledger is now 14 requests,
110,913 accounted tokens and CNY 1.10913, with one unknown reservation and no in-flight
request. No retry or second scenario was started.

## Known limits and next exact task

L1 is intentionally not admitted by the P0 raw-first Agent path: a source snapshot alone is
not enough to invent a fully grounded formal binding. P0 can admit conservative L2 or L3 and
always leaves publication at `VERIFY_FIRST`; future L1 support must consume an actually
qualified per-block Evidence/Truth partition without exposing formal Strategy or Draft.

The next decision is not to expand tools or scenarios. The progress and finalization repair is
implemented and tested, but the authorized provider attempt ended in an unknown-delivery
transport failure. A further external request requires a new explicit authorization; the
unknown reservation must remain occupied. Until a complete Agent result exists, real
quality/cost superiority is `NOT_MEASURABLE`, not failed and not passed.

The subsequent zero-cost network investigation is recorded in
`docs/geo-agent-v1/NETWORK_DIAGNOSTIC_2026-10-19.md`. It reproduced the `ConnectError` as a DNS
failure inside the restricted command environment, while the same interpreter reached the
DeepSeek API through DNS, TCP, verified TLS and unauthenticated HTTP when network access was
explicitly enabled. No application code, experiment state or budget reservation was changed,
and no paid retry was started.

The separately authorized network-enabled retry is recorded in
`docs/geo-agent-v1/REAL_RUN_NETWORK_RETRY_2026-10-19.md`. It reached DeepSeek, made three
accepted non-repeating tool decisions with complete prior observations in each subsequent
request, and then stopped fail-closed when the fourth response did not validate as an
`AgentDecision`. No Agent result version was created and comparison quality remains
`NOT_MEASURABLE`. The authoritative shared ledger records four requests and 26,579 actual
tokens for this retry; no further request or scenario was started.

The subsequent zero-call response-protocol and accounting repair is recorded in
`docs/geo-agent-v1/PROTOCOL_REPAIR_ACCEPTANCE_2026-10-20.md`. It removes arbitrary nested-JSON
recovery from the Agent path, strictly adapts one complete DSML `AgentDecision` or documented
Responses output item, and records provider usage before business parsing. The historical
Agent Run projection is reconciled to the unchanged shared ledger with append-only correction
events. Offline regression passes, but no new provider request or GEO result was produced.

The newly authorized single real validation is recorded in
`docs/geo-agent-v1/REAL_RUN_VALIDATION_5_2026-10-20.md`. The provider completed one request but
returned eight newline-delimited decisions in one output instead of the required single
`AgentDecision`. The strict adapter rejected it, settled usage and preserved the complete raw
provider response in the restricted seven-day audit archive. No tool or second model request
ran, no Agent result was created, and comparison quality remains `NOT_MEASURABLE`.

The zero-cost protocol convergence is recorded in
`docs/geo-agent-v1/SINGLE_DECISION_PROTOCOL_CONVERGENCE_2026-10-20.md`. Exact reconstruction of the
fifth request matched its persisted provider-payload hash and showed that local `strict_json` had not
enabled provider `text.format.strict`. The Agent-only transport now sends strict mode, leads with a
single-current-action contract, exposes a closed allowlisted decision Schema, rejects mixed actions,
and versions all affected identities. The exact eight-decision response remains wholly rejected in
offline replay. No external request was made.

The final authorized text-protocol validation is recorded in
`docs/geo-agent-v1/REAL_RUN_STRICT_SINGLE_DECISION_2026-10-20.md`. The corrected request reached
DeepSeek but received a non-200 response before any provider envelope, usage or `AgentDecision`.
The first protocol gate stopped the run after exactly one request; no tool, result or second request
ran. The shared ledger conservatively retains the full reservation. A local accounting/audit defect
masked the original HTTP detail and did not archive the raw non-200 body, so the rejected field
cannot be claimed from available evidence. The Agent/Workflow quality comparison remains
`NOT_MEASURABLE`. Per the approved architecture stop, the text JSON decision route is closed; any
next phase must separately choose between a provider-native single function and a minimal frozen
evidence package.

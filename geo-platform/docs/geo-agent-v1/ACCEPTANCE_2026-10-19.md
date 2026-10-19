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

## Known limits and next exact task

L1 is intentionally not admitted by the P0 raw-first Agent path: a source snapshot alone is
not enough to invent a fully grounded formal binding. P0 can admit conservative L2 or L3 and
always leaves publication at `VERIFY_FIRST`; future L1 support must consume an actually
qualified per-block Evidence/Truth partition without exposing formal Strategy or Draft.

The next decision is not to expand tools or scenarios. If the owner authorizes another paid
attempt, first change and test only the run-local turn policy so a model that has already read
the answer and citation list has room to synthesize a result, while preventing repeated
idempotent observations from consuming the whole run. Until a complete Agent result exists,
real quality/cost superiority is `NOT_MEASURABLE`, not failed and not passed.

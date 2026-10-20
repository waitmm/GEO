# GEO Agent V1 strict single-decision real validation

Date: 2026-10-20

## Decision

The one authorized Project 1 / Prompt 1 / Run 1 validation was executed and all external
activity stopped immediately afterward. The run did not pass the first protocol gate: DeepSeek
returned a non-200 HTTP response before any provider response envelope, token usage or
`AgentDecision` was available. Exactly one request was made. No retry, tool call, Agent result,
second scenario, sampling, fetch, publication or formal V2 write followed.

This is a provider request/protocol compatibility failure, not evidence that the model emitted
multiple decisions again and not evidence about GEO planning or delivery quality. The corrected
text decision protocol has reached its stated architecture stop condition. Do not make another
text-parser repair or paid retry. A subsequent product decision may compare one provider-native
single-function decision protocol with the simpler frozen-evidence-package Agent; neither route is
implemented or called by this validation.

## Frozen pairing and zero-cost preflight

- branch: `experiment/geo-agent-v1`
- single-decision protocol commit: `f63a0be6dbf853154247b2a35e7eab395a4cf25e`
- strict validation controller commit: `959fb05`
- artifact-root correction commit: `d4d8dba`
- Agent Run: `agent-run-0218c227-8516-49a3-ac94-bc43a1afc923`
- Project / Prompt / Run IDs: `1 / 1 / [1]`
- Analysis: `925ef2dc-605f-467d-a025-52033a574d92`
- Context: `ctx-5407fb2f-acd5-41ac-8ac7-41713a08a5aa`
- raw output hash: `11dca9e4438bdecf66a86472f2e8a498f6f7067c3bcc4f9f3cfd381d2c9ebccb`
- Agent input scope hash: `69a86f8ecdc574e5a7631d6982270e1a25e29485937df4c17d2205ed99a7b2c7`
- Agent execution hash: `9cb4d3018bf26d2f33ad7b5ba9b8bdd23248dc1741b2f4efcaccf8e22e0af512`
- citation manifest hash: `c0b5ad9c6924e04f117a901059adc4df10b19b9cc57fc05f1be36f833042ef35`
- completion manifest hash: `444719912b95cea6a03db1cfbf85196c4dd61e5b9b4772486d4b525e54fab1cf`
- Truth set hash: `34fb796a401856974477200a9ea5bf9bf65fcf5c8357df137746235f3bd30eae`
- Workflow result: `execution-v7:c2dc55b0d25749c7`
- Workflow result hash: `c2dc55b0d25749c712c4076260f2a1039c021e76ce8569df839ab04d842e9081`

The first zero-call preflight for this attempt was started from the experiment worktree's
`backend/`. That tree does not contain Run 1's immutable `semantic-regions.json`, so fail-closed
revalidation created a preserved `BLOCKED / RUN_SNAPSHOT_DRIFT` audit row with zero model calls,
zero tool calls and zero budget use. The live Run had not changed. The controller was then invoked
with worktree code through `PYTHONPATH`, but from the primary repository `backend/` where Run 1's
immutable monitoring artifacts live. A fresh idempotency key restored the exact expected scope
hash without copying or changing evidence.

The accepted preflight verified:

- execution contract `geo.agent.execution.v3`;
- prompt `geo-agent-loop.v3`, decision Schema `geo.agent.decision.v2`, loop input
  `geo.agent.loop-input.v3` and single-decision Responses transport;
- Agent-only `provider_schema_strict=true` and a two-request finalization reserve;
- shared ledger at 19 requests, 143,551 conservatively accounted tokens, CNY 1.43551 and zero
  in-flight requests;
- CNY 3 / 300,000-token / 10-request sub-budget with automatic retries disabled;
- unchanged, hash-valid Workflow baseline and strict pairing;
- restricted response audit directory mode `0700` and file mode `0600`.

The formal database SHA-256 before the run was
`e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`.
A no-inference GET from the exact Python worker environment reached `https://api.deepseek.com`
and returned HTTP 401. It did not call `/responses`.

## Real request and first protocol gate

The actual request used the external authorization on the frozen Agent Run, the
`deepseek-flash` effective model and `/responses`. Its request identity was persisted before
network I/O:

- model input payload hash: `883d0ad2b9d182d8755c4cfe203c5f555e7ecbc8807426f9caaa9d76590256db`
- external request input hash: `2265c328aaa355f2a40842f79f1c6ad8ec37d89f2f11272c50f66db62712251f`
- provider payload hash: `29e11cd29e783ad65bfed85e3656a0e3b62d793f577aa7ba5fae7aa30e911ef1`

The provider returned a 206-byte non-200 HTTP error body in about 1.4 seconds. There was no
Responses envelope, response model, output item or provider usage. The error-body SHA-256 is
`89567bfe3e9fdd93e26c7d87490772425f54dba83207a2c95aa3cbc15f195647`.
Because no decision existed, the required checks for a unique top-level object, legal
`action_type`, allowlisted tool and executable action could not pass. The run stopped before a
second request, exactly as required by the protocol gate.

The non-200 response is consistent with provider rejection of the request or one of its
structured-output fields. The exact rejected field cannot be asserted from the retained evidence.
In particular, this run does not prove that DeepSeek accepts or enforces
`text.format.strict=true`; it only proves that the corrected request was not admitted far enough to
produce a decision.

## Accounting and audit defect exposed by the run

The shared ledger received the rejected-response audit event first and conservatively retained the
full 32,623-token / CNY 0.32623 reservation. That is a risk ceiling, not actual provider usage or an
invoice. The provider returned no usage, so actual input tokens, output tokens and cost remain
unknown.

After the shared ledger recorded the event, local Agent accounting treated every `REJECTED` event
as if complete provider usage must exist. It raised `AGENT_PROVIDER_USAGE_INCOMPLETE`, masking the
original HTTP error in the Agent Run. The local Run consequently remains at
`RESERVED_IN_FLIGHT`, while the authoritative shared ledger has zero in-flight requests and a
terminal `FAILED` reservation. The restricted archive also did not create a new file because it
currently archives only rejected parsed provider envelopes, not raw non-200 HTTP bodies. The
206-byte body itself was therefore not retained; only its hash, length and request identity were.

This is a real audit/accounting compatibility defect and prevents exact attribution to a specific
HTTP status or request field. It does not authorize another provider call, a parser fallback,
release of the reservation or a silent rewrite of the historical event. The unchanged shared ledger
is authoritative until a separately scoped append-only reconciliation is approved.

## Trace, result and budget

Persisted Agent events are:

1. zero-cost preflight `MODEL_INPUT_CONTEXT`;
2. zero-cost preflight `MODEL_BLOCKED / CACHE_MISS`;
3. real turn-one `MODEL_INPUT_CONTEXT` with zero history and zero observations;
4. `RUN_FAILED / AGENT_PROVIDER_USAGE_INCOMPLETE` after the non-200 audit event.

Actual Agent tool trace: empty. Agent result versions: zero. Diagnosis, strategy, body, QA,
evidence grade and server qualification: not produced.

| Item | This validation | Shared batch after validation |
| --- | ---: | ---: |
| requests | 1 | 20 / 36 |
| actual provider tokens | unknown | unknown where reservations lack usage |
| conservative accounted tokens | 32,623 | 176,174 / 3,000,000 |
| conservative accounted cost | CNY 0.32623 | CNY 1.76174 / CNY 30 |
| remaining request capacity | - | 16 |
| remaining token capacity | - | 2,823,826 |
| remaining cost capacity | - | CNY 28.23826 |
| shared-ledger in-flight requests | - | 0 |
| elapsed | 1.431 seconds | - |

The historical `DELIVERY_UNKNOWN` reservation remains occupied. No reservation or history was
reset.

## Workflow comparison and architecture stop

The Workflow baseline made zero new calls and remains hash-valid. It still has a complete
reviewable diagnosis/strategy/execution chain and publication draft. The Agent has no artifact, so
content quality, factual accuracy, evidence-grade equivalence and cost per successful delivery are
`NOT_MEASURABLE`. Workflow is operationally complete for this paired input; that does not establish
general architecture superiority.

Layered verdict:

1. **Protocol validity: failed before decision output.** The supplier returned non-200; no unique
   `AgentDecision` was available.
2. **Execution completeness: not evaluated.** There were no tool calls or later turns.
3. **Business validity: not evaluated.** There was no result for grading or comparison.

Per the approved stop condition, the text JSON decision route now stops. The next architecture
checkpoint should compare, offline first, exactly two replacements: a provider-native single
`AgentDecision` function on a profile that documents/enforces it, and a minimal frozen-evidence
package that lets the model synthesize one complete GEO artifact with only bounded supplemental
reads. Given the accumulated loop/protocol cost and absence of one successful real artifact, the
frozen-evidence-package route remains the preferred baseline. No such work begins here.

## Regression

After external calls stopped:

- combined Agent / DeepSeek transport / derived identity / shared-budget / formal-delivery suite:
  `83 passed`;
- formal database SHA-256 remained
  `e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`;
- external calls after the failed first request: `0`.


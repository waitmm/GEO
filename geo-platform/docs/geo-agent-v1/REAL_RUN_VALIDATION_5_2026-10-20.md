# GEO Agent V1 fifth controlled real validation

Date: 2026-10-20

## Decision

The single authorized Project 1 / Prompt 1 / Run 1 execution was performed and external
activity stopped immediately afterward. Network, authentication, frozen pairing, shared-budget
settlement and full rejected-response retention all worked. The Agent did not deliver a result.

This run failed because DeepSeek returned eight newline-delimited top-level decisions inside
one `output_text`, despite the request's JSON Schema and the Agent contract requiring exactly
one decision per turn. The strict adapter correctly rejected the response. This is a
model/provider structured-protocol and decision-granularity failure, not the prior DSML nested
JSON extraction defect.

No second paid run was started and no Agent feature was changed after observing the failure.

## Frozen pairing and preflight

- code used for the response archive: `3d7e512`
- controller artifact-root binding: `8955ada`
- Agent Run: `agent-run-b20f25ad-3052-4560-97a6-fa1fa3864b96`
- Project / Prompt / Run IDs: `1 / 1 / [1]`
- Analysis: `925ef2dc-605f-467d-a025-52033a574d92`
- Context: `ctx-5407fb2f-acd5-41ac-8ac7-41713a08a5aa`
- raw output hash: `11dca9e4438bdecf66a86472f2e8a498f6f7067c3bcc4f9f3cfd381d2c9ebccb`
- Agent input scope hash: `69a86f8ecdc574e5a7631d6982270e1a25e29485937df4c17d2205ed99a7b2c7`
- citation manifest hash: `c0b5ad9c6924e04f117a901059adc4df10b19b9cc57fc05f1be36f833042ef35`
- completion manifest hash: `444719912b95cea6a03db1cfbf85196c4dd61e5b9b4772486d4b525e54fab1cf`
- Truth set hash: `34fb796a401856974477200a9ea5bf9bf65fcf5c8357df137746235f3bd30eae`
- Workflow result: `execution-v7:c2dc55b0d25749c7`
- Workflow result hash: `c2dc55b0d25749c712c4076260f2a1039c021e76ce8569df839ab04d842e9081`

The first zero-call preflight was deliberately preserved as `BLOCKED / RUN_SNAPSHOT_DRIFT`:
it ran from the repository root, while Run 1's immutable semantic-region artifacts are rooted
relative to `backend/`. A new idempotency key was used from the correct artifact root; it
restored the exact expected scope hash. The blocked row made zero model calls and consumed no
budget.

The accepted preflight recorded 18 prior shared requests, 137,492 accounted tokens, CNY
1.37492, zero in-flight requests, the CNY 3 / 300,000-token / 10-request sub-budget and the
seven-day restricted response archive. The unauthenticated HTTPS preflight returned HTTP 401,
proving reachability without invoking `/responses`.

## Actual model response and trace

One real `deepseek-flash` request completed. The provider response contained a completed
reasoning item and one completed message item. The message's `output_text` was 1,449 characters
with SHA-256 `f9083dad8a57d7d75684bbd854b7c16557e82ac63440128078b1fbcfcf3ebe62`.

Offline replay of the exact retained text produced JSON `Extra data` at line 2. It contains
eight individually parseable objects:

1. `TOOL_CALL get_scope_summary`
2. `TOOL_CALL read_answer`
3. `TOOL_CALL list_citations`
4. `TOOL_CALL read_product_truth`
5. `TOOL_CALL read_monitor_metrics`
6. `TOOL_CALL read_brand_context`
7. `TOOL_CALL list_runs`
8. `STOP`

These are proposed decisions embedded in one invalid response, not executed tool calls. The
actual Agent tool trace is empty. Returning both seven exploration requests and a conditional
stop in one turn also contradicts the instruction to choose one next action and avoid
mechanically requesting every tool. Accepting the first object, executing all objects, or
guessing a preferred branch would silently change Agent semantics, so the server correctly
returned `FAILED_PARSE`.

Persisted Agent events:

1. zero-call preflight `MODEL_INPUT_CONTEXT`
2. zero-call preflight `MODEL_BLOCKED / CACHE_MISS`
3. real `MODEL_INPUT_CONTEXT`
4. `MODEL_REQUEST_ACCOUNTED / REJECTED`
5. `MODEL_BLOCKED / FAILED_PARSE`

Agent final state: `FAILED`. Model requests: 1. Tool calls: 0. Result versions: 0. Evidence
grade and server delivery qualification: not applicable.

## Complete-response audit

The rejected provider envelope was saved to:

`/private/tmp/geo-agent-real-comparison-20261019/rejected-response-audit/agent-response-4335e0bd02c5-007593e636a2663f-f9083dad8a57d7d7.json`

- directory mode: `0700`
- file mode: `0600`
- file size: 32,474 bytes
- record hash: `664f5986c533898734d1b4d430659d2cfaa8b5486d1f434eb3d037d9875878f7`
- expiry: `2026-10-27T01:56:14.889956+00:00`
- request headers, Authorization and API key: not stored

The archive contains the full provider response envelope, including the exact output and usage,
and can reproduce the failure offline. The archive writer does not add outbound headers or the
request payload; the provider envelope can itself echo non-secret request fields such as the
Agent instructions.

## Usage and budget

| Item | Value |
| --- | ---: |
| requests | 1 |
| input tokens | 5,307 |
| cached input tokens reported by provider | 3,968 |
| output tokens | 752 |
| total tokens | 6,059 |
| conservative shared-ledger cost | CNY 0.06059 |
| cache-miss peak-price estimate | CNY 0.01663 |
| execution elapsed | 5.949 seconds |

The price estimate is not a provider invoice; the persistent ledger remains authoritative and
uses the approved CNY 10/million conservative rate.

Shared batch after the run:

- requests: 19 / 36; 17 remaining
- accounted tokens: 143,551 / 3,000,000; 2,856,449 remaining
- conservative cost: CNY 1.43551 / CNY 30; CNY 28.56449 remaining
- in-flight requests: 0
- the earlier `DELIVERY_UNKNOWN` reservation remains occupied

## Workflow comparison

The strict Workflow baseline remained unchanged and made zero new model calls. It has a complete
1,609-character publication draft titled `抖音跳转链接：场景对照与选择检查`, content hash
`bc2fc22c2805e70cc9a6df050d0b370589f1a089e7dad553c9424d0855098da9`, deterministic QA
`READY`, delivery status `READY`, and publication status `NEEDS_BUSINESS_CONFIRMATION`.

The Agent produced no diagnosis, strategy, draft or QA. Content quality, factual differences,
evidence-grade equivalence and cost per successful delivery are therefore `NOT_MEASURABLE`.
For this attempt only, Workflow wins operationally because it has a complete reviewable package
and Agent has none; this does not establish architecture-level superiority.

## Classification and stop condition

- protocol adapter: behaved correctly and retained replayable evidence
- model/provider protocol adherence: failed; multiple top-level decisions were returned
- Agent decision behavior: failed the one-action-per-turn contract and proposed broad batching
- tools: not exercised, so tool design cannot be blamed or evaluated
- GEO delivery quality: not measurable because no artifact reached validation
- formal V2 isolation: preserved; formal database SHA-256 remains
  `e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`

Post-run regression covering the shared guard, derived call identity, formal automatic delivery,
DeepSeek transport and Agent experiment: `77 passed`.

No further paid retry is authorized or warranted under this run. The next product decision is
whether to invest in stronger enforcement of one-decision output (for example provider-native
tool semantics or a different model/profile) or stop this Agent approach; that decision is not
implemented here.

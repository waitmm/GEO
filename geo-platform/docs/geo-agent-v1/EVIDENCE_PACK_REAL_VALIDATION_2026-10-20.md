# GEO Evidence Pack first real delivery validation

Date: 2026-10-20

Branch: `experiment/geo-agent-v1`

Offline Evidence Pack baseline: `0272ce6776298eff81ca55bcaa6a9542b60322a8`

Budget authorization/controller commit: `9bf6bbbd48d1dac1c669b6c2834f9d348fae8d40`

Change classification: `IMPLEMENTATION_CHANGE`

## Executive result

The single authorized DeepSeek request was made and external calls then stopped. The run did not
produce an `AgentResultVersion` and did not produce reviewable GEO content.

This is an engineering failure, not a measured GEO content-quality failure:

1. DeepSeek returned a definite response with `response.status=incomplete`.
2. The plain-text adapter rejected that status before extracting the provider `usage` or any
   returned output text.
3. The local Agent accounting sink then raised `AGENT_PROVIDER_USAGE_INCOMPLETE`.
4. Because accounting runs before the restricted response archive, the same exception prevented
   the complete rejected provider response from being archived.

The Agent run is therefore `FAILED`, with no result version and no content that can be compared to
Workflow. Business usability and relative quality remain `NOT_MEASURABLE`. No retry, repair model
call, tool call, second scenario or Workflow model call was performed.

## Frozen identity and Evidence Pack

- Project / Prompt / Run: `1 / 1 / [1]`
- analysis: `925ef2dc-605f-467d-a025-52033a574d92`
- context: `ctx-5407fb2f-acd5-41ac-8ac7-41713a08a5aa`
- raw output hash: `11dca9e4438bdecf66a86472f2e8a498f6f7067c3bcc4f9f3cfd381d2c9ebccb`
- Agent input scope hash: `69a86f8ecdc574e5a7631d6982270e1a25e29485937df4c17d2205ed99a7b2c7`
- Agent execution hash: `eafa64ecb9253c1ac1f4945a5b1e5958a7292f8983d53555dcf746ee274c32ae`
- Evidence Pack hash: `21260f1074248ead7939be0161c9e9a2b500d82aa185a09fa99bff3e3335c515`
- Agent run: `agent-run-ed72e423-4ee7-4929-b1e8-65b87989b909`

Coverage:

- valid answers: 1
- citation occurrences: 19
- source snapshots: 18
- source passages: 451 total, 191 included as whole passages, 260 omitted with individual
  `TEXT_BUDGET` records and hashes
- Product Truth facts: 6
- brand context mode: `EMPTY`
- deterministic included text estimate: 89,990 characters

The preflight computed a 259,191-token conservative ceiling and CNY 2.59191 reservation, below the
authorized 300,000-token / CNY 3 sub-limits. The actual request guard produced a 259,158-token
ceiling and CNY 2.59158 reservation. The difference reflects final canonical request serialization;
both values remained within the authorization.

## Authorization and offline gates

The original shared-ledger config and all historical request records remained unchanged. A new
append-only `geo-agent-budget-authorization-extension.v1` record authorized only:

- lane: `AGENT_EXPERIMENT`
- the exact Agent run above
- model: `deepseek-flash`
- transport: `RESPONSES_TEXT`
- transport version: `geo.deepseek.responses-text.v1`
- prompt: `geo-evidence-pack-synthesis.v1`
- result contract: `geo.evidence-pack.markdown-result.v1`
- one request, 300,000 tokens, CNY 3
- automatic retry 0 and max concurrency 1

The authorization remains linked to the request through a separate immutable relation. The old
`RESPONSES_JSON_SCHEMA` authorization continues to work, while text requests with a different run,
transport version, prompt version or result schema fail closed.

Offline evidence before the real request:

- shared-ledger extension tests: `12 passed`
- shared ledger + provider + Agent suite: `65 passed`
- combined Agent / formal Workflow / transport regression: `97 passed`
- copied-database and copied-ledger full controller preflight: passed with zero external calls
- same-worker, zero-inference network preflight: unauthenticated `GET /responses` returned HTTP 401

The price evidence was checked on 2026-10-20 against the official DeepSeek Chinese pricing page.
The published `deepseek-flash` peak rates were CNY 2 / million cache-miss input tokens and CNY 8 /
million output tokens. The ledger continued to reserve at CNY 10 / million total tokens, which is
more conservative for the batch guard.

## Real request evidence

- external model requests: 1
- automatic retries: 0
- repair model calls: 0
- Agent tool calls: 0
- elapsed time: 79.677 seconds
- provider response model: `deepseek-flash`
- provider response status: `incomplete`
- serialized response length recorded by the adapter: 53,252 characters
- raw response hash: `f941753eed9ecbed918aa3718819f7399253578d8a340d6af45a10d483f5e393`
- adapter rejection code: `FAILED_PARSE`
- final local blocker: `AGENT_PROVIDER_USAGE_INCOMPLETE`
- `AgentResultVersion`: none
- restricted raw-response archive files: none

The provider's exact `incomplete_details`, input tokens, output tokens and total tokens were not
persisted. They must not be reconstructed from the conservative ceiling. It is plausible that the
16,384-token output allowance was exhausted, but the missing raw response means this cannot be
asserted as the audited cause.

## Accounting

The shared ledger, not the local Agent Run usage display, remains authoritative for this failed
request.

Before:

- requests: 20 / 36
- accounted tokens: 176,174 / 3,000,000
- conservative accounted cost: CNY 1.76174 / 30

After:

- requests: 21 / 36
- accounted tokens: 435,332 / 3,000,000
- conservative accounted cost: CNY 4.35332 / 30
- remaining: 15 requests, 2,564,668 tokens, CNY 25.64668
- in flight: 0

This request's extension is fully consumed: 1 / 1 request. Because complete provider usage was not
persisted, it conservatively retains 259,158 tokens and CNY 2.59158. That amount is a risk/accounting
hold, not a claim about the exact DeepSeek invoice. Exact actual input/output tokens and actual CNY
cost are unknown.

The historical `DELIVERY_UNKNOWN` reservation remains untouched.

## Workflow pairing and comparison

The frozen Workflow chain was reverified after the real request. Its active execution result is:

- version: `execution-v7:c2dc55b0d25749c7`
- hash: `c2dc55b0d25749c712c4076260f2a1039c021e76ce8569df839ab04d842e9081`
- content delivery: `READY`
- publication status: `NEEDS_BUSINESS_CONFIRMATION`
- draft title: `抖音跳转链接：场景对照与选择检查`
- draft body length: 1,609 characters

The Workflow baseline remains strictly paired, but there is no Agent content to score. Diagnosis,
strategy, full draft, QA, factual accuracy, commercial value and relative cost-quality are all
`NOT_MEASURABLE` for this attempt.

## Isolation and artifacts

The formal V2 database was not written and its SHA-256 remains:

`e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`

The experiment used only the isolated database and shared budget ledger. No sampling, Search,
Fetch, page crawl, publication, formal result write or additional Prompt was started.

Restricted local artifacts (mode 0600 unless a directory):

- `/private/tmp/geo-agent-real-comparison-20261019/evidence-pack-preflight.json`
- `/private/tmp/geo-agent-real-comparison-20261019/evidence-pack-real-result.json`
- `/private/tmp/geo-agent-real-comparison-20261019/shared-budget.sqlite3`
- `/private/tmp/geo-agent-real-comparison-20261019/evidence-pack-response-audit/` (mode 0700;
  unexpectedly empty)

Post-run hashes:

- shared ledger: `35e1975a8ff5228d91caec2a658432ff5913f87dfdda0d90f8a91720b8b467dd`
- isolated experiment database: `54374e5ee13800558c71e45e2748d3d334331196d46b90d069dc2864fc362ff1`

## Root cause and stop decision

The observed failure has two layers:

1. **Incomplete provider generation:** DeepSeek returned `status=incomplete`; therefore the single
   call did not establish a complete Markdown delivery.
2. **Adapter/audit ordering defect:** the text adapter did not extract `usage` or output before
   rejecting an incomplete response, and the accounting exception occurred before secure raw
   response archival. This caused the final blocker and destroyed the exact replay evidence that
   the experiment explicitly required.

This attempt does not show that Evidence Pack content is poor; it shows that the current one-call
configuration and failure-path adapter did not yield an auditable deliverable. Per the authorization,
no code repair or paid rerun was started after this result. Any future work requires a new explicit
decision and authorization.

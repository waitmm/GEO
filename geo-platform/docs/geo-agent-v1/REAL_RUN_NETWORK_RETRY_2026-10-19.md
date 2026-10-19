# GEO Agent V1 controlled real run after network diagnosis — 2026-10-19

## Verdict

The authorized Project 1 / Prompt 1 / Run 1 retry reached DeepSeek successfully and obtained
four provider responses. It did not complete a GEO deliverable. The run stopped fail-closed at
turn 4 with `FAILED / FAILED_PARSE`, before an `AgentResultVersion` was created. No retry and no
second scenario was started.

This run proves real context continuity and non-repeating early investigation behavior, but it
does not prove end-to-end Agent delivery quality. Agent versus Workflow content quality remains
`NOT_MEASURABLE`.

## Authorization and pairing

- code branch and starting commit: `experiment/geo-agent-v1` at
  `70600b5bc041b3f5edb2261d93abe07b5acb0460`
- project / prompt / run IDs: `1 / 1 / [1]`
- Agent run: `agent-run-1f089136-1287-49f8-b97f-9efc22306c81`
- frozen input scope hash:
  `69a86f8ecdc574e5a7631d6982270e1a25e29485937df4c17d2205ed99a7b2c7`
- strict pairing: passed
- Workflow call required: false; the existing frozen Workflow baseline was reused
- sub-budget: 10 requests, 300,000 tokens and CNY 3
- automatic retries: 0
- shared batch ceiling retained: 36 requests, 3,000,000 tokens and CNY 30

The first zero-call attempt-4 preflight was deliberately retained as a
`BLOCKED / RUN_SNAPSHOT_DRIFT` audit row because it ran outside the artifact-relative backend
root. It made no model request and did not change the ledger. The accepted preflight then ran
against the existing artifact root, produced the expected frozen hash and authorized the run
above. No evidence was copied, fetched or regenerated.

Immediately before the paid execution, the same Python process performed an unauthenticated
`HEAD https://api.deepseek.com/` and received HTTP 401. The paid Agent worker then ran in that
same network-enabled process.

## Actual decision and tool trace

| Turn | Context carried into request | Accepted decision | Tool result |
| --- | --- | --- | --- |
| 1 | no prior history | `get_scope_summary` | 1 valid answer, 19 citation occurrences, brand mentioned 0, brand context EMPTY |
| 2 | turn-1 decision, full observation and catalog summary | `list_runs` | Run 1, success, 746 answer characters, 19 references, brand not mentioned |
| 3 | prior two decisions and both observations | `read_answer(run_id=1, 0..746)` | complete frozen answer and answer hash |
| 4 | all three prior decisions and observations | rejected before decision admission | provider response did not validate as `AgentDecision` |

Every real turn reported complete observation summaries, no history truncation and all prior
full results retained. History/catalog counts progressed `0/0`, `1/1`, `2/2`, `3/3`.
`get_scope_summary` was called once; no tool or normalized observation key was repeated. This is
the first real-provider evidence that the context-continuity and progress-inventory repair works
for multiple turns.

## Failure evidence

The fourth provider response completed at the HTTP/provider layer and included usage. Its
retained excerpt begins with a DeepSeek DSML invocation named `AgentDecision`, including
`action_type=TOOL_CALL` and a substantive reasoning field. Validation then received only
`{"run_id":"1"}` and rejected it because `action_type` and `reasoning` were missing and
`run_id` is not a top-level `AgentDecision` field.

The complete raw response is intentionally not retained; only its hash, length and redacted
excerpt are in the audit ledger. Based on that excerpt and the inspected parser path, the
high-confidence cause is a response-adapter mismatch: generic JSON-object extraction selected
the nested tool-arguments object from a DSML-encoded `AgentDecision`, while the existing DSML
recovery only accepts a direct invocation whose name is one of the tool allowlist entries. This
is not a DNS, TLS, authentication, database, budget or frozen-input failure. The exact intended
fourth tool name cannot be reconstructed safely from the retained excerpt.

No parser change was made in this run, and the failed response was not replayed.

## Usage, cost and time

| Request | Outcome | Input tokens | Output tokens | Total | Conservative ledger cost | Peak-price estimate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | accepted | 5,301 | 209 | 5,510 | CNY 0.05510 | CNY 0.012274 |
| 2 | accepted | 6,134 | 285 | 6,419 | CNY 0.06419 | CNY 0.014548 |
| 3 | accepted | 6,504 | 140 | 6,644 | CNY 0.06644 | CNY 0.014128 |
| 4 | rejected: `FAILED_PARSE` | 7,484 | 522 | 8,006 | CNY 0.08006 | CNY 0.019144 |
| Total | 3 accepted, 1 rejected | 25,423 | 1,156 | 26,579 | CNY 0.26579 | CNY 0.060094 |

The paid execution controller elapsed time was 12.805 seconds. The database Run lifecycle is
longer because it includes the zero-call cache-only preflight and the gap before network-enabled
execution.

All four provider calls used attempt 1. The sub-budget therefore ended at 4/10 requests,
26,579/300,000 tokens and CNY 0.26579/3.

The shared ledger after the stop is:

- 18/36 requests
- 137,492/3,000,000 conservatively accounted tokens
- CNY 1.37492/30 conservatively accounted cost
- remaining: 18 requests, 2,862,508 tokens and CNY 28.62508
- known provider usage: 106,320 tokens
- cumulative peak-price estimate for known usage: CNY 0.235956
- in-flight requests: 0
- the earlier `DELIVERY_UNKNOWN` reservation remains occupied

The conservative ledger cost is the binding guard value. The peak-price value is an estimate
from recorded provider usage and the authorized price schedule, not a claim about the provider
invoice.

## Result and Workflow comparison

The Agent produced no result version, evidence grade, diagnosis package, strategy, publication
draft or QA package. Server-side result/schema/fact-grade hash validation therefore did not run
and cannot be marked passed or failed.

The reused Workflow chain remains independently hash-valid:

- diagnosis: `diag-v1:864a6924a61a3e8b`
- citation contribution: `contribution-v1:be21567a6d114f4b`
- strategy: `strategy-v1:178f23f7c8de96a1`
- execution: `execution-v7:c2dc55b0d25749c7`
- execution result hash:
  `c2dc55b0d25749c712c4076260f2a1039c021e76ce8569df839ab04d842e9081`

Because the Agent side has no deliverable, diagnosis accuracy, strategy value, draft quality and
QA quality cannot be compared. The real evidence supports only these narrower findings:

1. network, authentication and Responses transport reached the provider;
2. the model made three coherent, non-repeating tool decisions;
3. previous observations were present in every subsequent request;
4. end-to-end delivery remains unproven because response-contract handling stopped the run.

## Audit consistency issue exposed

The shared ledger correctly records all four external requests and settles the rejected fourth
response as `FAILED` with complete actual usage. The Agent Run row counts only the three
admitted decisions (`model_call_count=3`, 17,939 input tokens and 634 output tokens) and leaves
its local authorization/progress view showing the fourth reservation as in flight. This is an
audit-display inconsistency, not an additional live reservation: the authoritative shared
ledger has `in_flight=0`.

No correction was made under this run authorization. Any future work should distinguish this
local Run-accounting cleanup from the separate DSML response-adapter issue, and neither may be
used to justify an automatic paid retry.

## Preserved artifacts and isolation

- zero-call accepted preflight:
  `/private/tmp/geo-agent-real-comparison-20261019/preflight-network-retry-4-artifact-root.json`
- complete real comparison:
  `/private/tmp/geo-agent-real-comparison-20261019/real-comparison-network-retry-4.json`
- shared ledger:
  `/private/tmp/geo-agent-real-comparison-20261019/shared-budget.sqlite3`
- isolated experiment database:
  `/private/tmp/geo-agent-real-comparison-20261019/isolated-upgrade/database.db`

Post-run hashes:

- preflight report:
  `cadd96d793d1a40e571f0b1674e5601db24c707ce36ede63becc4fdb73f2d8f0`
- comparison report:
  `08af2cca1fcfc30e2bcec23b9bde7dc084393a51cd0e919313bb22c509bcb3ad`
- shared ledger:
  `b44e160a16d651bd5fdb49e5cee146744542c0dc316c92c5aaa3711d98fecb4b`
- isolated database:
  `e11a61031487e141438a2140cfea5092d581dc33c64a6733d8d1c5fe124c3cd4`
- formal source database remains unchanged:
  `e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`


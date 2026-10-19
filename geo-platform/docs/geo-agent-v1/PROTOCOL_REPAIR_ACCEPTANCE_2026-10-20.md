# GEO Agent V1 response protocol repair — offline acceptance

Date: 2026-10-20

Scope classification: `IMPLEMENTATION_CHANGE`. This change only repairs the existing
DeepSeek Responses adapter and experiment-run usage projection. It does not change GEO
meaning, qualification levels, tools, sampling, formal Workflow state or publication gates.
No external request was made during this work.

## Root cause and evidence boundary

The fourth request of `agent-run-1f089136-1287-49f8-b97f-9efc22306c81` reached the provider,
completed, and reported 7,484 input plus 522 output tokens. The retained response metadata is:

- SHA-256: `a6d579307fac35a9d5e3c28adc8eead7bbc1ef0f10c201d4d2a3e062807014ab`
- reported content length: 661
- retained excerpt: an outer DSML invocation named `AgentDecision`, with explicit
  `action_type=TOOL_CALL` and a reasoning parameter
- validator input at failure: only the nested `{"run_id":"1"}` object

The old parser attempted generic JSON-object extraction before the DSML adapter. It therefore
selected a nested tool-arguments object and treated that object as the top-level decision. The
old DSML adapter also recognized only direct allowlisted tool invocations, not a complete
`AgentDecision` wrapper.

The complete fourth response was not durably retained. Only its hash, length and truncated
excerpt exist. Consequently this acceptance does **not** claim that the exact fourth response
was fully replayed or that its intended tool can be reconstructed. The real retained prefix is
tested as incomplete and must fail closed. A synthetic complete fixture matching the confirmed
wrapper structure is used only to test the protocol boundary.

## Repair

The Responses envelope is now parsed before business content:

1. Require the frozen Responses envelope and exactly one decision-bearing output item.
2. Ignore reasoning items, but reject multiple messages/calls, mixed candidates and unknown
   output types.
3. Accept a message only as its complete `output_text`, or a native `function_call` only when
   its name is exactly the frozen response Schema name and its complete `arguments` value is a
   JSON object.
4. For the observed DSML text form, require one anchored invocation. A wrapped
   `AgentDecision` must provide explicit fields and pass the unchanged strict Pydantic Schema;
   unknown fields, unknown tools, duplicates and incomplete markup are rejected.
5. Agent calls disable generic nested-JSON extraction. No `action_type`, tool, argument or
   artifact is guessed or synthesized from an arbitrary inner object.

The request already uses `POST /responses` with `text.format.type=json_schema`. The adapter
also recognizes the documented top-level `function_call` output form without switching the
Agent protocol or runtime. References:

- https://api-docs.deepseek.com/api/create-response/
- https://api-docs.deepseek.com/guides/responses_api/

## Usage accounting

Provider audit delivery now settles both the shared ledger and the local Agent Run before
`AgentDecision` parsing returns to the Runner. A completed-but-rejected response therefore
increments request count and records provider usage even when business parsing fails. The
operation is idempotent by frozen request input hash; a repeated audit callback cannot double
charge the Run. Transport-unknown requests retain their conservative hold.

An offline reconciliation command was added for historical experiment projections. It reads
the shared ledger in SQLite read-only mode, refuses active reservations, updates only the
explicit Agent Run, and appends `MODEL_USAGE_RECONCILED` with before/after values and a ledger
snapshot hash. It never edits the ledger.

Historical correction for the failed run:

| Field | Before | After |
| --- | ---: | ---: |
| model requests | 3 | 4 |
| input tokens | 17,939 | 25,423 |
| output tokens | 634 | 1,156 |
| conservative cost | CNY 0.18573 | CNY 0.26579 |
| local request state | `RESERVED_IN_FLIGHT` | `SETTLED` |
| accounted tokens/reservation | 56,451 | 26,579 |

Final reconciliation hash:
`bbbd2905775b8803410cbcda9cdde4dc87840f7a86b54caf7c855889d7b21d4c`.
Ledger snapshot hash:
`a3e78d2839ef4356355b28968db767dd55465e92337f814bc5ec826dbd5b837b`.
The command was run twice after the final projection and the second execution returned
`changed=false`. The ledger file hash remained
`b44e160a16d651bd5fdb49e5cee146744542c0dc316c92c5aaa3711d98fecb4b`.

The shared batch remains 18 requests, 137,492 accounted tokens, CNY 1.37492, zero in-flight;
the earlier `DELIVERY_UNKNOWN` reservation remains untouched. The formal release database
hash remains `e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`.

## Offline acceptance

Focused protocol and Agent tests: `37 passed`.

Regression covering the shared budget guard, derived call identity, formal automatic delivery,
DeepSeek transport and Agent experiment: `76 passed`.

The tests cover message and native function-call outputs, the complete DSML wrapper, the real
truncated prefix, nested arguments, multiple/conflicting candidates, invalid fields, unknown
tools, incomplete responses, history serialization, rejected-response accounting,
idempotent reconciliation, shared-budget behavior and formal-lane isolation.

## Stop decision

The adapter and accounting prerequisites for another controlled real test are satisfied.
This is only offline protocol acceptance: it does not prove that the exact lost fourth response
would parse, that a future provider response will use the same form, or that the Agent can
complete a GEO deliverable. No paid request, second scenario, new tool or formal write was
started. A further real call still requires separate explicit authorization.

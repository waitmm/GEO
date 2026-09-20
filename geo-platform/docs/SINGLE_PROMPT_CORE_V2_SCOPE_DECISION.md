# Single-Prompt Core V2 Scope Decision

Date: 2026-09-10
Decision: `SPC-V2-SCOPE-001`
Authorization: Product Owner explicitly authorized an isolated V2 control-plane slice.

## Decision

Build a parallel, generic Single-Prompt V2 entry that owns one analysis identity,
one fixed sampling plan, one exact collector task, one frozen Run scope and one
immutable raw-output version. This slice does not replace or reinterpret the
frozen V1/V1.1 steps 1-8.

The user-visible flow in this slice is:

```text
start analysis
-> persist analysis identity and sampling plan
-> execute the exact collector task
-> persist answer/reference/retrieval/failure observations
-> freeze exact Run scope and raw output
-> expose one backend-authoritative status
```

## Invariants Retained

- No empty or failed collection is promoted to a completed analysis.
- AnalysisContext is created only after every planned Run reaches a terminal
  state and at least one Run has a non-empty usable answer.
- Frozen Context reads its immutable snapshot, never live Prompt history.
- Every lookup binds `analysis_id + project_id + prompt_id`; there is no latest
  Package, Candidate, Snapshot or Prompt fallback.
- Duplicate create requests with the same idempotency key and plan reuse one
  analysis/task. A conflicting plan is rejected.
- One queued analysis can be claimed by only one worker attempt.
- Restarted in-flight external work becomes explicit `INTERRUPTED`; it is never
  silently retried or represented as success.
- A frozen Context cannot be retried in place. New sampling creates a new
  analysis identity and cannot mutate the earlier result.

## Reuse, Replacement, Deferral

| Area | Decision |
| --- | --- |
| BrowserMonitorTask/Run and persisted answer/reference/retrieval rows | Reuse by exact task identity |
| Wenxin collector | Provisional reuse; real acceptance remains gated by its collection contract |
| Existing V1 workflow status and frontend derivation | Not used by V2 |
| Runtime persistence spine | Deferred; V2 does not import or call it |
| Diagnosis, Product Truth, Strategy, Execution and Retest | Deferred to later slices |
| Historical migration/backfill | Not included |

The V2 Alembic revision intentionally branches from the last production
revision instead of depending on the separately gated Runtime migration
artifact. This is migration isolation, not Runtime cutover.

## Known Collector Contract Blocker

The current worktree's Wenxin collector does not pass the existing
`single_independent` reset guard: when historical turns remain and the new-chat
control is unavailable, collection continues. It also currently returns an
empty Retrieval candidate list unconditionally. Therefore code/fixture
acceptance of this V2 slice does not equal real-collector acceptance.

Required closure is narrowly scoped to the collector contract:

```text
prove independent conversation before submission
+ persist real Retrieval observations when exposed
+ rerun one new-Prompt production sample through V2
```

This blocker must not be hidden by mocks, by treating missing Retrieval as zero,
or by claiming that the configured `collection_mode` proves what happened in
the browser.

## Non-Goals

- No 16-stage Runtime implementation or Shadow capture.
- No V1 state bridge, latest/current compatibility layer or historical backfill.
- No diagnosis/strategy/execution rewrite.
- No Action, Experiment, publishing automation or retest platform.
- No hard-coded #19/#40 behavior.

## First-Slice Acceptance State

The isolated control plane, API, immutable result snapshot and V2 page are
implemented. Fixture acceptance covers idempotency, zero-result failure,
partial success, exact scope, restart, retry and post-freeze immutability.
Real collection remains `BLOCKED_BY_COLLECTOR_CONTRACT`; the slice must not be
described as end-to-end production accepted until that separate check passes.

The production smoke did prove the control-plane path with new Prompt #44:
Analysis `001da937-0baa-498a-a7e9-9d8801324fb3` froze one 1,902-character
answer and 30 references into `raw-v1:4213d19507cb840c`. The same request key
reused that identity and task. Retrieval remained absent and the collector
reported no independent-session proof, so this smoke does not close the
collector contract.

## Final First-Slice Verification

- The live status endpoint returns the frozen Context together with explicit
  `INDEPENDENT_SESSION_PROOF_UNAVAILABLE` and
  `RETRIEVAL_OBSERVATION_UNAVAILABLE` warnings. Missing Retrieval output is
  therefore no longer presented as an observed zero without qualification.
- SQLite development databases enforce frozen Context immutability with
  update/delete abort triggers; the Alembic revision installs the same guards.
- Seven focused V2 tests, backend compileall, frontend production build and
  `git diff --check` pass. Desktop and 390px mobile renders were checked after
  the final responsive navigation adjustment.
- The full backend baseline remains `477 passed / 5 failed`; all five failures
  are the separately recorded pre-existing contracts and were not changed to
  manufacture a V2 pass.

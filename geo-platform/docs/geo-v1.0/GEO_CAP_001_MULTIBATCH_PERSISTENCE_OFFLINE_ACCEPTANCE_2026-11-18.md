# GEO-CAP-001 Multi-Batch Offline Persistence Acceptance — 2026-11-18

## Result

`IMPLEMENTATION_CHANGE / OFFLINE_PERSISTENCE_ACCEPTED / PRODUCTION_NOT_CUT_OVER`

This slice implements additive persistence and restart-safe state transitions for
the frozen `SC-MULTI-BATCH-EVIDENCE-MERGE-001` contract. It remains an isolated
offline/replay path. It has no provider client, creates no `AgentResultVersion`
or Draft, and is not imported by the production Evidence Pack executor.

## Persisted identities

- immutable Plan and exact frozen-scope/plan/reservation hashes;
- append-only batch Attempts and successful replay Results;
- one append-only `SHADOW_CANDIDATE_ONLY` aggregate candidate;
- bounded attempt counts, durable cancellation and explicit runtime state;
- exact result-to-attempt payload, batch and attempt-number binding.

The aggregate candidate is recomputed from the current immutable Plan and the
complete ordered successful Result set during recovery. Candidate self-hashes
alone are not trusted.

## Safety and recovery evidence

- Targeted persistence and release migration tests: `11 passed`.
- Combined frozen shadow plus persistence tests: `21 passed`.
- Python compile and `git diff --check`: passed.
- A migrated SQLite database was exercised with two Sessions. A stale retry or
  aggregate writer cannot overwrite a committed cancellation because state
  transitions use conditional database updates.
- Attempt insertion has an additional database trigger that rejects terminal or
  cancelled Plan state.
- Failed payloads cannot be persisted as successful Results; replay attempt
  number and status must match the server-owned Attempt.
- Empty-schema downgrade is supported. If any multi-batch audit row exists,
  downgrade fails closed with `AGENT_MULTIBATCH_AUDIT_ROWS_PRESENT` instead of
  deleting execution history.

The warnings in the test output are existing Pydantic configuration and
`datetime.utcnow()` deprecation warnings; they are not hidden failures.

## Remaining gate

Production behavior is unchanged. This acceptance does **not** authorize:

- a provider/model call or synthetic data presented as business evidence;
- production executor wiring or an aggregate model request;
- creation of a formal Agent result or child Draft;
- upgrade of the M1.1 company database;
- production cutover, main merge or deployment.

The next D-line slice may implement an isolated aggregate replay/executor
candidate only if it preserves the same zero-external-call boundary. Any real
multi-call acceptance and production cutover remain separately authorized
gates.

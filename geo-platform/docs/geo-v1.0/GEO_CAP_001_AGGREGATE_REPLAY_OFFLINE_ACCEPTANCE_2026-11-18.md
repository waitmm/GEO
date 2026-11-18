# GEO-CAP-001 Aggregate Replay Candidate Offline Acceptance — 2026-11-18

## Result

`IMPLEMENTATION_CHANGE / AGGREGATE_REPLAY_OFFLINE_ACCEPTED / PRODUCTION_NOT_CUT_OVER`

This D3 slice consumes only a validated persisted `SHADOW_CANDIDATE_ONLY`
aggregate input from the frozen `SC-MULTI-BATCH-EVIDENCE-MERGE-001` contract.
It accepts a synthetic, schema-shaped protected replay fixture only. It does
not replay a real historical report. There is no provider client, model call,
external call, formal `AgentResultVersion`, Draft, or production executor
import.

## Persisted binding

- exact frozen-scope, plan, aggregate-input and ordered batch-result hashes;
- independent execution identity
  `geo.evidence-pack.multibatch-execution.candidate.v1`;
- one immutable reserved aggregate replay attempt with exact idempotency;
- raw synthetic replay response hash, Validation v6-shaped profile/status and
  fixture report hash, explicitly marked
  `NOT_REEXECUTED_PROTECTED_OFFLINE_REPLAY`;
- immutable binding hash and prospective result hash, explicitly not a formal
  result identity;
- CAS plan transitions for claim, completion and cancellation.
- restart recovery re-verifies every persisted Attempt/Result scalar mirror,
  structured identity, bundle, report, binding and derived terminal status.

Validation v6 is not re-run in this slice because the persisted aggregate input
does not contain the complete current single-pack validation payload. The slice
therefore preserves and audits a synthetic Validation v6-shaped fixture without
claiming a real Validation v6 execution, protected historical replay, or new
business qualification. Inventing or weakening a validation path would violate
the frozen contract.

## Evidence

- D3 targeted aggregate replay tests: `24 passed`.
- D2 persistence + D3 aggregate replay tests: `35 passed`.
- release-schema allowlist/head test: `1 passed`.
- Python compile and `git diff --check`: passed.
- covered restart recovery, one-attempt limit, exact idempotency, Validation
  failure, cancellation before claim and during an in-flight replay, tamper
  detection including every persisted scalar mirror and terminal status, empty
  upgrade/downgrade, and zero formal result writes.

Warnings are existing Pydantic/FastAPI/`datetime.utcnow()` deprecations, not
hidden failures.

## Remaining gate

This is not production multi-batch analysis. Real aggregate model execution,
independent Validation v6 execution against a complete authoritative pack,
usage settlement, formal parent/child result creation, UI exposure, M1.1
database upgrade and production cutover remain blocked pending their own
authorization and acceptance.

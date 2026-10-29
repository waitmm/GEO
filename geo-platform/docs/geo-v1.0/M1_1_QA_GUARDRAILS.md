# GEO M1.1 QA / Protection Slice

Date: 2026-10-29  
Scope: offline, isolated temporary databases only. No real sampling, source
fetching, model request, publication, or production database write was used.

## Result

The independent QA slice is in
`backend/tests/test_m1_1_qa_guardrails.py`. It covers the safety boundaries
around the current Evidence Pack v3 and local Beta release controls. The
existing `backend/tests/test_m1_beta_ops.py` covers the release CLI's full
backup/restore/upgrade/rollback path; this slice adds provider and accounting
checks without changing production code.

The combined protection suite was executed with the prepared project Python
environment on 2026-10-29: **24 passed**. A second targeted product regression
covering access isolation, internal-Beta policy, capacity, range selection,
manual import and Agent/Evidence Pack persistence completed with **88 passed**.
Frontend client tests completed with **36 passed**, followed by a successful
release build. All of these runs were offline and used temporary databases or
the existing read-only localhost UI path.

| Check | Expected boundary | Status |
|---|---|---|
| Capacity preflight | An oversized frozen pack fails before provider generation; no model call or result version | PASS (offline test) |
| Error classification | Current v3 retains `EVIDENCE_PACK_CORE_EXCEEDS_BUDGET:<actual>:<limit>` in `blocker_code`; no call is recorded | PASS; UI normalization remains a follow-up gap |
| Completed Optimize retry | Re-executing a completed run returns without another provider call/result | PASS (offline test) |
| Shared budget settlement | Same request/usage replay is idempotent; conflicting replay is rejected | PASS (offline test) |
| Active WAL backup | SQLite Online Backup includes committed WAL frames; direct `.db` copy does not | PASS (offline test) |
| Migration writer quiescence | Upgrade path requires stopped services and refuses active queue work | PASS in release CLI tests; requires operator stop before invocation |
| Restored artifact paths | Restore moves prepared source files under the new home and updates DB bindings | PASS in release CLI tests |
| Worker singleton | Second worker cannot acquire the DB lock; heartbeat is removed on clean stop | PASS (offline test) |
| Project permissions | Owner-only access config and cross-project request denial | PASS (offline test) |
| Offline external work | Scheduled sampling is disabled and cache-only generation returns `CACHE_MISS` without transport | PASS (offline test); queue quarantine still required by preflight |
| Prepared release identity | A full file manifest rejects post-fingerprint changes and excludes `.env`/browser state | PASS (offline test) |
| Rollback identity | Stopped marker plus backup/release/schema identity are required; `VERSION` follows the restored release | PASS (offline test) |
| Database preflight | Integrity, foreign-key violations, and active work all fail closed | PASS (offline test) |
| Historical budget audit | The model ledger is archived read-only and never restored as authorization | PASS (offline test) |
| launchd instance ownership | The controller accepts an older release of the same home but refuses an exact-path mismatch | PASS (mocked launchd subprocess) |

## Current Optimize behavior

The worker builds and freezes the Evidence Pack before it constructs or calls
the model client. Capacity exceptions are caught as a failed Agent run, with
zero model calls and no `AgentResultVersion`. The exact capacity detail is
currently retained as a raw blocker string; this is auditable but not ideal
for a user-facing error taxonomy. A later implementation may map it to a
stable code such as `EVIDENCE_PACK_CAPACITY_EXCEEDED` while retaining the raw
detail, but this QA slice intentionally does not modify that semantic path.

Completed runs are idempotent at the execution boundary: a second worker
attempt sees a non-`QUEUED` run and returns. Shared model accounting is also
idempotent at the ledger boundary, including after a process restart.

## Release / company-trial controls

The local Beta release scripts use these P0 controls:

1. A backup uses SQLite Online Backup rather than copying the live database
   file, and archives explicitly listed evidence roots and model-ledger audit
   history with hashes. The restored ledger is audit-only, never authorization.
2. `preflight` rejects database corruption, foreign-key violations, and active
   queue rows. Upgrade additionally requires the
   service-stopped marker, creates a recoverable pre-upgrade backup, validates
   an isolated restore/migration using the candidate runtime, and only then
   migrates the stopped live database.
3. Restore targets a new home, relocates prepared-source paths, and resets
   `daily-model-calls=0` and `scheduled-sampling-enabled=0`. Browser profiles
   and credentials are excluded from backups.
4. The Worker lock is database-scoped and single-instance. Project access is
   checked server-side; an invitation account cannot address another project.
5. Prepared releases carry a complete file manifest; runtime roots, `.env`,
   access credentials, and browser state are excluded. launchd labels must be
   proven to belong to the requested Beta home before they are touched.
6. Offline startup must not resume queued external work. The safe sequence is
   `preflight -> quarantine/refuse active work -> start API/worker`; setting
   the two capability flags to zero is not, by itself, permission to resume a
   queued task. The release scripts enforce this through active-work refusal;
   a live service-start test on the target company Mac is still pending.

## Remaining evidence gaps

- No company computer install, real path relocation, or browser permission
  test has been performed. Those require an explicit deployment environment.
- No real scheduled collection or model generation was enabled. The current
  test evidence proves fail-closed behavior, not external-provider success.
- Capacity preflight is deterministic, but raw blocker normalization and a
  user-facing progress state are product/UI work outside this QA-only slice.

## Acceptance command

From `backend/` with the prepared project environment:

```bash
python -m pytest -q tests/test_m1_1_qa_guardrails.py tests/test_m1_beta_ops.py
```

Expected external activity: zero. Expected production database writes: zero.

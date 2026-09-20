# PR5-B Human Review / Edit / Revalidation

Date: 2026-09-07

## Status

```text
PR5-A = FROZEN
PR5-B = FROZEN
PR5-C = NOT STARTED
```

PR5-B turns the frozen PR5-A execution proposals into an ephemeral human
review surface. It does not persist an execution proposal, freeze a snapshot,
or create an Action, Experiment, or ManagedAsset.

## Contract

```text
PR5-A source proposal
+ Human Edit Overlay
-> canonical rebuild
-> all eight safety validators
-> READY_FOR_CONFIRMATION / NEEDS_HUMAN_SELECTION / INVALID_EDIT
```

System-owned Strategy, Resolver Role, Theme/Reason scope, Product Truth,
Evidence Package, baseline, metric eligibility, measurement level, claim
policy, and input identity cannot be edited. Legal package, asset type,
provenance-backed section, title wording, publishing metadata, execution/defer
choice, and observation-window candidates are selected from backend-provided
closed sets.

Every request reruns Snapshot, Channel Role, Asset Fit, Claim Grounding, Title
Claim, Section Provenance, Baseline, and Metric Eligibility validators. Invalid
edits return structured errors with `draft_status=INVALID_EDIT`; they are not
silently corrected. `execute_this_proposal=false` yields
`DEFERRED_BY_HUMAN` without changing the channel Role.

## APIs

```text
POST /api/optimization/workflow/{project_id}/{prompt_id}/execution-proposal/revalidate
POST /api/optimization/workflow/{project_id}/{prompt_id}/execution-proposal/portfolio/revalidate
```

Both APIs are deterministic and read-only. The portfolio response exposes
source hashes, canonical proposals, human edit diffs, per-proposal validators,
safety audit, portfolio readiness, and `ready_for_freeze`. Only PR5-C may turn
that result into a persisted freeze.

## Real #57 Replay

```text
OFFICIAL_SITE: execute, P1_FOCUS, FEATURE_PAGE -> READY_FOR_CONFIRMATION
BAIJIAHAO: execute, minimum ARTICLE -> READY_FOR_CONFIRMATION
ZHIHU: defer -> DEFERRED_BY_HUMAN

Portfolio = READY_FOR_CONFIRMATION
ready_for_freeze = true
validators = 8/8 VALID per proposal
safety audit = all zero
external LLM calls = 0
DB writes = 0
```

Candidate #57, its effective payload, Action count, and Experiment count were
unchanged before and after the production API replay.

## Frontend

The Step 8 entry now loads PR5-A proposals before accepting input. It presents
one card per official/TEST proposal, legal package and asset-type controls,
safe title editing, provenance-backed section selection/reordering, publishing
metadata, observation window, allowed/restricted claims, metrics with
measurement level, baseline count, and collapsed audit details.

The only submit action is `Revalidate execution proposal`. It does not call
the legacy Action/Experiment creation API. A valid portfolio is reported as
ready for PR5-C freeze, not as already frozen or created.

## Validation

- 32 focused PR5-A/PR5-B tests passed.
- Full backend: 454 passed with the same five pre-existing unrelated failures.
- Real Candidate #57 FastAPI GET and portfolio POST passed.
- Frontend TypeScript/Vite production build passed.
- Python compile and `git diff --check` passed.
- External LLM calls and DB writes remained zero.

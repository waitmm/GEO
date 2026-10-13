# GEO Platform Agent Guide

## Authorization And Durable Truth

The latest explicit Product Owner instruction authorizes the current change,
pause, RFC, shadow, or review. Chat is not a durable semantic truth source and
must be written into the repository before future work can depend on it.

Use this order for durable semantic facts when repository sources conflict:

1. Current effective `FROZEN` contract in `docs/semantics/01_SEMANTIC_CONTRACTS.md`.
2. `FROZEN` Semantic RFC. An `APPROVED` RFC is implementation/shadow
   authorization only until a separate production cutover is approved.
3. Current Product Definition sources, using each file's real status:
   - `../产品纲要.md`: `SINGLE_PROMPT_GEO_V1_FROZEN`
   - `docs/00_PROJECT_BRIEF.md`: `ACTIVE`
   - `docs/01_PRODUCT_DIRECTION.md`: `ACTIVE`
4. `docs/07_DECISION_LOG.md`.
5. `docs/09_PRODUCT_ITERATION_LOG.md`.
6. Detailed Specs, using each file's real status:
   - `docs/05_OPTIMIZATION_LOOP_SPEC.md`: `ACTIVE`
   - `docs/PRODUCT_FUNCTION_SPEC.md`: `ACTIVE`
7. Current implementation and SQLite data as observed implementation evidence.
8. Historical or superseded logs.

If two sources at the controlling level conflict, do not resolve the conflict
from code age, row ID, frontend wording, or conversation recency. Register it in
`docs/semantics/04_CONFLICT_REGISTER.md` and request definition review.

## Semantic Change Guard

Before changing core business logic, read:

1. `docs/semantics/00_DOMAIN_MODEL.md`
2. `docs/semantics/01_SEMANTIC_CONTRACTS.md`
3. `docs/semantics/02_GOLDEN_SEMANTIC_CASES.md`
4. `docs/semantics/03_DEFINITION_REVIEW_CHECKLIST.md`
5. `docs/semantics/04_CONFLICT_REGISTER.md`

Classify the change before implementation:

```text
IMPLEMENTATION_CHANGE
SEMANTIC_CHANGE
SEMANTIC_RISK
```

- `IMPLEMENTATION_CHANGE` must preserve every applicable contract.
- `SEMANTIC_CHANGE` requires a Semantic RFC. Without an approved RFC, stop with
  `SEMANTIC_CONTRACT_REVIEW_REQUIRED`.
- `SEMANTIC_RISK` allows investigation, fixtures, planner, shadow, and replay
  only. It cannot cut over production behavior.
- A conflict with a current `FROZEN` contract stops with
  `SEMANTIC_CONTRACT_CONFLICT`.
- Contract maturity and implementation status are orthogonal. In particular,
  `OBSERVED + PRODUCTION` is not equivalent to `FROZEN`.
- Definition freeze, implementation authorization, and production cutover are
  separate approvals. Never infer the last from the first two.
- A hotfix may restore known frozen behavior. If semantic neutrality cannot be
  proven, handle it as `SEMANTIC_RISK` and do not cut over.

## Current Product Focus

### Approved 2026-10-09 Delivery Boundary

The Product Owner explicitly approved implementation of the 2026-10-09 final
delivery instruction. SC-DELIVERY-001 is the controlling release boundary:
continuous Monitor -> automatic Optimize -> independent batch comparison.
Publication, ExecutionConfirmation and global semantic Review are not
prerequisites for sampling, analysis, content delivery or observation comparison.
Existing publication records remain immutable, optional historical evidence.
This specific owner-approved replacement does not authorize changing unrelated
frozen semantics, weakening access control, widening external-call budgets,
changing raw data, inventing facts, or claiming unexecuted acceptance passed.
For this approved replacement, update the existing contracts and decision log;
do not demand another RFC for the already approved product decision.
The older P0 descriptions below are historical where they require publication.

The highest priority is the P0 optimization loop:

```text
problem discovery -> optimization action -> fixed retest -> effect conclusion
```

Do not widen the task into broad trend dashboards, additional collectors, device
coverage, Postgres migration, or complex diagnostic scoring unless explicitly
requested.

## Local Startup

From the workspace root:

```bash
./scripts/dev.sh
```

Default services:

- Release backend: `http://127.0.0.1:8021` (`app.release_main`, existing migrated release DB)
- Frontend: `http://localhost:5173` (release mode; `127.0.0.1:5173` when bound there)

`npm run dev` and bare Vite use the release UI by default. `GEO_API_PROXY_TARGET`
overrides the API proxy when a custom backend port is needed; `scripts/dev.sh`
sets it from `BACKEND_HOST/BACKEND_PORT`. Existing services must pass the mode/target
checks, not just occupy the ports. The legacy UI is explicit `npm run dev:legacy`
on port 5174 and must not be used to validate the release product. Default startup
does not start workers or external operations; opt-in `MONITORING_WORKER=1` runs
the release worker, not the retired monitoring scheduler.

## Validation Commands

Backend:

```bash
cd geo-platform/backend
.venv/bin/python -m compileall app
.venv/bin/python scripts/reference_parser_smoke.py
.venv/bin/python scripts/optimization_loop_smoke.py
```

Frontend:

```bash
cd geo-platform/frontend
npm run build
```

If `npm` is not on `PATH`, load `nvm` or use the installed Node binary recorded
in recent local run notes.

## Boundaries

- 2026-10-13 owner follow-up: offline relay accepted; authorize at most ONE
  real documentation-only smoke unit T25-RELAY-USAGE-SMOKE, zero repairs,
  600 seconds, 30,000 activity-token post-session soft threshold. No new GEO
  product unit or scheduler expansion. Require effective Sol Medium/non-priority
  configuration preflight; stop on mismatch without model fallback. This does
  not authorize GEO model/platform calls or a second paid attempt. Preserve
  existing semantic, permission and data-protection gates. Subsequent automated
  units must use the existing tasks ledger, an explicit independent gate and
  the `codex/geo-integration` baseline. Never auto-merge main, reset unknown
  usage/retries, or treat a relay gate as full product acceptance. See
  `docs/geo-v1.0/19_Codex开工说明.md` for recovery and invocation boundaries.
  Subsequent owner decision explicitly selects gpt-5.6-sol / medium / default
  and authorizes one rerun of the same documentation smoke after fixing the
  dependency symlink. Preserve/archive the prior no-exec preflight receipt;
  do not reset unknown usage. No further automatic task or paid repair.
  Sol5.6 rerun stopped at exec startup with EPERM and no usage events. That
  failed unit and UNKNOWN usage remain blocked; do not resume or drop protection.
  Latest owner authorization creates TERMINAL-SMOKE-20261013-01 solely for the
  identical T25 documentation acceptance target, via standalone local CLI.
  This agent turn may prepare/dry-run only, never exec. A later Terminal launch
  is limited to one fresh unit, zero repairs,600s/30000soft,5.6-sol/medium/default.
  Prior receipt may be retained byte-for-byte in its original batch directory
  with a review record; UNKNOWN historical usage is not reconciled or reset.

- Keep `Prompt` semantics stable: one Prompt is one question.
- Keep `run#` and `Sample` labels visible in user-facing run detail.
- `partial_success` is not a successful full parse; do not redefine success to
  hide missing reference data.
- Software delivery and observation comparison do not require publication.
  Never infer causal business success from observation changes, with or without
  a publication record. No universal cooling-period rule is introduced.
- Target users are Chinese-language operators who should not need to understand
  English. User-facing navigation, labels, empty states, warnings, and workflow
  actions must use Chinese. Stable English enum values may remain in storage or
  API payloads, but UI/API responses used directly by the frontend must provide
  Chinese labels.
- Any future change that alters the single Prompt main workflow order, adds a
  new top-level workflow module, or changes a workflow card's primary state
  source is a product-level change. Record it in both
  `docs/08_DEVELOPMENT_LOG.md` and `docs/09_PRODUCT_ITERATION_LOG.md`, and give
  the user a strong warning before implementation.
- Product iteration, development iteration, known pitfalls, and `产品纲要.md`
  maintenance are governed by `docs/12_DOCUMENTATION_GOVERNANCE.md`. If a
  change touches product semantics or a previously encountered pitfall, update
  the corresponding documentation in the same checkpoint instead of leaving the
  decision only in chat.
- Real semantic regression cases must bind immutable IDs and hashes through
  `docs/semantics/snapshots/*.manifest.json`. Never replace a missing fixed
  input with a `latest` query.

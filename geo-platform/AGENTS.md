# GEO Platform Agent Guide

## Fact Priority

Use this order when project facts conflict:

1. Latest user instruction in the active thread.
2. `docs/01_PRODUCT_DIRECTION.md` if marked `ACTIVE`.
3. `docs/07_DECISION_LOG.md`.
4. `docs/05_OPTIMIZATION_LOOP_SPEC.md`.
5. `docs/02_CURRENT_STATUS.md`.
6. Current code and SQLite data.
7. Older implementation logs.

## Current Product Focus

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

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://localhost:5173`

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

- Keep `Prompt` semantics stable: one Prompt is one question.
- Keep `run#` and `Sample` labels visible in user-facing run detail.
- `partial_success` is not a successful full parse; do not redefine success to
  hide missing reference data.
- Real business experiment success must not be claimed until release, cooling,
  retest, comparison, and human conclusion are all recorded.
- Target users are Chinese-language operators who should not need to understand
  English. User-facing navigation, labels, empty states, warnings, and workflow
  actions must use Chinese. Stable English enum values may remain in storage or
  API payloads, but UI/API responses used directly by the frontend must provide
  Chinese labels.

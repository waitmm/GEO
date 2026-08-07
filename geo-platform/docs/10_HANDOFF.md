# 10 Handoff

Status: ACTIVE

## Current Product Direction

Local GEO / AI visibility audit Alpha focused on the first trustworthy
optimization experiment loop:

```text
real Run -> real issue -> baseline -> Action -> manual release -> cooling -> retest -> human conclusion
```

Do not widen into broad BI, collector expansion, multi-device matrices, or
production migration before the first real loop is unblocked.

## Current Stage

```text
SOFTWARE_LOOP_READY
```

Project stage remains `SOFTWARE_LOOP_READY`. Experiment `#13` is
`READY_FOR_MANUAL_RELEASE` with a recollected retrieval-eligible baseline.
`REAL_EXPERIMENT_STARTED` is not reached because the external page has not been
manually updated and confirmed as published.

## Recently Completed

- B1 Evidence Package model/API/UI for deterministic fact reports.
- Former "Prompt daily report" entry reframed as
  `采集记录 / 证据事实报告`; legacy daily report remains available only as
  collection-history compatibility.
- First-class `target_page_retrieval_rate` metric with `valid_run_count`,
  `retrieved_run_count`, `retrieval_rate`, and `delta_pp`.
- Second-stage `target_page_conversion_rate` metric with `retrieved_count`,
  `cited_count`, `conversion_rate`, and `delta_pp`.
- Overall, per-Prompt, per-environment, and raw Run drilldown for experiment
  comparison.
- Structured `content_feature_changes` with legacy string compatibility.
- Unified human conclusion enum:
  `EFFECTIVE`, `PARTIALLY_EFFECTIVE`, `MIXED_RESULT`,
  `NO_MEASURABLE_EFFECT`, `NEGATIVE_EFFECT`,
  `INSUFFICIENT_EVIDENCE`.
- Release boundary:
  `PLANNED -> READY_FOR_MANUAL_RELEASE -> RELEASE_CONFIRMED`.
- Alembic migration skeleton and B1 release-preparation models/API:
  `PageSnapshot`, `OptimizationHypothesis`, and `ReleaseAuditRecord`.
- Isolated optimization smoke database:
  `scripts/optimization_loop_smoke.py` defaults to
  `geo_platform_smoke_test.db`, supports `GEO_DATABASE_URL`, refuses the main
  DB, and cleans test data/files.

## Current Real Experiment Status

- Experiment name: `Prompt 19 目标页面检索进入实验`.
- Project: `3` / "爱短链品牌监测".
- Prompt: `19` / "抖音跳转链接".
- Target page: `https://www.aifabu.com/card`.
- Historical Run IDs: `[135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146]`.
- Locked baseline Run IDs: `[173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184]`.
- Historical answer/citation window: Runs `135-146` are eligible for answer and
  citation analysis.
- Historical retrieval/funnel eligibility: `retrieval_eligible_run_count = 0`
  because each old Run captured 20 candidates while the configured minimum is
  30.
- Current retrieval metrics: `target_page_retrieval_rate = null` and
  `target_page_conversion_rate = null` with
  `insufficient_retrieval_candidates`.
- Locked baseline metrics: `target_page_retrieval_rate = 0 / 12 = 0%`;
  `target_page_conversion_rate = not_applicable`.
- DB chain: Issue `#21`, Action `#13`, Experiment `#13`.
- Accepted baseline Evidence Package: `#1`, hash prefix `ce4ad3c8393e`,
  source Run IDs `135-146`, evidence level `SOURCE_LEVEL_ONLY`.
- Latest B1 v4 fact report: Evidence Package `#7`, with platform/content/time
  matrices, unified drilldowns, retrieval eligibility, and locked baseline
  metrics.
- Retrieval coverage for Package `#6` is `INCOMPLETE`: historical Runs
  `135-146` stored 20 candidates per Run but 30 final references per Run. Old
  artifacts show `csaitab/searchresult?pn=0&rn=20`, so missing candidates cannot
  be backfilled from saved raw evidence. Candidate-not-cited and platform
  candidate-to-citation rows are disabled; captured candidates remain visible
  only as `captured_candidates`.
- B2 Strategy Candidate `#2` was generated from Package `#6` with
  `provider=local_rule`, `model=local-rule-v1`, and remains `PENDING_REVIEW`.
- B2 Strategy Candidate `#4` was generated from Package `#7`, bound to
  Experiment `#13`, has `target_metric=target_page_retrieval_rate`, and remains
  `PENDING_REVIEW`.
- PRE_RELEASE page snapshot: `#3`, HTTP `200`, canonical
  `https://www.aifabu.com/card`.
- Accepted human Hypothesis: `#1`, linked to Package `#1` and Experiment `#13`.
- Action `#13` and Experiment `#13` still have `released_at = null`.
- Do not start `REAL_EXPERIMENT_STARTED` until the user confirms the external
  target page has actually been published.

## Next Single Task

Review Strategy Candidate `#4` and the Package `#7` B1 report. If accepted,
proceed to manual target-page editing for `https://www.aifabu.com/card`, capture
POST_RELEASE evidence after the real external page is published, and only then
confirm release so Experiment `#13` can enter cooling.

Start here:

1. Read `AGENTS.md`.
2. Start the app with `../scripts/dev.sh` from the workspace root, or
   `./scripts/dev.sh` if already at `/Users/bmwqr/Desktop/python/GEO`.
3. Open the frontend at `http://localhost:5173`.
4. Use `采集记录 / 证据事实报告` for B1 reports.
5. Use “优化闭环” for P0 issue/action/experiment flow.

Recommended validation:

```bash
cd geo-platform/backend
.venv/bin/python -m compileall app
.venv/bin/python -m pytest tests/test_b1_gate.py
.venv/bin/python scripts/reference_parser_smoke.py
.venv/bin/python scripts/optimization_loop_smoke.py

cd ../frontend
npx tsc -p tsconfig.json --noEmit
npm run build
```

If continuing product work, next best task is source-depth analysis inside the
optimization loop or B2 LLM strategy-provider work only after the B1 facts are
accepted.

Known risk boundaries:

- Do not commit `.env`, SQLite DBs, cookies, storage state, browser profiles,
  untracked monitoring artifacts, frontend `dist`, or dependency folders.
- Do not discard tracked Run 27 artifacts without deciding whether they remain
  reference-parser fixtures.
- Do not write `released_at` or enter cooling unless the user confirms the
  external page is actually published.

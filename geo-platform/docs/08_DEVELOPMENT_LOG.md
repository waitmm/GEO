# 08 Development Log

Status: ACTIVE

## 2026-08-05

- Added `AGENTS.md` guidance and numbered project docs.
- Added P0 optimization-loop models:
  - `OptimizationIssue`
  - `OptimizationIssueRun`
  - `OptimizationAction`
  - `OptimizationExperiment`
- Added `/api/optimization` router for issue/action/experiment/evidence flow.
- Added frontend “优化闭环” page with candidate issue generation, issue
  confirmation, action creation/release, experiment baseline/validation, and
  conclusion controls.
- Added citation source analysis inside the evidence chain, covering cited
  sources and retrieved-but-not-cited candidates across ownership, content
  format, prompt match, freshness, authority, citation reason, and risk flags.
- Added experiment retest queue creation so fixed validation tasks can be
  generated directly from the optimization loop.
- Fixed analytics validation dashboard fall-through bug.
- Added `backend/scripts/optimization_loop_smoke.py`.
- Promoted `target_page_conversion_rate` to a first-class experiment metric:
  target URL retrieved Runs, cited Runs, conversion rate, `delta_pp`, per-Prompt
  drilldown, per-environment drilldown, and raw Run drilldown.
- Upgraded `content_feature_changes` to structured objects with legacy string
  read compatibility.
- Unified experiment conclusion writes to `EFFECTIVE`,
  `PARTIALLY_EFFECTIVE`, `MIXED_RESULT`, `NO_MEASURABLE_EFFECT`,
  `NEGATIVE_EFFECT`, and `INSUFFICIENT_EVIDENCE`.
- Added release boundary handling:
  `PLANNED -> READY_FOR_MANUAL_RELEASE -> RELEASE_CONFIRMED`; only confirmed
  release writes `released_at` and starts cooling.
- Audited real DB candidates. No "视频二维码制作" Prompt exists. Project 3 /
  Cluster 5 is the best real candidate, but strict URL-level retrieval
  candidates are missing for brand pages, blocking a valid primary-metric
  baseline.
- Reclassified Prompt 19 into a retrieval-entry experiment instead of a
  retrieval-to-citation experiment. Added `target_page_retrieval_rate` as a
  first-class metric and locked Experiment `#13`:
  `0 / 12 = 0%` for `https://www.aifabu.com/card`.
- Captured the pre-release target page snapshot under
  `backend/artifacts/optimization/prompt19-target-page-retrieval/` and recorded
  structured planned page variables on Action `#13`.

Validation performed:

- Frontend TypeScript check passed.
- Backend `compileall` passed.
- Optimization loop smoke passed.

## 2026-08-06

- Cleaned explicit local smoke data from the real SQLite database:
  - Deleted 13 projects with IDs `4-16`, matching
    `P0 Optimization Smoke ... / SmokeBrand`.
  - Deleted associated smoke Runs, references, retrieval candidates, issues,
    actions, experiments, tasks, batches, prompts, clusters, topics, and
    legacy observations.
  - Deleted 3 orphan `run_artifacts` rows pointing at missing Run IDs.
  - Kept Project `1` "演示项目" because it was not an explicit smoke marker.
  - `PRAGMA foreign_key_check` passed after cleanup.
- Added B1 Evidence Package support:
  - New `OptimizationEvidencePackage` model/table.
  - New API endpoints for listing, creating, and reading packages.
  - Package payload includes deterministic metrics, platform gap matrix,
    content type distribution, candidate-not-cited summary, time distribution,
    content-structure signals, representative sources, Run drilldown, and
    `SOURCE_LEVEL_ONLY` evidence level.
  - Repeated generation with identical inputs returns the existing package by
    hash instead of creating duplicate versions.
- Reframed the former Prompt daily report frontend entry as
  `采集记录 / 证据事实报告`.
  - Legacy daily report generation remains available as collection history.
  - The new main card generates and displays Evidence Packages.
  - Prompt labels now include the actual prompt text, e.g.
    `Prompt #19 · 抖音跳转链接`.
- Generated the first real B1 report:
  - Package `#1`.
  - Project `3` "爱短链品牌监测".
  - Prompt `19` "抖音跳转链接".
  - Target URL `https://www.aifabu.com/card`.
  - Baseline Run IDs `135-146`.
  - `target_page_retrieval_rate = 0 / 12 = 0%`.
  - `target_page_conversion_rate = not_applicable`.

Validation performed:

- Backend `compileall` passed.
- Frontend `npm run build` passed.
- SQLite `init_db()` synced the new table.
- Evidence Package repeated-generation idempotency passed:
  second generation returned Package `#1` with the same hash.
- API smoke passed:
  `/api/health`,
  `/api/optimization/projects/3/evidence-packages?prompt_id=19`, and
  `/api/optimization/evidence-packages/1`.

## 2026-08-06 B1 Gate Completion

- Added formal Alembic migration skeleton:
  - `backend/alembic.ini`
  - `backend/alembic/env.py`
  - `backend/alembic/versions/20260806_01_b1_gate_release_audit.py`
- Added release-preparation database objects:
  - `PageSnapshot`
  - `OptimizationHypothesis`
  - `ReleaseAuditRecord`
- Added API/service support for:
  - capturing/listing page snapshots;
  - creating/listing accepted human Hypotheses;
  - release confirmation through an explicit audit record.
- Hardened release boundary:
  - `release_action(... release_confirmed=True)` no longer writes
    `released_at` directly;
  - release confirmation requires accepted Hypothesis, PRE/POST successful
    snapshots, canonical/robots checks, release note, and confirmer.
- Upgraded Evidence Package generation to `b1.v2 / metric.v2` with versioned
  hash inputs:
  - source Run IDs;
  - target page URLs;
  - environment snapshot;
  - schema, metric, collector, retrieval parser, content classifier, and time
    extractor versions.
- Generated latest Prompt 19 B1 report:
  - Package `#3`;
  - `target_page_retrieval_rate = 0/12 = 0%`;
  - `target_page_conversion_rate = not_applicable`;
  - unified drilldown rows for metrics, platforms, content types, freshness
    buckets, and candidate-not-cited.
- Preserved Package `#1`; it remains active and is associated with the accepted
  Prompt 19 Hypothesis.
- Captured target-page PRE_RELEASE snapshot:
  - Snapshot `#3`;
  - URL `https://www.aifabu.com/card`;
  - HTTP `200`;
  - canonical `https://www.aifabu.com/card`;
  - title `抖音卡片_微信卡片_直播间卡片-爱短链`;
  - H1 `抖音获客私域 点击跳转加好友`.
- Created accepted human Hypothesis:
  - Hypothesis `#1`;
  - Evidence Package `#1`;
  - Experiment `#13`;
  - baseline value `0/12`.
- Isolated `scripts/optimization_loop_smoke.py`:
  - default DB `geo_platform_smoke_test.db`;
  - supports `GEO_DATABASE_URL`;
  - refuses main DB;
  - cleans the test DB file in `finally`.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_b1_gate.py` passed.

## 2026-08-06 Prompt 19 Retrieval Candidate Coverage Correction

- Investigated Prompt 19 Runs `135-146` after detecting that final references
  outnumbered retrieval candidates.
- Confirmed database counts:
  - `RetrievalCandidate`: 240 rows, exactly 20 per Run;
  - `ReferenceSource`: 360 rows, exactly 30 per Run;
  - unique captured candidate URLs: 23;
  - unique final reference URLs: 30.
- Confirmed historical artifacts cannot recover the missing candidate
  denominator:
  - each `searchresult-1.json` contains `data.results = 20`;
  - `network.jsonl` shows `csaitab/searchresult?pn=0&rn=20`;
  - therefore old Runs preserve only top-20 candidate responses while final
    references were captured as 30.
- Removed local collector hard caps:
  - DOM extraction no longer uses `slice(0, 20)`;
  - DOM/API merge no longer truncates to `[:20]`.
- Added `retrieval_coverage_summary` to Evidence Package payloads and bumped:
  - `schema_version = b1.v3`;
  - `retrieval_parser_version = retrieval_parser.v3_no_top20_cap`.
- Generated corrected Prompt 19 B1 report:
  - Package `#4`;
  - `target_page_retrieval_rate = 0/12 = 0%`;
  - `target_page_conversion_rate = not_applicable`;
  - `retrieval_coverage_status = INCOMPLETE`;
  - `incomplete_run_count = 12/12`;
  - `common_candidate_count_per_run = 20`;
  - `suspected_fixed_collection_limit = true`.
- Added frontend warning and Run-level coverage table in Evidence Package
  expanded view.
- Added regression test:
  - `test_retrieval_coverage_marks_candidate_denominator_incomplete`.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_b1_gate.py` passed: 9 tests.
- `npx tsc -p tsconfig.json --noEmit` passed.
- `npm run build` passed with the existing Vite chunk-size warning.
- `.venv/bin/python scripts/optimization_loop_smoke.py` passed on the isolated
  smoke database.
- Frontend `tsc -p tsconfig.json --noEmit` passed.

## 2026-08-06 B1 Metric Eligibility Downgrade And B2/B3 Entry

- Reclassified Prompt 19 historical Runs `135-146`:
  - `answer_metrics_eligible = true`;
  - `citation_metrics_eligible = true`;
  - `retrieval_metrics_eligible = false`;
  - reason `INSUFFICIENT_RETRIEVAL_CANDIDATES`;
  - configured minimum candidate count is `30`.
- Generated Prompt 19 Package `#6`:
  - `schema_version = b1.v4`;
  - `metric_spec_version = metric.v3`;
  - `answer_eligible_run_count = 12`;
  - `citation_eligible_run_count = 12`;
  - `retrieval_eligible_run_count = 0`;
  - `captured_candidate_total = 240`;
  - `citation_total = 360`;
  - `target_page_retrieval_rate = null`;
  - `target_page_conversion_rate = null`;
  - `candidate_scope = captured_candidates`.
- Added B2 strategy candidate storage/API and B3 human review API:
  - strategy candidates save provider/model/prompt version, raw request,
    structured payload, validator status, and human review status;
  - review states are `PENDING_REVIEW`, `ACCEPTED`,
    `ACCEPTED_WITH_EDITS`, `REJECTED`, and `DEFERRED`;
  - accepted candidates can request experiment-plan conversion, but readiness
    stays blocked when retrieval baseline is missing.
- Generated Strategy Candidate `#2` from Package `#6`:
  - provider `local_rule`;
  - model `local-rule-v1`;
  - review status `PENDING_REVIEW`;
  - target metric `official_reference_rate`.
- Recollected Prompt 19 retrieval baseline after the collector fix:
  - probe Task `#41`, Runs `170-172`, all success, each Run captured 34
    candidates and 30 references;
  - full baseline Tasks `#42` and `#43`, Runs `173-184`, all success;
  - full baseline candidate count per Run: 30-32;
  - full baseline reference count per Run: 31;
  - generated Package `#7`;
  - `retrieval_eligible_run_count = 12`;
  - `target_page_retrieval_rate = 0/12 = 0%`;
  - `target_page_conversion_rate = not_applicable`;
  - locked Experiment `#13` baseline to Runs `173-184`;
  - cleared `release_blocked` because the recollected retrieval baseline is now
    eligible.
- Generated Strategy Candidate `#4` from Package `#7` and Experiment `#13`:
  - provider `local_rule`;
  - model `local-rule-v1`;
  - review status `PENDING_REVIEW`;
  - target metric `target_page_retrieval_rate`.
- Updated frontend Evidence Package view:
  - displays answer/citation/retrieval eligibility;
  - labels incomplete candidates as `已捕获候选`;
  - disables candidate-not-cited and candidate-to-citation displays when
    retrieval candidates are insufficient;
  - adds B2/B3 strategy generation and human review controls without any
    automatic publish action.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest` passed: 13 tests.
- `.venv/bin/python scripts/reference_parser_smoke.py` passed.
- `.venv/bin/python scripts/optimization_loop_smoke.py` passed.
- `npm run build` passed with the existing Vite chunk-size warning.
- `curl -s http://127.0.0.1:8000/api/health` returned `{"status":"ok"}`.

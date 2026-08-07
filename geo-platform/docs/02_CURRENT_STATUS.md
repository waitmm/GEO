# 02 Current Status

Status: ACTIVE

## Implemented

- FastAPI backend with SQLite, SQLAlchemy `create_all` compatibility, and an
  Alembic migration skeleton for formal schema changes.
- React/Vite/AntD frontend.
- Project, competitor, topic, cluster, Prompt, batch, task, and run management.
- Wenxin browser-audit collector with artifact persistence.
- Prompt daily report model/API/UI remains as legacy collection-history
  compatibility. It is no longer the primary analysis surface.
- B1 Evidence Package model/API/UI for deterministic fact reports.
- Page snapshot, human Hypothesis, and release-confirmation audit models/API.
- Validation dashboard aggregation.
- P0 optimization-loop backend objects/API and frontend page.
- `target_page_retrieval_rate` is now the first-stage target-page funnel metric
  with valid/retrieved Run counts, `delta_pp`, per-Prompt, per-environment, and
  raw Run drilldown.
- `target_page_conversion_rate` remains the second-stage metric for retrieved
  pages that may or may not become citations.
- `OptimizationAction.content_feature_changes` now supports structured change
  objects while reading legacy strings as `LEGACY_NOTE`.
- Experiment conclusion writes now use the uppercase human conclusion enum.
- Action release now distinguishes planned/manual release from confirmed real
  publication.
- The former "Prompt daily report" frontend entry now carries:
  `采集记录 / 证据事实报告`. Legacy daily rows are kept for collection history,
  while Evidence Package is the primary path for analysis.

## Important Current Fixes

- Wenxin reference parsing now uses multi-snapshot and saved HTML fallback to
  avoid missing references that are present in `page.html`.
- Reference screenshot retention is now focused on reference-source evidence
  rather than a low-value single viewport screenshot.
- Validation dashboard service now returns a real `ValidationDashboard` instead
  of falling through to `None`.
- Citation/retrieval display rows are deduplicated by normalized URL, while
  occurrence counts and covered Run IDs remain visible.
- Wenxin retrieval candidate collection no longer applies a local top-20 cap.
  Evidence Packages now expose `retrieval_coverage_summary` so incomplete
  candidate denominators are visible instead of being treated as a complete
  retrieval library.

## Current Stage

```text
SOFTWARE_LOOP_READY
```

Experiment `#13` is `READY_FOR_MANUAL_RELEASE`, but the project must remain
`SOFTWARE_LOOP_READY` until the target page is actually published and confirmed.
`REAL_EXPERIMENT_STARTED` has not been reached. The first real experiment is
Prompt 19 "抖音跳转链接" for Project 3 "爱短链品牌监测".

```text
target_page_url = https://www.aifabu.com/card
baseline_run_ids = [135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146]
answer_eligible_run_count = 12
citation_eligible_run_count = 12
retrieval_eligible_run_count = 0
captured_candidate_total = 240
citation_total = 360
target_page_retrieval_rate = null / insufficient_retrieval_candidates
target_page_conversion_rate = null / insufficient_retrieval_candidates

recollected_baseline_package_id = 7
recollected_baseline_run_ids = [173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184]
recollected_retrieval_eligible_run_count = 12
recollected_target_page_retrieval_rate = 0 / 12 = 0%
recollected_target_page_conversion_rate = not_applicable
```

Issue `#21`, Action `#13`, and Experiment `#13` remain in the preparation
chain. Experiment `#13` baseline has been replaced with Runs `173-184`, and
`release_blocked` has been cleared because the retrieval baseline is now
eligible. Do not enter cooling or write `released_at` until the external page is
actually published and confirmed by the user.

Prompt 19 Evidence Packages:

```text
package_id = 1
schema_version = b1.v1
metric_spec_version = metric.v1
package_hash = ce4ad3c8393e...
status = active, preserved for the originally accepted baseline

package_id = 3
schema_version = b1.v2
metric_spec_version = metric.v2
package_hash = 27d883086938...
source_run_ids = [135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146]
target_page_retrieval_rate = 0 / 12 = 0%
target_page_conversion_rate = not_applicable
evidence_level = SOURCE_LEVEL_ONLY
current_metric_status = deprecated; superseded by b1.v4 metric eligibility

package_id = 4
schema_version = b1.v3
metric_spec_version = metric.v2
package_hash = aa1686e3c6e1...
source_run_ids = [135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146]
target_page_retrieval_rate = 0 / 12 = 0%
target_page_conversion_rate = not_applicable
retrieval_coverage_status = INCOMPLETE
retrieval_candidate_count = 240
reference_count = 360
common_candidate_count_per_run = 20
current_metric_status = deprecated; retrieval/funnel metrics are ineligible

package_id = 6
schema_version = b1.v4
metric_spec_version = metric.v3
package_hash = e862d233a6a5...
source_run_ids = [135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146]
answer_eligible_run_count = 12
citation_eligible_run_count = 12
retrieval_eligible_run_count = 0
retrieval_metrics_status = insufficient_retrieval_candidates
candidate_scope = captured_candidates
captured_candidate_total = 240
citation_total = 360

package_id = 7
schema_version = b1.v4
metric_spec_version = metric.v3
package_hash = latest recollected baseline
source_run_ids = [173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184]
answer_eligible_run_count = 12
citation_eligible_run_count = 12
retrieval_eligible_run_count = 12
target_page_retrieval_rate = 0 / 12 = 0%
target_page_conversion_rate = not_applicable
```

Package `#7` is the current retrieval-eligible B1 fact report. Package `#6`
preserves old Runs `135-146` as answer/citation evidence, while explicitly
disabling retrieval/funnel metrics: all 12 old Prompt 19 Runs stored 20
candidates but 30 final references. The saved `searchresult-1.json` artifacts
also contain `data.results = 20`, so the missing candidate denominator cannot be
reconstructed from historical raw evidence.

B2/B3 status:

```text
strategy_candidate_id = 4
evidence_package_id = 7
provider = local_rule
model = local-rule-v1
review_status = PENDING_REVIEW
target_metric = target_page_retrieval_rate
```

Prompt 19 release preparation:

```text
pre_release_snapshot_id = 3
hypothesis_id = 1
hypothesis_status = ACCEPTED
experiment_status = READY_FOR_MANUAL_RELEASE
experiment_released_at = null
action_released_at = null
```

## Worktree Classification

- Product source: backend models/routes/services, frontend app/client/types/css,
  monitoring collector, analytics service, startup script.
- Database or schema changes: additive SQLAlchemy optimization models,
  `optimization_evidence_packages`, `page_snapshots`,
  `optimization_hypotheses`, `release_audit_records`, plus
  `backend/alembic/versions/20260806_01_b1_gate_release_audit.py`.
- Tests and smoke: `reference_parser_smoke.py` and
  `optimization_loop_smoke.py`.
- Project docs: numbered docs plus `AGENTS.md` files.
- Valuable fixture/artifact candidate: tracked
  `backend/artifacts/monitoring/27/*` for reference parser evidence.
- Ignored local runtime: `.env`, `.venv`, SQLite DBs/WAL, frontend
  `node_modules`/`dist`, runtime logs, untracked monitoring artifacts, temp
  directories, browser/session state.

## Known Limits

- SQLite development schema still uses startup sync for local iteration, but
  formal Alembic migration files now exist for B1 release-preparation objects.
- Browser collection is still sensitive to login/captcha/session state.
- Prompt 19 historical Runs 135-146 cannot be replayed into a complete
  retrieval candidate set from existing artifacts: saved `searchresult-1.json`
  responses contain `rn=20` / `data.results=20`, while each Run has 30 final
  references.
- Optimization-loop smoke validates software flow. A real business experiment
  still requires actual release, cooling, new collection, and human conclusion.
- The first real experiment has a zero retrieval-entry baseline. The next risk
  is external publication discipline: the system must not start cooling until
  the updated `https://www.aifabu.com/card` page is truly published.

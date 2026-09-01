# 08 Development Log

Status: ACTIVE

## 2026-09-01 Step 7 Current Analysis State Fix

- Fixed a workflow state bug where a Prompt with upstream answer-decision or
  evidence signals but no generated V1.1 formal Evidence input could be shown
  as:

```text
NO_STRATEGY
NO_EXPERIMENT
```

This was misleading because "current V1.1 chain has not produced formal input"
is not the same as "current chain proved no strategy is needed".

- Added a current-chain input state check for:

```text
decision events
legacy SUPPORTS / RELATED evidence signals
formal V1.1 EvidenceAlignment input
completed V1.1 Shadow runs
```

- New workflow state:

```text
NEEDS_CURRENT_ANALYSIS
```

It is returned only when the current Prompt has upstream signals but lacks
V1.1 formal Evidence input. Step 7 and Step 8 remain unfinished in this state.

- `NO_STRATEGY` is now reserved for the terminal case where the current formal
  chain has run and still produced no Content/Evidence strategy candidate.

- The frontend now renders `NEEDS_CURRENT_ANALYSIS` as:

```text
第 7 步：需重跑主链
按钮：重新运行当前主链
```

The button calls:

```text
POST /api/optimization/workflow/{project_id}/{prompt_id}/run-analysis
{ "use_answer_binding_v1_1": true }
```

- The backend `run-analysis` pipeline now generates the V1.1 AnswerUnit /
  AnswerDecisionBinding shadow input before running formal SourceClaim /
  EvidenceAlignment when `use_answer_binding_v1_1=true`.
- When the frontend does not pass explicit `run_ids`, `run-analysis` now
  defaults to the active Evidence Package's frozen `source_run_ids` before
  falling back to all available Prompt runs. This keeps "current main chain"
  aligned to the current Evidence Package context.
- Follow-up fix: `run-analysis` now creates a persistent
  `PromptAnalysisRun(status=RUNNING)` record at task start and updates it to
  `COMPLETED` or `FAILED`. Workflow status maps these into:

```text
CURRENT_ANALYSIS_RUNNING
CURRENT_ANALYSIS_FAILED
```

This prevents the UI from looking unchanged after the user clicks "重新运行当前主链".
Failure details are surfaced from `PromptAnalysisRun.errors_json`.

Boundary:

```text
No Gap rule changes.
No Strategy rule changes.
No Step 8 or Step 9 changes.
Historical candidates/experiments still cannot light the current workflow.
```

## 2026-09-01 Step 7 Strategy Channel Resolver

- Audited current channel-decision logic. Formal Step 7 channel roles were
  previously distributed across:

```text
_strategy_planned_channels
_strategy_primary_intervention_path
_strategy_channel_roles
frontend display of planned_channels/channel_roles
Step 8 mechanism compatibility checks
```

- Introduced a single deterministic resolver:

```text
_resolve_strategy_channels(...)
```

It is now the only formal source for:

```text
primary_intervention_path
planned_channels
channel_roles
channel_rationales
```

- Resolver inputs are existing formal read-model signals only:

```text
capability_gap_items
priority_capabilities
citation_decision_values
channel_aggregation
product_truth
relevant_brand_assets
retrieval/citation state
benchmark evidence
```

- Deprecated distributed shortcuts are no longer consumed by formal Step 7:

```text
CONTENT/EVIDENCE -> first-party PRIMARY
Benchmark platform -> execution channel
Benchmark platform -> always OBSERVE
```

- Added deterministic policy behavior:

```text
CONTENT_GAP -> relevant first-party asset can be PRIMARY.
EVIDENCE_GAP + strong third-party Decision Citation -> third-party channel can be PRIMARY.
DISCOVERABILITY_GAP -> retrieval expansion path.
PRODUCT_GAP -> PRODUCT_IMPROVEMENT, no content-channel PRIMARY.
UNKNOWN -> no forced PRIMARY channel.
Benchmark-only without Decision Citation -> OBSERVE.
```

- The resolver explicitly does not decide Step 8 execution parameters:

```text
account
URL
page
title
section
asset instance
Draft
```

- Prompt `#40` read-only regression:

```text
Evidence Package #15
status = READY_FOR_HUMAN_CONFIRM
primary_intervention_path = FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION:OFFICIAL_SITE
OFFICIAL_SITE = PRIMARY
ZHIHU = SECONDARY
ZHIHU basis = Decision Citation 6/6 Runs; supported reasons 点击统计 / 自定义分享标题 / 营销场景使用; primary benchmark 1
resolver = resolve_strategy_channels / DETERMINISTIC_POLICY_ENGINE
```

The #40 output did not change for change's sake. The important correction is
that both OFFICIAL_SITE and ZHIHU roles now come from the same resolver rather
than two distributed rule fragments.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py tests/test_workflow_review_queue.py
.venv/bin/python -m compileall app
source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build
git diff --check
```

Results:

```text
91 passed
compileall passed
frontend build passed
git diff --check passed
```

## 2026-09-01 Citation Decision Value Step 7 Strategy Input

- Added a Citation Decision Value interpretation layer on top of existing
  Phase 2A eligible `EvidenceAlignment`. This is a derived read model only; it
  does not add a database table, migration, new Evidence Judge, new Citation
  Score, new Benchmark formula, new Gap type, Draft, or Step 9 behavior.
- Formal grain is now:

```text
SourceDocument
+ supported_entity
+ capability/reason
```

The same SourceDocument can therefore expose multiple values rather than a
single document-wide label.
- Implemented derived classes:

```text
DECISION_CITATION
ANSWER_SUPPORT_CITATION
PERIPHERAL_CITATION
UNCLASSIFIED_SUPPORT
NOT_EVALUABLE
```

- Added source-row output:

```text
citation_decision_values
citation_value_class
citation_value_summary
citation_run_ids
retrieval_run_ids
```

- Added `channel_aggregation` to `citation_decision_vertical_slice`, summarizing
  platform-level retrieval/citation/decision-citation coverage, supported
  entities/reasons, and benchmark counts.
- Updated Step 7 Strategy Core generation so `planned_channels` and
  `channel_roles` consume Citation Decision Value + Channel Aggregation. The
  old simplified behavior:

```text
CONTENT_GAP -> OFFICIAL_SITE PRIMARY
Benchmark platform -> OBSERVE
```

is no longer sufficient. Benchmark Channel still cannot automatically become an
execution channel; a platform can become `SECONDARY` or `EXPERIMENTAL` only when
Decision Citation coverage explains why.
- Prompt `#40` read-only regression:

```text
Evidence Package #15
source_count = 68
recommended_actions = 1
ZHIHU retrieval = 6/6
ZHIHU citation = 6/6
ZHIHU decision citation = 6/6
ZHIHU primary_benchmark_count = 1
supported reasons = 点击统计 / 自定义分享标题 / 营销场景使用
planned_channels = OFFICIAL_SITE PRIMARY + ZHIHU SECONDARY
```

- Scope deliberately excluded Step 8 Draft, Step 9, Channel Intelligence,
  Product Truth changes, Gap rule changes, EvidenceAlignment eligibility
  changes, Benchmark scoring changes, and Decision Stability changes.

Validation:

```text
.venv/bin/python -m compileall app
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py tests/test_workflow_review_queue.py
source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build
git diff --check
```

Results:

```text
compileall passed
84 passed
frontend build passed
git diff --check passed
```

## 2026-08-31 Step 7 V1.1 Current Candidate Eligibility Blocker Fix

- Fixed the current single Prompt Step 7 blocker where legacy, audit, test, or
  regression `OptimizationStrategyCandidate` rows could be selected as the
  current strategy candidate after Prompt `#40` was re-run.
- Added a centralized current Step 7 eligibility validator. A candidate is
  current-consumable only when it matches the active Prompt Evidence Package,
  package version, V1.1 answer-binding input mode, current generator family,
  `USER_FLOW` origin, and complete Strategy Core schema.
- `review_strategy_candidate` now writes the current workflow confirmation only
  for eligible current Step 7 candidates. Historical accepted candidates remain
  reviewable history but cannot mark the current main chain as confirmed.
- Step 8 backend entry points now reject ineligible candidates even if they are
  already `ACCEPTED` or `ACCEPTED_WITH_EDITS`; this prevents old candidates from
  creating current Action / Experiment rows.
- Added a dedicated current generation endpoint:

```text
POST /api/optimization/projects/{project_id}/prompts/{prompt_id}/strategy-candidates/generate-current-v1
```

- The frontend strategy page no longer calls the old `generate-v2` route for
  the current single Prompt Step 7 flow. It now generates through the current
  V1.1 endpoint and defaults the strategy list to
  `eligible_for_current_step7=true` rows only.
- Prompt `#40` read-only regression after the fix:

```text
evidence_package_id = 15
package_version = 2
strategy_step_status = READY_TO_GENERATE
current_strategy_candidate_ids = []
current_strategy_confirmed = false
execution_step_status = LOCKED
historical_strategy_candidate_count = 8
ineligible current candidates = #40-#47
```

- Scope deliberately excluded Evidence, Benchmark, Gap, Decision Stability,
  Strategy Core algorithm, Asset Brief, Claim Matrix, Draft, Experiment,
  Baseline, and Step 9 changes.

Validation:

```text
.venv/bin/python -m compileall app
.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py tests/test_strategy_step7_v1.py
nvm use 18.20.8 && npm run build
```

## 2026-08-31 Step 7/8 Current-State Alignment Fix

- Fixed the single Prompt workbench state source for Step 7 / Step 8. The
  current main-chain state is now derived from the current Prompt, current
  active Evidence Package, and the bound current StrategyCandidate instead of
  historical accepted candidates, historical experiments, or legacy
  `WorkflowConfirmation(action)` rows.
- `review_strategy_candidate` now writes a context-bound confirmation record
  when a StrategyCandidate is accepted:

```text
strategy_candidate_id
evidence_package_id
prompt_id
review_status
effective_validation_status
```

- `workflow_status` now returns central current-state fields for frontend use:

```text
strategy_step_status
execution_step_status
current_strategy_candidate_id(s)
current_strategy_confirmed
current_effective_payload_valid
current_action_id
current_experiment_id
historical_strategy_candidate_ids/count
historical_experiment_ids/count
```

- Step 7 status is now locked to:

```text
NOT_READY
READY_TO_GENERATE
PENDING_REVIEW
CONFIRMED
```

Only `CONFIRMED` marks Step 7 complete. `READY_TO_GENERATE` and
`PENDING_REVIEW` are actionable current states, not completion states.
- Step 8 is complete only when the current confirmed StrategyCandidate points
  to the current Action / Experiment Draft. Historical experiments remain
  visible as history but cannot light the current main chain.
- Removed the old workbench shortcut that could directly mark
  `WorkflowConfirmation(action)` from a legacy continue result. Strategy
  confirmation must go through StrategyCandidate human review.
- Frontend single Prompt cards and the citation decision stepper now consume
  backend current-state fields and keep history separate. User-facing labels
  use `策略确认` and `实验方案落地`.
- Scope deliberately excluded Evidence, Benchmark, Gap, Strategy generation,
  Asset Brief, Draft, Step 9, Decision Stability, and scoring changes.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py
7 passed
```

## 2026-08-31 Step 7 Strategy Confirmation UX Link Fix

- Fixed a Prompt `#40` UX regression where Step 7 appeared to only show two
  planned channels and did not clearly expose:

```text
StrategyCandidate
-> Human Strategy Confirmation
-> effective_payload
-> Step 8 Action / Experiment Draft
```

- Root cause: the strategy page displayed planned channels correctly, but the
  card did not lead with the StrategyCandidate confirmation state. The Step 8
  button was also a placeholder `message.info`, so confirmed strategies with an
  existing Experiment looked clickable but did not open the corresponding draft.
- Added a Chinese `策略确认链路` summary to each strategy card, including:

```text
机器候选 / 已人工确认 Strategy
effective_payload validation state
Action id
Experiment draft id
```

- Changed the Step 8 button behavior:
  - existing Action/Experiment -> open the matching experiment chain;
  - accepted Strategy without draft -> explain that execution-plan parameters
    are still required;
  - pending Strategy -> keep the explicit `确认策略` gate.
- When Step 7 generates a new StrategyCandidate from the single Prompt
  workbench, the strategy page now defaults to the newly generated candidate
  instead of letting historical accepted candidates steal the default view.
- This is a UI flow fix only. It does not change Strategy generation, Evidence,
  Benchmark, Gap, Product Truth, Action, Experiment, Baseline, Draft, or Step 9.
- Follow-up correction: `phase_*_regression` StrategyCandidates are now treated
  as historical acceptance artifacts, the same as `phase*_audit`. They no
  longer mark the current Prompt workflow Step 7/8 as complete. Planned channel
  rows now show `selection_basis` so users can see why a platform layer is
  suggested.

## 2026-08-31 Step 8 Asset Brief + Claim Matrix

- Added Step 8 Asset Brief + Claim Matrix as the second cut after Strategy Core
  protection. This checkpoint stays inside Step 8 and does not create Draft,
  Step 9, new scoring, new Gap semantics, or a parallel Strategy model.
- Reused existing storage instead of adding a new asset-brief table:

```text
OptimizationExperiment.brief_json
OptimizationExperiment.intervention_variables_json
OptimizationExperiment.controlled_intervention_json
OptimizationAction.release_evidence_json
OptimizationStrategyCandidate.experiment_plan_json / effective_payload
```

- Added `AssetBriefReviewPayload` and the backend review endpoint:

```text
POST /api/optimization/experiments/{experiment_id}/asset-brief/review
```

- Step 8 now builds an Asset Brief for the concrete Action / Asset /
  Execution Path. The brief freezes strategy snapshot/ref, selected asset
  ref/snapshot, required signals, claim matrix, Product Truth refs/snapshot,
  benchmark evidence refs, channel role, brief version, and review timestamp
  when confirmed.
- Claim Matrix is fact-boundary only. It lists required, optional, prohibited,
  and review-required claims; it does not generate article paragraphs, FAQ, or
  content draft.
- Product Truth discipline was enforced in backend logic:

```text
SUPPORTED     -> REQUIRED / OPTIONAL
UNKNOWN       -> REVIEW_REQUIRED / BLOCKED
NOT_SUPPORTED -> PROHIBITED
```

- Benchmark Evidence / SourceClaim can explain market standard and AI decision
  context, but can never become target-brand Product Truth.
- Added explicit draft gate: Asset Brief must be confirmed before later Draft
  preparation can start. This checkpoint still stops before Draft.
- Existing Step 8 draft objects are backfilled in place when missing Asset
  Brief data. The #40 official path reused `StrategyCandidate #44`,
  `Action #31`, and `Experiment #31`; no duplicate Action/Experiment was
  created.
- Prompt `#40` real regression:

```text
StrategyCandidate #44
Action #31
Experiment #31
created_new_draft = False
PRIMARY_BENCHMARK = 1 -> 1
recommended_action_count = 1 -> 1
Prompt #40 EvidenceAlignment = 660 -> 660
claim_matrix REQUIRED = 点击统计 / 自定义分享标题 / 营销场景使用
draft_gate = READY_FOR_DRAFT_PREPARATION
mechanism_compatibility = EXECUTION_COMPATIBLE
```

- A script selection pitfall was caught during audit: the first pass could pick
  a previously created channel-simulation candidate instead of the official
  Step 8 path. The audit runner now prefers the current experiment-bound
  `OFFICIAL_SITE` candidate for #40 acceptance evidence.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py
69 passed
```

## 2026-08-28 Step 7 Strategy Core / Step 8 Protection First Cut

- Updated Step 7 `StrategyCandidate` generation so the candidate carries a
  complete Strategy Core while still reusing existing
  `OptimizationStrategyCandidate.structured_payload/effective_payload`:

```text
target_decision_change
priority_capabilities
strategic_hypothesis
intervention_mechanism
primary_intervention_path
planned_channels
channel_roles
asset_direction
execution_sequence
required_signals
non_goals
attribution_intent
```

- Corrected the Step 7/8 boundary: Step 7 may define planned platform layer and
  channel role, such as `OFFICIAL_SITE` or `ZHIHU`, but it must not bind
  concrete account, URL, page, title, section, content structure, Draft,
  Baseline, Action, or Experiment.
- Added Step 8 Strategy Core Protection. If Step 8 payload attempts to change
  Strategy Core fields such as `intervention_mechanism`, the backend blocks the
  request and returns `RETURN_TO_STEP_7`.
- Added structured `execution_delta` rows with backend-calculated impact level:

```text
EXECUTION_ONLY
MECHANISM_REVIEW_REQUIRED
STRATEGY_CORE_CHANGE
```

- Added Mechanism Compatibility checks:

```text
EXECUTION_COMPATIBLE
REVIEW_REQUIRED
STRATEGY_RECONFIRM_REQUIRED
```

- Step 8 Experiment snapshots now freeze Strategy Core attribution intent,
  selected asset, action snapshot, baseline, execution delta, and mechanism
  compatibility. Existing StrategyCandidate and Experiment models were reused;
  no migration was required.
- Frontend strategy detail now renders Strategy Core, planned channels,
  channel roles, asset direction, execution sequence, and attribution intent in
  Chinese labels. The old warning `第 7 步不选择平台或文章类型` was replaced with
  the more precise planned-channel vs concrete-execution boundary.
- Prompt `#40` real regression:

```text
StrategyCandidate #44 = ACCEPTED_WITH_EDITS / VALIDATED
Action #31
Experiment #31
planned primary channel = OFFICIAL_SITE
Benchmark source channel = ZHIHU / OBSERVE only
BAIJIAHAO simulation = REVIEW_REQUIRED
intervention_mechanism mutation = RETURN_TO_STEP_7
```

- This checkpoint does not implement Asset Brief, Claim Matrix, Draft, Step 9,
  Decision Stability changes, Citation/Benchmark formula changes, or new Gap
  semantics.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py
54 passed
.venv/bin/python -m compileall -q app
frontend npm run build
git diff --check
```

## 2026-08-28 Step 7 Strategy Page Structured Payload Render Guard

- Fixed a white-screen crash after Step 7 `生成策略候选` succeeded.
- Root cause: the generated `StrategyCandidate` payload can contain structured
  objects such as `evidence_summary`. The strategy page rendered that value
  directly as a React child, which crashes when the value is an object.
- Added display-only normalization for strategy page text fields. Structured
  evidence summaries are now shown as concise Chinese summaries:

```text
对标来源
涉及能力
缺口
优先级
```

- This does not change StrategyCandidate payloads, effective_payload,
  Evidence lineage, Benchmark, Gap, Action, Experiment, Baseline, Decision
  Stability, or Step 9.

Validation:

```text
frontend npm run build
git diff --check
```

## 2026-08-28 Step 7 Strategy Confirm V1.1 Context Parity

- Fixed a Prompt `#40` blocker where clicking Step 7 `生成策略候选` looked like
  it had no effect.
- Root cause: the frontend read Citation Decision V1 with
  `use_answer_binding_v1_1=true`, so the page correctly showed a current
  strategy candidate could be generated. The confirm POST did not pass the same
  flag, so the backend recomputed the proposal with the default formal input
  setting and returned:

```text
没有可生成策略候选的 Content/Evidence Gap。Product/Unresolved 需要先人工补充 Product Truth 或资产信息。
```

- The Step 7 confirm payload now includes the exact V1.1 usage flag returned by
  the current Citation Decision result, falling back to the current frontend
  constant only when the API response omits it.
- No StrategyCandidate model, effective_payload validation, Evidence lineage,
  Benchmark, Gap, Action, Experiment, Baseline, Decision Stability, or Step 9
  behavior was changed.

Validation:

```text
frontend npm run build
.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py app/modules/optimization/service.py
git diff --check
```

## 2026-08-28 Step 7/8 Audit History Isolation

- Fixed a Prompt `#40` retest UX issue where Phase audit artifacts from final
  acceptance could make Step 7 and Step 8 look complete before the operator
  saw or confirmed a current StrategyCandidate.
- Root cause: Prompt `#40` already had audit-generated records on the current
  Evidence Package:

```text
StrategyCandidate #41 / #40 = ACCEPTED_WITH_EDITS / VALIDATED
reviewed_by = phase4_audit / phase3_audit
Experiment #30 / #29 = draft
```

- The frontend now treats audit-generated `StrategyCandidate` rows as history
  for the single Prompt main workflow. They remain visible under
  `全部策略（含历史验收）`, but they no longer mark Step 7 as confirmed, mark
  Step 8 as created, appear as the default current strategy, or allow accidental
  accept/experiment generation from the historical card.
- Current workflow Step 7 remains operable: when evidence and Gap are ready and
  there is no non-audit current StrategyCandidate, the next action is
  `生成策略候选`.
- No backend data, Evidence lineage, Benchmark formula, Gap decision tree,
  Product Truth, StrategyCandidate validation, Action/Experiment creation,
  Baseline, Decision Stability, or Step 9 behavior was changed.

Validation:

```text
frontend npm run build
.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py
git diff --check
```

## 2026-08-28 Step 7 Strategy Gate Unblock

- Fixed a single Prompt workflow blocker where Step 7 could remain
  `策略确认 / 等待缺口` even though the current Citation Decision V1 result had
  already completed Gap Diagnosis and the current Evidence Package had
  confirmed `StrategyCandidate` rows.
- Root cause: the frontend Step 7 gate still depended on legacy
  `WorkflowConfirmation` keys (`gap` / `action`). The frozen V1 main chain must
  use the current Citation Decision Gap result plus current
  Evidence-Package-scoped `OptimizationStrategyCandidate` review state.
- Updated the Step 7 current-chain guard:

```text
answer decision done
-> evidence review done
-> current Citation Gap decision done
-> current Evidence Package StrategyCandidate state
```

- Updated user-facing wording so completed evidence review no longer tells
  operators to click legacy `继续分析` to generate "缺口与动作". The next step is
  now displayed as generating or reviewing `策略候选`.
- Strategy detail entry buttons now route through the current Evidence Package
  selector before opening the strategy page, reducing empty strategy-context
  jumps.
- No data model, Evidence lineage, Benchmark formula, Gap decision tree,
  StrategyCandidate/effective_payload validation, Action, Experiment, Baseline,
  Decision Stability, or Step 9 behavior was changed.

Validation:

```text
.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py
frontend npm run build
git diff --check
```

## 2026-08-28 Evidence Review Group Batch Confirm

- Added semantic grouping for workflow EvidenceAlignment review items. The
  review queue now merges duplicated Run-level SUPPORTS alignments into one
  user-facing review group when they share:

```text
semantic reason text
source_document_id
source_claim_id
relation
evidence_role
```

- The grouped review item keeps all underlying `alignment_ids`, true
  `run_ids`, `run_count`, and `alignment_count`; no Run-level
  EvidenceAlignment is merged, deleted, or rewritten.
- Follow-up correction: V1.1 `recommendation_reason_id` can contain per-Run
  technical IDs such as `answer_unit:{id}:binding:{id}` and must not be used as
  the grouping key. The queue now uses `semantic_reason_key` when available and
  falls back to the legacy readable reason text.
- The batch confirm route is registered before the single-alignment dynamic
  route so `/confirm-batch` cannot be parsed as an `alignment_id`.
- Added a minimal batch confirmation endpoint:

```text
POST /api/optimization/workflow/review/alignments/confirm-batch
```

- The frontend manual review workspace now shows one card per grouped evidence
  item and provides one action: `确认这一组支持`.
- No data migration was required. The change only updates review queue payloads
  and review status confirmation behavior.
- No Evidence, Benchmark, Gap, Strategy, Action, Experiment, Baseline,
  Decision Stability, or Step 9 logic was changed.

Validation:

```text
.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py
4 passed

.venv/bin/python -m compileall -q app/modules/optimization/workflow.py app/modules/optimization/api.py
frontend npm run build
```

## 2026-08-28 Step 7 Current-Workflow State Integrity Bugfix

- Fixed a single Prompt workflow regression where Step 7 could display
  `策略确认 / 已确认` because the current Evidence Package already had a
  historical confirmed `StrategyCandidate`, even when the current workflow
  status still required evidence review or gap diagnosis.
- The frontend now gates current Step 7 state by the current workflow chain:

```text
answer_semantic done
-> evidence_review done
-> gap done
-> current StrategyCandidate state
```

- Existing StrategyCandidates and Experiments remain visible as historical
  objects, but they no longer mark the current main-chain Step 7 or Step 8 as
  complete unless the current workflow state has reached that step.
- Strategy page navigation now reloads the current Evidence Package before
  routing to the strategy confirmation page, preventing a "confirmed strategy"
  button from opening an empty strategy context.
- No data model, Evidence, Benchmark, Gap, StrategyCandidate validation,
  Action, Experiment, Baseline, Release Gate, Decision Stability, or Step 9
  behavior was changed.

Validation:

```text
frontend npm run build
backend compileall for workflow module
git diff --check
```

## 2026-08-27 Step 7 Strategy Confirmation UI Bugfix

- Fixed the single Prompt workflow Step 7 user-facing semantics after V1
  freeze. The product meaning is `StrategyCandidate + 人工策略确认`, not
  "推荐动作确认".
- Updated frontend Step 7 state derivation so it reads current
  Evidence-Package-scoped `StrategyCandidate` state:
  - confirmed StrategyCandidate -> `策略确认 / 已确认`
  - pending StrategyCandidate -> `策略确认 / 待审核`
  - no candidate but eligible Content/Evidence Gap -> `可生成策略候选`
- After generating StrategyCandidates from Citation Decision V1, the frontend
  now reloads the current evidence package's strategy list and routes the user
  to the strategy confirmation area.
- Updated legacy visible labels in the citation decision detail page from
  "推荐动作" to "策略候选 / 策略确认" where the action is actually Step 7
  strategy generation/review.
- Updated backend workflow label for the historical `step_key="action"` to
  display as `策略确认`. The key remains unchanged for compatibility.
- No data model, Citation/Benchmark/GAP formula, StrategyCandidate gate, Action,
  Experiment, Baseline, or Step 9 behavior was changed.

Validation:

```text
frontend npm run build
backend compileall for workflow module
git diff --check
```

## 2026-08-27 Documentation Governance

- Added repository-level documentation governance for product iteration,
  development iteration, known pitfalls, and `产品纲要.md` maintenance:

```text
docs/12_DOCUMENTATION_GOVERNANCE.md
```

- Updated `geo-platform/AGENTS.md` so future work must update documentation when
  product semantics, workflow state sources, or previously encountered pitfalls
  are touched.
- Updated root `产品纲要.md` from the older broad flow to the current frozen
  single Prompt GEO V1 Step 1-8 chain.
- No business code, data model, API, frontend workflow, scoring formula,
  Strategy, Action, Experiment, or Step 9 behavior was changed.

Validation:

```text
git diff --check
```

## 2026-08-27 Single Prompt GEO V1 Final Acceptance

- Completed final acceptance for the single Prompt GEO V1 Step 1-8 main chain
  using Prompt `#40` as the Golden Case.
- Added the final acceptance audit artifact:

```text
docs/SINGLE_PROMPT_GEO_V1_FINAL_ACCEPTANCE.md
```

- Added the read-only audit helper:

```text
backend/scripts/audit_prompt40_final_acceptance.py
```

- Prompt `#40` final accepted state:

```text
valid_run_ids = [238, 239, 240, 253, 254, 255]
evidence_package_id = 15
PRIMARY_BENCHMARK = 1
CONTENT_GAP = 3 capability-level items
StrategyCandidate #41 = ACCEPTED_WITH_EDITS / VALIDATED
Action #30 = PLANNED
Experiment #30 = draft / WAITING_FOR_RELEASE_AUDIT
Decision Stability = CO_DOMINANT / 100 / HIGH_STABILITY
```

- Applied one acceptance bugfix without changing the stability score formula or
  any Step 1-8 gate: Decision Stability reason coverage now uses the current
  formal-input `AnswerDecisionBinding` batch when V1.1 formal EvidenceAlignment
  payloads identify one. Historical Shadow bindings remain preserved but no
  longer pollute current reason coverage.
- No new product phase, model, Gap type, Strategy type, scoring formula, Step 9,
  validation run, monitoring loop, Prompt Cluster, Channel Intelligence, or
  automatic content generation/publishing was added.
- Validation:

```text
.venv/bin/python -m compileall -q app scripts/audit_prompt40_final_acceptance.py scripts/audit_prompt40_phase5_decision_stability.py
.venv/bin/python -m pytest -q tests/test_answer_evidence_shadow.py tests/test_evidence_lineage_v1.py tests/test_source_gap_v1.py
68 passed

frontend npm run build
passed

git diff --check
passed
```

- Phase status:

```text
SINGLE_PROMPT_GEO_V1_FROZEN
STEP_9_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Phase 5 Decision Stability

- Added Phase 5 Decision Stability as a read-only post-hoc metric for single
  Prompt multi-Run recommendation variance.
- No database migration was required. The metric is derived from existing:
  - fixed Evidence Package `source_run_ids`
  - valid `BrowserMonitorRun`
  - `RecommendationEvent`
  - `AnswerDecisionBinding`
  - `AnswerUnit`
- Added service/API support:

```text
GET /optimization/projects/{project_id}/prompts/{prompt_id}/decision-stability
```

- The `citation-decision-v1` response now includes `decision_stability` for
  the current Prompt/package context.
- Locked the calculation formula in code and docs:

```text
score = round(dominant_recommendation_outcome.run_count / valid_run_count * 100)
```

- Added fixed stability levels:

```text
HIGH_STABILITY: score >= 80
MIXED: 50 <= score < 80
HIGH_VOLATILITY: score < 50
NO_VALID_RUNS: valid_run_count = 0
```

- Decision Stability remains isolated from all formal gates:

```text
Evidence / Benchmark / Gap / Strategy / Action / Experiment / Baseline
```

- Added frontend display on the single Prompt main chain and citation decision
  detail page. The UI labels it as `只读观察` and explains that it does not
  change main-chain outcomes.
- Added Prompt `#40` Phase 5 audit output:

```text
docs/PROMPT_40_PHASE5_DECISION_STABILITY_AUDIT.md
```

- Added Phase 5 checkpoint:

```text
docs/CITATION_DECISION_V1_1_PHASE5_DECISION_STABILITY_CHECKPOINT.md
```

- Prompt `#40` result:

```text
valid_run_count = 6
brand_decision_run_count = 6
dominant_recommendation_outcome = CO_DOMINANT_RECOMMENDATION_ENTITIES
co_dominant_entities = Bitly / 小码短链接 / 缩我短链接 / 轻松短链接
unique_dominant_entity = none
decision_stability_score = 100
stability_level = HIGH_STABILITY
formal_output_impact = NONE
```

- Added dominant tie semantics: when multiple recommendation entities share the
  highest run coverage, Decision Stability returns `CO_DOMINANT` instead of
  selecting one entity by deterministic name ordering. This does not change the
  stability formula or any single Prompt V1 1-8 main-chain result.

- Also added/kept Phase 4 regression coverage for Strategy gate, Step 8
  execution-plan gate, strategy snapshot immutability, baseline freeze, required
  selected asset/channel, and benchmark-channel isolation.
- Validation:

```text
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase5_decision_stability.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
48 passed
```

- Phase status:

```text
PHASE_5_DECISION_STABILITY_CHECKPOINT_READY
STEP_9_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Phase 4 Execution Plan

- Completed the Phase 4 Preflight Audit inside the same product phase; no
  additional product phase was introduced.
- Reused existing objects instead of adding a parallel asset or strategy system:
  - `PageSnapshot` as the stable existing asset reference.
  - `OptimizationStrategyCandidate.effective_payload_json` as the Strategy
    confirmation payload.
  - `OptimizationAction` and `OptimizationExperiment` for Step 8 draft
    materialization.
  - `OptimizationExperiment.intervention_variables_json`,
    `baseline_run_ids_json`, and `baseline_metrics_json` for frozen snapshots
    and baseline state.
- Added the Step 8 service/API:

```text
POST /optimization/strategy-candidates/{candidate_id}/execution-plan
```

- Added `StrategyExecutionPlanPayload` with separated execution semantics:

```text
channel = OFFICIAL_SITE / PRODUCT_DOCS / ZHIHU / BAIJIAHAO / THIRD_PARTY_MEDIA / OTHER
asset_operation = UPDATE_EXISTING / CREATE_NEW
selected_asset = PAGE_SNAPSHOT:<id> or NEW_ASSET proposal
baseline_run_ids = explicit fixed Run IDs
```

- Locked the Step 7 -> Step 8 gate in backend code and tests:
  - `ACCEPTED_WITH_EDITS + PENDING_HUMAN_CHANNEL_REVIEW` can enter Step 8.
  - `PENDING_REVIEW` cannot enter Step 8.
- Added `baseline_metrics_for_fixed_runs`; it requires explicit Run IDs and
  separates brand-level from selected-asset-level retrieval/citation metrics.
- Experiment draft creation now freezes the confirmed Step 8
  `effective_payload` snapshot, selected asset reference, gap refs, action
  snapshot, baseline Run IDs, and baseline metrics.
- Added Prompt `#40` Phase 4 audit output:

```text
docs/PROMPT_40_PHASE4_EXECUTION_PLAN_AUDIT.md
```

- Added Phase 4 checkpoint:

```text
docs/CITATION_DECISION_V1_1_PHASE4_EXECUTION_PLAN_CHECKPOINT.md
```

- Prompt `#40` real regression created a draft experiment:

```text
strategy_candidate_id = 41
action_id = 30
experiment_id = 30
experiment_status = draft
release_blocked_reason = WAITING_FOR_RELEASE_AUDIT
baseline_run_ids = [238, 239, 240, 253, 254, 255]
```

- Validation:

```text
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase4_execution_plan.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
39 passed
git diff --check passed
```

- Phase status:

```text
PHASE_4_EXECUTION_PLAN_CHECKPOINT_READY
STEP_9_NOT_STARTED
```

## 2026-08-27 Single Prompt GEO V1 Phase 0/1 Handoff

- Added the review-only handoff document:
  `docs/SINGLE_PROMPT_GEO_V1_PHASE0_1_HANDOFF.md`.
- This is a docs-only Phase 0/1 checkpoint. No business code, model migration,
  API behavior, frontend workflow, StrategyCandidate, Action, or Experiment was
  changed in this step.
- Locked the single Prompt GEO V1 chain for review:

```text
1. 采集样本
2. 答案决策识别
3. 目标品牌事实
4. 引用证据
5. 对标来源
6. 缺口诊断
7. 策略候选 + 策略确认
8. 实验方案落地
```

- Recorded four hard constraints for Phase 2:
  - Reuse `OptimizationStrategyCandidate` and `effective_payload` as the
    strategy confirmation boundary.
  - `OptimizationExperiment` must freeze the confirmed `effective_payload`
    snapshot at creation time.
  - `DISCOVERABILITY_GAP` must be based on brand assets relevant to the current
    Prompt/capability, not arbitrary project assets.
  - Formal `EvidenceAlignment` consumers must verify full Run lineage, not just
    non-empty `run_id`.
- Recorded current conflict points before implementation:
  - `confirm_citation_decision_vertical_slice` can still directly materialize
    experiment plans.
  - Current experiment payload storage does not explicitly freeze an
    `effective_payload` snapshot.
  - `_latest_brand_asset_snapshot` can fall back to the latest project asset,
    which is unsafe for discoverability judgment.
  - Several legacy modules still query raw `EvidenceAlignment.relation =
    SUPPORTS` without a unified lineage/feature-flag read gate.
- Current phase status:

```text
PHASE_0_1_HANDOFF_READY_FOR_REVIEW
PHASE_2_BUSINESS_CODE_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Main Workflow Read

- 单 Prompt 主链路前端请求 `citation-decision-v1` 时显式传入
  `use_answer_binding_v1_1=true`，避免后端默认 OFF 时页面仍展示旧 V1
  `0 Benchmark / 0 Action`，导致操作者误以为第 4 步后无法推进。
- 该改动不调整 8 步主链路顺序，不新增模块，不改变后端默认 feature flag；
  后端仍可用 `use_answer_binding_v1_1=false` 验证正式结果回滚。
- Prompt `#40` 当前应进入“1 个核心对标，但推荐动作被 Product Truth
  闸门阻断”的状态，待人工补齐 `点击统计`、`自定义分享标题`、
  `营销场景使用` 等目标品牌事实后再继续生成动作。
- 单 Prompt 首页第 7/8 步只导航到执行策略详情，不直接调用确认接口；
  最终确认动作和创建实验草案必须在详情页查看依据后操作。

## 2026-08-26 Prompt 40 Phase 1 Formal Result Audit

- Audited the first small-scope formal Citation Decision V1.1 input switch on
  Prompt `#40`.
- Added the review artifact:
  `docs/PROMPT_40_PHASE1_FORMAL_RESULT_AUDIT.md`.
- Confirmed that Prompt `#40` moved from the previous false-negative shape to:

```text
status = READY_FOR_HUMAN_CONFIRM
primary_benchmark_count = 1
recommended_action_count = 1
channel_opportunity_count = 1
```

- Confirmed the formal `SUPPORTS` rows came from:

```text
reason_source = ANSWER_DECISION_BINDING
formal_input_version = citation_decision_v1_1_formal_input.v1
```

- Confirmed the result did not come from:

```text
RecommendationEvent.reasons_json
Shadow Evidence Result
Citation Prominence
title/entity string match
LEGACY_RELATED
```

- Found a Phase 2 blocker: the six formal `SUPPORTS` rows are all attached to
  Run `#238`, not spread across all six source Runs. The current formal
  alignment logic deduplicates answer-derived reasons by semantic text, scope,
  and entity, which collapses run-level coverage.
- Found a rollback-boundary blocker: `use_answer_binding_v1_1` currently
  controls generation input only. Once V1.1 formal `EvidenceAlignment` rows are
  written, the Citation Decision read path still consumes them even if the
  generation flag is later false.
- Found a Product Truth granularity risk: the current action focuses on
  `数据统计功能 / 自定义分享标题 / 营销场景`, while matched Product Truth is still
  the broader `短链生成` capability.
- Found a small toolchain drift: `run_single_case_evidence.py` passes
  `doc_id_filter` into Layer 3, but `run_reason_driven_retrieval` does not
  currently accept that parameter.
- Current phase status:

```text
PHASE_1_FORMAL_INPUT_PROVEN_ON_PROMPT_40
READY_FOR_FULL_PRODUCTION_SWITCH = false
```

- No main workflow order change was made in this audit.

## 2026-08-26 Prompt 40 Shadow Binding Scope Calibration

- Calibrated the V1.1 Phase 0 Shadow Binding semantics from strict explicit
  reason detection to Recommendation Explanation Scope detection.
- Added Shadow audit fields on `AnswerDecisionBinding`:
  - `scope_type`
  - `scope_reason`
- Updated Binding rules so recommended-brand capability, benefit, price,
  result, use-case, and comparative-advantage AnswerUnits inside the
  recommendation explanation scope default to `SUPPORTING_REASON`.
- Kept `DIRECT_REASON` reserved for explicit selection conditions, explicit
  causality, explicit comparison, or demand-fit language.
- Preserved exclusions for procedure steps, general background facts, other
  brands, limitations/counter facts, and content outside the recommendation
  explanation scope.
- Extended the Shadow-only evidence path so valuable unbound AnswerUnits can be
  audited as `BRAND_CAPABILITY_EVIDENCE`, `PROCEDURAL_EVIDENCE`, or
  `FACTUAL_EVIDENCE` without creating Recommendation Evidence.
- Added a SQLite compatibility migration for the Shadow-only
  `answer_evidence_shadow_results` table so `recommendation_event_id` and
  `decision_binding_id` can be null for unbound AnswerUnit evidence.
- Re-ran Prompt `#40` six-Run Shadow audit as `ShadowRun #7`.

Prompt `#40` ShadowRun `#7` result:

```text
answer_unit_count = 216
grounded_answer_unit_count = 216
binding_count = 30
direct_reason_count = 0
supporting_reason_count = 30
shadow_result_count = 252
shadow_source_claim_count = 222
SUPPORTS = 18
NO_SUPPORT = 234
CONTRADICTS = 0
recommendation_evidence_eligible_count = 18
```

Formal V1 zero-pollution check:

```text
formal SourceClaim: 545 -> 545
formal EvidenceAlignment for Prompt #40: 0 -> 0
PRIMARY_BENCHMARK: 0 -> 0
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 0 -> 0
channel_opportunity_count: 0 -> 0
formal_output_impact = NONE
```

Review artifact:

```text
docs/PROMPT_40_SHADOW_RUN_7_BINDING_REVIEW.md
```

Validation performed:

- Existing local SQLite Shadow result table was migrated without dropping
  `ShadowRun #7`; `answer_evidence_shadow_results` kept 787 rows.
- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  11 tests.

## 2026-08-26 Prompt 40 Shadow Audit Run

- Executed the real V1.1 Phase 0 Shadow Evidence Chain for Prompt `#40`
  across the six evidence-package Runs:
  `238, 239, 240, 253, 254, 255`.
- Added audit controls for focused Shadow runs:
  - `entity_filter`
  - `max_bindings`
- The controls only limit Shadow audit scope. They do not change the formal
  Citation Decision V1 chain or any formal Benchmark / Gap / Action output.
- Fixed Shadow summary formal-count scope so formal SourceClaim counts are
  project-scoped and formal EvidenceAlignment counts are project + prompt
  scoped.
- Added a regression test proving `entity_filter=小码短链接` does not bind other
  recommended entities in the same run.

Prompt `#40` ShadowRun `#6` result:

```text
answer_unit_count = 216
binding_count = 30
shadow_result_count = 252
shadow_source_claim_count = 222
SUPPORTS = 18
NO_SUPPORT = 234
CONTRADICTS = 0
recommendation_evidence_eligible_count = 18
```

Formal V1 zero-pollution check:

```text
formal SourceClaim: 545 -> 545
formal EvidenceAlignment for Prompt #40: 0 -> 0
PRIMARY_BENCHMARK: 0 -> 0
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 0 -> 0
channel_opportunity_count: 0 -> 0
```

Validation performed:

- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  6 tests.

## 2026-08-26 Prompt 40 Binding Review Gate

- Added a reusable Markdown export script for Shadow Binding review:
  `backend/scripts/export_answer_binding_review.py`.
- Exported `ShadowRun #6` into
  `docs/PROMPT_40_SHADOW_RUN_6_BINDING_REVIEW.md`.
- The review table keeps all 30 machine Binding rows as `待人工审计`; it does
  not pretend machine output is human-approved.
- Added Shadow-only `PROCEDURAL_CONTEXT` so procedure AnswerUnits can be audited
  as procedural source evidence without becoming recommendation reasons.
- Procedure evidence is classified as `PROCEDURAL_EVIDENCE` and does not count
  toward `recommendation_evidence_eligible_count`.

Gate observations:

```text
小码短链接支持长链接快速缩短: Binding 6/6, SUPPORTS 0/6
小码短链接自带点击统计: Binding 6/6, SUPPORTS 6/6
小码短链接自带二维码生成: Binding 6/6, SUPPORTS 0/6
小码短链接自带自定义分享标题: Binding 6/6, SUPPORTS 6/6
小码短链接适合营销场景使用: Binding 6/6, SUPPORTS 0/6
```

Validation performed:

- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  7 tests.

## 2026-08-26 Citation Decision V1.1 Phase 0 Shadow Chain

- Added an audit-only V1.1 Shadow Evidence Chain for recommendation reason
  bridging:
  `AnswerClaim -> AnswerUnit -> AnswerDecisionBinding -> Shadow Passage
  Retrieval -> Shadow SourceClaimJudge -> Shadow EvidenceAlignmentJudge ->
  Shadow Evidence Classification`.
- Added isolated Shadow data models:
  - `AnswerUnit`
  - `AnswerDecisionBinding`
  - `AnswerEvidenceShadowRun`
  - `AnswerEvidenceShadowResult`
- Added backend endpoints:
  - `POST /api/optimization/projects/{project_id}/prompts/{prompt_id}/answer-evidence-shadow/run`
  - `GET /api/optimization/projects/{project_id}/prompts/{prompt_id}/answer-evidence-shadow/latest`
- Preserved the formal production chain. Phase 0 writes no formal
  `SourceClaim` / `EvidenceAlignment` rows and does not change formal
  Benchmark, Source Gap, Priority, Action Route, StrategyCandidate, or
  Experiment output.
- Added rule-based answer-unit atomicization so answer claims such as
  `小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题...`
  become entity-specific ability units instead of a copied full title.
- Added a guarded binding fallback for empty `RecommendationEvent.reasons_json`:
  same-run answer units can become Shadow `DIRECT_REASON` /
  `SUPPORTING_REASON`, while procedure-only units are not treated as
  recommendation reasons.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py` passed:
  5 tests.
- The new tests verify:
  - answer-claim ability extraction for the Prompt `#40` pattern;
  - Shadow SUPPORTS can be recorded through the isolated chain;
  - formal `source_claims` and `evidence_alignments` counts remain unchanged;
  - procedure-style answer units do not bind as recommendation reasons.
  - neutral feature mentions do not bind without a recommendation event;
  - implicit use-case reasons can bind as Shadow supporting reasons.

## 2026-08-26 Prompt 40 Citation Reason Alignment Audit

- Added a handoff audit section to
  `docs/CITATION_OPTIMIZATION_DECISION_V1_AUDIT.md` for Prompt `#40`.
- Documented the current false-negative shape:
  - Decision Market recognizes `小码短链接` as a confirmed competitor
    recommendation across `6/6` Runs;
  - the matching Zhihu source is fetched and marked `CONTENT_VALID`;
  - Golden Case answer claims contain the concrete capability text;
  - but `RecommendationEvent.reasons_json = []`, so reason-driven passage
    retrieval does not create SourceClaims or EvidenceAlignments for that
    source.
- Clarified that `0 Primary / 0 Secondary Benchmark` is mechanically correct
  under the current V1 gates, but product-wise incomplete because answer-claim
  capability text is not bridged back into Recommendation Reasons.
- Recorded the safe fix direction:
  derive missing entity-specific recommendation reasons from same-run
  `AnswerClaim` / `answer_span`, mark them as answer-derived, then rerun the
  existing blind SourceClaim and EvidenceAlignment path.
- Preserved current hard boundaries:
  Citation Prominence, title/entity matching, and legacy `RELATED` must not
  directly upgrade a source into Benchmark support.
- Refined the implementation boundary for V1.1 Phase 0:
  Shadow Run must cover the full isolated evidence path
  `AnswerUnit -> AnswerDecisionBinding -> Shadow Passage Retrieval -> Shadow
  SourceClaimJudge -> Shadow EvidenceAlignmentJudge -> Shadow Audit`, not only
  answer binding.
- Recorded the data-impact boundary:
  Phase 0 must not change any formal Benchmark, Source Gap, Priority, Action
  Route, StrategyCandidate, or Experiment output. Shadow SourceClaims and
  Shadow EvidenceAlignments must be version-isolated, for example with
  `pipeline_version = citation_decision_v1_1_shadow` or an equivalent shadow
  run marker.

Validation performed:

- Read-only local API smoke for Prompt `#40`.
- Read-only local database spot-check for SourceDocument `#345`.
- Documentation-only change; no code path changed.

## 2026-08-25 Single Prompt Citation State Sync

- Fixed a single Prompt `GEO 工作台` state-sync gap where Prompt `#40` could
  already have an Evidence Package and Citation Decision V1 result, while the
  frontend step 4 still displayed `待生成证据包`.
- The `validation` page now loads Evidence Packages just like the execution
  detail page, so the main workflow can see current Prompt package state.
- Citation Decision V1 auto-loading now reacts to the refreshed workflow object,
  not only to `prompt_id` changes. This prevents stale "no package" state from
  surviving after operators generate or supplement evidence for the same Prompt.
- Preserved the existing product chain order:
  `采集样本 -> 答案决策识别 -> 目标品牌事实 -> 引用证据 -> 对标来源 -> 缺口诊断 -> 推荐动作 -> 实验草案`.

Validation performed:

- Prompt `#40` has active Evidence Packages `#15` and `#14`.
- Prompt `#40` Citation Decision V1 resolves to Package `#15` and returns
  `source_count = 68`, `primary_benchmark_count = 0`,
  `secondary_benchmark_count = 0`, and `recommended_action_count = 0`.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Browser-first Citation Refetch

- Upgraded Golden Case citation document refetch from "Playwright if the default
  browser exists, otherwise urllib" to a browser-first acquisition path.
- Source refetch now searches for the same local Chrome / Chromium executables
  used by browser collection instead of depending only on Playwright's default
  headless-shell path.
- Added a persistent visible-browser fallback for evidence refetch when
  headless launch fails on macOS. This matches the collection-side behavior more
  closely and avoids silently falling back to Python DNS / SSL behavior.
- Browser refetch now uses:
  - real Chrome user agent;
  - `ignore_https_errors = true`;
  - `domcontentloaded` as the primary wait condition;
  - best-effort `networkidle`;
  - HTML-to-text fallback when visible body text is too short.
- Failure reasons now preserve both browser failure and HTTP fallback failure
  when both paths fail.
- Live validation against `https://m.suolink.cn/` changed from Python DNS
  failure to browser success:
  - `fetch_status = SUCCESS`;
  - title captured;
  - clean text length = 1328.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_source_qualification.py` passed.
- Live browser refetch smoke for `https://m.suolink.cn/` passed.
- `git diff --check` passed.

## 2026-08-25 Single Prompt Citation Evidence Entry

- Corrected the single Prompt `GEO 工作台` step 4 entry:
  `引用证据` now routes operators to `证据标注`, where they can acquire
  citation page bodies, manually supplement missing body text, and inspect
  evidence alignment.
- Kept `引用资料` as a ranking / source-structure inspection page only. It is
  no longer the primary operation target for the main workflow citation
  evidence step.
- Preserved the integrated main chain order:
  `采集样本 -> 答案决策识别 -> 目标品牌事实 -> 引用证据 -> 对标来源 -> 缺口诊断 -> 推荐动作 -> 实验草案`.
- Localized the step-4 operator copy so the card describes the actual work:
  `查看/补录正文`, not generic source ranking.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Workflow State Integrity Guard

- Added a strict context identity to Citation Optimization Decision V1 responses:
  `project_id`, `prompt_id`, `evidence_package_id`,
  `analysis_version`, and `source_run_ids`.
- Hardened the single Prompt frontend workflow so Citation Decision data is only
  consumed when it belongs to the current Prompt; stale responses are discarded
  and Prompt switches clear Prompt-scoped proposal, benchmark, channel, action,
  experiment, and Citation Decision state before reloading.
- Corrected the answer-decision gate:
  `event_review = done` only means there are no pending human review items; it
  does not mean the Prompt has valid answer decision semantics. The workflow now
  requires `answer_semantic.done = true` before Product Truth, Citation
  Evidence, Benchmark, Gap, Action, or Experiment can advance.
- Reordered the single Prompt `GEO 工作台` into the product chain:
  `采集样本 -> 答案决策识别 -> 目标品牌事实 -> 引用证据 -> 对标来源 -> 缺口诊断 -> 推荐动作 -> 实验草案`.
- Separated current Citation V1 analysis from historical execution records:
  legacy `continueResult` may be shown as history, but it no longer marks
  current Citation Evidence, Benchmark, Gap, Action, or Experiment steps as
  completed.
- Preserved zero-result semantics:
  no Evidence Package stays `待生成证据包`; zero Primary/Secondary Benchmark is a
  valid completed benchmark judgment; `UNKNOWN` gaps require human judgment and
  do not become confirmable actions.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m pytest tests/test_source_gap_v1.py tests/test_citation_prominence_v1.py tests/test_gap_action.py`
  passed: 31 tests.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.
- Live API smoke:
  - Prompt `#40` workflow status still belongs to Prompt `#40`;
  - Prompt `#40` Citation Decision fails closed with
    `当前 Prompt 尚无 Evidence Package，不能生成纵向闭环 Proposal`;
  - Prompt `#19` Citation Decision returns `context_identity` bound to Prompt
    `#19` and Evidence Package `#12`.

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

## 2026-08-24 Citation Optimization Decision V1 Step 0/1

- Added `docs/CITATION_OPTIMIZATION_DECISION_V1_AUDIT.md` as the pre-implementation
  entity/API reuse map.
- Locked the V1 constraints before code changes:
  - `SourceClaimJudge` remains blind; answer reasons can guide passage retrieval
    but cannot define source truth;
  - legacy `RELATED` must not be upgraded to `PARTIAL_SUPPORT` without re-judge;
  - legacy `source_score` remains compatibility-only and must not drive new
    benchmark, priority, strategy, or experiment decisions.
- Added `citation_prominence_level` to source analysis output.
- Source analysis sorting now uses citation prominence, citation coverage,
  citation frequency, and reference position before legacy score.
- Kept `source_score` as a deprecated compatibility field and exposed
  `legacy_source_score` plus `source_score_deprecated`.
- Updated the Citation Ranking V0 frontend copy to label raw scores as legacy
  diagnostic scores, not strategy decision signals.
- Added V1 content status mapping on existing `SourceDocument` data:
  - `CONTENT_VALID`;
  - `CONTENT_PENDING`;
  - `CONTENT_UNAVAILABLE`;
  - `CONTENT_INVALID`.
- Golden Case document API now returns content status labels/reasons.
- Manual document capture now rejects blank non-empty-page submissions; empty
  pages must be explicitly marked as `MANUAL_EMPTY`.
- Added compatibility mapping for evidence alignment relations:
  legacy `RELATED` maps to `LEGACY_RELATED`, not `PARTIAL_SUPPORT`.
- Ran Step 0-3 live acceptance on Project `#3` / Prompt `#43`:
  - source analysis returned 83 rows sorted by citation prominence;
  - sampled prominence breakdowns only included citation behavior fields;
  - Prompt `#43` had both `CONTENT_VALID` and `CONTENT_UNAVAILABLE` source
    documents, and analysis remained available for valid documents;
  - EvidenceAlignment rows for Prompt `#43` all mapped `RELATED` to
    `LEGACY_RELATED`, with no `PARTIAL_SUPPORT` upgrade.
- Representative source payload now includes `citation_prominence_level` and
  keeps legacy score fields explicitly marked as deprecated.
- Updated product and loop specs so `source_score` is no longer documented as
  the V1 source analysis sort or decision signal.

Validation performed:

- `.venv/bin/python -m pytest tests/test_citation_prominence_v1.py tests/test_gap_action.py`
  passed: 4 tests.
- `.venv/bin/python -m pytest tests/test_source_qualification.py tests/test_golden_case_api.py tests/test_citation_prominence_v1.py`
  passed: 19 tests.
- `.venv/bin/python -m pytest tests/test_evidence_alignment.py` passed: 7 tests.
- Live smoke for blank manual document capture rejected empty non-empty-page
  payloads with HTTP 400.
- Live smoke for manual empty page produced `MANUAL_EMPTY`,
  `CONTENT_UNAVAILABLE`, zero blocks, zero SourceClaims, and zero Alignments;
  temporary smoke data was removed.

## 2026-08-24 Citation Optimization Decision V1 Step 4A

- Froze Step 0-3 as the Foundation Semantic Layer.
- Added Step 4A derived fields to source analysis without creating new tables:
  - `decision_support_level`;
  - `has_contradiction`;
  - `benchmark_tier`;
  - supporting / contradicting alignment ids and basis fields.
- Decision Support aggregation only reads V1 `EvidenceAlignment` rows with
  `SUPPORTS` / `CONTRADICTS`; historical `RELATED` stays excluded and cannot
  become support semantics.
- Benchmark Tier rules are deterministic:
  - invalid or unavailable content -> `NOT_EVALUABLE`;
  - direct support for recommendation/candidate decision -> `PRIMARY_BENCHMARK`;
  - fact-only or partial decision support -> `SECONDARY_BENCHMARK`;
  - valid but unsupported/tangential sources -> `REFERENCE_ONLY`.
- `citation_prominence_level` is now only a same-tier sort signal and cannot
  upgrade a source to Benchmark.
- Step 4B remains explicitly not started: no Source Gap, Priority, Action Route,
  StrategyCandidate, or Experiment behavior was added.
- Prompt `#43` live smoke after Step 4A:
  - 6 runs, 204 references, 284 retrieval candidates, 83 source rows;
  - existing alignments were `RELATED x 1440`;
  - output was `REFERENCE_ONLY x 2`, `NOT_EVALUABLE x 81`;
  - all rows had `decision_support_level = NONE`;
  - `PRIMARY_BENCHMARK = 0`, which is accepted as the correct result.

Validation performed:

- `.venv/bin/python -m pytest tests/test_citation_prominence_v1.py` passed:
  8 tests.
- `.venv/bin/python -m pytest tests/test_citation_prominence_v1.py tests/test_source_qualification.py tests/test_evidence_alignment.py tests/test_golden_case_api.py tests/test_recommendation_intelligence.py tests/test_gap_action.py`
  passed: 63 tests.

## 2026-08-25 Citation Optimization Decision V1 Step 4B-1

- Froze Step 4A as the Benchmark Decision Layer.
- Added Source Gap as source-analysis derived fields only:
  - `source_gap_type`;
  - `source_gap_precondition`;
  - `matched_product_truth_status`;
  - `existing_asset_status`;
  - `existing_asset_coverage`.
- Source Gap inputs are strictly limited to:
  - Primary/Secondary Benchmark Evidence;
  - `TargetBrandCapabilityTruth`;
  - existing brand asset content from successful `PageSnapshot` rows.
- Source Gap outputs are limited to:
  - `CONTENT_GAP`;
  - `EVIDENCE_GAP`;
  - `PRODUCT_GAP`;
  - `NO_GAP`;
  - `UNKNOWN`.
- Kept Step 4B-3 out of scope: no Recommended Action, Channel Opportunity,
  StrategyCandidate, or Experiment behavior was added.
- Prompt `#43` live smoke after Step 4B-1:
  - 83 source rows;
  - `PRIMARY_BENCHMARK = 0`;
  - eligible benchmark count = 0;
  - all rows returned `source_gap_type = null`;
  - all rows returned `source_gap_precondition = NO_ELIGIBLE_BENCHMARK`.
- Corrected the source gap semantics so "not eligible for Gap Analysis" is not
  represented as `UNKNOWN`. `UNKNOWN` is now reserved for eligible benchmark
  rows whose Product Truth, Brand Asset, or Benchmark Evidence is insufficient.
- Added deterministic Step 4B-2 `priority_level` and `action_route` fields:
  - Primary + actionable gap -> `PRIORITY_HIGH`;
  - Secondary + actionable gap -> `PRIORITY_MEDIUM`;
  - `NO_GAP` -> `NOT_PRIORITY + NO_ACTION`;
  - eligible Benchmark + `UNKNOWN` -> `UNRESOLVED + UNRESOLVED`;
  - `REFERENCE_ONLY` -> `NOT_PRIORITY + null`;
  - `NOT_EVALUABLE` -> `null + null`.
- Prompt `#43` live smoke after Step 4B-2:
  - `priority_level = NOT_PRIORITY x 2, null x 81`;
  - `action_route = null x 83`;
  - no `PRIORITY_HIGH` / `PRIORITY_MEDIUM`;
  - no CONTENT / EVIDENCE / PRODUCT route.

Validation performed:

- `.venv/bin/python -m pytest tests/test_source_gap_v1.py` passed: 15 tests.

## 2026-08-25 Citation Optimization Decision V1 Vertical Slice

- Switched from step-by-step field discussion to the V1 vertical slice:
  `Source Analysis -> Recommended Action -> Channel Opportunity -> Human
  Confirmation -> StrategyCandidate -> InterventionPlan -> Experiment Draft ->
  Fixed Retest / Recommendation Outcome`.
- Added proposal-only row fields:
  - `recommended_action`;
  - `channel_opportunity`.
- Added read/confirm service and API endpoints:
  - `GET /api/optimization/projects/{project_id}/prompts/{prompt_id}/citation-decision-v1`;
  - `POST /api/optimization/projects/{project_id}/prompts/{prompt_id}/citation-decision-v1/confirm`.
- Confirmation records a workflow confirmation, creates/updates an
  `InterventionPlan`, creates validated `StrategyCandidate` rows, and reuses
  the existing `strategy_to_experiment_plan()` materialization path.
- Kept hard strategy boundaries:
  - `REFERENCE_ONLY`, `NOT_EVALUABLE`, `LEGACY_RELATED`, and Citation
    Prominence alone do not generate actions;
  - `PRODUCT_GAP` remains a product finding and does not create external
    content experiments;
  - release/retest/conclusion gates remain unchanged.
- Added Recommendation Outcome to experiment analysis:
  candidate, recommendation, target reason, and citation before/after.
- Real DB read-only smoke:
  - Prompt `#43` has no Evidence Package and fails closed.
  - Prompt `#9` / Package `#13`: 0 Primary Benchmark, 0 actions.
  - Prompt `#19` / Package `#12`: 2 Primary Benchmarks, 0 actions because
    downstream Product Truth / Brand Asset / Source Gap gates still block.
  - Prompt `#16` / Package `#11`: 0 Primary Benchmark, 0 actions.

Validation performed:

- `.venv/bin/python -m pytest tests/test_source_gap_v1.py` passed: 17 tests.
- `.venv/bin/python -m pytest tests/test_source_gap_v1.py tests/test_citation_prominence_v1.py tests/test_source_qualification.py tests/test_evidence_alignment.py tests/test_golden_case_api.py tests/test_recommendation_intelligence.py tests/test_gap_action.py`
  passed: 80 tests.

## 2026-08-25 Single Prompt Main Workflow Integration Correction

- Corrected a frontend regression where Citation Decision V1 was rendered as a
  separate module-like panel inside the single Prompt monitoring page.
- Removed that standalone monitoring-page panel and folded its state into the
  single `GEO 工作台` workflow row:
  `采集样本 -> 决策诊断 -> 引用证据 -> 对标来源 -> 目标品牌事实 -> 推荐动作 -> 实验草案`.
- Kept detailed source analysis, product-fact supplementation, and action
  confirmation in the execution-strategy detail page, instead of creating a
  competing homepage module.
- Localized the affected user-facing labels and workflow actions so operators
  see Chinese wording rather than internal enum terms.
- Clarified the main-page action button behavior: when no confirmable
  recommendation action exists, the button is disabled and the user is routed to
  the detail page to supplement target-brand facts or inspect strategy details.

Validation performed:

- Frontend `npm run build` passed.
- `git diff --check` passed.

## 2026-08-25 Prompt 40 Review Queue Dead-Loop Fix

- Fixed a workflow review dead loop reproduced on Prompt `#40`:
  - `/workflow/3/40/status` reported `pending_review_steps = 1`;
  - `/workflow/3/40/review-queue` returned no `unique_events` and no
    `alignments`;
  - the frontend therefore kept showing "开始审核" while the review modal only
    showed "全部审核完成".
- Root cause:
  - workflow status counted all `RecommendationEvent` rows in the review
    denominator;
  - review queue only returned pending machine-reviewable events;
  - Prompt `#40` had 24 `RecommendationEvent` rows with
    `review_status = VALIDATION_FAILED`, which should not enter human review.
- Corrected the backend review denominator:
  - only `MACHINE_GROUNDED`, `MACHINE_CANDIDATE`, `HUMAN_CONFIRMED`, and
    `HUMAN_REJECTED` events are counted as reviewable;
  - `VALIDATION_FAILED` events remain analysis diagnostics and no longer block
    the workflow.
- Added a frontend guard so an empty ready review queue refreshes the main
  workflow status and closes the review modal instead of trapping the operator
  in an empty audit loop.
- Localized the workflow status step labels/details touched by this path:
  `证据分析`, `证据人工确认`, `缺口诊断`, `动作候选`, and experiment-entry copy.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Live API smoke for Prompt `#40` returned `pending_review_steps = 0` and
  `all_reviews_done = true`; `/continue` no longer blocked on review.

## 2026-08-25 Unresolved Decision Evidence Review Context

- Added explicit human-verification context when workflow continuation returns
  `UNRESOLVED` Gap / Action.
- `/workflow/{project_id}/{prompt_id}/continue` now returns `review_context`
  with:
  - sampled raw answer excerpts by Run / Sample;
  - machine event diagnostics, including validation-failed recommendation
    events;
  - event review-status counts;
  - an instruction telling operators to fix missed recommendation events in
    diagnosis before overriding the decision.
- Updated the single Prompt workflow UI so the manual decision area lists the
  answer samples and machine event diagnostics before showing "按此方向继续" or
  "标记搁置并结束".
- Kept the action override path human-only; the added context is audit evidence,
  not an automatic strategy decision.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py tests/test_gap_action.py`
  passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed.
- `git diff --check` passed.

## 2026-08-25 Workflow Conclusion Evidence Drawer

- Refined the single Prompt workflow interaction for `UNRESOLVED` Gap / Action:
  evidence is now attached to each conclusion through a Chinese "查看依据"
  button instead of being rendered as a large inline debug block.
- Added a right-side evidence drawer that shows:
  - the current Gap and Action conclusions;
  - raw answer samples for manual verification;
  - machine-recognized recommendation events and their Chinese review-status
    labels.
- Kept the manual decision controls in the main workflow, but made the required
  verification path explicit: operators can inspect answers first, then decide
  whether to override, shelve, or return to diagnosis to correct missed events.
- Preserved the product boundary that Citation Decision V1 belongs inside the
  single Prompt main workflow, not as a standalone homepage module.
- Localized the affected Gap / Action / confidence tags so users see labels
  such as "待确认" and "低置信" instead of raw enum values.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Competitor-First Review Evidence Clarification

- Clarified the single Prompt evidence wording:
  - "目标品牌出现" means the project brand itself appeared in the answer;
  - competitor and other answer entities are shown separately as answer object
    clues.
- Extended `/workflow/{project_id}/{prompt_id}/continue` review context so each
  answer sample can carry detected entities classified as:
  - target brand;
  - confirmed competitor;
  - unconfirmed object.
- Fixed the human review modal load behavior:
  - competitor candidates are now treated as pending review items;
  - the modal no longer auto-closes as "no pending review" when the event and
    alignment queues are empty but competitor candidates still need review.
- Updated the review instruction order to tell operators to confirm competitor /
  candidate objects before reviewing AI statements and evidence relations.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Single Prompt Workflow Card UX

- Reworked the single Prompt `GEO 工作台` workflow from a compact status-label
  row into actionable workflow cards.
- Each step now shows:
  - Chinese step status;
  - business detail for the current Prompt;
  - the next available operation, such as viewing runs, starting review,
    continuing analysis, running citation evidence, supplementing product
    truth, viewing evidence, or confirming actions.
- Corrected the citation step semantics:
  - not-yet-run citation evidence now appears as "待运行" / "运行引用证据";
  - a failed run is shown as a retryable current step instead of mixing
    "异常" with "等待运行".
- Kept Citation Decision V1 inside the single Prompt workflow and preserved
  detail pages only for deeper inspection.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Decision Recognition Repair Entry

- Fixed the Prompt `#40` correction dead end where "去修正诊断" led to the
  decision diagnosis page, but "进入审核" opened an empty review queue and
  immediately closed as "全部审核完成".
- Added a dedicated answer-decision repair action for Decision Market entities:
  operators can mark an unknown answer object as target brand, confirmed
  competitor, or not part of the decision.
- Repairing an entity updates the matching `RecommendationEvent` rows:
  - target brand / confirmed competitor -> `HUMAN_CONFIRMED`;
  - rejected object -> `HUMAN_REJECTED`.
- Tightened workflow semantics so `HUMAN_REJECTED` events no longer count as
  valid answer-decision events. This prevents "not a brand/object" corrections
  from advancing Product Truth, Citation Evidence, Gap, Action, or Experiment.
- Split the workflow gates explicitly:
  - `all_reviews_done` means the current human review queue is empty;
  - `ready_to_continue` means answer decision recognition and downstream
    prerequisites are valid enough to generate Gap / Action.
- Localized the Decision Market table labels and actions in the single Prompt
  decision diagnosis page; raw enum values such as `RECOMMENDATION` and
  `UNKNOWN_ENTITY` are no longer the primary operator-facing labels.

Validation performed:

- `.venv/bin/python -m pytest tests/test_workflow_review_queue.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Citation URL WWW Normalization

- Removed the legacy source acquisition rule that blindly prefixed `www.` to
  known platform domains before fetching citation documents.
- Preserved explicit `www.` when it is already present in the URL, but no longer
  turns platform subdomains such as `zhuanlan.zhihu.com`,
  `baijiahao.baidu.com`, or `jingyan.baidu.com` into invalid
  `www.<subdomain>` hosts.
- Canonicalized acquired source URLs for analysis storage while keeping raw
  observed URLs available as `original_url`.
- Updated citation-facing frontend tables to display normalized source URLs /
  domains and keep the original href for audit-safe clicking.
- Clarified Golden Case citation acquisition UX:
  - batch "抓取引用资料" only acquires citation pages that have not yet been
    stored;
  - row-level "重抓" always re-fetches the selected failed source and updates
    its status, canonical URL, domain, fetch time, content hash, and failure
    reason.
- Added frontend failure reason summaries so operators can decide whether a
  failed source should be retried or manually supplemented.
- Added `action_url` to Golden Case source document reads and switched citation
  links, manual supplementation defaults, and row-level refetch payloads to use
  normalized action URLs instead of raw `url` values. Raw URL remains available
  for audit, but it no longer drives default operator actions.
- Added regression tests for platform subdomain handling and inner-`www`
  domains such as `gjzwfw.www.gov.cn`.

Validation performed:

- `.venv/bin/python -m pytest tests/test_source_qualification.py` passed.
- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.

## 2026-08-25 Citation Refetch Row Status Feedback

- Kept Golden Case source refetch as a background browser-first operation
  instead of relying on a visible browser window as the operator feedback.
- Added backend `fetch_method` to row-level refetch responses so the frontend
  can explain whether the latest attempt used browser capture or HTTP fallback.
- Added row-level frontend feedback for citation source refetch:
  - the selected row immediately shows `重抓中`;
  - the button enters loading state and is disabled during the request;
  - the row records the latest refetch result,正文长度,抓取方式, and failure
    summary after completion.
- Extended the row-level `重抓` entry to all non-valid source documents except
  manually marked empty pages, so `PARTIAL` / invalid short-body sources can be
  retried without manual API calls.
- This is an interaction-state fix only. It does not alter the single Prompt
  main workflow order or create a new Citation module.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.

## 2026-08-25 Single Prompt Citation Evidence Run Entry

- Fixed the single Prompt workflow card getting stuck at step 4 (`引用证据`)
  after citation bodies had already been captured or manually supplemented.
- Root cause:
  - Citation Decision V1 correctly failed closed when Prompt `#40` had no
    `OptimizationEvidencePackage`;
  - the step 4 card only routed operators to `证据标注` for body capture and did
    not expose the next required operation: creating the current Prompt evidence
    package and running the citation decision chain.
- Added a dedicated frontend action for step 4:
  - current Prompt valid Runs -> create/reuse `OptimizationEvidencePackage`;
  - run Citation Decision V1 against that package;
  - refresh the workflow and keep the Citation Decision result bound to the
    current Prompt.
- Updated the step 4 copy:
  - no package -> `待生成证据包` / `生成证据包`;
  - loaded Citation Decision -> `已完成` / `查看证据正文`;
  - failed chain -> retry by regenerating/rerunning citation evidence.
- This keeps the existing 8-step single Prompt chain unchanged and only fixes a
  missing operation entry inside step 4.

Validation performed:

- Frontend `npm run build` passed with the existing Vite chunk-size warning.
- `git diff --check` passed.
- Prompt `#40` live smoke:
  - created Evidence Package `#15` from Runs `238,239,240,253,254,255`;
  - Citation Decision V1 returned `evidence_package_id = 15`;
  - summary returned `source_count = 68`, `primary_benchmark_count = 0`,
    `secondary_benchmark_count = 0`, and `recommended_action_count = 0`.

## 2026-08-26 Citation Decision V1.1 Phase 1 Formal Input Switch

- Added a guarded Phase 1 input switch for the formal Evidence Chain.
- Default remains off:
  - `citation_decision_v1_1_formal_input_enabled = false`
  - workflow/API callers must explicitly pass `use_answer_binding_v1_1 = true`
    or enable the env setting for a small-scope run.
- When enabled, formal Passage Retrieval and EvidenceAlignment can consume
  Phase 0 audited `AnswerUnit + AnswerDecisionBinding` rows as answer-derived
  recommendation reason inputs.
- The formal chain still does not consume `AnswerEvidenceShadowResult`
  directly. Shadow SUPPORTS cannot be promoted into Benchmark by itself.
- The old `RecommendationEvent.reasons_json` path remains active as fallback.
- Formal `EvidenceAlignment.machine_payload_json` now records reason
  provenance for Phase 1-derived rows:
  - `reason_source = ANSWER_DECISION_BINDING`
  - `formal_input_version = citation_decision_v1_1_formal_input.v1`
  - `answer_unit_id`
  - `decision_binding_id`
- This change does not alter the single Prompt workflow order, Product Truth
  gate, Benchmark rules, Gap rules, Action rules, StrategyCandidate creation,
  or Experiment creation.

Validation performed:

- `.venv/bin/python -m compileall app` passed.
- `.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py tests/test_evidence_alignment.py tests/test_source_claim.py` passed:
  `24 passed`.
- Prompt `#40` Phase 1 smoke:
  - Stage 3 with `--use-answer-binding-v1-1` read `ShadowRun #7`
    `AnswerDecisionBinding` rows and produced `5` unique answer-derived
    reasons from `30` binding candidates.
  - Fixed the formal content gate so sources with valid captured body but no
    `SourceQuality` row can still be treated through `derive_content_status`;
    this allowed SourceDocument `#345` to enter retrieval candidates.
  - Stage 4 created `32` formal `SourceClaim` rows from `13` unique passages;
    `4` passages failed due DeepSeek network `ConnectError`, while successful
    grounded claims were committed.
  - Stage 5 was rerun with `--doc-id-filter 345` after fixing the script
    parameter pass-through. It created `110` formal alignments for SourceDocument
    `#345`: `6 SUPPORTS`, `5 NONE`, `99 RELATED`.
  - `Citation Decision V1` for Prompt `#40` / Evidence Package `#15` naturally
    advanced to `READY_FOR_HUMAN_CONFIRM` with `1` Primary Benchmark and `1`
    recommended action.
  - The recommended action exists only because formal
    `EvidenceAlignment.relation = SUPPORTS` was written; Shadow SUPPORTS was
    not consumed directly.
- Replaced user-facing `Benchmark` copy in the activated action/gap path with
  Chinese labels such as `对标来源` / `对标证据`; internal enum names remain
  unchanged.

## 2026-08-27 Citation Decision V1.1 Phase 1.1 Closure

- Closed the Phase 1.1 blockers before any Phase 2 multi-Prompt expansion.
- Fixed formal multi-Run evidence preservation:
  - formal `EvidenceAlignment` still deduplicates semantic reason judging for
    efficiency;
  - each Run/Binding observation is now written as an explicit formal alignment
    row;
  - V1.1-derived alignment payload records `observed_run_ids`,
    `observed_event_ids`, `observed_answer_unit_ids`,
    `observed_decision_binding_ids`, `run_coverage_count`, and
    `run_coverage_denominator`.
- Upgraded `use_answer_binding_v1_1` into a true read/write isolation switch:
  - when disabled, formal generation does not consume Answer Binding inputs;
  - Citation Decision read path also ignores existing formal rows marked
    `reason_source = ANSWER_DECISION_BINDING` or
    `formal_input_version = citation_decision_v1_1_formal_input.v1`;
  - existing DB rows are kept for audit and rollback.
- Fixed the runner/Layer3 interface drift:
  - `run_reason_driven_retrieval(..., doc_id_filter=...)` is now a real
    supported parameter;
  - `run_source_claim_extraction` and `run_evidence_alignment` pass the same
    document scope through the chain.
- Added capability-level Product Truth gating for action generation:
  - Benchmark evidence from `AnswerUnit` now produces concrete
    `capability_truth_targets`;
  - broad facts such as `短链生成` no longer allow actions for finer abilities
    such as `点击统计` or `自定义分享标题`;
  - unmatched concrete abilities keep Source Gap at `UNKNOWN`, Priority at
    `UNRESOLVED`, and block recommended actions.
- Updated Citation Decision summary copy so it distinguishes:
  - no eligible Benchmark;
  - eligible Benchmark present but execution gates are not satisfied;
  - recommended actions available for human confirmation.
- This change does not alter the single Prompt workflow order and does not
  start Phase 2.

Validation performed:

- `.venv/bin/python -m compileall -q app` passed.
- `.venv/bin/python -m pytest -q tests/test_answer_evidence_shadow.py tests/test_source_gap_v1.py` passed:
  `39 passed`.
- `.venv/bin/python -m pytest -q tests/test_evidence_alignment.py tests/test_source_claim.py` passed:
  `11 passed`.
- Prompt `#40` Phase 1.1 formal rerun:
  - command:
    `.venv/bin/python scripts/run_single_case_evidence.py --project-id 3 --prompt-id 40 --run-ids 238,239,240,253,254,255 --stage 5 --use-answer-binding-v1-1 --doc-id-filter 345`
  - `unique_reasons = 5`
  - `reason_observations = 30`
  - `answer_binding_candidates = 30`
  - `alignments_created = 300`
  - `judge_calls = 50`
  - `errors = []`
- Prompt `#40` post-rerun audit:
  - formal `EvidenceAlignment` for Prompt `#40` = `660`;
  - `SUPPORTS = 36`, distributed evenly across Runs
    `238,239,240,253,254,255`;
  - V1.1 OFF -> `0` Primary Benchmark and `0` recommended actions;
  - V1.1 ON -> `1` Primary Benchmark and `0` recommended actions because
    concrete Product Truth is missing for `点击统计`, `自定义分享标题`,
    and `营销场景使用`;
  - V1.1 OFF again -> restored to `0` Primary Benchmark and `0` recommended
    actions without deleting DB rows.

## 2026-08-27 Citation Decision V1.1 Phase 2A Lineage Eligibility

- Entered Phase 2A after Phase 0/1 checkpoint approval. Scope was limited to
  formal `EvidenceAlignment` Run lineage, consistency validation, and V1
  consumption eligibility.
- Corrected Source of Truth wording:
  - `SourceDocument` and `SourceClaim` are document-level facts and can be
    reused across Runs;
  - Run lineage is proven through current Run `ReferenceSource` plus
    `AnswerUnit` / `AnswerDecisionBinding` / `RecommendationEvent`;
  - `SourceClaim` must not be forced to carry `run_id`, and
    `EvidenceAlignment.run_id` alone is not sufficient.
- Added centralized formal eligibility validation in
  `app/modules/optimization/evidence_lineage.py`.
  - validates package Run membership, AnswerUnit lineage,
    AnswerDecisionBinding lineage, RecommendationEvent lineage,
    SourceDocument/SourceClaim consistency, current Run ReferenceSource proof,
    Legacy relation exclusion, and V1.1 feature-flag read gating;
  - returns `eligible_for_v1`, `ineligibility_reasons`, and the proving
    `reference_source_id`.
- Connected eligibility to the formal
  `source_analysis -> _attach_decision_support_benchmarks ->
  _decision_support_by_doc_id` read path.
  - only eligible alignments enter SUPPORTS/CONTRADICTS statistics,
    Decision Support, Benchmark, Gap, Priority/Action, and StrategyCandidate
    benchmark evidence;
  - ineligible historical rows are kept and surfaced as
    `ineligible_alignment_counts`.
- Tightened `observed_run_ids` discipline:
  - prompt-level evidence coverage is now derived from the unique `run_id` set
    of eligible SUPPORTS rows;
  - payload-provided `observed_run_ids` is not trusted for formal coverage.
- Added `backend/tests/test_evidence_lineage_v1.py` covering:
  - same SourceDocument cited by two Runs with one reusable SourceClaim;
  - current Run not citing the document;
  - AnswerUnit/RecommendationEvent cross-Run mismatch;
  - non-empty `run_id` without matching ReferenceSource;
  - Legacy Alignment exclusion;
  - observed_run_ids derived only from eligible Runs;
  - no duplicate SourceClaim required for Run lineage.
- Added a reusable read-only audit script:
  `backend/scripts/audit_prompt40_phase2a_lineage.py`.
- Added checkpoint/audit docs:
  - `docs/CITATION_DECISION_V1_1_PHASE2A_LINEAGE_CHECKPOINT.md`
  - `docs/PROMPT_40_PHASE2A_LINEAGE_AUDIT.md`
- No migration is required: all checks use existing DB columns and existing
  V1.1 payload fields.
- Phase 2A explicitly did not implement `DISCOVERABILITY_GAP`, Step 7, Step 8,
  Decision Stability, frontend masking, or Citation/Benchmark scoring changes.

Validation performed:

- `.venv/bin/python -m pytest -q tests/test_evidence_lineage_v1.py tests/test_citation_prominence_v1.py tests/test_source_gap_v1.py`
  passed: `38 passed`.
- `.venv/bin/python scripts/audit_prompt40_phase2a_lineage.py --output ../docs/PROMPT_40_PHASE2A_LINEAGE_AUDIT.md`
  passed.
- Prompt `#40` Phase 2A audit:
  - `source_run_ids = [238, 239, 240, 253, 254, 255]`;
  - formal `SourceClaim` count stayed `577 -> 577`;
  - Prompt `#40` formal `EvidenceAlignment` count stayed `660 -> 660`;
  - each Run has `6` eligible SUPPORTS and `5` eligible NO_SUPPORT;
  - historical `RELATED` alignments are excluded as
    `LEGACY_RELATION_ONLY = 594`;
  - prompt-level observed run coverage is derived as
    `[238, 239, 240, 253, 254, 255]`, `6/6`.

## 2026-08-27 Citation Decision V1.1 Phase 2B Capability Gap Diagnosis

- Entered Phase 2B after Phase 2A checkpoint. Scope was limited to
  capability/reason-level Gap Diagnosis.
- Implemented the deterministic earliest-failure decision tree:
  `Product Truth -> Relevant Asset Expression -> RetrievalCandidate ->
  Evidence Adoption`.
  - Product Truth is checked at capability/reason granularity before any
    asset, retrieval, or adoption logic can decide the Gap.
  - Relevant Brand Asset is selected from existing `PageSnapshot` rows by
    capability/prompt/benchmark relevance and records an audit snapshot
    (`selected_snapshot_id`, URL, title, matched terms, candidate IDs).
  - Discoverability only uses valid `RetrievalCandidate` rows from eligible
    evidence observed Runs.
  - Evidence Adoption only uses current package `ReferenceSource` plus existing
    `DecisionEvidenceAdoption` context, and keeps the causal-boundary note.
- Reused existing `source_gap_type`, `source_gap_precondition`,
  Product Truth, `PageSnapshot`, `RetrievalCandidate`, and
  `DecisionEvidenceAdoption` structures.
  - Added only derived payload fields on source analysis:
    `capability_gap_layer`, `capability_gap_diagnosis`,
    `relevant_asset_snapshot`, `retrieval_candidate_context`, and
    `evidence_adoption_context`.
  - Added the minimal `source_gap_type` value `DISCOVERABILITY_GAP`; it is not
    mapped to Step 7 in this phase.
- Kept Phase 2A lineage as the evidence gate:
  only eligible `EvidenceAlignment` rows can produce Benchmark Evidence for
  this Gap layer.
- Added/updated tests in `backend/tests/test_source_gap_v1.py` for:
  - stopping at Product Truth before later layers;
  - stopping at Relevant Asset Expression before retrieval/adoption;
  - valid Retrieval-only Discoverability;
  - retrieved-but-not-adopted Evidence Gap;
  - `NO_GAP` requiring both retrieval and adoption context.
- Added a read-only #40 regression script:
  `backend/scripts/audit_prompt40_phase2b_gap.py`.
- Added checkpoint/audit docs:
  - `docs/CITATION_DECISION_V1_1_PHASE2B_GAP_CHECKPOINT.md`
  - `docs/PROMPT_40_PHASE2B_CAPABILITY_GAP_AUDIT.md`
- No migration is required: the new outputs are derived API payload fields.
- Phase 2B explicitly did not develop Step 7, Step 8, Decision Stability,
  frontend masking, or Citation/Benchmark scoring changes.

Validation performed:

- `.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase2b_gap.py`
  passed.
- `.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py`
  passed: `35 passed`.
- `.venv/bin/python scripts/audit_prompt40_phase2b_gap.py --output ../docs/PROMPT_40_PHASE2B_CAPABILITY_GAP_AUDIT.md`
  passed.
- Prompt `#40` Phase 2B audit:
  - `PRIMARY_BENCHMARK = 1`, `SECONDARY_BENCHMARK = 0`;
  - benchmark `SourceDocument #345` is diagnosed as `CONTENT_GAP`;
  - earliest failure layer is `RELEVANT_ASSET_EXPRESSION`;
  - matched Product Truth status is `TRUE`;
  - relevant asset snapshot is `PageSnapshot #3`;
  - asset coverage is `MISSING`;
  - Retrieval context is `RETRIEVED`;
  - Evidence Adoption context is `NOT_ADOPTED`;
  - formal `SourceClaim` stayed `577 -> 577`;
  - Prompt `#40` formal `EvidenceAlignment` stayed `660 -> 660`.

## 2026-08-27 Citation Decision V1.1 Phase 3 StrategyCandidate Gate

- Entered Phase 3 after Phase 2B checkpoint approval. Scope was limited to
  Step 7: `StrategyCandidate + Human Strategy Review`.
- Audited current Gap scope:
  - `source_gap_type` remains a source-analysis compatibility/display field;
  - formal Step 7 consumption now uses derived `capability_gap_items`, so a
    Benchmark Source with multiple capability/reason gaps does not collapse
    into one natural-language source-level conclusion.
- Reused existing `OptimizationStrategyCandidate` and `effective_payload`
  infrastructure; no parallel Strategy table was added.
- Changed `confirm_citation_decision_vertical_slice` behavior:
  - creates pending `OptimizationStrategyCandidate` rows only;
  - ignores legacy `create_experiments=true` for this path;
  - no longer creates `InterventionPlan`, `OptimizationAction`, or
    `OptimizationExperiment`.
- Changed machine-generated vertical StrategyCandidates:
  - `review_status = PENDING_REVIEW`;
  - `effective_payload = {}`;
  - `effective_validation_status = PENDING`;
  - `experiment_id = null`.
- Added capability/reason-level Strategy payload fields:
  - `gap_item_ids`, `target_capability_or_reason`, `target_capabilities`;
  - `benchmark_evidence_ids`, `product_truth_refs`,
    `relevant_asset_refs`, `observed_run_ids`;
  - `proposed_direction`, `mechanism`, `why_candidate`, `blockers`,
    `validation_metric`;
  - `benchmark_channel_boundary` and `effective_payload_snapshot_policy`.
- Prevented Benchmark Channel leakage:
  - a `PRIMARY_BENCHMARK` from Zhihu no longer auto-fills
    `target_platform=ZHIHU`;
  - `target_platform`, `target_asset`, and `target_content_type` remain
    `UNRESOLVED` until the execution-planning phase.
- Updated human review handling:
  - accepted/edited candidates write `effective_payload`;
  - if execution fields remain unresolved, the status becomes
    `PENDING_HUMAN_CHANNEL_REVIEW`, not `VALIDATED`;
  - `strategy_to_experiment_plan` remains fail-closed before Step 8.
- Added `backend/scripts/audit_prompt40_phase3_strategy.py`.
- Added checkpoint/audit docs:
  - `docs/CITATION_DECISION_V1_1_PHASE3_STRATEGY_CHECKPOINT.md`
  - `docs/PROMPT_40_PHASE3_STRATEGY_AUDIT.md`
- No migration is required.
- Phase 3 explicitly did not develop Step 8, Action, Experiment, Baseline Lock,
  platform selection, content task creation, Decision Stability, or Citation /
  Benchmark / Gap scoring changes.

Validation performed:

- `.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase3_strategy.py`
  passed.
- `.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py`
  passed: `35 passed`.
- `.venv/bin/python scripts/audit_prompt40_phase3_strategy.py --output ../docs/PROMPT_40_PHASE3_STRATEGY_AUDIT.md`
  passed.
- Prompt `#40` Phase 3 audit:
  - created `StrategyCandidate #40`;
  - capability Gap items: `点击统计`, `自定义分享标题`, `营销场景使用`;
  - each item keeps `CONTENT_GAP / RELEVANT_ASSET_EXPRESSION` and observed
    Runs `[238, 239, 240, 253, 254, 255]`;
  - before review: `PENDING_REVIEW`, `effective_validation_status=PENDING`;
  - after human edit/review: `ACCEPTED_WITH_EDITS`,
    `effective_validation_status=PENDING_HUMAN_CHANNEL_REVIEW`;
  - `OptimizationAction` stayed `16 -> 16`;
  - `OptimizationExperiment` stayed `16 -> 16`;
  - `strategy_to_experiment_plan` was rejected both before review and after
    review because Step 8 execution fields remain unresolved.

## 2026-08-28 Step 7 StrategyCandidate Expression Upgrade

- Scope was limited to Step 7 strategy candidate content and page expression.
  No Step 8, Step 9, Evidence, Benchmark, Gap, Action, Experiment, Baseline, or
  Decision Stability logic was redesigned.
- Extended vertical StrategyCandidate structured payload with Step 7 strategy
  fields:
  - `target_decision_change`;
  - `strategic_hypothesis`;
  - `priority_capabilities`;
  - `required_signals`;
  - `non_goals`;
  - `strategy_boundary_note`.
- Kept existing Step 8 compatibility fields in the payload, including
  `recommended_action`, `changed_features`, `required_sections`,
  `target_metric`, `product_truth_refs`, `relevant_asset_refs`, and
  `observed_run_ids`.
- Preserved execution isolation:
  - `target_platform = UNRESOLVED`;
  - `target_asset = UNRESOLVED`;
  - `target_content_type = UNRESOLVED`;
  - `intervention_type = UNRESOLVED`;
  - Benchmark channel still cannot become execution channel in Step 7.
- Updated the frontend Strategy page so the StrategyCandidate card leads with:
  - AI decision opportunity;
  - strategy hypothesis;
  - priority capabilities/reasons;
  - required brand-capability signals;
  - non-goals and Step 7/8 boundary.
- Demoted execution/platform/experiment controls to a Step 8 entry block with
  explicit copy that channel, asset, content form, baseline, release, and
  experiment details belong to Step 8.
- Added `backend/tests/test_strategy_step7_v1.py` to lock:
  - strategy payload is not only a gap restatement;
  - capability-level priority supports ties;
  - required signals do not choose execution channel or page sections;
  - non-goals prevent Benchmark channel leakage;
  - unresolved execution fields remain unresolved for Step 8.
- Prompt `#40` real regression:
  - generated `StrategyCandidate #43`;
  - status is `PENDING_REVIEW`;
  - target decision change is to make `爱短链` build a clearer
    brand-capability-recommendation-reason association for `点击统计`,
    `自定义分享标题`, and `营销场景使用`;
  - all three capabilities are `P1` with `6/6` observed Run coverage;
  - `target_platform` remains `UNRESOLVED`.

Validation performed:

- `.venv/bin/python -m pytest tests/test_strategy_step7_v1.py` passed:
  `4 passed`.
- `.venv/bin/python -m pytest tests/test_source_gap_v1.py` passed:
  `47 passed`.
- `source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && npm run build`
  passed.

## 2026-09-01 Step 7 Current Candidate Display Bugfix

- Fixed a frontend state-integrity bug where Step 7 strategy generation could
  succeed, but the Strategy page still displayed:
  `当前流程 0 个策略候选 / 全部 N 个版本`.
- Root cause:
  - the Strategy page prioritized `workflowData.current_strategy_candidate_ids`
    when filtering current candidates;
  - after generating a new current StrategyCandidate, the page refreshed the
    candidate list but did not refresh workflow status in the same path;
  - stale workflow IDs could therefore hide the newly generated candidate even
    when the API returned `eligible_for_current_step7 = true`.
- Fix:
  - refresh Prompt workflow status after current Step 7 generation;
  - when workflow IDs are stale and match no visible current candidate, fall
    back to candidates whose backend eligibility says
    `eligible_for_current_step7 = true`;
  - opening Strategy confirmation now refreshes the current Prompt workflow and
    uses the current evidence package from either Citation Decision or workflow
    context.
- Boundary:
  - no Strategy generation rule changed;
  - no historical StrategyCandidate is counted as current;
  - no Step 8 / Action / Experiment behavior changed.
- Prompt `#40` verification:
  - backend workflow reports `current_strategy_candidate_id = 50`;
  - Step 7 status is `PENDING_REVIEW`;
  - Step 8 remains `LOCKED` until Strategy is confirmed.

Validation performed:

- `source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build`
  passed.
- `curl -s http://127.0.0.1:8000/api/optimization/workflow/3/40/status`
  confirms `1 个当前策略候选待人工审核`.
- `git diff --check` passed.

## 2026-09-01 Step 7 No-Strategy Terminal State Bugfix

- Fixed a workflow state-source mismatch observed on Prompt `#19`.
- Symptom:
  - frontend loaded Prompt `#19` with Steps 1-6 completed;
  - Step 7 showed no current StrategyCandidate and no generatable
    content/evidence gap;
  - backend workflow still reported `strategy_step_status=READY_TO_GENERATE`
    because it only checked whether upstream reviews were done.
- Root cause:
  - Step 7 workflow status did not consume the formal Citation Decision result;
  - `reviews_done` was incorrectly treated as sufficient to say a
    StrategyCandidate could be generated.
- Fix:
  - workflow status now calls the current Citation Decision V1 path for the
    current Prompt/Evidence Package when no current candidate exists;
  - Step 7 is `READY_TO_GENERATE` only when formal recommended actions include
    a `CONTENT` or `EVIDENCE` route;
  - otherwise Step 7 returns `NO_STRATEGY` with
    `当前没有可生成策略的内容/证据缺口`;
  - Step 8 returns `NO_EXPERIMENT` with
    `本轮没有策略候选，无需创建实验草案`.
- Frontend behavior:
  - `NO_STRATEGY` is displayed as `无需策略`;
  - Step 8 is displayed as `无需创建`;
  - users can still click `查看依据` to inspect the Citation/Gap context.
- Workflow done semantics:
  - `NO_STRATEGY` and `NO_EXPERIMENT` are terminal done states for the current
    Prompt, not pending work;
  - they mean the current V1 chain has no strategy or experiment to create.
- Boundary:
  - no Citation / Benchmark / Gap / Strategy generation rules changed;
  - no historical StrategyCandidate or Experiment is counted as current;
  - no Step 8 materialization behavior changed.

Validation performed:

- `.venv/bin/python -m pytest -q tests/test_workflow_review_queue.py`
  passed: `12 passed`.

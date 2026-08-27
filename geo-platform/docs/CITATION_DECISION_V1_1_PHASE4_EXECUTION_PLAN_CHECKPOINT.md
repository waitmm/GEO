# Citation Decision V1.1 Phase 4 Execution Plan Checkpoint

状态：CHECKPOINT
日期：2026-08-27

## 1. 本阶段边界

Phase 4 只实现单 Prompt 主链 Step 8：

```text
已确认 StrategyCandidate
-> 人工确认渠道、资产操作和选定资产
-> 创建 Action / Experiment 草案
-> 冻结 Strategy / Asset / Gap / Action / Baseline 快照
```

本阶段不进入：

```text
自动内容发布
Release Audit
固定复采
Recommendation Outcome
Decision Stability
Prompt Cluster
新评分体系
```

## 2. Preflight Audit

### 2.1 Asset Inventory

已审计现有 `PageSnapshot`，可以稳定表示已有目标品牌资产：

```text
asset_id = PageSnapshot.id
canonical_url = PageSnapshot.canonical_url / final_url / url / target_url
asset_type = Step 8 人工选择
snapshot_type / capture_status / title = 审计辅助字段
```

因此本阶段不新增 `BrandAssetInventory` 大体系。

新资产不写成已有 URL，而是通过：

```text
selected_asset_ref.asset_ref_type = NEW_ASSET
selected_asset_ref.proposal = {...}
```

表达为 proposal。

### 2.2 Channel 与 Asset Operation

Step 8 将位置和资产动作拆开：

```text
channel:
OFFICIAL_SITE / PRODUCT_DOCS / ZHIHU / BAIJIAHAO / THIRD_PARTY_MEDIA / OTHER

asset_operation:
UPDATE_EXISTING / CREATE_NEW
```

`OFFICIAL_SITE + UPDATE_EXISTING` 与 `OFFICIAL_SITE + CREATE_NEW` 不再是两个 channel。

### 2.3 Baseline Metrics

现有 `OptimizationExperiment` 已有：

```text
baseline_run_ids_json
baseline_metrics_json
```

本阶段新增轻量 `baseline_metrics_for_fixed_runs`，输入必须显式包含固定
Run IDs。它不会按 `prompt_id` 动态读取最新 Runs。

指标分为：

```text
brand-level:
brand_mention
brand_candidate
brand_recommendation
target_reason_adoption
brand_retrieval_presence
brand_citation_presence

selected-asset-level:
selected_asset_retrieval_presence
selected_asset_citation_presence
```

`target_reason_adoption` 只统计目标品牌自己的目标能力/理由采纳，不把竞品推荐理由计入目标品牌指标。

### 2.4 Strategy Snapshot

现有 `OptimizationExperiment.intervention_variables_json` 足够保存最小不可变快照：

```text
strategy_snapshot
selected_asset_ref
gap_diagnosis_refs
action_snapshot
baseline_run_ids
baseline_metrics
```

因此本阶段不做 migration。Experiment 创建后，即使
`OptimizationStrategyCandidate.effective_payload_json` 后续被修改，实验里的
`strategy_snapshot` 不会自动变化。

## 3. 新增 / 修改对象

复用：

```text
OptimizationStrategyCandidate
effective_payload_json
OptimizationIssue
OptimizationAction
OptimizationExperiment
PageSnapshot
```

新增 API schema：

```text
StrategyExecutionPlanPayload
```

新增服务入口：

```text
confirm_strategy_execution_plan()
```

新增 API：

```text
POST /optimization/strategy-candidates/{candidate_id}/execution-plan
```

## 4. Step 7 -> Step 8 状态语义

已锁死：

```text
review_status = ACCEPTED / ACCEPTED_WITH_EDITS
= Strategy 已确认
```

```text
effective_validation_status = PENDING_HUMAN_CHANNEL_REVIEW
= Strategy 已确认，但 Step 8 执行方案还没确认
```

因此：

```text
ACCEPTED_WITH_EDITS + PENDING_HUMAN_CHANNEL_REVIEW
-> 允许进入 Step 8
```

```text
PENDING_REVIEW
-> 禁止进入 Step 8
```

Step 8 确认后，系统会把 `channel / asset_operation / selected_asset_ref`
合并进 `effective_payload`，校验通过后才将
`effective_validation_status` 更新为 `VALIDATED` 并创建草案。

## 5. 后端 Gate

后端保证：

```text
未人工确认的 StrategyCandidate
不能创建 Action
不能创建 Experiment
```

已有资产必须绑定真实 `PageSnapshot.id`。

新资产必须是 `NEW_ASSET proposal`。

Baseline 必须来自固定 `baseline_run_ids`，且这些 Run 必须属于当前
Evidence Package。

## 6. Prompt #40 真实回归

真实审计文档：

```text
docs/PROMPT_40_PHASE4_EXECUTION_PLAN_AUDIT.md
```

本次 #40 输出：

```text
strategy_candidate_id = 41
channel = OFFICIAL_SITE
asset_operation = UPDATE_EXISTING
selected_asset_id = 3
selected_asset_ref = PAGE_SNAPSHOT:3
baseline_run_ids = [238, 239, 240, 253, 254, 255]
action_id = 30
experiment_id = 30
experiment_status = draft
release_blocked = true
release_blocked_reason = WAITING_FOR_RELEASE_AUDIT
```

Baseline 指标：

```text
brand_mention = 0/6
brand_candidate = 0/6
brand_recommendation = 0/6
target_reason_adoption = 0/6
brand_retrieval_presence = 6/6
brand_citation_presence = 0/6
selected_asset_retrieval_presence = 0/6
selected_asset_citation_presence = 0/6
```

说明：本地审计过程中先生成过一条早期草案用于发现并修正快照冻结点问题，未删除历史记录；本 checkpoint 的权威 Phase 4 回归对象为 `StrategyCandidate #41 / Action #30 / Experiment #30`。

Experiment 冻结快照中：

```text
strategy_snapshot.effective_validation_status = VALIDATED
strategy_snapshot.target_platform = OFFICIAL_SITE
strategy_snapshot.target_asset = PAGE_SNAPSHOT:3
strategy_snapshot.target_content_type = ARTICLE
```

## 7. 验证

已运行：

```bash
cd geo-platform/backend
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase4_execution_plan.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
.venv/bin/python scripts/audit_prompt40_phase4_execution_plan.py --output ../docs/PROMPT_40_PHASE4_EXECUTION_PLAN_AUDIT.md
git diff --check
```

结果：

```text
39 passed
compileall passed
diff-check passed
```

pytest 仅有既有 datetime / Pydantic deprecation warnings。

## 8. 遗留问题

- 前端仍需要把第 8 步接到新的 `execution-plan` API，而不是旧的
  `experiment-plan` 自动转换入口。
- 真实发布确认、PRE/POST snapshot、固定复采和 Outcome 仍属于后续阶段。
- 本地数据库中保留了 Phase 4 审计产生的 Action / Experiment 草案；这是本阶段预期的真实回归结果。

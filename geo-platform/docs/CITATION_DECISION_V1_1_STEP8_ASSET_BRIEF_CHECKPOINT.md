# Citation Decision V1.1 Step 8 Asset Brief Checkpoint

状态：READY_FOR_REVIEW
日期：2026-08-31

## 1. 范围

本 checkpoint 只实现 Step 8 的第二刀：

```text
Asset Brief
Claim Matrix
Asset Brief Review Gate
Snapshot Freeze
```

不做：

```text
Draft
Step 9
自动发布
Channel Intelligence
新评分体系
新 Gap 类型
新 Strategy 表
```

## 2. 复用对象

本轮优先复用现有对象和 JSON 字段：

```text
OptimizationStrategyCandidate.structured_payload_json
OptimizationStrategyCandidate.effective_payload_json
OptimizationStrategyCandidate.experiment_plan_json
OptimizationAction.release_evidence_json
OptimizationExperiment.intervention_variables_json
OptimizationExperiment.controlled_intervention_json
OptimizationExperiment.brief_json
```

没有新增数据库表，也不需要 migration。

## 3. 新增接口

新增 Asset Brief 审核接口：

```text
POST /api/optimization/experiments/{experiment_id}/asset-brief/review
```

该接口只更新 Asset Brief 审核状态和快照，不创建 Draft，不创建新的 Action 或
Experiment。

## 4. Claim Matrix 语义

Claim Matrix 只表达事实边界：

```text
REQUIRED
OPTIONAL
PROHIBITED
REVIEW_REQUIRED
```

Product Truth 映射：

```text
SUPPORTED     -> REQUIRED / OPTIONAL
UNKNOWN       -> REVIEW_REQUIRED / BLOCKED
NOT_SUPPORTED -> PROHIBITED
```

目标品牌 Claim 只能由目标品牌 Product Truth 支持。Benchmark Evidence /
SourceClaim 只能作为对标证据上下文，不能改写成目标品牌事实。

## 5. 快照冻结

Asset Brief 确认时冻结：

```text
strategy_snapshot/ref
selected_asset_ref/snapshot
required_signals
claim_matrix
product_truth_refs/snapshot
supporting_evidence_refs
channel_role
brief_version
confirmed_at
```

这些快照写入：

```text
Experiment.intervention_variables_json.asset_brief
Experiment.controlled_intervention_json.asset_brief_snapshot
Experiment.brief_json.asset_brief
Action.release_evidence_json.asset_brief_snapshot
StrategyCandidate.experiment_plan_json.asset_brief
```

## 6. Prompt #40 回归

本轮真实回归使用当前 #40 官方路径：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
StrategyCandidate #44
Action #31
Experiment #31
created_new_draft = False
```

主链零污染：

```text
StrategyCandidate: 7 -> 7
OptimizationAction: 20 -> 20
OptimizationExperiment: 20 -> 20
Prompt #40 EvidenceAlignment: 660 -> 660
PRIMARY_BENCHMARK: 1 -> 1
推荐动作: 1 -> 1
```

Claim Matrix 目标品牌 Claim：

```text
点击统计       REQUIRED / SUPPORTED / PRODUCT_TRUTH
自定义分享标题 REQUIRED / SUPPORTED / PRODUCT_TRUTH
营销场景使用   REQUIRED / SUPPORTED / PRODUCT_TRUTH
```

Required Signal 映射：

```text
点击统计       MAPPED
自定义分享标题 MAPPED
营销场景使用   MAPPED
```

审核状态：

```text
before_brief_status = PENDING_REVIEW
after_brief_status = CONFIRMED
draft_gate = READY_FOR_DRAFT_PREPARATION
mechanism_compatibility = EXECUTION_COMPATIBLE
```

完整审计文档：

```text
docs/PROMPT_40_STEP8_ASSET_BRIEF_AUDIT.md
```

## 7. 测试覆盖

新增后端测试：

```text
tests/test_asset_brief_v1.py
```

覆盖：

```text
Step 8 生成 Asset Brief 和 Claim Matrix
Asset Brief 审核不创建新 Action / Experiment
已有 Step 8 draft 原地补 Asset Brief
UNKNOWN Product Truth 阻断 REQUIRED Claim
NOT_SUPPORTED Product Truth 生成 PROHIBITED Claim
目标品牌 Claim 与 Benchmark Evidence 边界隔离
Required Signal 可追溯到 Claim Matrix
Mechanism REVIEW_REQUIRED 需要显式批准
Asset Brief 快照不随 Product Truth / Asset 后续变化漂移
```

已通过相关测试：

```text
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py
69 passed
```

## 8. 踩坑记录

本轮审计脚本第一次可能选中历史 BAIJIAHAO 模拟候选，而不是当前官方路径
`StrategyCandidate #44 / Action #31 / Experiment #31`。

已修正为优先选择当前 experiment-bound 的 `OFFICIAL_SITE` 候选，避免把历史模拟对象当成
#40 正式验收对象。

## 9. 遗留问题

- 本轮不进入 Draft，因此 `READY_FOR_DRAFT_PREPARATION` 只是说明 Asset Brief
  事实边界已确认，不代表已生成正文。
- Release Audit 仍是发布前 Gate。`Experiment #31` 保持 draft / waiting for
  release audit 是正常状态。
- 后续若开发 Draft，必须消费已确认的 Asset Brief / Claim Matrix，不得重新从
  Benchmark Evidence 生成目标品牌事实。

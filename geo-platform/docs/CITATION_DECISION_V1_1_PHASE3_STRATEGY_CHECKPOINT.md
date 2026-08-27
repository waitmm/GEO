# Citation Decision V1.1 Phase 3 StrategyCandidate Checkpoint

状态：READY_FOR_REVIEW
日期：2026-08-27

## 1. 本阶段边界

Phase 3 只实现主链第 7 步：

```text
StrategyCandidate
-> Human Review/Edit
-> effective_payload
-> Confirmed Strategy
```

本阶段不进入：

```text
Step 8 实验草案
Action
Experiment
Baseline Lock
发布平台选择
内容任务创建
Decision Stability
Citation / Benchmark / Gap 规则修改
```

## 2. Gap 真值作用域

审计结论：

```text
source_gap_type
```

继续作为 source analysis 行上的兼容展示字段。

Phase 3 正式消费不直接把单一 `source_gap_type` 当作策略真值，而是消费：

```text
capability_gap_items
```

每个 item 保留：

```text
gap_item_id
capability_label
gap_type
gap_layer
benchmark_evidence_ids
product_truth_ids/status
relevant_asset_snapshot
retrieval_candidate_context
evidence_adoption_context
observed_run_ids
run_coverage_count
```

这样同一 Benchmark Source 暴露多个 capability/reason 时，策略候选不会丢失能力级 lineage。

## 3. StrategyCandidate 复用

本阶段复用现有表：

```text
OptimizationStrategyCandidate
```

复用字段：

```text
review_status
structured_payload_json
human_edited_payload_json
effective_payload_json
effective_payload_version
effective_validation_status
evidence_validation_status
hypothesis_validation_status
```

不新增平行 Strategy 表。

## 4. Candidate 数据结构

机器候选 `structured_payload` 至少包含：

```text
strategy_phase = PHASE_3_STRATEGY_CANDIDATE
prompt_id
gap_item_ids
target_capability_or_reason
target_capabilities
benchmark_evidence_ids
product_truth_refs
relevant_asset_refs
observed_run_ids
run_coverage_count
proposed_direction
mechanism
why_candidate
blockers
validation_metric
benchmark_channel_boundary
effective_payload_snapshot_policy
```

关键边界：

```text
Benchmark 来源平台不能自动成为 Strategy 执行平台；
target_platform / target_asset / target_content_type 默认保留 UNRESOLVED；
平台、资产和具体执行方式属于 Step 8。
```

## 5. Human Review / Confirm 链

机器生成候选时：

```text
review_status = PENDING_REVIEW
effective_payload = {}
effective_validation_status = PENDING
experiment_id = null
```

人工审核后：

```text
review_status = ACCEPTED 或 ACCEPTED_WITH_EDITS
human_edited_payload 记录人工改动
effective_payload = structured_payload + human edits
effective_payload_version = effective_payload.v1
```

如果执行字段仍未确认：

```text
effective_validation_status = PENDING_HUMAN_CHANNEL_REVIEW
```

这表示 Strategy 语义已确认，但仍不可物化 Action / Experiment。

## 6. API Gate

后端 Gate 保持 fail-closed：

```text
未人工接受 StrategyCandidate
-> strategy_to_experiment_plan 拒绝

已人工接受但 effective_payload 仍为 PENDING_HUMAN_CHANNEL_REVIEW
-> strategy_to_experiment_plan 拒绝

只有 effective_validation_status = VALIDATED
且执行字段不含 UNRESOLVED
-> 才允许后续 Step 8 物化
```

本阶段 `confirm_citation_decision_vertical_slice` 已改为只创建待审核 StrategyCandidate。
即使 payload 传入：

```text
create_experiments = true
```

也不会创建 Action 或 Experiment。

## 7. #40 真实回归

审计文档：

```text
docs/PROMPT_40_PHASE3_STRATEGY_AUDIT.md
```

真实结果：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
candidate_id = 40
```

Capability Gap 输入：

```text
点击统计           CONTENT_GAP / RELEVANT_ASSET_EXPRESSION / observed_runs 6/6
自定义分享标题     CONTENT_GAP / RELEVANT_ASSET_EXPRESSION / observed_runs 6/6
营销场景使用       CONTENT_GAP / RELEVANT_ASSET_EXPRESSION / observed_runs 6/6
```

策略候选：

```text
review_status_before = PENDING_REVIEW
effective_validation_status_before = PENDING

review_status_after = ACCEPTED_WITH_EDITS
effective_validation_status_after = PENDING_HUMAN_CHANNEL_REVIEW
effective_payload_version = effective_payload.v1
```

执行表零推进：

```text
OptimizationAction: 16 -> 16
OptimizationExperiment: 16 -> 16
```

Gate 验证：

```text
确认前 strategy_to_experiment_plan 被拒绝；
确认后仍因 PENDING_HUMAN_CHANNEL_REVIEW 被拒绝；
Step 8 未开始。
```

## 8. Migration

不需要 migration。

原因：

```text
1. StrategyCandidate 复用现有表。
2. capability_gap_items 是 source_analysis 派生 payload。
3. effective_payload / review_status / validation_status 均复用既有字段。
4. 不新增 Action / Experiment 字段。
```

## 9. 验证

```bash
cd geo-platform/backend
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase3_strategy.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
.venv/bin/python scripts/audit_prompt40_phase3_strategy.py --output ../docs/PROMPT_40_PHASE3_STRATEGY_AUDIT.md
```

结果：

```text
compileall passed
35 passed
Prompt #40 audit generated
```

## 10. 尚未解决

```text
1. 前端第 7 步仍需在后续阶段改成“策略候选/策略确认”语义，
   不应继续显示成“确认推荐动作”。
2. Step 8 需要定义如何把 confirmed effective_payload 补齐执行平台、
   target_asset、target_content_type，并冻结到 Experiment。
3. 旧 workflow action/channel/experiment 草案入口仍是历史兼容面，
   后续需要统一到 StrategyCandidate/effective_payload 后再进入实验草案。
```

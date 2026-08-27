# Citation Decision V1.1 Phase 5 Decision Stability Checkpoint

状态：CHECKPOINT_READY
日期：2026-08-27

## 1. 阶段边界

Phase 5 只实现 Decision Stability 后置观察指标。

它只回答：

```text
同一个 Prompt 的多次独立采样中，AI 的品牌/方案推荐结果有多稳定。
```

它不参与任何正式主链 Gate：

```text
RecommendationEvent
AnswerDecisionBinding
EvidenceAlignment eligibility
Citation / Benchmark score
Benchmark tier
GapDiagnosis
StrategyCandidate
Strategy confirmation
Action
Experiment
Baseline
```

本阶段没有进入 Step 9，没有创建复采任务，也没有生成实验结论。

## 2. 数据结构

Decision Stability 作为只读派生结果返回，不新增数据库表，不需要 migration。

后端返回字段：

```text
version
project_id
prompt_id
evidence_package_id
metric_role
valid_run_ids
valid_run_count
brand_decision_run_count
brand_decision_rate
recommendation_entities
dominant_recommendation_outcome
recommendation_reasons
decision_stability_score
stability_level
stability_level_label
formula
thresholds
boundary_note
```

API：

```text
GET /api/optimization/projects/{project_id}/prompts/{prompt_id}/decision-stability
```

`citation-decision-v1` 主接口也附带同一份只读 `decision_stability`，方便单 Prompt 主链页面展示。

## 3. 计算公式

有效样本来自当前 Evidence Package 固定的 `source_run_ids`，并只保留正式有效 Run。

核心公式：

```text
decision_stability_score
= round(dominant_recommendation_outcome.run_count / valid_run_count * 100)
```

分数为 0-100 的整数，避免假精确。

稳定性等级：

```text
HIGH_STABILITY: score >= 80
MIXED: 50 <= score < 80
HIGH_VOLATILITY: score < 50
NO_VALID_RUNS: valid_run_count = 0
```

推荐理由覆盖：

```text
reason_observed_run_count / 对应推荐对象 recommendation_run_count
```

推荐理由只消费已有 `AnswerDecisionBinding`，不重新调用 LLM。

展示口径只保留适合作为推荐理由的 AnswerUnit 类型：

```text
FEATURE
BENEFIT
PRICE
USE_CASE
RESULT_EFFECT
COMPARATIVE_ADVANTAGE
```

明显的操作步骤、补充提问和注意事项文本不会进入 Decision Stability 的主要推荐理由列表。

## 4. 前端展示

单 Prompt 主链页面新增“决策稳定性观察”信息块。

展示：

```text
有效样本
品牌决策发生
主导推荐对象
稳定性分数
Top 推荐覆盖
Top 理由覆盖
```

引用资料决策详情页也展示同一指标，并明确标注：

```text
只读观察
不改变当前证据、对标、缺口、策略、动作或实验结果
```

本次没有新增单独模块，也没有改变 1-8 主链顺序。

## 5. Prompt #40 真实结果

真实审计文件：

```text
docs/PROMPT_40_PHASE5_DECISION_STABILITY_AUDIT.md
```

Prompt `#40` 当前结果：

```text
valid_run_ids = [238, 239, 240, 253, 254, 255]
valid_run_count = 6
brand_decision_run_count = 6
dominant_recommendation_outcome = RECOMMENDATION_ENTITY Bitly
dominant_observed_run_ids = [238, 239, 240, 253, 254, 255]
decision_stability_score = 100 / 100
stability_level = HIGH_STABILITY
```

主链零影响：

```text
EvidenceAlignment 总数: 660 -> 660
正式 SUPPORTS: 36 -> 36
PRIMARY_BENCHMARK: 1 -> 1
SECONDARY_BENCHMARK: 0 -> 0
CONTENT_GAP: 1 -> 1
推荐动作: 1 -> 1
StrategyCandidate #41: unchanged
Action #30: unchanged
Experiment #30: unchanged
decision_stability_formal_output_impact = NONE
```

## 6. Phase 4 补充回归

本阶段补齐并继续验证 Phase 4 行为：

```text
Strategy 未确认不能进入 Step 8
ACCEPTED_WITH_EDITS + PENDING_HUMAN_CHANNEL_REVIEW 可以进入 Step 8
Experiment 创建后 strategy_snapshot 不随 effective_payload 后续修改改变
Prompt 新增 Run 不修改历史 Experiment baseline
selected channel / selected asset 不完整时不能创建正式执行方案
Benchmark 来源平台不能自动写入 intervention channel
```

## 7. 验证结果

```text
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase5_decision_stability.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
48 passed
```

## 8. 遗留问题

Decision Stability 当前只读反映已有 `RecommendationEvent` 和
`AnswerDecisionBinding`。如果上游 Binding 本身把较宽泛的能力说明也绑定为
推荐理由，Phase 5 会按只读观察层展示，但不会修正正式 Binding。

后续如需进一步提升理由质量，应回到 Answer Binding 生成和审核层处理，不应在
Decision Stability 中替代主链判断。

## 9. 阶段状态

```text
PHASE_5_DECISION_STABILITY_CHECKPOINT_READY
STEP_9_NOT_STARTED
SINGLE_PROMPT_V1_1_1_TO_8_READY_FOR_FINAL_ACCEPTANCE
```

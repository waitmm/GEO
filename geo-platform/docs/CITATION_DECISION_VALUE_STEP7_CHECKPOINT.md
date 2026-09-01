# Citation Decision Value Step 7 Checkpoint

状态：CHECKPOINT
日期：2026-09-01

## 1. 本轮目标

本轮不重新设计 Single Prompt GEO V1.1 主链，不进入 Step 9，不新增新的
Citation Score、Benchmark Score、Channel Score、Gap 类型或 Evidence Judge。

目标是把已有正式证据：

```text
eligible EvidenceAlignment
-> SUPPORTS / CONTRADICTS / NO_SUPPORT
-> observed_run_ids
-> Benchmark / Gap
```

翻译成 Step 7 可以消费的策略信号：

```text
source × entity × capability/reason Citation Decision Value
-> Channel Aggregation
-> planned_channels / channel_roles
```

## 2. Citation Decision Value 粒度

正式粒度不是整篇 `SourceDocument` 一个标签，而是：

```text
SourceDocument
+ supported_entity
+ capability/reason
```

同一篇来源可以同时包含多个价值：

```text
点击统计 -> DECISION_CITATION
营销场景说明 -> ANSWER_SUPPORT_CITATION
其他引用上下文 -> PERIPHERAL_CITATION
```

## 3. 分类

```text
DECISION_CITATION
ANSWER_SUPPORT_CITATION
PERIPHERAL_CITATION
UNCLASSIFIED_SUPPORT
NOT_EVALUABLE
```

`DECISION_CITATION` 必须来自：

```text
Run
-> RecommendationEvent
-> AnswerDecisionBinding
-> AnswerUnit
-> ReferenceSource
-> SourceDocument
-> SourceClaim
-> EvidenceAlignment = SUPPORTS
```

`ANSWER_SUPPORT_CITATION` 暂时保守输出：只有 eligible SUPPORTS 支撑
AnswerUnit 且没有绑定 Recommendation Decision 时才输出。不能为了凑分类新增 Judge
或降低证据标准。

## 4. 新增派生输出

来源行新增：

```text
citation_decision_values
citation_value_class
citation_value_label
citation_value_summary
citation_run_ids
retrieval_run_ids
```

纵向链路新增：

```text
channel_aggregation
```

平台聚合字段包括：

```text
retrieval_run_count
citation_run_count
decision_citation_run_count
answer_support_run_count
peripheral_run_count
eligible_support_run_count
supported_entities
supported_capabilities
supported_reasons
primary_benchmark_count
secondary_benchmark_count
```

## 5. Step 7 消费规则

Step 7 的 `planned_channels` 和 `channel_roles` 现在消费：

```text
Citation Decision Value
Channel Aggregation
Product Truth
Capability Gap
Relevant Brand Asset
Retrieval / Citation 状态
Benchmark Evidence
```

这替代旧的过简逻辑：

```text
CONTENT_GAP -> OFFICIAL_SITE PRIMARY
Benchmark 平台 -> OBSERVE
```

但仍然保持边界：

```text
Benchmark Channel != Automatic Strategy Channel
Channel Aggregation != Step 8 concrete account / URL / title / Draft
```

## 6. Prompt #40 真实回归

只读运行：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
use_answer_binding_v1_1 = true
```

结果：

```text
status = READY_FOR_HUMAN_CONFIRM
source_count = 68
recommended_actions = 1
```

平台聚合：

```text
ZHIHU retrieval = 6/6
ZHIHU citation = 6/6
ZHIHU decision citation = 6/6
ZHIHU answer support = 0/6
ZHIHU primary benchmark count = 1
```

知乎支持的 reasons：

```text
小码短链接自带点击统计
小码短链接自带自定义分享标题
小码短链接适合营销场景使用
```

来源级决策引用：

```text
SourceDocument #345
title = 如何将长链接缩短-小码至营
platform = ZHIHU
benchmark_tier = PRIMARY_BENCHMARK
citation_value_class = DECISION_CITATION
support_run_ids = [238, 239, 240, 253, 254, 255]
decision_citation_count = 3
```

Step 7 计划平台：

```text
OFFICIAL_SITE = PRIMARY
  角色：承载目标品牌自己的能力事实表达和可摘录证据。

ZHIHU = SECONDARY
  依据：Decision Citation 覆盖 6/6 Runs；
       支撑理由包括点击统计、自定义分享标题、营销场景使用；
       核心对标来源 1 个。
```

该结果不是因为：

```text
PRIMARY_BENCHMARK = 知乎
```

直接推出知乎执行，而是因为知乎在当前 #40 数据中存在真实、多 Run 的
`DECISION_CITATION`。

## 7. 验证

```text
cd geo-platform/backend
.venv/bin/python -m compileall app
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py tests/test_workflow_review_queue.py
source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build
git diff --check
```

结果：

```text
compileall passed
84 passed
frontend build passed
git diff --check passed
```

## 8. 未改变范围

本轮没有改变：

```text
EvidenceAlignment eligibility
Run lineage
Product Truth
Capability Gap
Citation Score
Benchmark Tier formula
Decision Stability
StrategyCandidate / effective_payload gate
Step 8 Draft
Step 9
```

## 9. Source of Truth

正式定义由：

```text
产品纲要.md
geo-platform/docs/05_OPTIMIZATION_LOOP_SPEC.md
```

共同承担。`PRODUCT_FUNCTION_SPEC.md` 是产品功能说明，`08_DEVELOPMENT_LOG.md` 和
`09_PRODUCT_ITERATION_LOG.md` 记录本轮实现与迭代原因。

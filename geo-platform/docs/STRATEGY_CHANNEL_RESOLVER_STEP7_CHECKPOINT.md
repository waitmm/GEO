# Strategy Channel Resolver Step 7 Checkpoint

状态：CHECKPOINT
日期：2026-09-01

## 1. 本轮目标

本轮不重新设计 Single Prompt GEO V1.1 主链，不进入 Draft 或 Step 9。

目标是把 Step 7 所有渠道角色判断收口到一个唯一、确定性、证据驱动的
Strategy Channel Resolver。

```text
Capability Gap
Citation Decision Value
Channel Aggregation
Product Truth
Relevant Brand Asset
Retrieval / Citation State
Benchmark Evidence
↓
resolve_strategy_channels(...)
↓
primary_intervention_path
planned_channels
channel_roles
channel_rationales
```

## 2. 旧渠道规则审计

开发前审计到的渠道相关逻辑位置：

```text
backend/app/modules/optimization/service.py
  _strategy_planned_channels
  _strategy_primary_intervention_path
  _strategy_channel_roles
  _strategy_asset_direction
  _strategy_execution_sequence

frontend/src/App.tsx
  只展示 planned_channels / channel_roles，不正式推断平台角色

Step 8 compatibility
  只校验确认后的 planned_channels，不重新决策平台策略
```

本轮停止消费的旧分散捷径：

```text
CONTENT/EVIDENCE -> first-party PRIMARY
Benchmark platform -> execution channel
Benchmark platform -> always OBSERVE
```

## 3. 唯一 Resolver

正式函数：

```text
_resolve_strategy_channels(...)
```

只输出：

```text
primary_intervention_path
planned_channels
channel_roles
channel_rationales
```

不输出、不决定：

```text
具体账号
具体 URL
具体页面
具体标题
具体 section
具体资产实例
Draft
Action
Experiment
```

## 4. 规则边界

```text
CONTENT_GAP
-> 相关一方资产可 PRIMARY
-> 强第三方 Decision Citation 可 SECONDARY / EXPERIMENTAL

EVIDENCE_GAP + 强第三方 Decision Citation
-> 第三方渠道可 PRIMARY
-> 一方资产可作为 SECONDARY 事实锚点

DISCOVERABILITY_GAP
-> DISCOVERABILITY_RETRIEVAL_EXPANSION
-> Retrieval 信号优先，但不自动选择执行平台

PRODUCT_GAP
-> PRODUCT_IMPROVEMENT
-> 不包装成官网或第三方内容动作

UNKNOWN
-> 不强行生成 PRIMARY

Benchmark-only + 无 Decision Citation
-> OBSERVE
```

## 5. Prompt #40 真实回归

只读运行：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
use_answer_binding_v1_1 = true
```

输出：

```text
status = READY_FOR_HUMAN_CONFIRM
recommended_actions = 1
resolver.name = resolve_strategy_channels
resolver.decision_mode = DETERMINISTIC_POLICY_ENGINE
resolver.scope = STEP_7_CHANNEL_ROLE_AND_INTERVENTION_PATH_ONLY
```

计划平台：

```text
OFFICIAL_SITE
role = PRIMARY
intervention_type = FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION
basis = Product Truth + 相关品牌资产表达缺口 + Retrieval/Citation 状态

ZHIHU
role = SECONDARY
intervention_type = THIRD_PARTY_DECISION_EVIDENCE
basis = Decision Citation 6/6 Runs; 支撑理由：点击统计 / 自定义分享标题 / 营销场景使用; 核心对标来源 1 个
```

关键解释：

```text
#40 不是因为官网天然优先而选择官网 PRIMARY。
#40 也不是因为 Benchmark 在知乎就直接选择知乎。
两个平台角色都来自同一个 Resolver。
```

## 6. 验收 Fixture

新增/更新测试覆盖：

```text
CONTENT_GAP + 强第三方 Decision Citation
-> 一方资产 PRIMARY，第三方 SECONDARY

EVIDENCE_GAP + 强第三方 Decision Citation
-> 第三方 PRIMARY

DISCOVERABILITY_GAP
-> Retrieval expansion path

PRODUCT_GAP
-> PRODUCT_IMPROVEMENT，无内容渠道 PRIMARY

UNKNOWN
-> 不强行 PRIMARY

Benchmark-only + 无 Decision Citation
-> Benchmark 平台 OBSERVE
```

## 7. 未改变范围

本轮没有改变：

```text
EvidenceAlignment
Run lineage
Citation Decision Value 分类
Benchmark
Capability Gap
Product Truth
Decision Stability
Asset Brief
Claim Matrix
Draft
Step 9
```

## 8. 验证

```text
cd geo-platform/backend
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py tests/test_asset_brief_v1.py tests/test_workflow_review_queue.py
.venv/bin/python -m compileall app
source /Users/bmwqr/.nvm/nvm.sh && nvm use 18.20.8 && cd geo-platform/frontend && npm run build
git diff --check
```

结果：

```text
91 passed
compileall passed
frontend build passed
git diff --check passed
```

## 9. Source of Truth

正式定义由：

```text
产品纲要.md
geo-platform/docs/05_OPTIMIZATION_LOOP_SPEC.md
geo-platform/docs/PRODUCT_FUNCTION_SPEC.md
```

共同承担。产品迭代记录见 `09_PRODUCT_ITERATION_LOG.md`，开发记录见
`08_DEVELOPMENT_LOG.md`，风险记录见 `09_OPEN_ISSUES_AND_RISKS.md`。

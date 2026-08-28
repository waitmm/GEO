# Citation Decision V1.1 Step 7 Strategy Core Checkpoint

状态：FIRST_CUT_READY
日期：2026-08-28

## 1. 本轮范围

本轮只修复 Step 7 / Step 8 的正式边界和保护逻辑：

```text
Step 7 StrategyCandidate
-> Strategy Core + 人工策略确认
-> Step 8 Execution Plan
```

不开发：

```text
Asset Brief
Claim Matrix
Draft
Step 9
Decision Stability 新公式
Citation / Benchmark 新评分
Gap 新类型
```

## 2. Step 7 正式边界

Step 7 现在允许表达计划平台层：

```text
OFFICIAL_SITE
PRODUCT_DOCS
ZHIHU
BAIJIAHAO
THIRD_PARTY_MEDIA
OTHER
```

但 Step 7 不能决定：

```text
具体账号
具体 URL
具体页面
具体标题
具体 section
具体内容结构
Draft
Baseline
Action
Experiment
```

## 3. Strategy Core

本轮复用现有 `OptimizationStrategyCandidate.structured_payload` 和
`effective_payload`，不新增 `StrategyV2`。

Strategy Core 至少包含：

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

## 4. Step 8 Protection

Step 8 可以确认具体执行参数：

```text
selected_channel instance
selected_asset
URL / account / location
title
section
content_structure
baseline_run_ids
```

Step 8 不能直接修改 Strategy Core。若 payload 试图改动
`intervention_mechanism`、`planned_channels`、`channel_roles`、`required_signals`
或 `attribution_intent` 等字段，后端返回：

```text
RETURN_TO_STEP_7
```

## 5. Execution Delta

Step 8 会生成结构化 `execution_delta`：

```text
field_path
original_value
new_value
reason
changed_by
changed_at
impact_level
```

`impact_level` 由后端计算：

```text
EXECUTION_ONLY
MECHANISM_REVIEW_REQUIRED
STRATEGY_CORE_CHANGE
```

## 6. Mechanism Compatibility

Step 8 会检查执行参数是否仍满足：

```text
intervention_mechanism
channel_role
required_signals
attribution_intent
```

结果包括：

```text
EXECUTION_COMPATIBLE
REVIEW_REQUIRED
STRATEGY_RECONFIRM_REQUIRED
```

## 7. Benchmark Channel 纪律

本轮继续锁死：

```text
PRIMARY_BENCHMARK = 知乎
≠
planned_channel = 知乎
≠
selected_channel_instance = 某知乎账号/URL
```

如果 `ZHIHU` 出现在 `planned_channels`，必须有明确 `channel_role`，且不能由
Benchmark 平台直接复制为执行渠道。

## 8. Prompt #40 真实回归

本地回归对象：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
StrategyCandidate #44 = ACCEPTED_WITH_EDITS / VALIDATED
Action #31
Experiment #31
```

Strategy Core 摘要：

```text
target_decision_change:
让「爱短链」在「长链接缩短」这类 AI 回答中，围绕「点击统计、自定义分享标题、
营销场景使用」建立更明确的品牌-能力-推荐理由关联。

primary_intervention_path:
FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION:OFFICIAL_SITE

planned_channels:
OFFICIAL_SITE = PRIMARY
ZHIHU = OBSERVE

asset_direction:
UPDATE_EXISTING / PAGE_SNAPSHOT #3 / https://www.aifabu.com/card

attribution_intent:
primary_capability = 点击统计
secondary_capabilities = 自定义分享标题、营销场景使用
attribution_scope = CAPABILITY_BUNDLE
```

Step 8 模拟结果：

```text
修改普通 URL / 标题 / section
-> EXECUTION_ONLY

OFFICIAL_SITE 执行
-> EXECUTION_COMPATIBLE

知乎观察来源改为百家号执行
-> REVIEW_REQUIRED

修改 intervention_mechanism
-> STRATEGY_CORE_CHANGE
-> RETURN_TO_STEP_7
```

## 9. 不受影响项

本轮不修改：

```text
Evidence lineage
Benchmark tier
Capability Gap
Decision Stability
历史 Experiment
Baseline
Step 9
```

Prompt #40 回归后仍为：

```text
PRIMARY_BENCHMARK = 1
SECONDARY_BENCHMARK = 0
recommended_action_count = 1
```

## 10. 测试

```bash
cd geo-platform/backend
.venv/bin/python -m pytest -q tests/test_strategy_step7_v1.py tests/test_source_gap_v1.py
.venv/bin/python -m compileall -q app

cd geo-platform/frontend
nvm use 18.20.8
npm run build

git diff --check
```

结果：

```text
54 passed
backend compileall passed
frontend build passed
git diff --check passed
```

## 11. 下一 checkpoint

下一刀再开发：

```text
Asset Brief
Claim Matrix
Draft
```

仍不进入 Step 9。

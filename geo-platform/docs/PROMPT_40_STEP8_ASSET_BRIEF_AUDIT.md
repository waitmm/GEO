# Prompt #40 Step 8 Asset Brief + Claim Matrix 审计

状态：待评审
日期：2026-08-31

## 1. 审计边界

本轮只审计 Step 8 的 Asset Brief + Claim Matrix，不生成 Draft、不发布、不复采、不进入 Step 9。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
strategy_candidate_id = 44
action_id = 31
experiment_id = 31
created_new_draft = False
```

## 2. 对象与主链零污染

| 对象 | 运行前 | 运行后 |
| --- | --- | --- |
| StrategyCandidate | 7 | 7 |
| OptimizationAction | 20 | 20 |
| OptimizationExperiment | 20 | 20 |
| Prompt #40 EvidenceAlignment | 660 | 660 |
| PRIMARY_BENCHMARK | 1 | 1 |
| 推荐动作 | 1 | 1 |

结论：Asset Brief 只补充 Step 8 审核快照，不改变 Evidence / Benchmark / Gap / Strategy 计算。

## 3. Strategy Core 与执行上下文

| 字段 | 值 |
| --- | --- |
| target_decision_change | 让「爱短链」在「长链接缩短」这类 AI 回答中，围绕「点击统计、自定义分享标题、营销场景使用」建立更明确的品牌-能力-推荐理由关联；本轮观察覆盖 6 个有效 Run。 |
| intervention_mechanism | 把「爱短链」已确认支持的「点击统计、自定义分享标题、营销场景使用」沉淀为可被 AI 摘录的一方品牌事实信号；针对当前 内容缺口，先让相关资产明确表达品牌-能力-场景关系，再用固定 Run 复测观察目标品牌是否进入候选/推荐理由。本机制基于 6 个有效 Run 的能力级证据链，不复制竞品事实。 |
| primary_intervention_path | FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION:OFFICIAL_SITE |
| channel | OFFICIAL_SITE |
| channel_role | {'channel_label': '官网', 'intervention_priority': 'PRIMARY', 'channel_role': '承载目标品牌自己的能力事实表达和可摘录证据，先修正品牌资产而不是追随对标来源平台。', 'selection_basis': '由 Product Truth、相关品牌资产表达缺口、检索/引用状态共同确定；不是由 Benchmark 平台直接推出。'} |
| asset_operation | UPDATE_EXISTING |
| selected_asset_ref | {'asset_ref_type': 'PAGE_SNAPSHOT', 'asset_id': 3, 'snapshot_id': 3, 'canonical_url': 'https://www.aifabu.com/card', 'url': 'https://www.aifabu.com/card', 'asset_type': 'ARTICLE', 'snapshot_type': 'PRE_RELEASE', 'capture_status': 'success', 'title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'channel': 'OFFICIAL_SITE', 'asset_operation': 'UPDATE_EXISTING'} |

## 4. Claim Matrix：目标品牌 Claim

| 能力 | 表达要求 | Product Truth | 依据 | 边界 |
| --- | --- | --- | --- | --- |
| 点击统计 | REQUIRED | SUPPORTED | PRODUCT_TRUTH | 只能表达已确认 Product Truth 覆盖的「点击统计」能力边界。 |
| 自定义分享标题 | REQUIRED | SUPPORTED | PRODUCT_TRUTH | 只能表达已确认 Product Truth 覆盖的「自定义分享标题」能力边界。 |
| 营销场景使用 | REQUIRED | SUPPORTED | PRODUCT_TRUTH | 只能表达已确认 Product Truth 覆盖的「营销场景使用」能力边界。 |

## 5. Claim Matrix：对标证据上下文

| 能力 | 依据 | Evidence IDs | Run IDs | 边界 |
| --- | --- | --- | --- | --- |
| 点击统计 | ELIGIBLE_BENCHMARK_EVIDENCE | [14803, 14804, 14805, 14806, 14807, 14808, 14809, 14810, 14811, 14812, 14813, 14814] | [238, 239, 240, 253, 254, 255] | 该 Claim 只说明对标证据和市场标准，不得改写为目标品牌事实。 |
| 自定义分享标题 | ELIGIBLE_BENCHMARK_EVIDENCE | [15049, 15050, 15051, 15052, 15053, 15054] | [238, 239, 240, 253, 254, 255] | 该 Claim 只说明对标证据和市场标准，不得改写为目标品牌事实。 |
| 营销场景使用 | ELIGIBLE_BENCHMARK_EVIDENCE | [15187, 15188, 15189, 15190, 15191, 15192, 15199, 15200, 15201, 15202, 15203, 15204, 15205, 15206, 15207, 15208, 15209, 15210] | [238, 239, 240, 253, 254, 255] | 该 Claim 只说明对标证据和市场标准，不得改写为目标品牌事实。 |

## 6. Required Signal 映射

| 能力 | 映射状态 | Claim IDs | Required Signal |
| --- | --- | --- | --- |
| 点击统计 | MAPPED | ['2280aea21c24b277'] | ['回答或引用资料能够明确表达「爱短链 支持 点击统计」'] |
| 自定义分享标题 | MAPPED | ['90548effc2c76a2a'] | ['回答或引用资料能够明确表达「爱短链 支持 自定义分享标题」'] |
| 营销场景使用 | MAPPED | ['fb3e93780d7d2e05'] | ['回答或引用资料能够明确表达「爱短链 支持 营销场景使用」'] |

## 7. 审核状态

```text
before_brief_status = PENDING_REVIEW
after_brief_status = CONFIRMED
draft_gate = READY_FOR_DRAFT_PREPARATION
requirement_counts = {'REQUIRED': 3}
mechanism_compatibility = EXECUTION_COMPATIBLE
```

## 8. 快照落点

| 位置 | 是否包含 asset_brief |
| --- | --- |
| Experiment.intervention_variables_json | True |
| Experiment.controlled_intervention_json | True |
| Experiment.brief_json | True |
| Action.release_evidence_json | True |
| StrategyCandidate.experiment_plan_json | True |

## 9. 边界结论

- Asset Brief 不是 StrategyCandidate，不重写 Strategy Core。
- Claim Matrix 只列事实 Claim，不生成正文段落、FAQ 或 Draft。
- 目标品牌 Claim 只由 Product Truth 支持；Benchmark Evidence 只作为对标上下文。
- Step 8 仍然只创建/复用 Action 与 Experiment Draft；真实发布仍等待 Release Audit。

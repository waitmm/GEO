# Prompt #40 Phase 5 决策稳定性审计

状态：待评审
日期：2026-08-27

## 1. 审计边界

本次只审计 Decision Stability 后置描述指标，不改变单 Prompt V1 1-8 主链。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
version = decision_stability.phase5.v1
metric_role = POST_HOC_DESCRIPTIVE_ONLY
```

## 2. #40 稳定性结果

```text
valid_run_ids = [238, 239, 240, 253, 254, 255]
valid_run_count = 6
brand_decision_run_count = 6
dominant_recommendation_outcome = RECOMMENDATION_ENTITY Bitly
dominant_observed_run_ids = [238, 239, 240, 253, 254, 255]
decision_stability_score = 100 / 100
stability_level = HIGH_STABILITY (高稳定)
formula = round(dominant_recommendation_outcome.run_count / valid_run_count * 100)
```

## 3. 推荐对象覆盖

| 推荐对象 | 覆盖 | 分母 | Run IDs |
| --- | --- | --- | --- |
| Bitly | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 缩我短链接 | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 轻松短链接 | 6 | 6 | [238, 239, 240, 253, 254, 255] |

## 4. 推荐理由覆盖

| 推荐对象 | 理由 | 角色 | 覆盖 | 分母 | Run IDs |
| --- | --- | --- | --- | --- | --- |
| Bitly | ‌Bitly‌提供链接管理、A/B测试等高级功能 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| Bitly | 按需设置自定义后缀、访问密码等配置 | SUPPORTING_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| Bitly | 还支持点击数据追踪等实用功能 | SUPPORTING_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | ‌小码短链接‌支持长链接快速缩短 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | ‌小码短链接‌自带二维码生成 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | ‌小码短链接‌自带点击统计 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | ‌小码短链接‌自带自定义分享标题 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | ‌小码短链接‌适合营销场景使用 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | 按需设置自定义后缀、访问密码等配置 | SUPPORTING_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 小码短链接 | 还支持点击数据追踪等实用功能 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 缩我短链接 | ‌缩我短链接‌可自定义链接有效期 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| 缩我短链接 | ‌缩我短链接‌支持永久免费生成短链接 | DIRECT_REASON | 6 | 6 | [238, 239, 240, 253, 254, 255] |

## 5. 主链零影响对比

| 对象 | 调用稳定性前 | 调用稳定性后 |
| --- | --- | --- |
| EvidenceAlignment 总数 | 660 | 660 |
| 正式 SUPPORTS | 36 | 36 |
| PRIMARY_BENCHMARK | 1 | 1 |
| SECONDARY_BENCHMARK | 0 | 0 |
| CONTENT_GAP | 1 | 1 |
| 推荐动作 | 1 | 1 |
| StrategyCandidate #41 | {'exists': True, 'review_status': 'ACCEPTED_WITH_EDITS', 'effective_validation_status': 'VALIDATED', 'experiment_id': 30} | {'exists': True, 'review_status': 'ACCEPTED_WITH_EDITS', 'effective_validation_status': 'VALIDATED', 'experiment_id': 30} |
| Action #30 | {'exists': True, 'status': 'PLANNED'} | {'exists': True, 'status': 'PLANNED'} |
| Experiment #30 | {'exists': True, 'status': 'draft', 'release_blocked_reason': 'WAITING_FOR_RELEASE_AUDIT', 'baseline_run_ids': [238, 239, 240, 253, 254, 255]} | {'exists': True, 'status': 'draft', 'release_blocked_reason': 'WAITING_FOR_RELEASE_AUDIT', 'baseline_run_ids': [238, 239, 240, 253, 254, 255]} |

```text
decision_stability_formal_output_impact = NONE
```

## 6. 边界说明

Decision Stability 只描述多 Run 推荐结果分布；不参与 Evidence、Benchmark、Gap、Strategy、Action、Experiment 或 Baseline 的任何 Gate。

本阶段不进入 Step 9，不创建复采任务，不产生实验结论。

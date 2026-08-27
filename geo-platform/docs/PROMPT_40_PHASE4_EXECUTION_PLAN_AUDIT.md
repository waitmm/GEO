# Prompt #40 Phase 4 实验方案落地审计

状态：待评审
日期：2026-08-27

## 1. 审计边界

本次只审计 Step 8：人工确认渠道/资产执行方案，并创建 Experiment 草案。不进入发布、复采或效果结论。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
strategy_candidate_id = 41
channel = OFFICIAL_SITE
asset_operation = UPDATE_EXISTING
selected_asset_id = 3
baseline_run_ids = [238, 239, 240, 253, 254, 255]
```

说明：本次审计过程中先生成过一条早期草案用于发现快照冻结点问题，已保留为本地审计历史；修正后重新运行得到的权威 Phase 4 审计对象为 `strategy_candidate_id = 41 / action_id = 30 / experiment_id = 30`。

## 2. 执行表变化

| 对象 | 运行前 | 运行后 |
| --- | --- | --- |
| StrategyCandidate | 1 | 2 |
| OptimizationAction | 17 | 18 |
| OptimizationExperiment | 17 | 18 |

## 3. Step 7 -> Step 8 状态

```text
review_status = ACCEPTED_WITH_EDITS
effective_validation_status = VALIDATED
effective_payload_version = effective_payload.v1
PENDING_HUMAN_CHANNEL_REVIEW 表示 Strategy 已确认但待 Step 8；Step 8 后变为 VALIDATED。
```

## 4. selected_asset_ref

```text
asset_ref_type = PAGE_SNAPSHOT
asset_id = 3
canonical_url = https://www.aifabu.com/card
asset_type = ARTICLE
channel = OFFICIAL_SITE
asset_operation = UPDATE_EXISTING
```

## 5. Baseline Metrics

| 指标 | 层级 | 分子 | 分母 | Run IDs |
| --- | --- | --- | --- | --- |
| brand_mention | brand_level | 0 | 6 | [] |
| brand_candidate | brand_level | 0 | 6 | [] |
| brand_recommendation | brand_level | 0 | 6 | [] |
| target_reason_adoption | brand_level | 0 | 6 | [] |
| brand_retrieval_presence | brand_level | 6 | 6 | [238, 239, 240, 253, 254, 255] |
| brand_citation_presence | brand_level | 0 | 6 | [] |
| selected_asset_retrieval_presence | selected_asset_level | 0 | 6 | [] |
| selected_asset_citation_presence | selected_asset_level | 0 | 6 | [] |

## 6. Action / Experiment 草案

```text
action_id = 30
action_status = PLANNED
experiment_id = 30
experiment_status = draft
release_blocked = True
release_blocked_reason = WAITING_FOR_RELEASE_AUDIT
experiment_baseline_run_ids = [238, 239, 240, 253, 254, 255]
```

## 7. 快照冻结

```text
strategy_snapshot.strategy_candidate_id = 41
strategy_snapshot.effective_validation_status = VALIDATED
strategy_snapshot.target_platform = OFFICIAL_SITE
strategy_snapshot.target_asset = PAGE_SNAPSHOT:3
strategy_snapshot.target_content_type = ARTICLE
intervention_variables.selected_asset_ref = {'asset_ref_type': 'PAGE_SNAPSHOT', 'asset_id': 3, 'snapshot_id': 3, 'canonical_url': 'https://www.aifabu.com/card', 'url': 'https://www.aifabu.com/card', 'asset_type': 'ARTICLE', 'snapshot_type': 'PRE_RELEASE', 'capture_status': 'success', 'title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'channel': 'OFFICIAL_SITE', 'asset_operation': 'UPDATE_EXISTING'}
```

## 8. 结论

Phase 4 复用现有 StrategyCandidate/effective_payload、OptimizationAction 和 OptimizationExperiment。
Step 8 已将人工确认的渠道、资产操作和资产引用冻结进 Experiment 草案；Baseline Metrics 明确绑定固定 Run IDs，属于 Experiment 语义。
本次不进入自动发布、Release Audit、固定复采或 Step 9。

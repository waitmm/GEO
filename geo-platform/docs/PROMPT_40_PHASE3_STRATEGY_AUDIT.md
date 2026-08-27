# Prompt #40 Phase 3 StrategyCandidate 审计

状态：待评审
日期：2026-08-27

## 1. 审计边界

本次只审计 Step 7：StrategyCandidate + 人工 Strategy 确认。不进入 Step 8，不创建 Action / Experiment。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
use_answer_binding_v1_1 = true
```

## 2. 执行表变化

| 对象 | 运行前 | 运行后 |
| --- | --- | --- |
| StrategyCandidate | 0 | 1 |
| OptimizationAction | 16 | 16 |
| OptimizationExperiment | 16 | 16 |

## 3. capability-level Gap 输入

| gap_item_id | 能力/理由 | Gap | 最早失败层 | Benchmark Evidence | Observed Runs |
| --- | --- | --- | --- | --- | --- |
| 1e918cd2d02b5e2c | 点击统计 | CONTENT_GAP | RELEVANT_ASSET_EXPRESSION | [14803, 14804, 14805, 14806, 14807, 14808, 14809, 14810, 14811, 14812, 14813, 14814] | [238, 239, 240, 253, 254, 255] |
| 749abd4e4483e2f8 | 自定义分享标题 | CONTENT_GAP | RELEVANT_ASSET_EXPRESSION | [15049, 15050, 15051, 15052, 15053, 15054] | [238, 239, 240, 253, 254, 255] |
| 94b806415ebbd29e | 营销场景使用 | CONTENT_GAP | RELEVANT_ASSET_EXPRESSION | [15187, 15188, 15189, 15190, 15191, 15192, 15199, 15200, 15201, 15202, 15203, 15204, 15205, 15206, 15207, 15208, 15209, 15210] | [238, 239, 240, 253, 254, 255] |

## 4. StrategyCandidate

```text
candidate_id = 40
generation_status = GENERATED
review_status_before = PENDING_REVIEW
effective_validation_status_before = PENDING
review_status_after = ACCEPTED_WITH_EDITS
effective_validation_status_after = PENDING_HUMAN_CHANNEL_REVIEW
effective_payload_version = effective_payload.v1
```

## 5. 候选策略结构

```text
gap_item_ids = ['1e918cd2d02b5e2c', '749abd4e4483e2f8', '94b806415ebbd29e']
target_capability_or_reason = 点击统计、自定义分享标题、营销场景使用
gap_type = CONTENT_GAP
benchmark_evidence_ids = [14803, 14804, 14805, 14806, 14807, 14808, 14809, 14810, 14811, 14812, 14813, 14814, 15049, 15050, 15051, 15052, 15053, 15054, 15187, 15188, 15189, 15190, 15191, 15192, 15199, 15200, 15201, 15202, 15203, 15204, 15205, 15206, 15207, 15208, 15209, 15210]
product_truth_refs = {'status': 'TRUE', 'ids': [4]}
relevant_asset_refs = [{'status': 'AVAILABLE', 'snapshot_id': 3, 'url': 'https://www.aifabu.com/card', 'title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_status': 'RELEVANT', 'coverage': 'MISSING', 'reason': '已找到可用于判断的品牌资产快照。', 'audit': {'candidate_snapshot_ids': [3], 'selected_snapshot_id': 3, 'selected_url': 'https://www.aifabu.com/card', 'selected_title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_score': 1, 'matched_terms': ['长链接缩短'], 'relevance_status': 'RELEVANT', 'selection_method': 'CAPABILITY_PROMPT_RELEVANCE'}}, {'status': 'AVAILABLE', 'snapshot_id': 3, 'url': 'https://www.aifabu.com/card', 'title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_status': 'RELEVANT', 'coverage': 'MISSING', 'reason': '已找到可用于判断的品牌资产快照。', 'audit': {'candidate_snapshot_ids': [3], 'selected_snapshot_id': 3, 'selected_url': 'https://www.aifabu.com/card', 'selected_title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_score': 1, 'matched_terms': ['长链接缩短'], 'relevance_status': 'RELEVANT', 'selection_method': 'CAPABILITY_PROMPT_RELEVANCE'}}, {'status': 'AVAILABLE', 'snapshot_id': 3, 'url': 'https://www.aifabu.com/card', 'title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_status': 'RELEVANT', 'coverage': 'MISSING', 'reason': '已找到可用于判断的品牌资产快照。', 'audit': {'candidate_snapshot_ids': [3], 'selected_snapshot_id': 3, 'selected_url': 'https://www.aifabu.com/card', 'selected_title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_score': 1, 'matched_terms': ['长链接缩短'], 'relevance_status': 'RELEVANT', 'selection_method': 'CAPABILITY_PROMPT_RELEVANCE'}}]
observed_run_ids = [238, 239, 240, 253, 254, 255]
proposed_direction = CONTENT
mechanism = 如果目标品牌已真实具备这些能力，但当前相关资产没有形成可被引用和摘录的能力表达，则补齐能力说明、适用场景和证据表达，可能提高后续 AI 回答中目标品牌进入候选/推荐理由的机会。
why_candidate = 该候选只来自已完成的 capability-level Gap、Phase 2A eligible Benchmark Evidence、Product Truth 和冻结的 Relevant Asset Snapshot；Step 7 不重新执行 Citation/Evidence/Gap 推理。
blockers = ['待人工确认 Strategy 机制和范围', 'Step 8 前不得选择发布平台或创建执行任务', 'target_platform / target_asset / target_content_type 仍为 UNRESOLVED 时不得物化 Action/Experiment']
validation_metric = brand_mention_rate
target_platform = UNRESOLVED
target_asset = UNRESOLVED
benchmark_channel_boundary = Benchmark 来源平台不能自动成为 Strategy 执行平台；平台和资产选择属于 Step 8。
```

## 6. 人工编辑后的 effective_payload 摘要

```text
human_review_summary = 确认 #40 的能力表达缺口成立；本次只冻结 Strategy 语义，不创建动作或实验。
confirmed_strategy_scope = 围绕点击统计、自定义分享标题、营销场景使用补齐目标品牌资产表达。
target_platform = UNRESOLVED
target_asset = UNRESOLVED
target_content_type = UNRESOLVED
snapshot_policy = 未来 Experiment 必须绑定创建时已确认的 effective_payload 快照，不得读取候选后续修改作为历史依据。
```

## 7. Gate 验证

```text
before_review_strategy_to_experiment_plan = 只有人工接受后的策略候选才能转换实验计划
after_review_strategy_to_experiment_plan = Strategy Candidate #40 effective payload is not validated (status=PENDING_HUMAN_CHANNEL_REVIEW). Cannot execute. Backfilled candidates must be re-validated before execution.
Action/Experiment count unchanged = true
```

## 8. 结论

Phase 3 已生成并人工确认 StrategyCandidate，但 effective_payload 仍处于 PENDING_HUMAN_CHANNEL_REVIEW。
这表示 Strategy 语义已确认，执行平台/资产/内容类型仍属于 Step 8；后端 Gate 阻止其创建 Action 或 Experiment。

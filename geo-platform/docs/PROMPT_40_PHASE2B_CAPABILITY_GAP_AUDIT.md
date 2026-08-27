# Prompt #40 Phase 2B Capability Gap 回归审计

状态：待评审
日期：2026-08-27

## 1. 审计边界

本次只审计 capability/reason-level Gap Diagnosis，不进入 Step 7，不创建动作或实验。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
use_answer_binding_v1_1 = true
decision_tree = Product Truth -> Relevant Asset Expression -> RetrievalCandidate -> Evidence Adoption
```

## 2. 零污染核对

| 对象 | 运行前 | 运行后 |
| --- | --- | --- |
| SourceClaim 总数 | 577 | 577 |
| Prompt #40 EvidenceAlignment 总数 | 660 | 660 |

## 3. Proposal 摘要

```text
status = READY_FOR_HUMAN_CONFIRM
source_count = 68
primary_benchmark_count = 1
secondary_benchmark_count = 0
existing_downstream_recommended_action_count = 1
existing_downstream_channel_opportunity_count = 1
all_source_gap_counts = {'CONTENT_GAP': 1, 'null': 67}
all_capability_gap_layer_counts = {'EMPTY': 67, 'RELEVANT_ASSET_EXPRESSION': 1}
benchmark_gap_counts = {'CONTENT_GAP': 1}
benchmark_layer_counts = {'RELEVANT_ASSET_EXPRESSION': 1}
```

说明：以上下游动作/渠道计数来自现有 `citation_decision_vertical_slice` 摘要，用于提示当前接口仍会投影后续结果；Phase 2B 本身没有开发或创建 Step 7/Step 8 对象。

## 4. 核心/辅助对标来源 Gap 逐条结果

| SourceDocument | 来源 | 对标层级 | 缺口类型 | 最早失败层 | 能力目标 | 未匹配能力 | Product Truth | 资产快照 | 资产覆盖 | 检索状态 | 采纳状态 | 冻结 failure_layer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 345 | 如何将长链接缩短-小码至营 | PRIMARY_BENCHMARK | CONTENT_GAP | RELEVANT_ASSET_EXPRESSION | 点击统计 / 自定义分享标题 / 营销场景使用 |  | TRUE | 3 | MISSING | RETRIEVED | NOT_ADOPTED | RELEVANT_ASSET_EXPRESSION |

## 5. 冻结诊断快照示例

```text
source_document_id = 345
source_gap_type = CONTENT_GAP
source_gap_precondition = READY
source_gap_reason = 目标品牌事实已确认，但现有品牌资产未覆盖对标来源中的关键能力表达。
capability_gap_layer = RELEVANT_ASSET_EXPRESSION
capability_truth_targets = [{'label': '点击统计', 'source': 'ANSWER_UNIT', 'answer_unit_id': 1086, 'alignment_id': 14803, 'alignment_ids': [14803, 14804, 14805, 14806, 14807, 14808, 14809, 14810, 14811, 14812, 14813, 14814], 'observed_run_ids': [238, 239, 240, 253, 254, 255], 'run_coverage_count': 6}, {'label': '自定义分享标题', 'source': 'ANSWER_UNIT', 'answer_unit_id': 1088, 'alignment_id': 15049, 'alignment_ids': [15049, 15050, 15051, 15052, 15053, 15054], 'observed_run_ids': [238, 239, 240, 253, 254, 255], 'run_coverage_count': 6}, {'label': '营销场景使用', 'source': 'ANSWER_UNIT', 'answer_unit_id': 1089, 'alignment_id': 15187, 'alignment_ids': [15187, 15188, 15189, 15190, 15191, 15192, 15199, 15200, 15201, 15202, 15203, 15204, 15205, 15206, 15207, 15208, 15209, 15210], 'observed_run_ids': [238, 239, 240, 253, 254, 255], 'run_coverage_count': 6}]
unmatched_capability_truth_targets = []
relevant_asset_snapshot = {'status': 'AVAILABLE', 'snapshot_id': 3, 'url': 'https://www.aifabu.com/card', 'title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_status': 'RELEVANT', 'coverage': 'MISSING', 'reason': '已找到可用于判断的品牌资产快照。', 'audit': {'candidate_snapshot_ids': [3], 'selected_snapshot_id': 3, 'selected_url': 'https://www.aifabu.com/card', 'selected_title': '抖音卡片_微信卡片_直播间卡片-爱短链', 'relevance_score': 1, 'matched_terms': ['长链接缩短'], 'relevance_status': 'RELEVANT', 'selection_method': 'CAPABILITY_PROMPT_RELEVANCE'}}
retrieval_candidate_context = {'status': 'RETRIEVED', 'retrieved': True, 'valid_retrieval_count': 258, 'observed_run_ids': [238, 239, 240, 253, 254, 255], 'matched_retrievals': [{'id': 3563, 'run_id': 238, 'rank': 8, 'title': '长链接缩短:在线一键把长链接缩短免费', 'url': 'https://www.aifabu.com/details/42360', 'domain': 'aifabu.com'}, {'id': 3756, 'run_id': 239, 'rank': 8, 'title': '长链接缩短:在线一键把长链接缩短免费', 'url': 'https://www.aifabu.com/details/42360', 'domain': 'aifabu.com'}, {'id': 3947, 'run_id': 240, 'rank': 7, 'title': '长链接缩短:在线一键把长链接缩短免费', 'url': 'https://www.aifabu.com/details/42360', 'domain': 'aifabu.com'}, {'id': 4139, 'run_id': 253, 'rank': 7, 'title': '长链接缩短:在线一键把长链接缩短免费', 'url': 'https://www.aifabu.com/details/42360', 'domain': 'aifabu.com'}, {'id': 4332, 'run_id': 254, 'rank': 8, 'title': '长链接缩短:在线一键把长链接缩短免费', 'url': 'https://www.aifabu.com/details/42360', 'domain': 'aifabu.com'}, {'id': 4521, 'run_id': 255, 'rank': 8, 'title': '长链接缩短:在线一键把长链接缩短免费', 'url': 'https://www.aifabu.com/details/42360', 'domain': 'aifabu.com'}], 'rule': '仅使用当前证据包 Run 内有 URL/域名/标题信号的有效 RetrievalCandidate。'}
evidence_adoption_context = {'status': 'NOT_ADOPTED', 'adopted': False, 'observed_run_ids': [238, 239, 240, 253, 254, 255], 'matched_citations': [], 'matched_adoptions': [], 'boundary_note': '引用/采纳上下文不等于模型内部因果，只用于判断当前样本是否出现目标品牌资产采纳迹象。'}
eligible_evidence_lineage = {'supporting_alignment_ids': [14803, 14804, 14805, 14806, 14807, 14808, 14809, 14810, 14811, 14812, 14813, 14814, 15049, 15050, 15051, 15052, 15053, 15054, 15187, 15188, 15189, 15190, 15191, 15192, 15199, 15200, 15201, 15202, 15203, 15204, 15205, 15206, 15207, 15208, 15209, 15210], 'observed_run_ids': [238, 239, 240, 253, 254, 255]}
```

## 6. 结论

本次 #40 回归只验证 Gap 诊断层：Product Truth、资产表达、有效检索、引用/采纳上下文均写入可审计快照。
推荐动作和实验草案不属于 Phase 2B，本次未进入 Step 7。

# Prompt #40 Phase 2A EvidenceAlignment Run Lineage 审计

状态：待评审
日期：2026-08-27

## 1. 审计边界

本次只验证 EvidenceAlignment 的 Run lineage、一致性和正式 V1 消费资格。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
source_run_ids = [238, 239, 240, 253, 254, 255]
phase = Phase 2A
scope = EvidenceAlignment lineage eligibility only
```

本次没有进入 DISCOVERABILITY_GAP、Step 7、Step 8、Decision Stability，也没有修改 Citation / Benchmark 评分公式。

## 2. 正式链零污染核对

| 对象 | 运行前 | 运行后 |
| --- | --- | --- |
| SourceClaim 总数 | 577 | 577 |
| Prompt #40 EvidenceAlignment 总数 | 660 | 660 |
| 正式状态 | READY_FOR_HUMAN_CONFIRM | READY_FOR_HUMAN_CONFIRM |
| PRIMARY_BENCHMARK | 1 | 1 |
| SECONDARY_BENCHMARK | 0 | 0 |
| 推荐动作 | 1 | 1 |
| 渠道机会 | 1 | 1 |

结论：本审计脚本只读执行；正式表计数和正式派生输出前后一致。

## 3. 现有模型真实关系图

```text
BrowserMonitorRun
├── RecommendationEvent(run_id)
├── AnswerUnit(run_id)
├── AnswerDecisionBinding(run_id, recommendation_event_id, answer_unit_id)
└── ReferenceSource(run_id, url/canonical_url/domain/title)
        ↓ URL/domain-title matching
    SourceDocument(url/original_url/canonical_url/domain/title)
        ↓
    SourceClaim(source_document_id)
        ↓
    EvidenceAlignment(run_id, recommendation_event_id, source_document_id, source_claim_id)
```

SourceDocument 和 SourceClaim 是文档级事实，可跨 Run 复用；正式 V1 的 Run lineage 由当前 Run 的引用实例和答案侧绑定共同证明。

## 4. Run 级分布

| Run | 采集状态 | RecommendationEvent | AnswerDecisionBinding | ReferenceSource | 全部 Alignment | Eligible Alignment | Ineligible 原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 238 | success | 4 | 188 | 29 | NO_SUPPORT=104, SUPPORTS=6 | NO_SUPPORT=5, SUPPORTS=6 | LEGACY_RELATION_ONLY=99 |
| 239 | success | 4 | 174 | 29 | NO_SUPPORT=104, SUPPORTS=6 | NO_SUPPORT=5, SUPPORTS=6 | LEGACY_RELATION_ONLY=99 |
| 240 | success | 4 | 174 | 29 | NO_SUPPORT=104, SUPPORTS=6 | NO_SUPPORT=5, SUPPORTS=6 | LEGACY_RELATION_ONLY=99 |
| 253 | success | 4 | 174 | 29 | NO_SUPPORT=104, SUPPORTS=6 | NO_SUPPORT=5, SUPPORTS=6 | LEGACY_RELATION_ONLY=99 |
| 254 | success | 4 | 174 | 29 | NO_SUPPORT=104, SUPPORTS=6 | NO_SUPPORT=5, SUPPORTS=6 | LEGACY_RELATION_ONLY=99 |
| 255 | success | 4 | 174 | 29 | NO_SUPPORT=104, SUPPORTS=6 | NO_SUPPORT=5, SUPPORTS=6 | LEGACY_RELATION_ONLY=99 |

## 5. 正式 SUPPORTS 逐条 lineage

| Alignment | Run | Eligible | Ineligible 原因 | AnswerUnit | SourceClaim | SourceDocument | ReferenceSource 证明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 14803 | 238 | 是 | - | 1086: ‌小码短链接‌自带点击统计 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4330: 如何将长链接缩短-小码至营 |
| 14809 | 238 | 是 | - | 1086: ‌小码短链接‌自带点击统计 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4330: 如何将长链接缩短-小码至营 |
| 15049 | 238 | 是 | - | 1088: ‌小码短链接‌自带自定义分享标题 | 813: 小码短链接的自定义分享功能支持设置标题和描述 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4330: 如何将长链接缩短-小码至营 |
| 15187 | 238 | 是 | - | 1089: ‌小码短链接‌适合营销场景使用 | 814: 小码短链接的自定义分享功能能增加用户点击兴趣 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4330: 如何将长链接缩短-小码至营 |
| 15199 | 238 | 是 | - | 1089: ‌小码短链接‌适合营销场景使用 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4330: 如何将长链接缩短-小码至营 |
| 15205 | 238 | 是 | - | 1089: ‌小码短链接‌适合营销场景使用 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4330: 如何将长链接缩短-小码至营 |
| 14804 | 239 | 是 | - | 1122: ‌小码短链接‌自带点击统计 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4479: 如何将长链接缩短-小码至营 |
| 14810 | 239 | 是 | - | 1122: ‌小码短链接‌自带点击统计 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4479: 如何将长链接缩短-小码至营 |
| 15050 | 239 | 是 | - | 1124: ‌小码短链接‌自带自定义分享标题 | 813: 小码短链接的自定义分享功能支持设置标题和描述 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4479: 如何将长链接缩短-小码至营 |
| 15188 | 239 | 是 | - | 1125: ‌小码短链接‌适合营销场景使用 | 814: 小码短链接的自定义分享功能能增加用户点击兴趣 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4479: 如何将长链接缩短-小码至营 |
| 15200 | 239 | 是 | - | 1125: ‌小码短链接‌适合营销场景使用 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4479: 如何将长链接缩短-小码至营 |
| 15206 | 239 | 是 | - | 1125: ‌小码短链接‌适合营销场景使用 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4479: 如何将长链接缩短-小码至营 |
| 14805 | 240 | 是 | - | 1158: ‌小码短链接‌自带点击统计 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4628: 如何将长链接缩短-小码至营 |
| 14811 | 240 | 是 | - | 1158: ‌小码短链接‌自带点击统计 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4628: 如何将长链接缩短-小码至营 |
| 15051 | 240 | 是 | - | 1160: ‌小码短链接‌自带自定义分享标题 | 813: 小码短链接的自定义分享功能支持设置标题和描述 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4628: 如何将长链接缩短-小码至营 |
| 15189 | 240 | 是 | - | 1161: ‌小码短链接‌适合营销场景使用 | 814: 小码短链接的自定义分享功能能增加用户点击兴趣 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4628: 如何将长链接缩短-小码至营 |
| 15201 | 240 | 是 | - | 1161: ‌小码短链接‌适合营销场景使用 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4628: 如何将长链接缩短-小码至营 |
| 15207 | 240 | 是 | - | 1161: ‌小码短链接‌适合营销场景使用 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4628: 如何将长链接缩短-小码至营 |
| 14806 | 253 | 是 | - | 1194: ‌小码短链接‌自带点击统计 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4777: 如何将长链接缩短-小码至营 |
| 14812 | 253 | 是 | - | 1194: ‌小码短链接‌自带点击统计 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4777: 如何将长链接缩短-小码至营 |
| 15052 | 253 | 是 | - | 1196: ‌小码短链接‌自带自定义分享标题 | 813: 小码短链接的自定义分享功能支持设置标题和描述 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4777: 如何将长链接缩短-小码至营 |
| 15190 | 253 | 是 | - | 1197: ‌小码短链接‌适合营销场景使用 | 814: 小码短链接的自定义分享功能能增加用户点击兴趣 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4777: 如何将长链接缩短-小码至营 |
| 15202 | 253 | 是 | - | 1197: ‌小码短链接‌适合营销场景使用 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4777: 如何将长链接缩短-小码至营 |
| 15208 | 253 | 是 | - | 1197: ‌小码短链接‌适合营销场景使用 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4777: 如何将长链接缩短-小码至营 |
| 14807 | 254 | 是 | - | 1230: ‌小码短链接‌自带点击统计 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4926: 如何将长链接缩短-小码至营 |
| 14813 | 254 | 是 | - | 1230: ‌小码短链接‌自带点击统计 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4926: 如何将长链接缩短-小码至营 |
| 15053 | 254 | 是 | - | 1232: ‌小码短链接‌自带自定义分享标题 | 813: 小码短链接的自定义分享功能支持设置标题和描述 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4926: 如何将长链接缩短-小码至营 |
| 15191 | 254 | 是 | - | 1233: ‌小码短链接‌适合营销场景使用 | 814: 小码短链接的自定义分享功能能增加用户点击兴趣 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4926: 如何将长链接缩短-小码至营 |
| 15203 | 254 | 是 | - | 1233: ‌小码短链接‌适合营销场景使用 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4926: 如何将长链接缩短-小码至营 |
| 15209 | 254 | 是 | - | 1233: ‌小码短链接‌适合营销场景使用 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 4926: 如何将长链接缩短-小码至营 |
| 14808 | 255 | 是 | - | 1266: ‌小码短链接‌自带点击统计 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 5075: 如何将长链接缩短-小码至营 |
| 14814 | 255 | 是 | - | 1266: ‌小码短链接‌自带点击统计 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 5075: 如何将长链接缩短-小码至营 |
| 15054 | 255 | 是 | - | 1268: ‌小码短链接‌自带自定义分享标题 | 813: 小码短链接的自定义分享功能支持设置标题和描述 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 5075: 如何将长链接缩短-小码至营 |
| 15192 | 255 | 是 | - | 1269: ‌小码短链接‌适合营销场景使用 | 814: 小码短链接的自定义分享功能能增加用户点击兴趣 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 5075: 如何将长链接缩短-小码至营 |
| 15204 | 255 | 是 | - | 1269: ‌小码短链接‌适合营销场景使用 | 816: 小码短链接自带数据统计功能 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 5075: 如何将长链接缩短-小码至营 |
| 15210 | 255 | 是 | - | 1269: ‌小码短链接‌适合营销场景使用 | 817: 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 345: https://www.zhuanlan.zhihu.com/p/938392385 | 5075: 如何将长链接缩短-小码至营 |

## 6. Prompt-level observed_run_ids 推导

```text
eligible_support_observed_run_ids = [238, 239, 240, 253, 254, 255]
eligible_support_run_coverage = 6/6
```

该集合只来自通过完整 lineage 的 SUPPORTS Alignment 的去重 run_id，不从 Prompt 下所有 Run、payload observed_run_ids 或同一 SourceDocument 出现情况反推。

## 7. Ineligible Alignment 摘要

```text
LEGACY_RELATION_ONLY=594
```

| Alignment | Run | Relation | 原因 | SourceDocument | SourceClaim |
| --- | --- | --- | --- | --- | --- |
| 14623 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 808 |
| 14635 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 810 |
| 14641 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 811 |
| 14647 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 812 |
| 14653 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 813 |
| 14659 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 814 |
| 14665 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 815 |
| 14671 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 816 |
| 14677 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 817 |
| 14683 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 818 |
| 14689 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 819 |
| 14695 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 828 |
| 14701 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 829 |
| 14707 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 830 |
| 14713 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 831 |
| 14719 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 832 |
| 14725 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 833 |
| 14731 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 834 |
| 14737 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 835 |
| 14743 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 836 |
| 14749 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 837 |
| 14755 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 808 |
| 14767 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 810 |
| 14773 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 811 |
| 14779 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 812 |
| 14785 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 813 |
| 14791 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 814 |
| 14797 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 815 |
| 14815 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 818 |
| 14821 | 238 | RELATED | LEGACY_RELATION_ONLY=1 | 345 | 819 |

仅展示前 30 条；完整 ineligible 数量：594。

## 8. 结论

正式 SUPPORTS 覆盖 Evidence Package 内全部 Run，且每条 SUPPORTS 均能证明 AnswerUnit、Binding、RecommendationEvent、ReferenceSource、SourceDocument、SourceClaim 的完整链路。

历史 Alignment 保留；未通过 lineage 的 Alignment 可供 Legacy 查看，但不能进入新的正式单 Prompt V1 Benchmark / Gap / StrategyCandidate 证据。


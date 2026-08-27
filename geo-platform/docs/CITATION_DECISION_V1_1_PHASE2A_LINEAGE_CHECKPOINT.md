# Citation Decision V1.1 Phase 2A Lineage Checkpoint

状态：READY_FOR_REVIEW
日期：2026-08-27

## 1. 本阶段边界

Phase 2A 只处理：

```text
EvidenceAlignment 的 Run lineage
EvidenceAlignment 的一致性验证
正式 V1 消费资格
```

本阶段不处理：

```text
DISCOVERABILITY_GAP
Step 7 / Step 8
Decision Stability
Citation / Benchmark 评分公式调整
前端遮盖后端归属问题
历史 Evidence 清空或重建
```

## 2. 现有模型真实关系

当前仓库中真实关系是：

```text
BrowserMonitorRun
├── answer_text
├── RecommendationEvent.run_id
├── AnswerUnit.run_id
├── AnswerDecisionBinding.run_id
│   ├── recommendation_event_id
│   └── answer_unit_id
└── ReferenceSource.run_id
    ├── url
    ├── canonical_url
    ├── domain
    └── display_title / matched_title

SourceDocument
├── url / original_url / canonical_url
├── domain
└── title
    ↓
SourceClaim.source_document_id

EvidenceAlignment
├── run_id
├── recommendation_event_id
├── source_document_id
├── source_claim_id
└── machine_payload_json.answer_unit_id / decision_binding_id
```

正确的 Run lineage 不是要求 `SourceDocument` 或 `SourceClaim` 自己带
`run_id`，而是要求：

```text
当前 Run 的 AnswerUnit
当前 Run 的 AnswerDecisionBinding
当前 Run 的 RecommendationEvent
当前 Run 的 ReferenceSource
同一个 SourceDocument
同一个 SourceClaim
同一个 EvidenceAlignment
```

能够完整闭合。

## 3. Source of Truth 修正

已修正文档中的错误风险：

```text
SourceDocument / SourceClaim 不是 Run 级重复事实；
它们是可跨 Run 复用的文档级事实。
```

禁止为了建立 lineage 做以下事情：

```text
给同一 SourceDocument 按 Run 重复建档
给同一 SourceClaim 按 Run 重复抽取
强制要求 SourceClaim 本身带 run_id
只检查 EvidenceAlignment.run_id 非空
```

## 4. 复用 / 新增 / 废弃映射

| 类型 | 对象 | 处理 |
| --- | --- | --- |
| REUSE | `BrowserMonitorRun` | 作为 Run lineage 根节点。 |
| REUSE | `ReferenceSource` | 作为当前 Run 真实引用实例。 |
| REUSE | `SourceDocument` | 作为跨 Run 可复用文档事实。 |
| REUSE | `SourceClaim` | 作为跨 Run 可复用来源主张。 |
| REUSE | `AnswerUnit` | 作为答案侧原子理由事实。 |
| REUSE | `AnswerDecisionBinding` | 作为答案理由与推荐事件绑定事实。 |
| REUSE | `EvidenceAlignment` | 作为正式对齐事实，但必须通过 V1 eligibility。 |
| EXTEND | `source_analysis` / Benchmark 派生 | 新增集中 eligibility 过滤，不改评分公式。 |
| NEW | `evidence_lineage.py` | 集中式 V1 正式消费资格判断。 |
| NEW | `test_evidence_lineage_v1.py` | 覆盖 Run lineage 和 observed_run_ids 推导。 |
| DEPRECATE_FOR_V1 | Legacy `RELATED` / 无完整 lineage Alignment | 保留历史展示，不进入正式单 Prompt V1 决策。 |

本阶段不新增平行 Strategy、Benchmark、Opportunity 或 Experiment 表。

## 5. 集中式 Eligibility 规则

正式 V1 消费前统一调用：

```text
evaluate_evidence_alignment_v1_eligibility
eligible_evidence_alignments_for_v1
```

核心判断：

```text
1. EvidenceAlignment 必须属于当前 Project / Prompt / Package Run 集。
2. AnswerUnit 必须存在，且 project_id / prompt_id / run_id 一致。
3. AnswerDecisionBinding 必须存在，且与 AnswerUnit、RecommendationEvent、Run 一致。
4. RecommendationEvent 必须存在，且属于同一 Run。
5. SourceDocument 必须存在。
6. SourceClaim 必须存在，且属于该 SourceDocument。
7. 当前 Run 必须真实存在 ReferenceSource 指向该 SourceDocument。
8. Legacy RELATED 或非 V1.1 完整 lineage Alignment 不能进入正式 V1。
9. `use_answer_binding_v1_1=false` 时，V1.1-derived Alignment 不能被读取消费。
```

输出：

```text
eligible_for_v1: true / false
ineligibility_reasons: [...]
reference_source_id: 可证明当前 Run 引用了该文档的 ReferenceSource
```

主要 ineligibility reason：

```text
MISSING_RUN_LINEAGE
RUN_NOT_IN_CURRENT_PACKAGE
RUN_MISMATCH
MISSING_RECOMMENDATION_EVENT
MISSING_ANSWER_UNIT
MISSING_DECISION_BINDING
SOURCE_DOCUMENT_MISMATCH
SOURCE_NOT_REFERENCED_IN_RUN
LEGACY_RELATION_ONLY
ANSWER_BINDING_V1_1_DISABLED
```

## 6. 正式查询接入

已接入正式 `source_analysis -> _attach_decision_support_benchmarks ->
_decision_support_by_doc_id` 路径。

只有通过 eligibility 的 Alignment 才能进入：

```text
SUPPORTS / CONTRADICTS 统计
Decision Support Level
PRIMARY / SECONDARY Benchmark 判定
Source Gap
Priority / Action Route
StrategyCandidate benchmark evidence
```

未通过的 Alignment 会保留，并在 source row payload 中记录：

```text
ineligible_alignment_counts
```

## 7. observed_run_ids 纪律

正式 Prompt-level 覆盖只能由真实 eligible Alignment 的 `run_id` 去重推导：

```text
eligible SUPPORTS
-> unique run_id
-> observed_run_ids / run_coverage
```

禁止：

```text
从 Prompt 下所有 Run 直接填充
从 Alignment payload 复制 observed_run_ids
因为同一 SourceDocument 出现就推断所有 Run 支持
人工补齐不存在的 Run 归属
```

## 8. 是否需要 Migration

不需要 migration。

原因：

```text
1. 本阶段不新增数据库字段。
2. SourceDocument / SourceClaim 保持文档级事实，不加 run_id。
3. Eligibility 通过现有字段和 payload 中已有 answer_unit_id / decision_binding_id 判断。
4. 历史 Alignment 保留，通过动态 eligibility 排除正式 V1 消费。
```

## 9. 测试

新增测试文件：

```text
backend/tests/test_evidence_lineage_v1.py
```

覆盖：

```text
1. 同一 SourceDocument 被两个 Run 引用，SourceClaim 可复用，observed_run_ids 包含两个 Run。
2. SourceDocument 存在但当前 Run 未引用时，Alignment 不 eligible。
3. AnswerUnit 与 RecommendationEvent 跨 Run 错配时，Alignment 不 eligible。
4. 只有 run_id 但引用实例不属于该 Run 时，Alignment 不 eligible。
5. Legacy Alignment 保留但不进入正式 V1 Benchmark。
6. observed_run_ids 只能来自真实 eligible Run。
7. 同一 SourceClaim 跨 Run 复用，不重复创建 SourceClaim。
```

验证命令：

```bash
cd geo-platform/backend
.venv/bin/python -m pytest -q tests/test_evidence_lineage_v1.py tests/test_citation_prominence_v1.py tests/test_source_gap_v1.py
```

结果：

```text
38 passed
```

## 10. Prompt #40 真实审计

审计文档：

```text
docs/PROMPT_40_PHASE2A_LINEAGE_AUDIT.md
```

真实结果：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
source_run_ids = [238, 239, 240, 253, 254, 255]
```

正式链零污染：

```text
SourceClaim: 577 -> 577
Prompt #40 EvidenceAlignment: 660 -> 660
PRIMARY_BENCHMARK: 1 -> 1
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 1 -> 1
channel_opportunity_count: 1 -> 1
```

Run 级 eligible SUPPORTS：

```text
Run #238: SUPPORTS = 6
Run #239: SUPPORTS = 6
Run #240: SUPPORTS = 6
Run #253: SUPPORTS = 6
Run #254: SUPPORTS = 6
Run #255: SUPPORTS = 6
```

Prompt-level observed_run_ids 真实推导：

```text
eligible_support_observed_run_ids = [238, 239, 240, 253, 254, 255]
eligible_support_run_coverage = 6/6
```

历史 `RELATED`：

```text
LEGACY_RELATION_ONLY = 594
```

结论：

```text
之前担心的“SUPPORTS 只落在某一个 Run，却在 Prompt 层显示多个 Runs”
已被 eligibility 和真实审计阻止。
```

## 11. 兼容策略

历史数据：

```text
保留，不删除，不重绑历史 Experiment。
```

Legacy Alignment：

```text
可继续用于历史页面或 Legacy 兼容查看；
不能进入新的正式单 Prompt V1 Benchmark / Gap / StrategyCandidate 证据链。
```

V1.1 Feature Flag：

```text
关闭时不消费 V1.1-derived Alignment；
打开时仍必须通过完整 lineage eligibility。
```

## 12. 尚未解决的问题

本阶段刻意不处理：

```text
DISCOVERABILITY_GAP
Step 7 / Step 8 交互
Decision Stability
多 Prompt 泛化验证
Citation / Benchmark 评分公式
推荐动作文案质量
实验草案创建体验
```

这些应进入后续 Phase，不能混入 Phase 2A。

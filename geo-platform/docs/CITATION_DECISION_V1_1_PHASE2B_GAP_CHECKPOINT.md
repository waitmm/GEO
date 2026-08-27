# Citation Decision V1.1 Phase 2B Capability Gap Checkpoint

状态：READY_FOR_REVIEW
日期：2026-08-27

## 1. 本阶段边界

Phase 2B 只开发：

```text
capability / reason-level Gap Diagnosis
```

本阶段不开发：

```text
Step 7 推荐动作交互
Step 8 实验草案
Decision Stability
新的 Strategy / Experiment 表
Citation / Benchmark 评分公式
强制人工资产白名单
```

## 2. 决策树

Gap 必须按最早失败层判断：

```text
Product Truth
-> Relevant Asset Expression
-> RetrievalCandidate
-> Evidence Adoption
```

含义：

```text
1. Product Truth 未确认或不支持时，后续资产/检索/采纳不抢占缺口。
2. Product Truth 支持后，先看目标品牌是否有相关资产表达。
3. 相关资产表达充分后，才看该资产是否进入当前 Prompt 的有效检索候选。
4. 进入有效检索候选后，才看当前答案是否出现引用/采纳上下文。
```

## 3. 复用与最小扩展

继续复用：

```text
source_gap_type
source_gap_precondition
source_gap_basis
matched_product_truth_ids
matched_product_truth_status
existing_asset_snapshot_id
existing_asset_coverage
```

新增 payload 字段：

```text
capability_gap_layer
capability_gap_diagnosis
relevant_asset_snapshot
retrieval_candidate_context
evidence_adoption_context
```

最小扩展 `source_gap_type`：

```text
DISCOVERABILITY_GAP
```

原因：

```text
Product Truth 已支持、品牌资产已有充分表达，
但该资产没有进入有效 RetrievalCandidate，
这个语义不等于 CONTENT_GAP、EVIDENCE_GAP 或 PRODUCT_GAP。
```

`DISCOVERABILITY_GAP` 本阶段不映射 Step 7 动作路径。

## 4. Product Truth 层

输入：

```text
Benchmark capability targets
TargetBrandCapabilityTruth
```

规则：

```text
缺同粒度 Product Truth
-> source_gap_type = UNKNOWN
-> capability_gap_layer = PRODUCT_TRUTH

Product Truth = NOT_SUPPORTED
-> source_gap_type = PRODUCT_GAP
-> capability_gap_layer = PRODUCT_TRUTH

Product Truth = SUPPORTED / PARTIALLY_SUPPORTED
-> 进入 Relevant Asset Expression
```

边界：

```text
竞品来源主张不能自动变成目标品牌 Product Truth。
宽泛能力不能放行细能力动作。
```

## 5. Relevant Asset Expression 层

输入：

```text
PageSnapshot
Prompt
Benchmark capability targets
Benchmark Evidence
```

资产选择方式：

```text
从当前项目 PageSnapshot 中自动选择；
按 capability / prompt / benchmark text 相关性打分；
冻结 selected_snapshot_id、selected_url、matched_terms、candidate_snapshot_ids；
不建设强制人工白名单。
```

规则：

```text
无可用资产快照
-> UNKNOWN / BRAND_ASSET_INCOMPLETE

资产没有覆盖能力表达
-> CONTENT_GAP
-> capability_gap_layer = RELEVANT_ASSET_EXPRESSION

资产只有能力声明但缺案例、数据、证明、场景或具体性
-> EVIDENCE_GAP
-> capability_gap_layer = RELEVANT_ASSET_EXPRESSION

资产表达充分
-> 进入 RetrievalCandidate
```

## 6. RetrievalCandidate 层

输入：

```text
当前 Evidence Package Run 内的 RetrievalCandidate
```

有效 Retrieval 约束：

```text
必须属于 eligible evidence observed runs；
必须有 URL / canonical URL / domain / title 中至少一个有效信号；
不能从 Prompt 下所有 Run、任意品牌资产或历史候选补齐。
```

规则：

```text
相关品牌资产未进入有效 RetrievalCandidate
-> DISCOVERABILITY_GAP
-> capability_gap_layer = RETRIEVAL_CANDIDATE
```

## 7. Evidence Adoption 层

输入：

```text
当前 Evidence Package Run 内的 ReferenceSource
DecisionEvidenceAdoption
```

规则：

```text
资产已进入有效检索，但没有引用/采纳上下文
-> EVIDENCE_GAP
-> source_gap_precondition = EVIDENCE_ADOPTION_MISSING
-> capability_gap_layer = EVIDENCE_ADOPTION

资产已进入有效检索，并出现引用/采纳上下文
-> NO_GAP
```

边界：

```text
Citation / Adoption Context 不等于模型内部因果支撑；
只说明当前样本出现了目标品牌资产采纳迹象。
```

## 8. Phase 2A Eligible Evidence 约束

Benchmark Evidence 只消费 Phase 2A 已确认 eligible 的
`EvidenceAlignment`：

```text
supporting_alignment_ids
-> _benchmark_evidence_by_alignment_id
-> capability targets / benchmark evidence
```

历史 `RELATED`、无完整 lineage 的 Alignment 不进入本阶段 Gap。

## 9. Prompt #40 回归

审计文档：

```text
docs/PROMPT_40_PHASE2B_CAPABILITY_GAP_AUDIT.md
```

真实结果：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15

PRIMARY_BENCHMARK = 1
SECONDARY_BENCHMARK = 0
```

核心对标来源：

```text
SourceDocument #345
如何将长链接缩短-小码至营
```

能力目标：

```text
点击统计           observed_run_ids = [238,239,240,253,254,255]
自定义分享标题     observed_run_ids = [238,239,240,253,254,255]
营销场景使用       observed_run_ids = [238,239,240,253,254,255]
```

诊断结果：

```text
source_gap_type = CONTENT_GAP
capability_gap_layer = RELEVANT_ASSET_EXPRESSION
matched_product_truth_status = TRUE
relevant_asset_snapshot_id = 3
existing_asset_coverage = MISSING
retrieval_candidate_context = RETRIEVED
evidence_adoption_context = NOT_ADOPTED
```

解释：

```text
当前不是 Product Truth 缺失；
也不是品牌资产完全没进入检索；
最早失败层是目标品牌相关资产没有覆盖 Benchmark 暴露出的具体能力表达。
```

下游边界说明：

```text
如果当前接口摘要仍显示 recommended_action_count / channel_opportunity_count，
它来自既有 citation_decision_vertical_slice 的下游投影；
Phase 2B 没有新增或修改 Step 7 / Step 8，
也没有创建、确认或推进任何 Action / Experiment。
```

## 10. 验证

```bash
cd geo-platform/backend
.venv/bin/python -m compileall -q app scripts/audit_prompt40_phase2b_gap.py
.venv/bin/python -m pytest -q tests/test_source_gap_v1.py tests/test_evidence_lineage_v1.py
.venv/bin/python scripts/audit_prompt40_phase2b_gap.py --output ../docs/PROMPT_40_PHASE2B_CAPABILITY_GAP_AUDIT.md
```

结果：

```text
compileall passed
35 passed
Prompt #40 audit generated
```

## 11. Migration

不需要 migration。

原因：

```text
1. 不新增数据库表。
2. 不新增数据库字段。
3. Gap snapshot 作为 source_analysis 派生 payload 输出。
4. 资产快照复用现有 PageSnapshot。
5. Product Truth、RetrievalCandidate、DecisionEvidenceAdoption 均复用现有对象。
```

## 12. 尚未进入范围

本阶段完成后停止，不进入：

```text
Step 7 推荐动作
Step 8 实验草案
DISCOVERABILITY_GAP 的动作路径设计
多 Prompt 泛化
Decision Stability
```

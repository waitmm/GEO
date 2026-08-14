# Gap Diagnosis

状态：ACTIVE
日期：2026-08-12

## Brand Opportunity Gate

任何品牌 Gap 诊断前，必须先判断：

```text
choice_slot_runs / eligible_runs
brand_mention_runs / eligible_runs
recommendation_runs / eligible_runs
```

没有稳定选择空间时，停止输出品牌关联、候选进入、明确推荐缺口。

## Primary Gap

一次诊断只允许一个 Primary Gap，最多两个 Contributing Gaps。

推荐顺序：

```text
ASSOCIATION_GAP
CAPABILITY_RECOGNITION_GAP
CANDIDATE_INCLUSION_GAP
RECOMMENDATION_GAP
TOP_RECOMMENDATION_GAP
```

前提是 Brand Opportunity Gate 已通过。

## 可追溯要求

每个 Gap 至少保存：

```text
gap_type
diagnosis_basis
supporting_metrics
supporting_run_ids
counterexample_run_ids
confidence
```

需要能下钻到：

```text
Gap -> Run -> Recommendation -> Span -> Reason -> Reason Span -> Citation Context
```

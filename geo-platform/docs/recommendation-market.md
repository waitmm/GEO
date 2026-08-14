# 决策诊断工作台

状态：ACTIVE
日期：2026-08-12

## 总链路

```text
COLLECT -> UNDERSTAND -> EXPLAIN -> DECIDE -> VERIFY
```

`决策诊断` 不负责自动发布内容，也不直接宣称效果。它只基于真实 Answer、Citation 和人工确认事实，生成可审核的诊断和可送入 `最终策略` 的草案。

## COLLECT

- 保留 `Prompt / BrowserMonitorRun / ReferenceSource / RetrievalCandidate` 原始事实。
- 原始采集事实不可被分析逻辑覆盖。
- `RetrievalCandidate` 和 final `ReferenceSource` 是两个独立可观测集合，不允许计算 Retrieval -> Citation 漏斗。

## UNDERSTAND

- Run-level 保存 `has_choice_slot`、`has_brand_mention`、`has_explicit_recommendation`。
- 三个事实独立判断，不能互相推导。
- Recommendation 必须保存 span、offset、strength、polarity、target entity、confidence、extractor、review status。

## EXPLAIN

- Answer-side Why：`Brand -> Recommendation -> Recommendation Reason`。
- Evidence-side Context：只能叫 Citation Context。
- Citation 与 Recommendation 在同一答案中共现，不等于 Citation 支撑 Recommendation。

## DECIDE

- 先过 Brand Opportunity Gate。
- 没有稳定选择空间时，停止输出 Association / Candidate / Recommendation Gap。
- 只输出一个 Primary Gap，最多两个 Contributing Gaps。

## VERIFY

- 现阶段只生成实验草案。
- 真实效果必须经过发布确认、固定复采、对比分析和人工结论。

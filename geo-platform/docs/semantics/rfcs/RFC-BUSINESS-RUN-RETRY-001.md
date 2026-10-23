# RFC-BUSINESS-RUN-RETRY-001: Business Run Retry And Attempt Audit

```yaml
rfc_id: RFC-BUSINESS-RUN-RETRY-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: PRODUCTION
authors: [Product Owner, Codex]
created_at: 2026-10-22
definition_approved_by: Product Owner
definition_approved_at: 2026-10-23
definition_approval_reference: 用户明确回复“批准” RFC-BUSINESS-RUN-RETRY-001 Definition Freeze
production_cutover_approved_by: Product Owner
production_cutover_approved_at: 2026-10-23
production_cutover_approval_reference: 用户明确回复“批准”本机 Beta 切换
affected_contracts: [SC-DELIVERY-001@1.0.0, SC-HISTORY-001@1.0.0, SC-SCOPE-001@1.0.0]
supersedes: append-only physical retry Run behavior from 2026-10-15
```

## Classification

`SEMANTIC_CHANGE`：调整失败采样在成为可信业务观测之前的生命周期；不改变成功 Run、分析、
Evidence、Truth 或分级交付语义。

## Definition

`BrowserMonitorRun` 表达业务样本槽位，`BrowserMonitorRunAttempt` 表达该槽位的一次重试执行。
失败且没有可用回答、没有进入任何不可变 AnalysisContext 或正式下游的 Run 可以显式重试。
重试不会增加业务样本数；成功时同一 Run ID 保存新的回答、引用、采集时间和 hash。

## Immutable Boundary

- 成功或部分成功的 Run 不允许原位重试。
- 即使状态为失败，只要仍保存真实回答或部分可用内容，也不允许清空覆盖。
- Run 一旦被 AnalysisContext 或正式下游结果引用，就永远不能原位覆盖。
- 上述场景需要重新采集时创建新的业务 Run，并明确冻结新的输入身份。

## Attempt Audit And Recovery

- 每次重试都有唯一 Attempt、Task 和幂等键，记录前态、前次错误、开始/结束时间和结果。
- 重复提交相同幂等键返回同一 Attempt；并发冲突 fail closed。
- Worker 中断时不自动重放不确定的外部调用，而是把 Attempt 和 Run 标记为明确失败，等待人工重试。
- 失败 Attempt 不进入 Run 池样本分母，也不触发自动分析、Optimize、Evidence Pack 或 Validate。

## Product Behavior

提交重试后，同一 Run 行立即显示“重试中”。前端只读轮询 Run 池，直到同一行成为成功、
部分成功、失败或阻断。执行尝试总数与业务样本数分别展示。

## Legacy Reconciliation

本机 Beta 中历史追加式重试只有在来源 Run/结果 Run 均未被不可变下游消费、结果完整且已完成
备份时，才允许一次性对账成一个业务 Run 和一个内部 Attempt。

# RFC-SERVER-MODEL-POLICY-001: Server-Owned Model Execution Policy

```yaml
rfc_id: RFC-SERVER-MODEL-POLICY-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: PRODUCTION
authors: [Product Owner, Codex]
created_at: 2026-10-26
definition_approved_by: Product Owner
definition_approved_at: 2026-10-26
definition_approval_reference: 用户明确决定“预算控制完全没必要……服务端后续给不同账号不同的额度”
production_cutover_approved_by: Product Owner
production_cutover_approved_at: 2026-10-26
production_cutover_approval_reference: 同一指令要求取消用户自行设置限制并改为服务端额度策略
affected_contracts: [SC-DELIVERY-001@1.0.0, SC-SERVER-MODEL-POLICY-001@1.0.0]
supersedes: M1 Beta 每个 Evidence Pack 任务由员工填写请求、Token、金额、价格依据和核实日期的交互
```

## Classification

`SEMANTIC_CHANGE`：改变付费模型任务的授权所有者和产品交互，但不放宽冻结输入、证据、
Product Truth、分级交付、项目权限或正式 V2 隔离。

## Definition

员工的“AI 优化”动作只表达对当前已冻结 Analysis/Context/Run 范围发起生成的业务意图。
员工不定义请求数、Token、金额、模型单价、计费来源或核实日期，也不需要理解这些字段。

服务端模型执行策略是唯一运行资格来源。它决定当前账号/部署是否可以运行、允许的模型与
Transport、并发、重试和技术停止边界。M1 本机 Beta 使用部署级策略；未来可在不改变员工流程的
情况下扩展为账号级额度。

## Product Behavior

- 服务端策略可用时，“创建并运行 AI 优化”一次完成冻结、服务端准入和排队。
- 不显示任务额度设置弹窗，不接受客户端提交价格或预算作为运行依据。
- 服务端策略不可用时，在产生模型调用前明确阻断；员工只看到“AI 生成暂未启用”或可读错误。
- 结果页可显示实际调用次数、Token 和费用作为审计信息，但不能要求员工配置它们。
- 历史任务、历史授权、账本和 AgentResultVersion 保持不可变。

## Server Boundary

- 模型、Transport、并发和自动重试仍由服务端固定；模型不能自行扩大权限。
- 当前部署的账本/停止保护是技术防失控机制，不是员工逐任务审批流程。
- 未来账号额度由认证主体和服务端策略绑定，客户端展示值不能授予或扩大额度。
- 服务端策略或账本异常必须 fail closed，不能回退到历史实验余额或客户端输入。

## Non-Goals

- 不实现商业 SaaS 计费。
- 不新增模型、采样、抓取、发布或正式 V2 写入权限。
- 不改变 Evidence Pack 的一次生成协议、事实资格和结果校验。


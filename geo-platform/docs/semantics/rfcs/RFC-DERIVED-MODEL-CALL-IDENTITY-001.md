# RFC-DERIVED-MODEL-CALL-IDENTITY-001: Versioned Derived Model Call Identity

```yaml
rfc_id: RFC-DERIVED-MODEL-CALL-IDENTITY-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: IMPLEMENTED
authors: [Codex]
created_at: 2026-10-19
definition_approved_by: Product Owner
definition_approved_at: 2026-10-19
definition_approval_reference: GEO 1.0 continuous delivery instruction / transport identity remediation
production_cutover_approved_by: Product Owner
production_cutover_approved_at: 2026-10-19
production_cutover_approval_reference: same instruction, limited to frozen business semantics
affected_contracts: [SC-RUNTIME-001@0.1.0, SC-HISTORY-001@1.0.0]
supersedes: null
```

## Problem

派生语义结果虽冻结 Prompt/Schema/模型别名，却未完整冻结 endpoint、实际
transport、schema/prompt hash、生成参数和 cache identity。别名在不同 transport
下可能解析成不同 effective model，导致预算、缓存与任务声明的身份不一致。

## Classification

`SEMANTIC_CHANGE`：新增技术身份对象及 fail-closed 行为；不改变任何产品级
Answer、Evidence、Truth、Strategy 或 Delivery 推断。

## Proposed Semantics

每次正式派生模型调用在发送前必须形成不可变 `DerivedModelCallIdentity.v1`：

- provider、完整 endpoint、requested/effective model；
- transport kind/version、prompt/schema version 及其内容 hash；
- generation parameters；
- 固定业务 input scope 的 canonical hash；
- versioned cache identity 和完整 call identity hash。

响应只接受与冻结 effective model 和已发送 transport 一致的 provider envelope。
缺失或未知身份必须拒绝，不能猜测。缓存只能用完整 v1 identity 命中。

## Non-Goals

- 不改变模型对 GEO 对象的业务判断规则或输出 schema。
- 不增加调用次数、预算、重试、Provider 或 endpoint。
- 不改写历史结果或旧缓存。

## Identity / Scope Impact

Source of Truth 是任务/Diagnosis 冻结 config 与单次请求 canonical identity。
历史缺少 v1 identity 的调用和缓存统一视为 `LEGACY_UNBOUND`，仅保留审计，
不得被新任务消费。新 identity 不使用 latest fallback。

## UNKNOWN Semantics

Provider 未返回 model、返回未知 model、response envelope 与 transport 不符，或
旧任务未冻结完整 identity 时，分别进入明确拒绝状态；禁止从别名、URL 或历史
缓存推断 effective identity。

## Golden Cases

- Normal：冻结 Responses JSON Schema identity，请求与响应 model/transport 一致。
- Boundary：Prompt、Schema、generation parameter 或 endpoint 任一变化产生新 cache identity。
- Failure：旧缓存、transport drift、response model drift、预算 identity drift 均在发送/消费前拒绝。

## Historical Compatibility And Migration

不迁移、不回填、不覆盖历史。旧 cache key 和旧任务为 `LEGACY_UNBOUND`；新任务
使用 v1 identity。回滚代码也不得把 legacy 数据升级成 v1。

## Step Boundary And Allowed Consumers

调用方任务生产冻结 identity；DeepSeek transport、cache 和 budget guard 只验证及
消费该 identity。不得据此改变 Step 1–8 的业务对象或推断。

## Definition Review

```text
Status: APPROVED
Contracts Referenced: SC-RUNTIME-001@0.1.0, SC-HISTORY-001@1.0.0
Golden Snapshot IDs: deterministic unit fixtures only; no real-call snapshot
Blocking Issues: none within the authorized technical identity boundary
Non-blocking Issues: historical rows remain LEGACY_UNBOUND by design
Category Error Audit: technical call identity is not business evidence
Causal Audit: no provider response is promoted into causal evidence
Identity / Scope Audit: exact task + call + payload hashes; no latest fallback
Forbidden Inference Audit: legacy/model aliases never infer effective identity
Golden Cases: normal, drift, cache isolation, legacy and budget denial
Counterexamples: otherwise-valid request with one mismatched identity component is rejected
Step Boundary: validation only; product steps unchanged
Historical Compatibility: append-only/no backfill
Contract Gaps: none for this bounded implementation
Freeze Recommendation: YES
```

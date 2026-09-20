# RFC-XXXX: Semantic Change Title

```yaml
rfc_id: RFC-XXXX
status: DRAFT | APPROVED | REJECTED | SUPERSEDED
semantic_maturity: CANDIDATE
implementation_status: NOT_IMPLEMENTED
authors: []
created_at: YYYY-MM-DD
definition_approved_by: null
definition_approved_at: null
definition_approval_reference: null
production_cutover_approved_by: null
production_cutover_approved_at: null
production_cutover_approval_reference: null
affected_contracts: []
supersedes: null
```

## Problem

说明当前业务定义为什么不足或冲突。不要以代码便利性代替问题定义。

## Current Semantics

列出当前 FROZEN/OBSERVED Contract、允许推断、禁止推断、unknown behavior 和 production 实现。

## Current Production Behavior

列出实际 production 输入、输出、版本和 observed implementation refs。实现事实不是定义来源。

## Observed Failure

绑定具体 Case/Snapshot，描述当前定义或实现无法解释的行为。

## Proposed Semantics

给出候选定义、状态转换和步骤边界。所有新增推断必须明确列出。

## Non-Goals

列出本 RFC 不改变的对象、步骤、数据库和用户路径。

## Affected Domain Objects

列出对象、identity/scope、Source of Truth、owner step 和 allowed consumers。

## Contract Diff

```text
old contract/version:
new contract/version:
allowed inference diff:
forbidden inference diff:
unknown behavior diff:
step boundary diff:
```

## Golden Cases

列出 normal、boundary、unknown/failure，以及 Real Manifest（若需要）。

## Counterexamples

每个反例必须写全 Given/And/When、其他合法 Gate、Expected、Forbidden 和 Contract Version。

## Identity / Scope Impact

说明对象集合、dedupe key、lineage、历史/current/shadow interpretation 是否变化。

## UNKNOWN Semantics

明确 UNKNOWN、input unavailable、contract gap 的处理，不得依赖隐藏 fallback。

## Step Boundary And Allowed Consumers

说明 producer step、allowed consumers 和禁止跨步写入。

## Implementation Plan

只在 RFC APPROVED 后实施。区分 Shadow、migration、enforcement 和 production cutover。

## Historical Compatibility And Migration

说明历史对象是否保留、如何 version/supersede、是否需要 migration。禁止原地覆盖已接受事实。

## Shadow Plan

说明固定输入、current vs proposed diff、critical regression 审计和 DB write boundary。

## Cutover Gate

列出语义验收、Golden replay、冲突清零、回滚和独立 Product Owner cutover approval。

## Risks And Conflicts

链接 `04_CONFLICT_REGISTER.md` 条目。

## Rollback

Rollback 恢复旧 implementation；已经批准并生效的 Contract 不能通过代码回滚静默删除。

## Approval Gates

1. Definition Freeze approval：允许把定义标为 FROZEN。
2. Implementation/Shadow approval：APPROVED RFC 可授权实现与只读验证。
3. Production Cutover approval：必须独立批准，不能由前两项推导。

## Definition Review

使用 `docs/semantics/03_DEFINITION_REVIEW_CHECKLIST.md` 的固定输出格式。

## Product Owner Approval

分别记录 definition approval 与 production cutover approval，不得合并或推导。

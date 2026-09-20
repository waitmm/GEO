# RFC-FOUNDATION-CITATION-SPLIT

```yaml
rfc_id: RFC-FOUNDATION-CITATION-SPLIT
status: DRAFT
semantic_maturity: CANDIDATE
implementation_status: NOT_IMPLEMENTED
authors: [Product Owner, Codex]
created_at: 2026-09-08
definition_approved_by: null
definition_approved_at: null
definition_approval_reference: null
production_cutover_approved_by: null
production_cutover_approved_at: null
production_cutover_approval_reference: null
affected_contracts:
  - SC-GAP-001@1.0.0
  - SC-CHANNEL-001@1.1.0
  - SC-STRATEGY-001@1.1.0
proposed_contract: SC-FOUNDATION-001@0.1.0
supersedes: null
```

## Problem

当前 Resolver Path C 可在“目标品牌 Product Truth 已确认 + 权威资产门槛满足”时把官网解析为 PRIMARY。该机制解决了“没有 eligible Benchmark/Decision Citation 就无策略”的错误，但它同时可能把两个不同问题折叠在一起：

```text
目标品牌是否需要一个可承载真实能力的 Foundation Asset
第三方/官方渠道是否已有证据证明其可作为 Citation Intervention
```

## Current Semantics

- `SC-PT-001` 防止竞品事实污染目标品牌事实。
- `SC-GAP-001` 允许无 eligible SUPPORTS 但有 Product Truth 时形成答案决策证据缺口。
- `SC-CHANNEL-001` 的 production Path C 可把官网权威承载解析为 PRIMARY。
- #19/#57 当前结果必须保持不变，#40/#50 Benchmark 语义也必须保持不变。

## Proposed Semantics

候选定义将“Foundation Requirement”和“Citation Intervention Evidence”分开：

```text
Product Truth + missing target authority asset
=> Foundation Requirement

eligible decision citation / bounded channel experiment evidence
=> Citation Intervention candidate
```

这不等价于取消官网，也不预设新的 Role。需要后续 Definition Review 决定：两类对象是否属于同一 StrategyCandidate、如何排序、如何进入 Step 8，以及缺少 Citation Evidence 时官网应保留 PRIMARY、降为另一职责，还是采用新字段表达。

## Allowed Candidate Inferences

- Product Truth 可以证明“有真实能力可被承载”。
- 缺少权威资产可以形成 Foundation Requirement。
- Citation Intervention 必须有独立证据或明确 TEST 假设。

## Forbidden Candidate Inferences

- Product Truth 单独证明某渠道会进入 Retrieval/Citation。
- 本 DRAFT 覆盖 production Path C。
- 修改 #19/#40 Candidate、Role、Action、Experiment 或数据库。

## Unknown Behavior

在角色映射、优先级和 Step 8 归属确认前，维持当前 production 行为并登记 `SEM-CONFLICT-001`。

## Golden Cases

- `CASE-SYN-001`：同一前提下并列 current/proposed expectation。
- `CASE-REAL-019`：固定 #19 当前结果，候选定义不得作为 production assertion。
- 后续若获 Definition approval，必须新增角色映射 boundary cases 后才能 Shadow。

## Non-Goals

- 不重设计 Step 1-8。
- 不进入 Step 9。
- 不修改 EvidenceAlignment、Benchmark、Product Truth 或 PR5-B。
- 不实现 PR5-C。

## Approval Gates

当前仅登记 `DRAFT + CANDIDATE + NOT_IMPLEMENTED`。Product Owner 下一步先做 Definition Review；即使 RFC 变为 APPROVED/FROZEN，也只允许实现和 Shadow，production cutover 仍需独立批准。

## Conflict

见 `docs/semantics/04_CONFLICT_REGISTER.md::SEM-CONFLICT-001`。

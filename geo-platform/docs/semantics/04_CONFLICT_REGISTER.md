# Semantic Conflict Register

状态：ACTIVE
日期：2026-09-08

## 1. 登记规则

Conflict 不允许通过“代码已经如此运行”或“最后一条聊天如此说”自动解决。每项必须记录定义成熟度、实现状态、双方来源、当前 enforcement、临时处理和最近核验时间。

## 2. Open Conflicts

### SEM-CONFLICT-006 员工逐任务预算表单与服务端策略

- Status: RESOLVED, 2026-10-26.
- Source A: M1 实验实现要求员工为每个冻结任务填写请求、Token、金额、价格依据和核实日期。
- Source B: Product Owner 决定内部员工和未来客户均不自行设置模型限制，未来额度由服务端按账号配置。
- Winning contract: `SC-SERVER-MODEL-POLICY-001@1.0.0`。
- Resolution: 新任务只接受业务意图；服务端策略负责准入和技术停止保护，客户端预算字段不再具有授权能力。
- Preservation: 历史授权、账本、用量、结果、冻结输入、证据 Gate 和正式 V2 隔离保持不变。
- Resolution RFC: `docs/semantics/rfcs/RFC-SERVER-MODEL-POLICY-001.md`。

### SEM-CONFLICT-005 Publication prerequisite versus continuous monitoring

- Status: RESOLVED_DEFINITION_IMPLEMENTATION_PENDING, 2026-10-09.
- Source A: PRD-VAL / original T20 dependencies require an execution confirmation and publication.
- Source B: explicit Product Owner final-delivery approval removes those prerequisites.
- Winning contract: SC-DELIVERY-001@1.0.0; sampling and comparison do not require publication.
- Preserve scope, unknown semantics, ownership, authorization, old immutable results and optional publication history.
- Implementation and tests must change together. This is an approved SEMANTIC_CHANGE, not a weakening of unrelated Gates.

### SEM-CONFLICT-001 Foundation Requirement 与 Citation Intervention

```yaml
status: RESOLVED
severity: HIGH
affected_contracts:
  - SC-CHANNEL-001@1.1.0 (maturity=OBSERVED, implementation_status=PRODUCTION)
  - SC-FOUNDATION-001@0.1.0 (maturity=CANDIDATE, implementation_status=NOT_IMPLEMENTED)
affected_objects: [Product Truth, Gap, Channel Role, StrategyCandidate]
source_a: 当前 Resolver Path C 允许已确认 Product Truth 在满足权威资产条件时形成官网 PRIMARY。
source_b: RFC Candidate 提议把 Foundation Requirement 与 Citation Intervention 分开，Product Truth 不单独证明 Citation Intervention。
current_production_behavior: 历史 #19/#57 与旧 Candidate 保持不可变；GEO 1.0 新策略输入不再使用 Path C 的 Product Truth => OFFICIAL_SITE PRIMARY 等价关系。
risk: 如果未经审议直接切换，可能把“需要权威事实承载”误删，或把“事实承载”继续误表述成已证明 Citation 效果。
observed_implementation_refs:
  - backend/app/modules/optimization/channel_resolution_shadow.py::resolve_channel_shadow
enforcement_refs:
  - backend/tests/test_channel_resolution_shadow.py
temporary_behavior: 不适用。
resolution_required: 已完成；实现仍按各切片独立验收。
owner_decision_required: 已确认 FACT_ANCHOR 与 Citation/Discovery/Corroboration 角色解耦。
resolution_rfc: docs/semantics/rfcs/RFC-FOUNDATION-CITATION-SPLIT.md
resolution_reference: docs/semantics/01_SEMANTIC_CONTRACTS.md::SC-CHANNEL-002@1.0.0,SC-FOUNDATION-001@1.0.0
latest_definition_review: docs/semantics/reviews/RFC-FOUNDATION-CITATION-SPLIT.review-001.md
latest_review_result: SUPERSEDED_BY_EXPLICIT_PRODUCT_OWNER_APPROVAL
resolved_at: 2026-09-28
resolved_by: Product Owner
winning_contract_version: SC-CHANNEL-002@1.0.0 + SC-FOUNDATION-001@1.0.0
superseded_contract_version: SC-CHANNEL-001@1.1.0 Path C + SC-FOUNDATION-001@0.1.0
last_verified_at: 2026-09-28
```

### SEM-CONFLICT-002 旧 P0 Target Page Gate 与当前 CREATE_NEW Execution Proposal

```yaml
status: RESOLVED_DEFINITION_IMPLEMENTATION_PENDING
severity: MEDIUM
affected_contracts:
  - SC-STEP8-001@1.0.0 (maturity=OBSERVED, implementation_status=PRODUCTION)
affected_objects: [ExecutionProposal, Action, Experiment, ManagedAsset]
source_a: docs/01_PRODUCT_DIRECTION.md 的 ACTIVE P0 描述强调目标页面与可编辑资产门槛。
source_b: 当前 PR5-A/B 对无 ManagedAsset 的新外部资产明确使用 CREATE_NEW，并允许人工审核后 ready_for_freeze。
current_production_behavior: 历史 PR5-B Proposal 保持不可变；GEO 1.0 新执行路径在资产盘点不完整时必须返回 UNKNOWN/VERIFY_ASSET_FIRST。
risk: 如果直接进入 PR5-C，旧资产门槛与新建资产身份可能产生 Action/Experiment attribution 冲突。
observed_implementation_refs:
  - backend/app/modules/optimization/execution_proposal_shadow.py::resolve_asset_operation
enforcement_refs:
  - backend/tests/test_execution_proposal_shadow.py
temporary_behavior: 未实现最小 AssetInventory 前，新路径不得从“无 row”推出 CREATE_NEW。
resolution_required: 定义已完成；实现留待 Asset Resolver 切片。
owner_decision_required: 已确认只有完整资产盘点且无适配资产时才允许 CREATE_NEW。
resolution_rfc: null
resolution_reference: docs/semantics/01_SEMANTIC_CONTRACTS.md::SC-ASSET-001@1.0.0
resolved_at: 2026-09-28
resolved_by: Product Owner
winning_contract_version: SC-ASSET-001@1.0.0
superseded_contract_version: PR5 CREATE_NEW default when inventory completeness is unproven
last_verified_at: 2026-09-28
```

### SEM-CONFLICT-003 Runtime ANSWER_SEMANTIC 输出契约不可执行

```yaml
status: OPEN
severity: HIGH
affected_contracts:
  - SC-RUNTIME-001@0.1.0 (maturity=FROZEN, implementation_status=PARTIAL)
affected_objects: [AnalysisContext, StageExecution, ANSWER_SEMANTIC, StageAttempt]
source_a: RFC-RUNTIME-001 要求 ANSWER_SEMANTIC output identity 使用 closed-enum member_kind，并要求每个 eligible Run 有冻结成员或显式 deterministic skip。
source_b: Frozen RFC 未登记 member_kind 的合法字面量；Legacy run_answer_semantic 对成功 0 event 只增加 runs_associated，不持久化逐 Run 终态，LLM 失败同样可能没有 RecommendationEvent row。
current_production_behavior: Legacy 继续以 RecommendationEvent rows 加 PromptAnalysisRun 汇总表达执行结果；Runtime Phase 1B 未接入。
risk: Capture 若自行创造 RECOMMENDATION_EVENT/NO_EVENT 等字面量或把缺行解释为成功零输出，会静默改写 Frozen Contract 并把失败误记为成功。
observed_implementation_refs:
  - backend/app/modules/optimization/answer_semantic.py::run_answer_semantic
enforcement_refs:
  - docs/semantics/rfcs/RFC-RUNTIME-001.md::RuntimeStageProfile-v1
temporary_behavior: Phase 1B 停止生产 instrumentation；保持 Phase 1A 隔离，禁止构造正式 ANSWER_SEMANTIC Stage output。
resolution_required: Independent Definition Review 明确 member_kind literal registry、逐 Run zero/skip 终态及其 identity，然后重新授权 Phase 1B。
owner_decision_required: 批准修订后的 ANSWER_SEMANTIC output contract；不得由实现者从 Legacy 行名推断。
resolution_rfc: docs/semantics/rfcs/RFC-RUNTIME-001.md
resolution_reference: null
investigation_reference: docs/semantics/shadows/RFC-RUNTIME-001.phase-1b-prospective-shadow-capture.md
last_verified_at: 2026-09-10
```

### SEM-CONFLICT-004 Runtime BINDING 上游 lineage 与 Legacy 边界冲突

```yaml
status: OPEN
severity: HIGH
affected_contracts:
  - SC-RUNTIME-001@0.1.0 (maturity=FROZEN, implementation_status=PARTIAL)
affected_objects: [ANSWER_SEMANTIC, BINDING, AnswerClaim, AnswerUnit, AnswerDecisionBinding]
source_a: RFC-RUNTIME-001 要求 BINDING 消费 ANSWER_SEMANTIC 的 AnswerUnit/Reason immutable output member/ref/hash。
source_b: Legacy run_answer_semantic 只产出 RecommendationEvent；AnswerUnit 在 run_answer_evidence_shadow_chain 的 Binding 调用内部从 AnswerClaim 新建，缺少先于 Binding 的已提交 upstream Stage output。
current_production_behavior: Legacy Binding 在一次调用内创建 AnswerUnit 并结合 RecommendationEvent 生成 AnswerDecisionBinding；没有 formal Stage dependency edge。
risk: 将本次内部创建的 AnswerUnit 反写成先前 ANSWER_SEMANTIC 输出会形成循环/重构 lineage，使 Runtime Capture 看似完整但不代表真实执行。
observed_implementation_refs:
  - backend/app/modules/optimization/answer_semantic.py::run_answer_semantic
  - backend/app/modules/optimization/answer_evidence_shadow.py::_build_answer_units
  - backend/app/modules/optimization/answer_evidence_shadow.py::_build_decision_bindings
enforcement_refs:
  - docs/semantics/rfcs/RFC-RUNTIME-001.md::Stage-Input-Role-matrix
temporary_behavior: 停止 BINDING prospective mapping；不创建猜测 dependency edge，不选择最新 ShadowRun 补齐。
resolution_required: 通过 Definition Review 决定建立真实的 pre-Binding AnswerUnit/Reason Stage boundary，或修订 Frozen Stage split/dependency contract。
owner_decision_required: 明确 AnswerUnit 的 Stage ownership 和 BINDING 的合法 upstream identity。
resolution_rfc: docs/semantics/rfcs/RFC-RUNTIME-001.md
resolution_reference: null
investigation_reference: docs/semantics/shadows/RFC-RUNTIME-001.phase-1b-prospective-shadow-capture.md
last_verified_at: 2026-09-10
```

### SEM-CONFLICT-005 失败 Run 不可变性与业务样本重试

```yaml
status: RESOLVED
severity: MEDIUM
affected_contracts:
  - SC-RUN-RETRY-001@1.0.0
affected_objects: [Run, BrowserMonitorRunAttempt, AnalysisContext]
source_a: 旧 Run 定义及追加式重试把每次失败/重试都保存为独立物理 Run。
source_b: Product Owner 决定失败采样是任务执行状态；未被消费的失败业务 Run 应在同一逻辑槽位重试。
current_production_behavior: 未被消费且无可用回答的失败 Run 原位进入 retrying 并由内部 Attempt 审计；成功或已被消费的 Run 不可覆盖。
risk: 若不区分业务 Run 与 Attempt，偶发失败会污染样本池；若无冻结保护原位更新，则会破坏分析历史。
resolution_required: 已完成；SC-RUN-RETRY-001 同时冻结允许更新条件与不可变边界。
resolution_rfc: docs/semantics/rfcs/RFC-BUSINESS-RUN-RETRY-001.md
resolution_reference: docs/semantics/01_SEMANTIC_CONTRACTS.md::SC-RUN-RETRY-001@1.0.0
resolved_at: 2026-10-23
resolved_by: Product Owner
winning_contract_version: SC-RUN-RETRY-001@1.0.0
superseded_contract_version: 2026-10-15 append-only physical retry Run behavior
last_verified_at: 2026-10-23
```

### SEM-CONFLICT-006 单稿父结果与多内容资产版本

```yaml
status: RESOLVED
severity: MEDIUM
affected_contracts:
  - SC-MULTI-DRAFT-ARTIFACT-001@1.0.0
affected_objects: [AgentResultVersion, DraftArtifactVersion]
source_a: 旧 AgentResultVersion 通过一个 deliverable_markdown 暗含一次结果等于一篇稿件。
source_b: Product Owner 决定一次冻结 Optimize 可交付多个独立稿件，并要求单稿反馈、导出和重生成。
current_production_behavior: 父结果保持不可变；明确 HELP_DOC/FAQ 追加为子版本；旧单稿不回填。
risk: 若改写父结果或从旧文案猜类型，会破坏历史 identity；若只保留父状态，会掩盖部分失败。
resolution_required: 已完成；采用不可变父结果加 append-only child lineage，父状态仅派生。
resolution_rfc: docs/semantics/rfcs/RFC-MULTI-DRAFT-ARTIFACT-001.md
resolution_reference: docs/semantics/01_SEMANTIC_CONTRACTS.md::SC-MULTI-DRAFT-ARTIFACT-001@1.0.0
resolved_at: 2026-10-30
resolved_by: Product Owner
winning_contract_version: SC-MULTI-DRAFT-ARTIFACT-001@1.0.0
superseded_contract_version: implicit one-result-one-draft read assumption
last_verified_at: 2026-10-30
```

## 3. Tracked Gaps, Not Yet Conflicts

- `SC-EXPERIMENT-001` 当前 `implementation_status=PARTIAL`：旧 Step 8 服务具备部分 snapshot freeze，但 PR5-C 尚未实现。这是已知实现阶段缺口，不代表可绕过 PR5-C。
- `SC-DECISION-STABILITY-001` 当前 enforcement_refs 为空：边界有文档和观察实现，但缺少专门自动化 guard。
- `SC-RUNTIME-001@0.1.0` 已完成 Definition Freeze，但 production Runtime 尚未实现或 Cutover；其只读 Projection Spike 不构成生产 enforcement。
- `SC-RUNTIME-001@0.1.0` Phase 1B prospective capture 因 `SEM-CONFLICT-003/004` 停止；Root 的部分可映射性不能替代合法 Stage output/dependency contract。
- 其余首批 `OBSERVED` Contract 尚未经过新治理流程的 Definition Freeze，不能作为 FROZEN truth 使用。

## 4. Resolution Record

解决冲突时必须追加记录：

```text
resolved_at
resolved_by
approval_reference
winning/new contract version
superseded contract/version
implementation and cutover status
golden cases rerun
```

不得删除原冲突条目。

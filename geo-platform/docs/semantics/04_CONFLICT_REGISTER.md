# Semantic Conflict Register

状态：ACTIVE
日期：2026-09-08

## 1. 登记规则

Conflict 不允许通过“代码已经如此运行”或“最后一条聊天如此说”自动解决。每项必须记录定义成熟度、实现状态、双方来源、当前 enforcement、临时处理和最近核验时间。

## 2. Open Conflicts

### SEM-CONFLICT-001 Foundation Requirement 与 Citation Intervention

```yaml
status: OPEN
severity: HIGH
affected_contracts:
  - SC-CHANNEL-001@1.1.0 (maturity=OBSERVED, implementation_status=PRODUCTION)
  - SC-FOUNDATION-001@0.1.0 (maturity=CANDIDATE, implementation_status=NOT_IMPLEMENTED)
affected_objects: [Product Truth, Gap, Channel Role, StrategyCandidate]
source_a: 当前 Resolver Path C 允许已确认 Product Truth 在满足权威资产条件时形成官网 PRIMARY。
source_b: RFC Candidate 提议把 Foundation Requirement 与 Citation Intervention 分开，Product Truth 不单独证明 Citation Intervention。
current_production_behavior: 继续执行 strategy_channel_resolver.v1_1 Path C；#19/#57 保持 OFFICIAL_SITE PRIMARY。
risk: 如果未经审议直接切换，可能把“需要权威事实承载”误删，或把“事实承载”继续误表述成已证明 Citation 效果。
observed_implementation_refs:
  - backend/app/modules/optimization/channel_resolution_shadow.py::resolve_channel_shadow
enforcement_refs:
  - backend/tests/test_channel_resolution_shadow.py
temporary_behavior: 保持当前 production 行为；Candidate 只用于文档讨论、Golden proposed expectation 和后续 Shadow，禁止覆盖 #19/#40。
resolution_required: Product Owner Definition Review；若批准新定义，仍需独立 Production Cutover。
owner_decision_required: 确认 Foundation Requirement 与 Citation Intervention 的对象、Role 和 Step 8 归属。
resolution_rfc: docs/semantics/rfcs/RFC-FOUNDATION-CITATION-SPLIT.md
resolution_reference: null
latest_definition_review: docs/semantics/reviews/RFC-FOUNDATION-CITATION-SPLIT.review-001.md
latest_review_result: NEEDS_REVISION
last_verified_at: 2026-09-08
```

### SEM-CONFLICT-002 旧 P0 Target Page Gate 与当前 CREATE_NEW Execution Proposal

```yaml
status: OPEN
severity: MEDIUM
affected_contracts:
  - SC-STEP8-001@1.0.0 (maturity=OBSERVED, implementation_status=PRODUCTION)
affected_objects: [ExecutionProposal, Action, Experiment, ManagedAsset]
source_a: docs/01_PRODUCT_DIRECTION.md 的 ACTIVE P0 描述强调目标页面与可编辑资产门槛。
source_b: 当前 PR5-A/B 对无 ManagedAsset 的新外部资产明确使用 CREATE_NEW，并允许人工审核后 ready_for_freeze。
current_production_behavior: PR5-B 生成 ephemeral CREATE_NEW Proposal 并重新校验，但不持久化 Action/Experiment。
risk: 如果直接进入 PR5-C，旧资产门槛与新建资产身份可能产生 Action/Experiment attribution 冲突。
observed_implementation_refs:
  - backend/app/modules/optimization/execution_proposal_shadow.py::resolve_asset_operation
enforcement_refs:
  - backend/tests/test_execution_proposal_shadow.py
temporary_behavior: PR5-B 保持只读 Proposal/overlay/revalidation；不进入 PR5-C，不创建 Action/Experiment。
resolution_required: Product Owner 明确 ACTIVE Product Definition 的适用版本或修订旧 P0 文档。
owner_decision_required: 确认 CREATE_NEW 在当前 Step 8 的合法身份、持久化边界与旧 P0 文档适用范围。
resolution_rfc: null
resolution_reference: null
last_verified_at: 2026-09-08
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

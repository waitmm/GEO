# GEO Semantic Contracts

状态：ACTIVE REGISTRY
日期：2026-09-08

## 1. Registry 规则

- 本文件登记当前可审计 Contract；登记不等于冻结。
- `maturity` 与 `implementation_status` 独立维护，不得互相推导。
- `OBSERVED + PRODUCTION` 只说明代码当前如此运行，不代表 Product Owner 已重新确认定义。
- 只有 Definition Review 明确批准后才能标为 `FROZEN`。
- `APPROVED RFC` 只授权实现、Shadow 和 Replay；替换生产语义仍需独立 Production Cutover 批准。
- FROZEN Contract 与实现冲突时返回 `SEMANTIC_CONTRACT_CONFLICT`，不得静默选择代码或旧文档。

## 2. 首批 Contract

### SC-SERVER-MODEL-POLICY-001 Server-Owned Model Execution Policy

```yaml
contract_id: SC-SERVER-MODEL-POLICY-001
contract_name: Server-Owned Model Execution Policy
contract_version: 1.0.0
maturity: FROZEN
implementation_status: PRODUCTION
definition: 员工只提交当前冻结 GEO 输入的 AI 优化意图；运行资格、模型、Transport、并发、重试与技术停止边界由服务端策略决定，客户端任务表单不能授予或扩大额度。
allowed_inferences:
  - 服务端策略可用且冻结身份通过时，一次用户操作可以创建并排队 Evidence Pack 任务。
  - 实际调用次数、Token 和费用可以作为只读审计信息展示。
  - 未来可以按认证账号配置服务端额度而不改变员工操作流程。
forbidden_inferences:
  - 要求员工填写请求数、Token、金额、价格来源或核实日期才能运行。
  - 接受客户端预算字段作为模型运行授权来源。
  - 策略不可用时回退到历史实验余额、默认无限额度或模型自行决定。
unknown_behavior: 服务端策略、账本或运行身份不可验证时，在外部请求前阻断并返回业务可读错误。
identity: authenticated actor/deployment policy + project + prompt + frozen Agent run identity + server ledger authorization
history: 历史任务、授权、账本、用量和结果保持不可变；只改变新任务的准入交互。
step_boundary: Optimize 执行准入；不改变采样、Evidence、Truth、Review、正式 V2 或发布权限。
source_references:
  - docs/semantics/rfcs/RFC-SERVER-MODEL-POLICY-001.md
enforcement_refs:
  - backend/app/modules/agent_experiment/api.py
  - backend/app/services/internal_beta_model_budget.py
  - backend/tests/test_agent_internal_beta.py
  - frontend/tests/agent-internal-beta.test.mjs
approved_by: Product Owner
approved_at: 2026-10-26
approval_reference: 用户明确取消客户端预算设置并决定未来由服务端按账号配置额度
golden_case_ids: [CASE-SYN-008]
effective_from: 2026-10-26
```

### SC-DELIVERY-001 Continuous Monitor And Independent Validate

```yaml
contract_id: SC-DELIVERY-001
version: 1.0.0
maturity: FROZEN
implementation_status: PARTIAL
approval: Product Owner 2026-10-09 explicit final-delivery implementation instruction
definition: Monitor and Validate consume the same versioned measurements of explicit Run scopes. Automatic Optimize produces qualified outputs without mandatory human semantic approvals or publication prerequisites.
supersedes: release publication/ExecutionConfirmation prerequisites in PRD-VAL, T20 -> T21/T22 dependencies and E2E-04; not historical publication facts
allowed_inferences:
  - Compare explicitly selected compatible scopes without PublicationRecord.
  - Continue with qualified partial inputs while reporting excluded/unknown members.
  - Freeze an explicit PARTIAL source-input manifest retaining every unavailable occurrence; consume only its READY snapshots. PARTIAL is not completion, WAIVE, NO_SUPPORT or global evidence sufficiency.
  - Restrict a machine contribution to an explicitly admitted Run while retaining the entire fixed Context identity; failed Runs do not inherit its qualification.
  - Use versioned user-supplied context with its provenance, not as independently verified Truth.
  - Under approved BRD-002 / AC-BRD-03, an alias-only literal hit without an admitted, grounded entity remains unknown, not a brand hit or negative. Canonical-name occurrence remains an observable mention, not a recommendation.
forbidden_inferences:
  - Failed/unevaluated semantic results imply no recommendation.
  - Missing or failed references imply a source disappeared.
  - Citation correspondence proves generation causality.
  - A model, review or lack of inventory proves brand facts or publishing permissions.
  - Automatic operation grants unlimited external calls or retries.
identity: project + prompt + explicit run IDs/raw hashes + measurement identity/version + optional exact semantic result versions
unknown_behavior: Report per-metric evaluable members and limitations; zero denominator is null.
history: Preserve raw Runs, valid historical results, v7 and publication facts; new inputs create new versions.
acceptance: AC-VAL-01..05, E2E-01..05, release acceptance harness
```

2026-10-09 implementation clarification: measurement `v4_alias_evidence` and identity
rule `alias_evidence.v2` apply the already approved ambiguous-alias constraint.
Stored older measurements are not rewritten. This does not claim universal entity
disambiguation or upgrade a literal canonical-name mention to a recommendation.

### SC-PT-001 Target Brand Product Truth Isolation

```yaml
contract_id: SC-PT-001
contract_name: Target Brand Product Truth Isolation
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: Product Truth 只确认目标品牌自己的真实能力，并保留 TRUE/FALSE/UNKNOWN 与人工来源边界。
allowed_inferences:
  - MANUAL_CONFIRMED 且正向的目标品牌能力可进入安全内容事实集合。
forbidden_inferences:
  - 由竞品、Benchmark、SourceClaim 或模型常识自动推出目标品牌能力。
  - 将 UNKNOWN 改写为 TRUE。
unknown_behavior: 保持 UNKNOWN，阻止确定性目标品牌能力陈述并进入人工确认。
step_boundary: Step 3 产生；Step 6-8 只读消费。
source_references:
  - 产品纲要.md::目标品牌事实边界
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Product Truth
observed_implementation_refs:
  - backend/app/models/db.py::TargetBrandCapabilityTruth
  - backend/app/modules/optimization/service.py::formal gap/strategy assembly
enforcement_refs:
  - backend/tests/test_source_gap_v1.py::product truth matching tests
  - backend/tests/test_execution_proposal_shadow.py::claim grounding tests
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-001, CASE-REAL-019]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-UNKNOWN-001 Unknown Preservation

```yaml
contract_id: SC-UNKNOWN-001
contract_name: Unknown Preservation
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: UNKNOWN 表示当前正式输入无法证明真或假，是合法业务状态，不是待代码猜测的空值。
allowed_inferences:
  - 请求人工确认、补充证据或保持不确定。
forbidden_inferences:
  - 静默升级 TRUE/SUPPORTED/eligible/ready。
  - 用竞品事实、LLM 常识或 fallback 填补。
unknown_behavior: 原样保留 UNKNOWN，并阻止依赖确定事实的下游动作。
step_boundary: 贯穿 Step 3-8；每一步只能消费，不能跨步骤升级。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::unknown and human confirmation boundaries
observed_implementation_refs:
  - backend/app/modules/optimization/service.py
  - backend/app/modules/optimization/execution_proposal_shadow.py
enforcement_refs:
  - backend/tests/test_source_gap_v1.py::unknown product truth tests
  - backend/tests/test_strategy_step7_v1.py::unknown strategy tests
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-001, CASE-SYN-006]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-EVIDENCE-001 Retrieval-Only Is Not Decision Citation

```yaml
contract_id: SC-EVIDENCE-001
contract_name: Retrieval-Only Is Not Decision Citation
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: Retrieval observation 只证明来源进入某次检索候选环境，不能单独证明其被引用或支持答案决策理由。
allowed_inferences:
  - 作为 Channel Evidence exposure 和受限 TEST 输入。
forbidden_inferences:
  - RETRIEVAL_ONLY => DECISION_CITATION/SUPPORTS/PRIMARY。
unknown_behavior: 缺少 Citation/Alignment 时保持 retrieval-only。
step_boundary: Step 1 产生；Step 4/7 受限消费。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::retrieval and citation boundary
observed_implementation_refs:
  - backend/app/modules/optimization/channel_evidence.py
  - backend/app/modules/optimization/channel_resolution_shadow.py
enforcement_refs:
  - backend/tests/test_channel_evidence.py
  - backend/tests/test_channel_resolution_shadow.py
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-004, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-EVIDENCE-002 Peripheral Citation Is Not Decision Citation

```yaml
contract_id: SC-EVIDENCE-002
contract_name: Peripheral Citation Is Not Decision Citation
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: 被观察到的外围引用可以描述引用环境，但在未绑定到同一 Decision Reason 前不是 Decision Citation。
allowed_inferences:
  - 作为 reference environment/exposure 观察。
forbidden_inferences:
  - PERIPHERAL_CITATION => DECISION_CITATION/SUPPORTS/PRIMARY。
unknown_behavior: 绑定不足时维持 peripheral/unproven，不扩展 prompt-scope cross-product。
step_boundary: Step 1/4；只在满足 lineage 后升级为正式 Evidence 关系。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::citation decision eligibility
observed_implementation_refs:
  - backend/app/modules/optimization/evidence_lineage.py
  - backend/app/modules/optimization/evidence_alignment_candidates.py
enforcement_refs:
  - backend/tests/test_answer_evidence_shadow.py
  - backend/tests/test_evidence_alignment.py
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-002, CASE-REAL-019, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-EVIDENCE-003 Phase 2A Evidence Lineage

```yaml
contract_id: SC-EVIDENCE-003
contract_name: Phase 2A Evidence Lineage
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: 只有属于当前固定 Run scope 且满足 Phase 2A lineage 的 AnswerUnit-SourceClaim 关系可进入正式 V1.1。
allowed_inferences:
  - 对候选范围内具体 pair 保存并人工审核 SUPPORTS/CONTRADICTS/非支持关系。
forbidden_inferences:
  - 使用 prompt-scope 历史全库 cross-product 补齐关系。
  - 将 HUMAN_CONFIRMED 用作未来候选召回白名单。
unknown_behavior: 无可验证 lineage 时排除正式关系并显式报告。
step_boundary: Step 4；不决定 Benchmark、Channel Role 或 Strategy。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Phase 2A
  - docs/v1_1_incremental_materialization.md
observed_implementation_refs:
  - backend/app/modules/optimization/evidence_alignment.py::run_evidence_alignment
  - backend/app/modules/optimization/evidence_alignment_candidates.py
  - backend/app/modules/optimization/evidence_lineage.py
enforcement_refs:
  - backend/tests/test_evidence_alignment.py
  - backend/tests/test_materialization_executor.py
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-002, CASE-REAL-019, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-BENCHMARK-001 Benchmark Isolation

```yaml
contract_id: SC-BENCHMARK-001
contract_name: Benchmark Isolation
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: Benchmark 是相同理由上符合资格的外部证据比较，不是引用热度、目标品牌事实或执行渠道选择。
allowed_inferences:
  - 描述符合资格来源在同一 capability/reason 上的可比较证据。
forbidden_inferences:
  - Citation Prominence 决定 Benchmark。
  - Benchmark 平台自动成为执行平台。
  - Benchmark 能力自动成为 Product Truth。
unknown_behavior: 无 eligible Benchmark 时仍允许形成其他类型 Gap，但不得伪造 Benchmark。
step_boundary: Step 5 产生；Step 6/7 受限消费。
source_references:
  - 产品纲要.md::Benchmark 边界
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Step 5
observed_implementation_refs:
  - backend/app/modules/optimization/service.py::formal evidence and strategy assembly
enforcement_refs:
  - backend/tests/test_source_gap_v1.py::benchmark boundary assertions
  - backend/tests/test_strategy_step7_v1.py::benchmark channel boundary assertions
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-003, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-GAP-001 Reason-Level Gap Diagnosis

```yaml
contract_id: SC-GAP-001
contract_name: Reason-Level Gap Diagnosis
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: Gap 在 capability/reason 层结合答案选择、Product Truth、Evidence 与可选 Benchmark 分类。
allowed_inferences:
  - 无 eligible SUPPORTS 但有已确认 Product Truth 时形成 ANSWER_DECISION_EVIDENCE_GAP。
forbidden_inferences:
  - 无 Benchmark 等价为无 Gap。
  - 将其他 Reason 的证据或 Product Truth 串入当前 Reason。
unknown_behavior: 输入事实不足时保留 UNKNOWN/HUMAN_REVIEW_REQUIRED，不生成确定执行结论。
step_boundary: Step 6；不创建 StrategyCandidate、Action 或 Experiment。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Step 6
  - docs/09_PRODUCT_ITERATION_LOG.md::2026-09-04 evidence gap correction
observed_implementation_refs:
  - backend/app/modules/optimization/service.py::gap diagnosis paths
enforcement_refs:
  - backend/tests/test_source_gap_v1.py
  - backend/tests/test_strategy_step7_v1.py::answer decision evidence gap tests
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-001, CASE-REAL-019]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-CHANNEL-001 Current Channel Resolver Roles (SUPERSEDED)

```yaml
contract_id: SC-CHANNEL-001
contract_name: Current Channel Resolver Roles
contract_version: 1.1.0
maturity: OBSERVED
implementation_status: PRODUCTION
lifecycle_status: SUPERSEDED_FOR_GEO_1_0
definition: Resolver 依据 reason-level Evidence、Product Truth、资产权威性与渠道资格确定 PRIMARY/SECONDARY/TEST/OBSERVE；Role 与执行优先级分离。
allowed_inferences:
  - 符合当前 Path A/B/C/D 门槛的渠道进入对应角色候选。
  - TEST 仅表示值得验证，不表示已证明有效。
forbidden_inferences:
  - Benchmark 或引用数量自动决定 Role。
  - Step 8 修改 Role。
  - LLM 新增渠道或升级 Role。
unknown_behavior: 资格不足时 OBSERVE 或 HUMAN_REVIEW_REQUIRED，不猜测渠道效果。
step_boundary: Step 7；只确定渠道职责，不选择账号、URL、标题、section 或资产实例。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Step 7
  - docs/STRATEGY_SYNTHESIS_PR4_CHECKPOINT.md
observed_implementation_refs:
  - backend/app/modules/optimization/channel_resolution_shadow.py::resolve_channel_shadow
  - backend/app/modules/optimization/strategy_synthesis_shadow.py::run_strategy_synthesis_core
enforcement_refs:
  - backend/tests/test_channel_resolution_shadow.py
  - backend/tests/test_strategy_synthesis_shadow.py
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-003, CASE-SYN-004, CASE-REAL-019, CASE-REAL-040]
effective_from: null
supersedes: null
superseded_by: SC-CHANNEL-002@1.0.0
superseded_scope: Product Truth/FACT_ANCHOR 推导 OFFICIAL_SITE PRIMARY 的 Path C；历史 Candidate 和 V1 审计记录保持不可变。
last_verified_at: 2026-09-28
```

### SC-CHANNEL-002 Asset Role And Citation Channel Role Separation

```yaml
contract_id: SC-CHANNEL-002
contract_name: Asset Role And Citation Channel Role Separation
contract_version: 1.0.0
maturity: FROZEN
implementation_status: NOT_IMPLEMENTED
definition: FACT_ANCHOR 是资产角色；CITATION、DISCOVERY、CORROBORATION 是内容或渠道角色。资产角色与渠道角色必须独立判断。
allowed_inferences:
  - 官网资产可承担 FACT_ANCHOR 或 PROCEDURAL_SOURCE。
  - 第三方来源可承担 CORROBORATION、COMPARISON_CONTEXT 或 DISCOVERY_SURFACE。
  - Citation channel role 只能由其明确 scope 内的可消费观察和资格 Gate 决定。
forbidden_inferences:
  - FACT_ANCHOR 自动推出 OFFICIAL_SITE PRIMARY。
  - Product Truth、Benchmark 平台或引用数量自动推出执行渠道。
  - 发布位置反向改写 Strategy channel_key/channel_role。
unknown_behavior: 渠道依据不足时保留 NONE/UNKNOWN/VERIFY_FIRST，不用官网兜底。
step_boundary: Strategy/Execution 输入边界；不在 Citation Contribution P1 生成策略。
source_references:
  - docs/semantics/01_SEMANTIC_CONTRACTS.md::SC-CITATION-CONTRIBUTION-001
  - docs/semantics/04_CONFLICT_REGISTER.md::SEM-CONFLICT-001
observed_implementation_refs: []
enforcement_refs: []
approved_by: Product Owner
approved_at: 2026-09-28
approval_reference: GEO Citation Contribution P1 implementation order
golden_case_ids: [CASE-SYN-001, CASE-SYN-008]
effective_from: 2026-09-28
supersedes: SC-CHANNEL-001@1.1.0 Path C
last_verified_at: 2026-09-28
```

### SC-STRATEGY-001 Step 7 Strategy Truth

```yaml
contract_id: SC-STRATEGY-001
contract_name: Step 7 Strategy Truth
contract_version: 1.1.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: Step 7 确定并人工确认 Reasons、Themes、Gaps、Channel Roles 和策略范围；结构优先确定性生成。
allowed_inferences:
  - Theme coverage 等于成员 Reason observed Run IDs 的并集除以 analyzable Runs。
  - 已确认 Candidate 允许进入 Step 8 审核。
forbidden_inferences:
  - Step 7 创建 Action/Experiment。
  - 历史 Candidate 计入当前 Evidence Package 状态。
  - LLM 改 ID、Role、事实、coverage 或渠道集合。
unknown_behavior: 确定性输入有真实歧义时可标记 needs_human_*；LLM 失败回退且不阻塞 Strategy Truth。
step_boundary: Step 7 产生 StrategyCandidate；具体资产执行参数属于 Step 8。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Step 7
  - docs/STRATEGY_SYNTHESIS_PR4_CHECKPOINT.md
observed_implementation_refs:
  - backend/app/modules/optimization/strategy_synthesis_shadow.py
  - backend/app/modules/optimization/service.py::review_strategy_candidate
enforcement_refs:
  - backend/tests/test_strategy_step7_v1.py
  - backend/tests/test_strategy_synthesis_shadow.py
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-005, CASE-REAL-019, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-STEP7-001 Step 7 Ownership Boundary

```yaml
contract_id: SC-STEP7-001
contract_name: Step 7 Ownership Boundary
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: Step 7 只生成和人工确认 StrategyCandidate，不创建具体执行事实。
allowed_inferences:
  - 已确认 StrategyCandidate 允许用户进入 Step 8 审核。
forbidden_inferences:
  - 创建 Action、Experiment、具体资产实例、URL、标题或 section。
unknown_behavior: Strategy 未确认时 Step 8 保持锁定，不使用历史对象绕过。
step_boundary: Step 7 producer；Step 8 只读消费已确认 Strategy Truth。
source_references:
  - 产品纲要.md::Step 7/8 boundary
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Step 7
observed_implementation_refs:
  - backend/app/modules/optimization/service.py::review_strategy_candidate
  - backend/app/modules/optimization/workflow.py
enforcement_refs:
  - backend/tests/test_strategy_step7_v1.py
  - backend/tests/test_workflow_review_queue.py
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-REAL-019, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-STEP8-001 Step 8 Execution Proposal Isolation

```yaml
contract_id: SC-STEP8-001
contract_name: Step 8 Execution Proposal Isolation
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: ExecutionProposal 只把已确认 Strategy Truth 编译成一资产一渠道的可审核建议；人工编辑是 overlay 并必须 canonical rebuild + revalidation。
allowed_inferences:
  - 用户在系统给出的合法 package/type/title/sections/window 中选择或暂缓。
forbidden_inferences:
  - 修改 Role、Theme/Reason Scope、Product Truth、Baseline 或 metric eligibility。
  - 将 ready_for_freeze 解释为已创建 Action/Experiment。
  - 自动选择第一个合法方案。
unknown_behavior: 缺少人工选择时 NEEDS_HUMAN_SELECTION；非法 overlay 整体拒绝，不宽松修复。
step_boundary: Step 8 审核；PR5-B 不进行 PR5-C 持久化。
source_references:
  - docs/EXECUTION_PROPOSAL_PR5_A.md
  - docs/EXECUTION_PROPOSAL_PR5_B.md
observed_implementation_refs:
  - backend/app/modules/optimization/execution_proposal_shadow.py::build_execution_proposal_portfolio
  - backend/app/modules/optimization/execution_proposal_shadow.py::revalidate_execution_proposal_portfolio
enforcement_refs:
  - backend/tests/test_execution_proposal_shadow.py
  - backend/app/modules/optimization/execution_proposal_shadow.py::validate_execution_proposal
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-006, CASE-REAL-019]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-EXPERIMENT-001 Experiment Snapshot Freeze

```yaml
contract_id: SC-EXPERIMENT-001
contract_name: Experiment Snapshot Freeze
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PARTIAL
definition: 每个 Experiment 绑定一个具体 Action，并冻结 strategy/gap/action/selected asset/baseline runs/baseline metrics 快照。
allowed_inferences:
  - 冻结后用相同口径复测和比较。
forbidden_inferences:
  - 用后续 Candidate、Gap 或资产变化重写历史实验。
  - 一个 Experiment 合并多个独立渠道 Proposal。
  - PR5-B ready_for_freeze 自动创建 Experiment。
unknown_behavior: 缺少任一必需快照时阻止创建并返回明确校验错误。
step_boundary: Step 8；发布、复测、结论不新增 Step 9。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::Step 8
  - 产品纲要.md::Experiment freeze
observed_implementation_refs:
  - backend/app/modules/optimization/service.py::confirm_strategy_execution_plan
  - backend/app/modules/optimization/service.py::create_experiment
enforcement_refs:
  - backend/tests/test_source_gap_v1.py::strategy snapshot and baseline tests
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-SYN-007]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-HISTORY-001 Accepted History Is Immutable

```yaml
contract_id: SC-HISTORY-001
contract_name: Accepted History Is Immutable
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: 已接受或已生效的历史语义对象不可原地覆盖；更改必须创建新版本并显式 supersede，原对象继续可审计。
allowed_inferences:
  - 新 Candidate/Contract/Experiment snapshot 通过 version/supersedes 关系替代旧对象。
forbidden_inferences:
  - 原地重写已接受 Candidate 的核心 payload、已冻结实验快照或已生效 Contract。
unknown_behavior: 无法证明对象是否已接受/生效时阻止覆盖并进入人工审查。
step_boundary: 贯穿 Step 1-8 的版本化与历史审计。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::current workflow state
  - docs/09_PRODUCT_ITERATION_LOG.md::history isolation decisions
observed_implementation_refs:
  - backend/app/modules/optimization/service.py::candidate supersede and review paths
enforcement_refs:
  - backend/tests/test_strategy_step7_v1.py::candidate supersede tests
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-REAL-019, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-SCOPE-001 Current Scope History Isolation

```yaml
contract_id: SC-SCOPE-001
contract_name: Current Scope History Isolation
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: 当前主链状态只读取当前 Prompt、固定 Evidence Package/Run scope 和 current Candidate lineage；历史与 Shadow 对象只作审计。
allowed_inferences:
  - superseded Candidate、Action、Experiment 可展示为历史记录。
forbidden_inferences:
  - 历史 StrategyCandidate/Experiment 点亮当前 Step 7/8。
  - Shadow 结果决定 production 状态。
  - latest-by-id 替代固定 package/candidate identity。
unknown_behavior: 无法证明 current lineage 时显示未加载/需确认，不回退历史对象。
step_boundary: 贯穿 Step 1-8 的状态读取，不改变各步骤归属。
source_references:
  - docs/05_OPTIMIZATION_LOOP_SPEC.md::current workflow state
  - docs/09_PRODUCT_ITERATION_LOG.md::history isolation decisions
observed_implementation_refs:
  - backend/app/modules/optimization/workflow.py
  - backend/app/modules/optimization/api.py
enforcement_refs:
  - backend/tests/test_workflow_review_queue.py
  - backend/tests/test_strategy_step7_v1.py::current candidate isolation tests
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: [CASE-REAL-019, CASE-REAL-040]
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-DECISION-STABILITY-001 Sidecar Observation Only

```yaml
contract_id: SC-DECISION-STABILITY-001
contract_name: Decision Stability Sidecar
contract_version: 1.0.0
maturity: OBSERVED
implementation_status: PRODUCTION
definition: Decision Stability 只作为旁路观测指标。
allowed_inferences:
  - 在不改变主链状态的详情或报告中展示稳定性。
forbidden_inferences:
  - 决定 Step 1-8 是否完成、锁定、生成 Strategy 或创建 Experiment。
unknown_behavior: 无法计算时显示不可用，不阻塞主链。
step_boundary: 旁路，只读。
source_references:
  - 产品纲要.md::Decision Stability boundary
observed_implementation_refs:
  - backend/app/modules/optimization/workflow.py
enforcement_refs: []
approved_by: null
approved_at: null
approval_reference: null
golden_case_ids: []
effective_from: null
supersedes: null
last_verified_at: 2026-09-08
```

### SC-FOUNDATION-001 Foundation/Citation Semantic Split

```yaml
contract_id: SC-FOUNDATION-001
contract_name: Foundation/Citation Semantic Split
contract_version: 1.0.0
maturity: FROZEN
implementation_status: NOT_IMPLEMENTED
definition: Product Truth 与可证明的权威事实资产缺口可以建立 FACT_ANCHOR/Foundation Requirement，但不得单独证明 Citation、Discovery 或渠道干预资格。
allowed_inferences:
  - FACT_ANCHOR 与 Citation channel role 可同时存在，也可任一为 NONE/UNKNOWN。
  - Foundation 是否成立只回答事实承载需求，不决定执行渠道效果。
forbidden_inferences:
  - Product Truth 或 Foundation REQUIRED 自动推出官网 PRIMARY。
  - 未完成资产盘点时推断目标品牌没有适配资产。
unknown_behavior: 事实或资产盘点不足时保持 UNKNOWN/VERIFY_ASSET_FIRST，不默认 CREATE_NEW 或 OFFICIAL_SITE PRIMARY。
step_boundary: Foundation/Strategy 输入定义；不修改历史 Candidate，不授权 Citation Contribution P1 生成 Strategy。
source_references:
  - docs/semantics/rfcs/RFC-FOUNDATION-CITATION-SPLIT.md
observed_implementation_refs: []
enforcement_refs: []
approved_by: Product Owner
approved_at: 2026-09-28
approval_reference: GEO Citation Contribution P1 implementation order
golden_case_ids: [CASE-SYN-001, CASE-SYN-008, CASE-REAL-019]
effective_from: 2026-09-28
supersedes: SC-FOUNDATION-001@0.1.0
last_verified_at: 2026-09-28
```

### SC-CITATION-CONTRIBUTION-001 Citation Contribution V1

```yaml
contract_id: SC-CITATION-CONTRIBUTION-001
contract_name: Citation Contribution V1
contract_version: 1.0.0
maturity: FROZEN
implementation_status: NOT_IMPLEMENTED
definition: 在固定 Run 内，将完整 Answer 拆为可回指原文的 AnswerUnit，并判断每条 Citation 的 Source Passage/Claim 对各 AnswerUnit 的可观察内容对应与证据关系；不证明模型生成因果。
dimensions:
  processing_status: [PENDING, DONE, FAILED, NOT_EVALUATED, SOURCE_UNAVAILABLE, WAIVED]
  correspondence_mode: [DIRECT_REUSE, FAITHFUL_PARAPHRASE, SUMMARY_OR_SYNTHESIS, TOPICAL_ONLY, NO_CORRESPONDENCE, UNKNOWN]
  evidence_relation: [SUPPORTS_FULL, SUPPORTS_PARTIAL, CONTRADICTS, RELATED_ONLY, NO_MATCH, INSUFFICIENT_EVIDENCE]
  answer_anchor: [PROVEN, UNPROVEN]
  generation_influence: [PROVEN, UNPROVEN, UNAVAILABLE]
allowed_inferences:
  - DONE 的 pair 可分别记录 correspondence_mode、evidence_relation 和 attribution。
  - 多个独立 Binding 可由 AnswerUnitEvidenceSet 投影 composite_support=true。
  - 每条 Citation 必须有 BOUND、NO_BINDING_FOUND_AFTER_SEARCH、INSUFFICIENT_SOURCE_CONTENT、SOURCE_WAIVED、ANALYSIS_FAILED 或 NOT_EVALUATED disposition。
forbidden_inferences:
  - FAILED/NOT_EVALUATED 自动变成 NO_MATCH、NO_SUPPORT 或任何负面关系。
  - 高内容对应自动升级 answer_anchor 或 generation_influence。
  - 将旧 SourceClaim-to-Reason Alignment verdict 直接映射为本 Contract verdict。
  - 将 COMPOSITE_SUPPORT 写成单个 pair verdict。
unknown_behavior: 无法完成判断时保留 processing_status、UNKNOWN/INSUFFICIENT_EVIDENCE 与 limitation，不制造贡献解释。
step_boundary: Answer/Evidence 分析；P1 不创建 StrategyCandidate、Execution 或 Product Truth。
source_references:
  - docs/semantics/snapshots/CASE-REAL-V2-P1-CITATION-CONTRIBUTION.checkpoint-0.json
observed_implementation_refs:
  - backend/app/modules/single_prompt_v2/citation_contribution.py
enforcement_refs:
  - backend/tests/test_single_prompt_v2_citation_contribution.py
approved_by: Product Owner
approved_at: 2026-09-28
approval_reference: GEO Citation Contribution P1 implementation order
golden_case_ids: [CASE-SYN-008, CASE-SYN-009, CASE-REAL-V2-P1]
effective_from: 2026-09-28
supersedes: null
last_verified_at: 2026-09-28
```

### SC-MECHANISM-SCOPE-001 Scoped Mechanism State

```yaml
contract_id: SC-MECHANISM-SCOPE-001
contract_name: Scoped Mechanism State
contract_version: 1.0.0
maturity: FROZEN
implementation_status: NOT_IMPLEMENTED
definition: CONTENT、DISCOVERY、SELECTION、CONTRIBUTION/ABSORPTION、ASSOCIATION、DECISION 的状态必须绑定各自对象与 Run scope；历史投影还必须绑定 fixed run set、time window 和 sampling protocol。
forbidden_inferences:
  - 仅在 Prompt 层记录 CONTENT=EXISTS 而不指明 claim/capability 与 managed asset scope。
  - 将固定样本覆盖解释为时间趋势。
unknown_behavior: 时间或采样条件不可比时 trend_status=NOT_COMPARABLE。
step_boundary: 横跨分析投影，不新增顶层工作流步骤。
approved_by: Product Owner
approved_at: 2026-09-28
approval_reference: GEO Citation Contribution P1 implementation order
effective_from: 2026-09-28
supersedes: null
last_verified_at: 2026-09-28
```

### SC-ASSET-001 Managed Asset Inventory Boundary

```yaml
contract_id: SC-ASSET-001
contract_name: Managed Asset Inventory Boundary
contract_version: 1.0.0
maturity: FROZEN
implementation_status: NOT_IMPLEMENTED
definition: SourceSnapshot 是被观察引用来源的不可变正文快照；ManagedAsset 是目标品牌拥有、控制或明确纳入盘点的资产。两者身份与资格不可互换。
allowed_inferences:
  - 资产盘点完整且确认没有适配资产时才允许 CREATE_NEW。
forbidden_inferences:
  - SourceSnapshot 自动成为 ManagedAsset。
  - 数据库中没有 ManagedAsset row 就推断品牌没有资产并自动 CREATE_NEW。
unknown_behavior: 资产盘点不完整时 asset_state=UNKNOWN，下一步为 VERIFY_ASSET_FIRST。
step_boundary: Asset Resolver/Execution；Citation Contribution 只消费 SourceSnapshot，不决定资产操作。
approved_by: Product Owner
approved_at: 2026-09-28
approval_reference: GEO Citation Contribution P1 implementation order
effective_from: 2026-09-28
supersedes: PR5 CREATE_NEW default when inventory completeness is unproven
last_verified_at: 2026-09-28
```

### SC-RUNTIME-001 Analysis Context And Stage Lifecycle

```yaml
contract_id: SC-RUNTIME-001
contract_name: Analysis Context And Stage Lifecycle
contract_version: 0.1.0
maturity: FROZEN
implementation_status: PARTIAL
definition: 单个 Prompt 的分析由不可变 AnalysisContext Root 与固定 16 节点 Stage DAG 表达；Stage 输入、输出、审核、失效、当前选择和 legacy 投影均绑定确定性 identity/hash，不能通过 latest/current fallback 拼接。
allowed_inferences:
  - 固定 Manifest、固定数据库身份与 Frozen Legacy Projection Profile 可生成只读 VIRTUAL_RUNTIME_PROJECTION。
  - legacy 缺失、可恢复但不完整、歧义分别保持 UNAVAILABLE、PARTIAL、UNSAFE。
forbidden_inferences:
  - 以最新 EvidencePackage、Candidate、AnalysisRun、Strategy 或 Experiment 替代固定对象。
  - 将 virtual projection 写入或用于 production current pointer、Review、Strategy、Action、Experiment、PR5 或 cache。
  - 将 mutable legacy review 状态升级为 immutable authoritative ReviewDecision。
unknown_behavior: 无法唯一恢复 lineage 时保留 null/missing refs 并输出 UNSAFE 或 UNAVAILABLE，不选择历史 winner。
step_boundary: 横跨 Step 1-8 的 runtime identity/lifecycle；不改变任何步骤业务语义，也不新增 Step 9。
source_references:
  - docs/semantics/rfcs/RFC-RUNTIME-001.md
  - docs/semantics/approvals/RFC-RUNTIME-001.definition-freeze.md
  - docs/semantics/reviews/RFC-RUNTIME-001.review-005.md
observed_implementation_refs:
  - docs/semantics/05_RUNTIME_SEMANTIC_MAP.md
  - backend/app/modules/runtime_persistence
enforcement_refs:
  - backend/app/modules/runtime_projection
  - backend/scripts/runtime_projection_spike.py
  - backend/tests/test_runtime_projection_spike.py
  - backend/app/modules/runtime_persistence
  - backend/alembic/versions/20260910_01_runtime_persistence_spine.py
  - backend/tests/test_runtime_persistence_spine.py
  - docs/semantics/spikes/RFC-RUNTIME-001.read-only-projection-spike.md
  - docs/semantics/shadows/RFC-RUNTIME-001.phase-1a-persistence-spine.md
approved_by: Product Owner
approved_at: 2026-09-09T15:25:02+08:00
approval_reference: docs/semantics/approvals/RFC-RUNTIME-001.definition-freeze.md
golden_case_ids: [CASE-REAL-019, CASE-REAL-040]
effective_from: 2026-09-09T15:25:02+08:00
supersedes: null
last_verified_at: 2026-09-10
```

### SC-AUTOMATION-001 Machine Continuation And Per-Use Qualification

```yaml
contract_id: SC-AUTOMATION-001
contract_name: Machine Continuation And Per-Use Qualification
contract_version: 1.0.0
maturity: FROZEN
implementation_status: PARTIAL
definition: Machine computation does not require a global human Review. Each exact-version object is qualified independently for Diagnosis, Strategy Direction, internal Execution Draft, public Claim and Publication. Human Review is an optional correction overlay; business approval remains required for external action.
allowed_inferences:
  - A grounded Answer Reason fully covered by confirmed target-brand capabilities may produce a Strategy Direction and internal Execution Draft.
  - A first-party asserted target capability may establish target applicability while its public Claim remains VERIFY_FIRST.
  - Partial Citation Contribution may enrich a direction only inside its exact Run scope.
forbidden_inferences:
  - Treating Review completion as universal fact, claim or publication eligibility.
  - Treating missing Review as a global blocker for all machine computation.
  - Expanding Run 1 Citation Contribution into a nine-Run citation, channel or generation-causality conclusion.
  - Using a source-free target capability as public copy.
  - Treating an internal Execution Draft as external-action authorization.
unknown_behavior: Missing or insufficient object dependencies remain VERIFY_FIRST, OBSERVE_ONLY or NOT_CONSUMABLE for the affected use without erasing independently qualified uses.
step_boundary: V2 read-only Strategy Direction and internal Execution Draft projection; no StrategyCandidate, Review, Publication or external action is created.
source_references:
  - docs/GEO_1_0_QUALIFICATION_VERTICAL_SLICE.md
observed_implementation_refs:
  - backend/app/modules/single_prompt_v2/qualification.py
enforcement_refs:
  - backend/tests/test_single_prompt_v2_qualification.py
approved_by: Product Owner
approved_at: 2026-09-29
approval_reference: GEO Platform 1.0 four-plane implementation final override
golden_case_ids: [CASE-REAL-V2-QUALIFICATION]
effective_from: 2026-09-29
supersedes: null
last_verified_at: 2026-09-29
```

### SC-GRADED-DELIVERY-001 Evidence-Graded Product Delivery

```yaml
contract_id: SC-GRADED-DELIVERY-001
contract_name: Evidence-Graded Product Delivery
contract_version: 1.0.0
maturity: FROZEN
implementation_status: PRODUCTION
definition: Exact, identity-safe inputs produce an immutable pre-request DeliveryQualificationPlan and an append-only admitted Result. Evidence quality selects L1-L4 delivery form; identity, permission, version and fact-grounding integrity remain hard blockers.
allowed_inferences:
  - Fully grounded selected blocks may form L1 content.
  - Independently supported blocks may form L2 while unsupported parts are deleted or kept as explicit verification work.
  - Valid inputs with no consumable fact evidence may form L3 instruction-only action, research and verification content.
  - Integrity-valid but unusable or missing analytic input may form an L4 recovery package with zero model calls.
forbidden_inferences:
  - A lower delivery level upgrades Evidence, Product Truth, public-claim or publication eligibility.
  - UNKNOWN, failed or unevaluated input becomes a fact.
  - L4 masks identity, permission, version or scope failure, or unlocks content-delivery dependencies.
  - Synthetic graded-delivery fixtures pass a real E1/E2/E3 scenario.
unknown_behavior: Preserve UNKNOWN and excluded members; convert only their known limitations into verification or recovery actions.
step_boundary: Qualification inside the existing Optimize -> Strategy -> Execution -> QA chain; no second chain or new product step.
source_references:
  - docs/semantics/rfcs/RFC-GRADED-DELIVERY-001.md
  - docs/semantics/approvals/RFC-GRADED-DELIVERY-001.definition-freeze.md
observed_implementation_refs:
  - backend/app/modules/single_prompt_v2/graded_delivery.py
  - backend/app/modules/single_prompt_v2/automatic_delivery.py
  - backend/app/modules/single_prompt_v2/execution.py
  - backend/app/modules/single_prompt_v2/delivery_generation.py
  - frontend/src/DeliveryQualificationCard.tsx
  - frontend/src/deliveryQualification.ts
enforcement_refs:
  - docs/semantics/snapshots/CASE-GRADED-DELIVERY-001.manifest.json
approved_by: Product Owner
approved_at: 2026-10-19
approval_reference: docs/semantics/approvals/RFC-GRADED-DELIVERY-001.definition-freeze.md
golden_case_ids: [CASE-GRADED-DELIVERY-001, GRADED-L1-NORMAL, GRADED-L2-PARTIAL-UNKNOWN, GRADED-L3-LOW-EVIDENCE, GRADED-L4-NO-CONSUMABLE-ANSWER, GRADED-MIXED-DIRECTIONS]
effective_from: 2026-10-19
supersedes: null
last_verified_at: 2026-10-19
```

### SC-RUN-IMPORT-001 Manual Observation Run Admission

```yaml
contract_id: SC-RUN-IMPORT-001
contract_name: Manual Observation Run Admission
contract_version: 1.0.0
maturity: FROZEN
implementation_status: PRODUCTION
definition: 用户人工观察并提交的真实 AI 回答，只有在服务端严格冻结 Project、Prompt、观察时有效的 PromptVersion 与 ProjectConfigurationVersion、observed_at、来源平台、原文/引用 hash 和导入人后，才可作为 MANUAL_IMPORT Run 进入正式范围选择。
allowed_inferences:
  - 完整性、身份和 hash 校验通过的 MANUAL_IMPORT Run 可与合格自动采集 Run 一样进入明确的时间范围或 Run ID 冻结分析。
  - COMPLETE、CONFIRMED_NONE、UNKNOWN、PARSE_FAILED 分别表达引用记录的观测状态。
forbidden_inferences:
  - 本地 hash、导入人声明或字段完整证明第三方平台真实性。
  - 未提供引用等于零引用，或解析失败等于无引用。
  - latest 版本回填、LEGACY_UNBOUND 升级、人工导入冒充自动采集。
  - 导入自动触发语义分析、Optimize、Evidence Pack、Validate、外部采集或模型调用。
unknown_behavior: 来源真实性保持 USER_ATTESTED_UNVERIFIED；引用未知或解析失败保持 UNKNOWN/失败，不升级为合法零。
identity: project + prompt + exact prompt/config version IDs and hashes + observed_at + platform + answer/citation hashes + MANUAL_IMPORT + importer
history: Run 与人工导入审计追加保存；既有 Run、AnalysisContext 和结果均不改写。
step_boundary: 仅扩展 Step 1 Run 准入；不改变下游分析、Evidence、Truth 或分级交付规则。
source_references:
  - docs/semantics/rfcs/RFC-MANUAL-RUN-IMPORT-001.md
enforcement_refs:
  - backend/app/modules/single_prompt_v2/manual_import.py
  - backend/tests/test_manual_run_import.py
approved_by: Product Owner
approved_at: 2026-10-21
approval_reference: GEO M1 — MANUAL_IMPORT 窄语义契约批准
golden_case_ids: [MANUAL-IMPORT-NORMAL, MANUAL-IMPORT-VERSION-TIME-REJECT, MANUAL-IMPORT-CITATION-UNKNOWN, MANUAL-IMPORT-LEGACY-BLOCK]
effective_from: 2026-10-21
supersedes: null
last_verified_at: 2026-10-21
```

### SC-RUN-RETRY-001 Business Run Retry And Attempt Audit

```yaml
contract_id: SC-RUN-RETRY-001
contract_name: Business Run Retry And Attempt Audit
contract_version: 1.0.0
maturity: FROZEN
implementation_status: PRODUCTION
definition: 失败且尚未被任何不可变分析或下游结果消费的采样 Run 是可重试的业务样本槽位；重试是内部 Attempt，不新增业务 Run。成功后以同一 Run ID 保存回答、引用、实际采集时间和 hash，失败过程保留在内部执行审计。
allowed_inferences:
  - 一个业务 Run 可以有多次 Attempt，Run 池样本数与执行尝试数分别统计。
  - 无可用回答、未被消费的 failed 或明确可恢复的 blocked/rate_limited Run 可由用户显式重试。
forbidden_inferences:
  - 已成功、部分成功、含真实回答或已进入 AnalysisContext/正式下游的 Run 可以原位覆盖。
  - 失败 Attempt 是独立业务样本，或可以进入 GEO 分析分母。
  - 重试会自动触发分析、Evidence Pack、Validate、内容生成或额外重试。
unknown_behavior: Worker 在外部调用期间中断时，本次 Attempt 标记失败且不自动重放；Run 保留明确失败原因，等待新的人工重试。
identity: stable BrowserMonitorRun.id + logical_run_id for the business sample; unique BrowserMonitorRunAttempt.attempt_id/task/idempotency for each retry execution
history: 已冻结成功观测和所有下游结果不可改写；失败尝试以追加式 Attempt 审计保存。
step_boundary: 仅调整 Step 1 失败采样的生命周期与 UI 状态，不改变分析、Evidence、Truth 或分级交付语义。
source_references:
  - docs/semantics/rfcs/RFC-BUSINESS-RUN-RETRY-001.md
enforcement_refs:
  - backend/app/modules/single_prompt_v2/service.py::queue_run_retry
  - backend/scripts/release_worker.py::recover_interrupted_run_retries
  - backend/tests/test_run_retry_lineage.py
  - backend/tests/test_release_first_slice.py
approved_by: Product Owner
approved_at: 2026-10-23
approval_reference: 用户明确批准 RFC-BUSINESS-RUN-RETRY-001 Definition Freeze 与本机 Beta 切换
golden_case_ids: [RUN-RETRY-NORMAL, RUN-RETRY-FAIL-AGAIN, RUN-RETRY-CONSUMED-BLOCK, RUN-RETRY-PARTIAL-CONTENT-BLOCK]
effective_from: 2026-10-23
supersedes: append-only physical retry Run behavior from 2026-10-15
last_verified_at: 2026-10-23
```

### SC-MULTI-DRAFT-ARTIFACT-001 Frozen Optimize And Versioned Draft Assets

```yaml
contract_id: SC-MULTI-DRAFT-ARTIFACT-001
contract_name: Frozen Optimize And Versioned Draft Assets
contract_version: 1.0.0
maturity: FROZEN
implementation_status: PARTIAL
definition: AgentResultVersion 表示一次冻结 Optimize；明确类型的 HELP_DOC/FAQ 以不可变 DraftArtifactVersion 子版本保存，分别绑定 Evidence、QA、反馈、导出和重生成 lineage。
allowed_inferences:
  - 子资产最新版本全部成功时父交付状态为 SUCCESS；成功与失败并存为 PARTIAL_SUCCESS；无成功为 FAILED。
  - 单资产重生成只追加相同 artifact_id 的下一版本，并引用 previous_artifact_version。
  - 无子资产的旧结果继续按 LEGACY_SINGLE_DRAFT 读取。
forbidden_inferences:
  - 改写父 AgentResultVersion、兄弟资产或旧子版本。
  - 从旧 deliverable 文案猜测 HELP_DOC/FAQ 并补绑。
  - 子资产成功升级 Evidence、Truth、Review、Gate 或发布资格。
  - 客户端自定模型次数、Token、金额或跨 Project/Prompt 访问。
unknown_behavior: 子资产缺失、正文为空或 Evidence/QA 不完整时只影响该子资产并保留失败；UNKNOWN 不升级。
identity: exact parent result version + project/prompt/run scope + logical artifact id + version + hashes
history: parent and children append-only; feedback append-only; regeneration request identity immutable
step_boundary: existing isolated Agent Experiment Optimize result only; no formal V2 write and no second analysis chain
source_references:
  - docs/semantics/rfcs/RFC-MULTI-DRAFT-ARTIFACT-001.md
  - docs/semantics/approvals/RFC-MULTI-DRAFT-ARTIFACT-001.definition-freeze.md
enforcement_refs:
  - backend/app/modules/agent_experiment/service.py
  - backend/tests/test_agent_draft_artifacts.py
approved_by: Product Owner
approved_at: 2026-10-30
approval_reference: GEO M1.2 B-line explicit approved semantic change
golden_case_ids: [MULTI-DRAFT-PARTIAL, MULTI-DRAFT-REGENERATE-ONE, MULTI-DRAFT-CROSS-SCOPE, MULTI-DRAFT-LEGACY]
effective_from: 2026-10-30
supersedes: null
last_verified_at: 2026-10-30
```

### SC-AGGREGATE-OBSERVATION-001 Server-Verified Aggregate Observation

```yaml
contract_id: SC-AGGREGATE-OBSERVATION-001
contract_name: Server-Verified Aggregate Observation
contract_version: 1.0.0
maturity: FROZEN
implementation_status: IMPLEMENTED_OFFLINE_NOT_RELEASED
definition: Prompt v10 / Execution v12 / Validation v5 中的总体品牌字面缺席观察由服务端基于非空、身份完整的冻结有效回答集合计算，并以独立的 Evidence Set 与 Observation hash 固定；模型只可复用服务端规范文字和 locator，不能决定成员或事实值。
allowed_inferences:
  - 完整非空的 FROZEN_VALID_SCOPE 中所有有效完整回答均未命中冻结品牌名称/别名时，可陈述该范围内目标品牌字面未出现。
  - v5 初始切片只接受服务端 FROZEN_VALID_SCOPE 缺席观察；普通完整回答证据不构成 SAMPLE 观察，也不能升级为总体观察。
forbidden_inferences:
  - 字面未出现证明未推荐、能力不足、排名、竞品更优、因果原因或 Product Truth。
  - 合法 Evidence Set ID 允许模型自定 predicate、量词、事实值或额外总体断言。
  - 少成员、多成员、重复成员、跨 Project/Prompt/version、旧 hash 或部分回答构成合法总体范围。
  - 通过相邻免责声明、限制说明或整章关键词改变另一条观察的 scope。
unknown_behavior: 空范围、无效或未决成员、品牌身份/匹配规则不确定、身份/hash/version 不完整或不一致时不生成已验证缺席观察；UNKNOWN 不计为零。
output_boundary: 品牌事实区必须逐字等于服务端规范观察；其他章节出现原始冻结回答范围断言时阻断，不通过相邻说明推断或改变 scope。
identity: evidence_set_hash over canonical frozen members and scope identity; separate observation_hash over predicate + subject + quantifier + scope + evidence_set_hash + server-computed value
history: v9/v11/v4 及既有结果保持原解释和状态；不回填、不重验、不重标。
step_boundary: Evidence Pack 构建与结果校验内部；不改变采样、正式 V2、Truth、Review、发布或父子资产不可变规则。
source_references:
  - docs/semantics/rfcs/RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001.md
  - docs/semantics/approvals/RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001.definition-freeze.md
enforcement_refs:
  - backend/app/modules/agent_experiment/evidence_pack.py
  - backend/tests/test_agent_experiment.py
approved_by: Product Owner
approved_at: 2026-11-10
approval_reference: GEO M1.2 third real acceptance approval
golden_case_ids: [AGGREGATE-ABSENCE-ALL, AGGREGATE-ABSENCE-PRESENCE-BLOCK, AGGREGATE-SET-IDENTITY-BLOCK, AGGREGATE-EXTRA-CLAIM-BLOCK, AGGREGATE-HISTORY-COMPAT]
effective_from: 2026-11-10
supersedes: null
last_verified_at: 2026-11-10
```

## 3. Definition Freeze Queue

`SC-RUNTIME-001@0.1.0` 已由 Product Owner 在独立 Review 005 通过后正式
Definition Freeze；Phase 1A 后其 `implementation_status=PARTIAL`，仅表示隔离的
persistence spine 已实现，不代表 live Shadow capture 或 Production Cutover。

可提交 Product Owner 首轮 Freeze Review 的稳定边界候选：`SC-HISTORY-001`、`SC-PT-001`、`SC-UNKNOWN-001`、`SC-EVIDENCE-001/002/003`、`SC-BENCHMARK-001`、`SC-STEP7-001`、`SC-STEP8-001`、`SC-EXPERIMENT-001`、`SC-SCOPE-001`、`SC-DECISION-STABILITY-001`。

暂不建议冻结、仍需定义收敛：`SC-GAP-001`、`SC-STRATEGY-001`。`SC-CHANNEL-001` 的 Path C 已被 `SC-CHANNEL-002@1.0.0` 取代；`SC-FOUNDATION-001@1.0.0`、`SC-CITATION-CONTRIBUTION-001@1.0.0`、`SC-MECHANISM-SCOPE-001@1.0.0` 与 `SC-ASSET-001@1.0.0` 已由 Product Owner 冻结。

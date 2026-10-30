# GEO Semantic Domain Model

状态：ACTIVE
日期：2026-09-08

## 1. 用途

本文件维护 GEO 主链中业务对象的稳定词汇。它描述对象是什么、由谁产生、可以支持什么推断，以及不能跨越的边界；它不以数据库表或前端文案代替业务定义。

语义成熟度与实现状态是两个正交维度：

```text
maturity = OBSERVED | CANDIDATE | FROZEN | SUPERSEDED
implementation_status = NOT_IMPLEMENTED | SHADOW | PARTIAL | PRODUCTION | DIVERGED | SUPERSEDED
```

首批对象是对当前系统的观察，除非 Product Owner 后续按 Definition Review 明确批准，否则不因进入本文件而自动成为 FROZEN。

## 2. 核心对象

### Server Model Execution Policy

- 定义：由服务端绑定部署或认证账号的模型运行资格与技术停止边界；它不是员工填写的任务参数。
- 标识：当前 M1 为部署策略与持久化账本身份；未来账号级策略必须绑定认证主体。
- 产生：服务部署配置，不由 Optimize 页面或模型产生。
- 可推断：当前员工是否可对一个已冻结输入发起 AI 优化。
- 禁止推断：客户端填写额度、历史实验余额或模型输出不能授予/扩大运行权限。
- 未知行为：策略、账本或价格配置不可验证时，在外部请求前阻断。
- 当前实现：`backend/app/services/internal_beta_model_budget.py`。

### Run

- 定义：一次 Prompt 在指定平台和采集上下文中的业务观测槽位。失败且尚未被正式分析消费时，
  槽位可通过新的内部 Attempt 重试；只有形成可用观测或进入不可变下游后，Run 内容才冻结。
- 标识：`BrowserMonitorRun.id`。
- 产生：Step 1 数据采集。
- 可推断：本次回答、引用、检索候选和采集状态。
- 禁止推断：单个 Run 不代表稳定效果；`success` 不自动等于正式分析可用。
- 重试边界：失败 Attempt 只属于执行审计，不是新的业务样本；已有部分真实回答或已进入
  AnalysisContext/正式下游的 Run 不得原位覆盖。
- 当前实现：`backend/app/models/db.py::BrowserMonitorRun`。

### AnswerUnit

- 定义：从一个 Run 的回答中切分出的、可独立判断语义和证据关系的最小回答单元。
- 标识：`AnswerUnit.id`，语义复用另由 semantic hash/version 约束。
- 产生：Step 2 答案/决策识别。
- 可推断：该回答片段表达的实体、能力、场景或理由。
- 禁止推断：AnswerUnit 本身不证明目标品牌能力，也不等于引用证据。
- 当前实现：`backend/app/models/db.py::AnswerUnit`。

### AnswerDecisionBinding

- 定义：AnswerUnit 与同一 Run 中可观察引用/检索上下文之间的绑定事实。
- 标识：`AnswerDecisionBinding.id`。
- 产生：Step 2/4 的 lineage 构建。
- 可推断：哪些来源在该回答语义的局部上下文中被观察到。
- 禁止推断：绑定不自动等于 SUPPORTS；低质量或缺失绑定不得扩展为历史全库关系。
- 当前实现：`backend/app/models/db.py::AnswerDecisionBinding`。

### Decision Reason

- 定义：答案选择、推荐或排除某一对象时可归因的 capability/reason-level 语义理由。
- 标识：当前为 Evidence/Gap/Strategy payload 中的稳定 reason identity，并非独立表。
- 产生：Step 2 识别，Step 6 归并诊断。
- 可推断：同一理由上的证据、Product Truth、缺口和策略覆盖关系。
- 禁止推断：不同理由不得仅因文本相似而共享证据或 Product Truth。
- 当前实现：`workflow.py`、`service.py` 与策略结构化 payload。

### Theme

- 定义：由兼容的 Decision Reasons 确定性归组形成的策略主题。
- 标识：Strategy Candidate payload 内 theme id。
- 产生：Step 7 Strategy Synthesis。
- 可推断：成员 Reasons 的合集及其 Run ID 并集覆盖。
- 禁止推断：标题不得引入成员 Reasons 中不存在的新能力、实体或限定；coverage 不得相加或由 LLM 猜测。
- 当前实现：`strategy_synthesis_shadow.py` 的 production core/read model。

### Product Truth

- 定义：经人工确认的目标品牌自身能力事实及其事实边界。
- 标识：`TargetBrandCapabilityTruth.id`。
- 产生：Step 3。
- 可推断：目标品牌可被安全陈述的明确能力。
- 禁止推断：竞品能力、第三方 SourceClaim 或 Benchmark 不能自动推出目标品牌能力；UNKNOWN 必须保持 UNKNOWN。
- 当前实现：`backend/app/models/db.py::TargetBrandCapabilityTruth`。

### Reference / Citation

- 定义：Run 回答中实际展示或解析出的引用来源观测。
- 标识：`ReferenceSource.id`，并保留 run lineage 和 URL identity。
- 产生：Step 1。
- 可推断：某来源在某次回答中被引用。
- 禁止推断：被引用不自动等于支撑某个 Decision Reason，也不自动成为 Benchmark 或执行渠道。
- 当前实现：`backend/app/models/db.py::ReferenceSource`。

### Retrieval Candidate

- 定义：采集过程中观察到的检索候选来源。
- 标识：`RetrievalCandidate.id`。
- 产生：Step 1。
- 可推断：来源曾进入该 Run 的检索候选环境。
- 禁止推断：Retrieval 不等于 Citation、SUPPORTS、渠道有效性或因果效果。
- 当前实现：`backend/app/models/db.py::RetrievalCandidate`。

### SourceDocument

- 定义：按规范化来源身份和正文版本保存的来源文档。
- 标识：`SourceDocument.id`，内容复用还受 content hash/version 约束。
- 产生：Step 4 来源抓取与正文解析。
- 可推断：指定来源版本的正文和 passage 上下文。
- 禁止推断：相同 URL 不保证正文版本相同；文档存在不等于任何具体 Claim 成立。
- 当前实现：`backend/app/models/db.py::SourceDocument`。

### SourceClaim

- 定义：从 SourceDocument passage 中按版本化提取契约得到的原子来源主张。
- 标识：`SourceClaim.id`；物化真相由 `SourceClaimMaterialization` 管理。
- 产生：Step 4。
- 可推断：来源文本明确表达的主张。
- 禁止推断：SourceClaim 不自动适用于目标品牌，不自动支持任意 AnswerUnit；`DONE + 0 claims` 是合法物化结果。
- 当前实现：`backend/app/models/db.py::SourceClaim`、`source_claim.py`。

### EvidenceAlignment

- 定义：在 Phase 2A run lineage 和候选范围内，AnswerUnit 与 SourceClaim 之间的版本化语义关系。
- 标识：`EvidenceAlignment.id`；物化真相由 `EvidenceAlignmentMaterialization` 管理。
- 产生：Step 4。
- 可推断：具体 pair 的 SUPPORTS、CONTRADICTS 或非支持关系及人工审核状态。
- 禁止推断：无有效 lineage 的旧关系不得进入正式 V1.1；人工审核不成为未来候选召回白名单。
- 当前实现：`evidence_alignment.py`、`evidence_alignment_candidates.py`。

### CitationContribution

- 定义：固定 Run 内，Source Passage/Claim 对原文可回指 AnswerUnit 的可观察内容对应和证据关系。
- 身份：固定 Analysis/Context、Run、Answer Result/Review、Citation Manifest、Completion Manifest、AnswerUnit、Citation occurrence、Passage/Claim 及 Contract version 的确定性组合。
- 独立维度：`processing_status`、`correspondence_mode`、`evidence_relation`、`answer_anchor`、`generation_influence`。
- 集合关系：Composite Support 只存在于 `AnswerUnitEvidenceSet` 聚合投影，不是 pair verdict。
- 禁止推断：内容对应不证明模型使用该来源生成答案；失败或未评估不等于 NO_MATCH/NO_SUPPORT；旧 Alignment 不能直接迁移为 CitationContribution。

### ManagedAsset / AssetInventory

- `SourceSnapshot`：AI 回答所列来源正文的冻结快照，只用于证据分析。
- `ManagedAsset`：目标品牌拥有、控制或明确纳入资产盘点的页面/内容。
- `AssetInventory`：声明盘点范围及是否完整；不完整时资产状态为 `UNKNOWN`。
- 禁止推断：SourceSnapshot 不是 ManagedAsset；缺少 ManagedAsset row 不是“资产不存在”；只有完整盘点确认无适配资产时才允许 CREATE_NEW。

### Benchmark

- 定义：在满足资格条件的证据关系上，对可比较来源能力/理由进行的只读对标归纳。
- 标识：当前为 Step 5 结构化派生结果，不是独立持久化实体。
- 产生：Step 5。
- 可推断：外部来源在相同理由上的可比较证据模式。
- 禁止推断：Citation Prominence 不能决定 Benchmark；Benchmark 平台不能自动成为执行平台；Benchmark 不证明目标品牌能力。
- 当前实现：`service.py` 的 formal evidence/diagnosis 组装路径。

### Gap

- 定义：在 Decision Reason、Product Truth、Evidence 和 Benchmark 约束下得到的 capability/reason-level 缺口。
- 标识：当前为诊断记录及 Strategy input 中 gap identity。
- 产生：Step 6。
- 可推断：属于产品能力、答案决策证据、内容承载或未知中的哪一类缺口。
- 禁止推断：无 Benchmark 不等于无缺口；UNKNOWN 不得自动变成可执行内容结论。
- 当前实现：`service.py` 与 `OptimizationIssue/DecisionGapDiagnosis` 相关路径。

### Channel Evidence

- 定义：按渠道聚合 Reference、Retrieval、Document、Claim 和 Decision Citation 的只读观察画像。
- 标识：channel key + 固定 Run scope + evidence contract version。
- 产生：Step 7 Resolver 输入层。
- 可推断：渠道在当前 scope 中的观测类型和覆盖。
- 禁止推断：引用数量不自动等于决策价值；渠道画像不直接决定 Role。
- 当前实现：`channel_evidence.py`。

### Channel Role

- 定义：Resolver 在固定 Reason、Product Truth、Channel Evidence 和资格门槛下给出的 `PRIMARY/SECONDARY/TEST/OBSERVE`。
- 标识：Strategy Candidate payload 中 channel key + resolver version。
- 产生：Step 7。
- 可推断：该渠道在当前 Strategy Core 中的职责和优先级边界。
- 禁止推断：Benchmark 渠道不自动升级；Step 8 不能改 Role；历史 Role 不跨 Candidate 继承。
- 当前实现：`channel_resolution_shadow.py::resolve_channel_shadow`（生产与 shadow 共享 core）。

### StrategyCandidate

- 定义：对固定 Evidence Package 的 Reasons、Themes、Gaps、Channel Roles 和策略边界的待人工确认快照。
- 标识：`OptimizationStrategyCandidate.id`。
- 产生：Step 7。
- 可推断：确认后可进入 Step 8 选择具体执行参数。
- 禁止推断：生成或确认 StrategyCandidate 不创建 Action/Experiment；历史 Candidate 不计入当前主链。
- 当前实现：`backend/app/models/db.py::OptimizationStrategyCandidate`、`service.py::review_strategy_candidate`。

### ExecutionProposal

- 定义：从已确认 Strategy Truth 确定性编译出的、一资产一渠道的可审核执行建议。
- 标识：当前为 PR5-A/B 临时 snapshot/proposal id，未持久化为正式实体。
- 产生：Step 8 审核阶段。
- 可推断：合法资产包、类型、标题、Sections、观察窗口和指标候选。
- 禁止推断：不能改写 Strategy、Role、Reason Scope、Product Truth、Baseline 或指标资格；`ready_for_freeze` 不等于已创建 Action/Experiment。
- 当前实现：`execution_proposal_shadow.py`、PR5-B API/read model。

### Action

- 定义：经 Step 8 最终确认后要执行的具体渠道、资产和发布动作。
- 标识：`OptimizationAction.id`。
- 产生：Step 8，且仅在独立 cutover/确认路径中。
- 可推断：谁在何处对哪个资产做什么。
- 禁止推断：Step 7 不能创建；历史 Action 不点亮当前 Evidence Package。
- 当前实现：`backend/app/models/db.py::OptimizationAction`、`service.py::confirm_strategy_execution_plan`（现有路径）。

### Experiment

- 定义：绑定一个 Action、固定 Baseline 和成功指标的可复测执行单元。
- 标识：`OptimizationExperiment.id`。
- 产生：Step 8。
- 必须冻结：`strategy_snapshot`、`gap_snapshot`、`action_snapshot`、selected asset snapshot/ref、`baseline_run_ids`、`baseline_metrics`。
- 禁止推断：创建草案不等于发布或有效；Decision Stability 仅旁路观测，不改变 Step 1–8。
- 当前实现：`backend/app/models/db.py::OptimizationExperiment`、`service.py::create_experiment`。

### OptimizeResult / DraftArtifactVersion

- `AgentResultVersion`：一次明确冻结 Project/Prompt/Run 输入上的不可变 Optimize 结果，不等于单篇稿件。
- `DraftArtifactVersion`：该结果下一个明确内容资产的追加式版本；首批类型仅 `HELP_DOC`、`FAQ`。
- 标识：`parent_result_version + artifact_id + version_number`；重生成保存 `previous_artifact_version`。
- 可推断：各子资产独立成功或失败，父交付状态可派生为 SUCCESS/PARTIAL_SUCCESS/FAILED。
- 禁止推断：子稿不得升级 Evidence/Truth/发布资格；一稿成功不得掩盖另一稿失败；旧单稿不得猜测类型回填。
- 当前实现：`AgentDraftArtifactVersion`、`AgentDraftArtifactFeedback`、`AgentDraftArtifactRegeneration`。

## 3. 对象流与边界

```text
Run
-> AnswerUnit / Decision Reason
-> Product Truth
-> Reference / Retrieval / SourceDocument / SourceClaim / EvidenceAlignment
-> Benchmark
-> Gap
-> Channel Evidence / Channel Role
-> StrategyCandidate
-> ExecutionProposal
-> Action / Experiment
```

任何跨箭头推断都必须由对应 Semantic Contract 允许。数据库外键、相邻前端卡片或同名字段不能代替该许可。

## 4. Identity、Source Of Truth 与生命周期矩阵

下表补齐每个对象的治理字段。`Current Maturity` 描述本次文档观察成熟度，不等于对应 Contract 已冻结。

| Object | Not This / Aliases | Identity / Scope Key | Source of Truth | Inputs -> Outputs | Owner / Allowed Consumers | Mutability / Lifecycle / Terminal | Current Maturity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Run | 不是“稳定结论”、失败 Attempt 或 Sample 展示标签 | run id；project + prompt + logical sample identity | `BrowserMonitorRun`、`BrowserMonitorRunAttempt` 与原始 artifact | collector input -> answer/reference/retrieval facts；失败重试 -> internal Attempt | Step 1 / Step 2-8 只读 | 未被消费且无可用回答的失败槽位可重试更新；成功、部分成功、含真实回答或被下游消费后不可覆盖 | FROZEN |
| AnswerUnit | 不是整个答案，也不是 Product Truth | id；run + unit order + semantic contract | `AnswerUnit` persisted row | Run answer -> atomic semantic unit | Step 2 / Binding、Evidence、Gap | 新版本重建或语义复用，不原地改历史语义 | OBSERVED |
| AnswerDecisionBinding | 不是 EvidenceAlignment | id；answer unit + same-run source lineage + binding version | `AnswerDecisionBinding` | AnswerUnit + observed context -> binding | Step 2/4 / candidate builder | 可追加版本；verified/rejected/low/none 显式 | OBSERVED |
| Decision Reason | 不是 Theme 或自由文案 | stable reason id within fixed evidence/strategy input | versioned structured payload | AnswerUnit/recommendation -> reason | Step 2/6 / Evidence、Gap、Strategy | 随输入版本化；不能跨 scope 偷换 identity | OBSERVED |
| Theme | 不是新的能力事实 | theme id + member reason ids + synthesis version | Candidate effective structured payload | compatible reasons -> theme + union coverage | Step 7 / Step 8 只读 | Candidate version内不可变；随 Candidate supersede | OBSERVED |
| Product Truth | 不是竞品 Claim/Benchmark | truth id + target brand + capability scope | `TargetBrandCapabilityTruth` + human provenance | manual confirmation -> TRUE/FALSE/UNKNOWN fact | Step 3 / Gap、Strategy、Execution | 追加确认/版本；UNKNOWN 是合法稳定状态 | OBSERVED |
| Reference/Citation | 不是 Decision Citation | reference id + run lineage + normalized URL | `ReferenceSource` | Run parse -> observed citation | Step 1 / Document、Evidence、Channel Evidence | 原始观测不可覆盖；解析修复保留 lineage | OBSERVED |
| Retrieval Candidate | 不是 Citation/SUPPORTS | retrieval id + run lineage + URL/rank | `RetrievalCandidate` | Run retrieval artifact -> exposure observation | Step 1 / Channel Evidence | 原始观测不可覆盖 | OBSERVED |
| SourceDocument | 不是 URL 字符串或 PageSnapshot | document id + canonical source identity + content version/hash | `SourceDocument` | source fetch -> versioned body/passages | Step 4 / SourceClaim | 新正文新版本；fetch failure/ready 显式 | OBSERVED |
| SourceClaim | 不是目标品牌事实 | claim id；materialization key + passage/content contract | `SourceClaimMaterialization` ledger + bound claims | passage semantic input -> zero or more claims | Step 4 / Alignment、Benchmark | lookup-first；DONE+0 合法；版本 stale 后补算 | OBSERVED |
| EvidenceAlignment | 不是 Binding 或 Citation count | alignment id；answer semantic hash + claim semantic hash + version + lineage | `EvidenceAlignmentMaterialization` ledger + alignments | eligible pair -> verdict/review | Step 4 / Benchmark、Gap | verdict/review 追加；历史不可删除；DONE negative 合法 | OBSERVED |
| CitationContribution | 不是生成归因，也不是旧 Reason Alignment | fixed input hashes + Run + AnswerUnit + citation occurrence + passage/claim + contract | V2 immutable result payload | full Answer + same-run citations + fixed snapshots -> contribution | Answer/Evidence / 后续 mechanism projection | 结果版本不可变；人工校准追加；旧 Alignment 仅作线索 | FROZEN/PARTIAL_P1 |
| ManagedAsset | 不是 SourceSnapshot | project + owned/control identity + content version + permission evidence | 后续最小 AssetInventory/ManagedAsset | explicit inventory -> asset eligibility | Asset Resolver / Execution | 资产盘点版本化；UNKNOWN 不得自动 CREATE_NEW | FROZEN/NOT_IMPLEMENTED |
| Benchmark | 不是热门来源榜 | fixed evidence package + reason + benchmark contract | versioned formal evidence/diagnosis payload | eligible alignments -> comparable pattern | Step 5 / Gap、Strategy | 随 Evidence Package 重算；无 eligible 是合法空结果 | OBSERVED |
| Gap | 不是 Strategy/Action | gap id + reason + fixed evidence/truth scope | persisted diagnosis/versioned Candidate input | reason + truth + evidence + benchmark -> gap type | Step 6 / Step 7 | 按 package/version supersede；UNKNOWN 合法 | OBSERVED |
| Channel Evidence | 不是 Channel Role | channel key + fixed run scope + aggregation version | deterministic read model from persisted observations | references/retrieval/docs/claims/alignments -> profile | Step 7 input / Resolver | 派生可重算；必须固定 scope/version | OBSERVED |
| Channel Role | 不是具体发布位置或效果结论 | candidate + channel key + resolver version | Candidate effective payload generated by Resolver | reason/truth/channel evidence/gates -> role | Step 7 / Step 8 只读 | Candidate 内冻结；随 Candidate supersede | OBSERVED |
| StrategyCandidate | 不是 Action/Experiment | candidate id + project/prompt/package/input contract | persisted candidate + effective payload + contract version | Gap/Resolver -> reviewable strategy | Step 7 / Step 8 | 只能 review/version/supersede，不原地覆盖已接受对象 | OBSERVED |
| ExecutionProposal | 不是 Action，也不是 persisted truth | proposal/snapshot id + accepted candidate + package/channel | PR5-A/B canonical ephemeral payload | Strategy + allowed assets -> review proposal | Step 8 / human revalidation only | overlay 重建；READY 不等于持久化终态 | OBSERVED |
| Action | 不是 Strategy proposal | action id + accepted candidate/experiment lineage | `OptimizationAction` | confirmed execution choice -> concrete action | Step 8 / Experiment | 创建后按状态推进；历史 action 不改 current scope | OBSERVED |
| Experiment | 不是效果结论 | experiment id + one action + frozen snapshot set | `OptimizationExperiment` frozen fields | action + asset + baseline -> draft/retest unit | Step 8 / release、retest、conclusion | 快照不可变；draft/released/retested/concluded 显式 | OBSERVED |
| OptimizeResult | 不是单篇稿件或正式 V2 ResultVersion | exact AgentResultVersion + frozen scope hashes | `AgentResultVersion` | Evidence Pack/Agent result -> immutable parent result | Agent Experiment / child asset read only | 追加版本，不原位改写；子稿状态只派生展示 | FROZEN |
| DraftArtifactVersion | 不是父结果、Truth 或发布批准 | parent result + logical artifact id + version | `AgentDraftArtifactVersion` | explicit HELP_DOC/FAQ deliverable + Evidence/QA -> child version | internal Beta content use / exact feedback/export | append-only；重生成追加 lineage；失败独立保存 | FROZEN |

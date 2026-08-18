# GEO Platform 产品项目功能说明书

状态：ACTIVE
日期：2026-08-17
适用版本：`main` at `6292f6ca31d5841df900e582d91c7ab03016ea5d`

## 1. 产品定位

GEO Platform 是一个面向中文业务操作者的 AI/GEO 品牌可见性审计与优化闭环工具。

它要回答的核心业务问题是：

```text
当 AI 回答目标用户问题时，我们的品牌有没有被看见、有没有进入候选、有没有被明确推荐；
如果没有，差距在哪里、下一步应该改什么、改完以后是否经过固定复测证明有效。
```

产品不是通用 SEO 工具，也不是泛 BI 趋势看板。当前 P0 目标是建立第一条可信的证据驱动优化闭环：

```text
采集真实 AI 回答
-> 解析回答、引用和检索候选
-> 生成确定性证据包
-> 诊断品牌选择空间和推荐差距
-> 生成待审核策略候选
-> 人工审核并形成 effective_payload
-> 创建动作和实验
-> 人工确认发布
-> 固定复采
-> 对比指标
-> 人工记录效果结论
```

当前真实数据路径以文心网页端浏览器采集为主：

```text
Project -> Prompt -> Batch/Task -> BrowserMonitorRun -> ReferenceSource/RetrievalCandidate -> Evidence/Diagnosis/Optimization
```

## 2. 目标用户与使用场景

目标用户是负责品牌 GEO、内容优化、产品增长或 AI 搜索可见性的中文业务操作者。

典型场景包括：

- 运营人员想知道某个用户问题里，AI 是否提到了自家品牌。
- 品牌负责人想区分“被提及”“进入候选”和“被明确推荐”。
- 内容负责人想知道 AI 引用了哪些页面、哪些内容形态更容易进入回答。
- 产品负责人想判断竞品被推荐的理由是否也适用于自己品牌。
- 优化负责人想把诊断结论变成一个可审计实验，而不是直接拍脑袋改页面。
- 审核人员需要确认 Product Truth、发布状态、复测结果和最终业务结论。

## 3. 产品核心原则

### 3.1 一个 Prompt 就是一个用户问题

`Prompt` 是业务问题的最小单位。一个 Prompt 只表达一个用户问题，不能把多行问题拆成隐式多问题，也不能在展示层用原始数据库 ID 替代业务语义。

当前正式 GEO 分析单元也是单 Prompt，而不是 PromptCluster。PromptCluster 在本阶段只用于问题组织、筛选和后续扩展，不生成集合级 Opportunity、集合级市场份额或跨 Prompt 策略。

采样时，一个 Prompt 可以有多次独立采集记录：

```text
Prompt #9
  Sample 1 -> BrowserMonitorRun
  Sample 2 -> BrowserMonitorRun
  Sample 3 -> BrowserMonitorRun
```

### 3.2 采集事实不可被分析覆盖

原始采集事实存储在 `BrowserMonitorRun`、`ReferenceSource`、`RetrievalCandidate` 和 artifact 文件中。分析层只能读取、解释和追加标注，不能改写原始事实。

正式分析前必须先判断 Prompt Run Eligibility。`collection_status=success` 只表示采集完成，不自动表示可用于正式 GEO 分析。

Run Eligibility 状态包括：

```text
ELIGIBLE
PARTIAL
INELIGIBLE
UNKNOWN
```

正式单 Prompt 分析必须展示：

```text
eligible_runs / total_runs
analysis_usable_runs / total_runs
```

连续会话、问题不匹配、空回答或复用同一 conversation 的记录，不能作为正式独立样本进入决策市场。

### 3.3 引用上下文不等于因果支撑

Citation 与 Recommendation 或 Reason 在同一回答中出现，只能说明存在 Citation Context，不能自动说明引用内容支撑了推荐理由。

产品语义必须区分：

```text
Recommendation Reason
Citation Context
Passage Alignment
Evidence Support
```

其中 Passage Alignment 只能证明文本相似或段落对齐，不能证明 AI 内部采用了该来源作为因果依据。

### 3.4 Product Truth 必须人工确认

竞品因为某个能力被推荐，不代表目标品牌也具备该能力。目标品牌能力必须来自人工确认或明确官方事实源。

Product Truth 状态包括：

```text
SUPPORTED
PARTIALLY_SUPPORTED
NOT_SUPPORTED
UNKNOWN
```

当 Product Truth 仍为 `UNKNOWN` 时，系统不能生成确定性执行策略。

### 3.5 最终策略必须经过人工审核

Decision Market 只能生成待审核 `StrategyCandidate`，不能直接创建 Action 或 Experiment。

正式执行链必须是：

```text
Decision Market
-> StrategyCandidate
-> 人工审核
-> effective_payload = VALIDATED
-> Action
-> Experiment
```

如果 `effective_payload` 中仍存在 `UNRESOLVED` 的执行字段，执行入口必须 fail-closed。

## 4. 产品导航与模块说明

当前前端按三组能力组织：

```text
业务闭环
  - 监测总览
  - 决策诊断
  - 最终策略

证据工作台
  - 引用资料
  - 证据标注
  - 采集记录

系统配置
  - 问题配置
```

## 5. 系统配置：问题配置

问题配置负责建立产品分析对象和采集任务的基础结构。

核心能力：

- 创建和维护项目 `Project`。
- 维护目标品牌名称、别名、官网、行业、地区和语言。
- 维护竞品 `Competitor`，包括名称、别名和官网。
- 维护主题 `Topic` 和问题组 `PromptCluster`。
- 维护 Prompt，包括用户问题、意图类型、重要性和采样次数。
- 创建采集批次 `MonitoringBatch`。
- 配置采集模式。

采集模式包括：

```text
single_independent
```

每个 Prompt 每次采样都单独开启新会话，推荐用于正式采集，避免同一对话上下文污染后续问题。

```text
single_continuous
```

兼容模式，允许同一对话连续采集，仅用于明确需要连续上下文的人工场景。

关键规则：

- 一个 Prompt 是一行、一个问题。
- 采样次数代表独立采集记录数量，不代表市场总体概率。
- 批次采集可以排队，也可以选择立即执行。

## 6. 采集记录：真实回答与原始证据

采集记录是系统最底层的审计轨迹。它展示每次浏览器采集的真实过程和结果。

核心对象：

- `BrowserMonitorTask`：一次采集任务。
- `BrowserMonitorRun`：一次 Prompt x Sample 的真实采集记录。
- `ReferenceSource`：AI 最终回答展示的引用资料。
- `RetrievalCandidate`：回答前或回答过程中的检索候选。
- `RunArtifact`：保存 page.html、network、截图、原始响应等证据文件。

核心能力：

- 查看每条采集的状态：成功、部分成功、失败、排队、执行中。
- 查看原始问题、页面问题、检索问题和回答正文。
- 查看品牌是否出现、出现次数、推荐强度。
- 查看引用资料数量、解析数量、已解析 URL 数量。
- 查看检索候选的标题、URL、域名和排名。
- 查看采集耗时、错误阶段、错误类型和错误信息。
- 对失败或异常采集执行 retry。
- 导入文心插件采集结果。

关键边界：

- `partial_success` 不是完整成功，不能为了展示好看而重定义为成功。
- `ReferenceSource` 和 `RetrievalCandidate` 是两个独立可观测集合，不能默认当作严格漏斗上下游。
- 文心网页采集受登录、验证码、账号状态和页面结构变化影响。

## 7. 监测总览：项目级观察面

监测总览负责展示项目当前采集样本的整体状态。

核心能力：

- 展示项目基本信息和当前样本环境。
- 汇总 Prompt 数量、已采集问题、成功采集、总采集次数。
- 展示品牌是否被提及、是否被明确推荐、缺失数量。
- 展示数据质量，包括成功采集、部分成功、失败、引用完整性。
- 给出当前样本层面的品牌可见性概览。

它回答：

```text
当前已有采集样本质量如何？
品牌在这些样本里有没有出现？
有没有明确推荐？
是否具备继续诊断的基础？
```

它不负责：

- 输出最终策略。
- 宣称优化有效。
- 替代 Evidence Package 或 Decision Market 的单 Prompt 诊断。

## 8. 引用资料：来源结构与引用证据分析

引用资料模块面向最终引用来源和检索候选的来源分析。

核心能力：

- 基于 Evidence Package 展示引用资料排名。
- 对引用来源按 normalized URL 去重，同时保留出现次数和覆盖 Run。
- 分析来源归属：官方、竞品、品牌相关、第三方。
- 分析内容形态：教程、FAQ、对比、文档、新闻、文章、首页等。
- 分析平台来源：百度百家号、知乎、微信公众号、抖音、小红书、B 站、普通网页等。
- 展示 prompt match、freshness、authority、account identity、risk flags。
- 输出 `source_score`，用于解释该来源在当前回答样本中的引用贡献。

source_score 是回答引用贡献分，不是通用网页质量分。

核心边界：

- 引用资料模块解释可见来源结构，不声称知道模型隐藏排序机制。
- 检索候选可能不完整，不能被当作最终引用全集分母。
- 对第三方平台或缺失 URL 的页面，负样本判断必须谨慎。

## 9. 证据标注：主张、正文和段落对齐

证据标注模块用于把 AI 回答和引用页面变成可审核证据。

核心对象：

- `SourceDocument`：引用页面正文、抓取状态和页面内容。
- `AnswerClaim`：AI 回答中的主张。
- `AtomicClaim`：更细粒度的原子主张。
- `PassageAlignment`：回答主张与来源段落的对齐结果。

核心能力：

- 为一个 Prompt 的多次采集准备 Golden Case 工作台。
- 从答案中抽取回答主张。
- 抓取引用页面正文，保存页面 title、正文、hash、抓取状态。
- 支持人工补录引用页面正文。
- 支持空页面补录，用于页面已删除或没有可用正文的情况。
- 抽取原子主张，并支持确认或拒绝。
- 展示回答主张与来源段落的对齐。
- 输出 Need Map、Brand Gap、URL Audit 等辅助证据。

核心边界：

- 证据标注产出的是被审核证据，不直接产出最终策略。
- 空页面是合法证据状态，表示该来源已无法补全正文，而不是系统异常。
- 文本对齐不等于因果证明。

## 10. 决策诊断：从回答事实到结构化差距

决策诊断是单 Prompt 的语义分析和决策解释工作台。

它的总链路是：

```text
COLLECT -> UNDERSTAND -> EXPLAIN -> DECIDE -> VERIFY
```

### 10.1 Snapshot

每次诊断生成一个 `RecommendationIntelligenceSnapshot`。

Snapshot 保存：

- source run ids
- schema/extractor version
- decision mode
- metric eligibility
- landscape
- positioning
- evidence links
- gap diagnosis
- intervention candidates

它是一次诊断的父对象，历史版本保留，方便审计和回溯。

### 10.2 答案语义事实

`AnswerSemanticFact` 在 Run 级别判断回答结构。

核心事实包括：

- `has_choice_slot`：回答是否存在品牌、工具、平台、方案之间的选择空间。
- `has_brand_mention`：回答是否出现真实品牌、产品或服务品牌实体。
- `has_explicit_recommendation`：回答作者是否对某个实体作出正向选择行为。
- `has_comparison`：回答是否出现对比或优劣判断。

这些事实互相独立，不能彼此推导。

### 10.2.1 单 Prompt Run Eligibility

决策诊断首先对当前 Prompt 的采集记录进行资格判断。

合格样本必须满足：

- 属于当前 Prompt。
- 有可分析回答正文。
- 来自独立新会话采样。
- 未被连续上下文污染。

`partial_success` 可以作为部分分析样本进入非引用类诊断，但必须保留 `PARTIAL` 标记。失败、空回答、连续会话和 Prompt 不匹配记录必须 fail-closed，不进入正式决策市场。

### 10.2.2 单 Prompt Decision Space

系统按单 Prompt 合格样本判断当前问题属于哪类决策空间：

```text
NO_BRAND_DECISION_SPACE
SOLUTION_CHOICE_SPACE
BRAND_CANDIDATE_SPACE
BRAND_RECOMMENDATION_PRESENT
BRAND_COMPARISON_PRESENT
```

如果没有稳定选择空间，系统停止输出品牌关联、候选进入或明确推荐缺口，只提示补样本或重写 Prompt。

### 10.3 品牌实体、候选和推荐

系统抽取并展示：

- `RecommendationEntity`：品牌、竞品、平台、规则方、方案对象等实体。
- `RecommendationClaim`：提及、候选、明确推荐等事实。
- `RecommendationReasonClaim`：推荐或候选理由。

推荐判断不只看“推荐”关键词，而要判断回答作者是否真的在正向选择某个实体。

例如：

```text
可以优先考虑天天外链
```

属于明确推荐。

```text
网上很多人推荐天天外链，但风险较高
```

不属于作者本人的正向推荐。

单 Prompt Recommendation Market 必须按实体展示：

- mention share
- candidate share
- positive recommendation share
- top recommendation share
- negative recommendation share

所有指标必须同时展示 numerator、denominator、eligible_denominator 和 sample_size，避免裸百分比误导。

### 10.4 选择标准和能力识别

系统抽取：

- `DecisionSelectionCriterion`：AI 回答中显式或隐式使用的选择标准。
- `BrandCapabilityClaim`：AI 当前如何描述某品牌能力。

这些属于 AI Observed Truth，只说明 AI 当前回答怎么说，不说明产品真实具备。

系统会把 `RecommendationReasonClaim`、`DecisionSelectionCriterion` 和 `BrandCapabilityClaim` 聚合为 Prompt Recommendation Drivers。Driver 不是词频榜，而是回答为何把某些实体作为候选或推荐对象的结构化原因。

Driver 必须关联 Product Truth：

```text
真实支持但 AI 未识别 -> TRUE_CAPABILITY_NOT_RECOGNIZED_BY_AI
未确认 -> NEEDS_PRODUCT_TRUTH_REVIEW
不支持 -> DO_NOT_CLAIM_UNSUPPORTED_CAPABILITY
```

### 10.5 Citation Context

系统把推荐、理由和引用上下文关联起来。

`DecisionEvidenceAdoption` 表达的是 Citation Context 和 evidence_status：

```text
LINKED
PARTIALLY_LINKED
UNLINKED
UNCERTAIN
```

它不再把“共现”自动视为 `supports_claim=true`。

### 10.6 Product Truth 人工核对

`TargetBrandCapabilityTruth` 用来人工确认目标品牌能力事实。

Product Truth 是最终策略前置闸门：

- 竞品能力不能自动套给目标品牌。
- Product Truth UNKNOWN 时，只能提示人工补录或确认。
- Product Truth 未确认时，不能接受或执行确定性策略候选。

### 10.7 Brand Opportunity Gate

在输出品牌 Gap 前，系统必须先看：

```text
choice_slot_runs / eligible_runs
brand_mention_runs / eligible_runs
recommendation_runs / eligible_runs
```

没有稳定选择空间时，系统停止输出品牌关联、候选进入或明确推荐缺口。

### 10.8 Gap Diagnosis

Gap Diagnosis 诊断目标品牌当前卡在哪一层。

主要类型包括：

```text
ASSOCIATION_GAP
CAPABILITY_RECOGNITION_GAP
CANDIDATE_INCLUSION_GAP
RECOMMENDATION_GAP
TOP_RECOMMENDATION_GAP
```

一次诊断只允许一个 Primary Gap，最多两个 Contributing Gaps。

Primary Gap 必须遵循前置链路：

```text
ASSOCIATION_GAP
-> CAPABILITY_RECOGNITION_GAP
-> CANDIDATE_INCLUSION_GAP
-> RECOMMENDATION_GAP
-> TOP_RECOMMENDATION_GAP
```

选择理由缺口、引用证据缺口和来源结构问题只能作为辅助上下文，不能在前置链路未完成时抢占 Primary Gap。

Gap 必须能追溯到：

```text
Gap -> Run -> Recommendation -> Span -> Reason -> Reason Span -> Citation Context
```

### 10.9 送入最终策略

决策诊断可以点击“送入最终策略”，但它现在只创建待审核 `StrategyCandidate`。

它不会直接创建：

- `OptimizationIssue`
- `OptimizationAction`
- `OptimizationExperiment`

这样可以避免 Decision Market 绕过人工审核和 effective_payload。

### 10.10 单 Prompt 干预候选

决策诊断会基于单 Prompt 诊断生成非执行的 Intervention Candidate。

当前干预类型包括：

```text
CONTENT_CREATE
CONTENT_UPDATE
PLATFORM_PUBLISH
TECHNICAL_INDEXABILITY
STRUCTURED_DATA
ENTITY_CONSISTENCY
INTERNAL_INFORMATION_ARCHITECTURE
PLATFORM_AUTHORITY_BUILD
RECRAWL_OR_REFRESH
NO_ACTION
```

Intervention Candidate 只能表达建议方向和证据前提。人工审核前，`target_platform`、`target_asset`、`target_url` 不能被系统自动定死。

## 11. 最终策略：唯一执行出口

最终策略模块承接 Evidence Package、StrategyCandidate、Action 和 Experiment。

它回答：

```text
基于已经审核的证据和诊断，最终要做什么；
是否允许执行；
如何锁定基线、发布、复测、分析和结论化。
```

### 11.1 Evidence Package

`OptimizationEvidencePackage` 是确定性证据事实报告。

它包括：

- source Run IDs
- target page URLs
- environment snapshot
- metric rows
- metric snapshot
- platform gap matrix
- content type distribution
- candidate-not-cited summary
- time distribution
- representative sources
- raw Run drilldown
- unified drilldowns
- retrieval coverage summary

重复使用相同输入生成证据包时，系统返回已有 package，而不是创建重复版本。

旧包 append-only 保留。指标或解析规则升级时，应创建新版本。

### 11.2 Strategy Candidate

`OptimizationStrategyCandidate` 是策略候选。

它保存：

- provider/model/prompt version
- structured payload
- human edited payload
- effective payload
- evidence validation status
- hypothesis validation status
- review status
- formal identity fields
- experiment plan

候选状态包括：

```text
PENDING_REVIEW
ACCEPTED
ACCEPTED_WITH_EDITS
REJECTED
DEFERRED
VALIDATION_FAILED
```

只有人工接受后的候选才能进入实验计划。

### 11.3 effective_payload

`effective_payload` 是所有策略执行路径的 single executable truth。

正式执行时，系统只信任：

```text
effective_validation_status = VALIDATED
```

以下状态不能执行：

```text
BACKFILLED_UNVERIFIED
LEGACY_INVALID
PENDING
VALIDATION_FAILED
BLOCKED_PRODUCT_TRUTH
PENDING_HUMAN_CHANNEL_REVIEW
```

如果 effective payload 中仍有这些字段为 `UNRESOLVED`，也不能执行：

```text
intervention_type
target_platform
target_object
target_asset
target_content_type
```

`NO_ACTION` 是特殊情况，表示不创建 Action/Experiment，只记录继续观察。

### 11.4 Issue / Action / Experiment

`OptimizationIssue` 记录问题。

状态路径：

```text
candidate -> confirmed -> in_action -> validating -> resolved
```

`OptimizationAction` 记录要改什么。

发布边界：

```text
PLANNED -> READY_FOR_MANUAL_RELEASE -> RELEASE_CONFIRMED
```

只有 `RELEASE_CONFIRMED` 可以写入 `released_at` 并让实验进入 cooling。

`OptimizationExperiment` 记录实验设计和结果。

实验状态路径：

```text
draft -> baseline_locked -> cooling -> validating -> analyzing -> completed
```

真实业务效果必须由人工结论关闭，系统计算 delta 但不自动宣称有效。

### 11.5 Release Audit

真实发布必须经过 release confirmation。

发布确认需要：

- 已接受的人类 Hypothesis。
- 成功 PRE_RELEASE page snapshot。
- 成功 POST_RELEASE page snapshot。
- deployed feature changes。
- release note。
- confirmer 和确认时间。
- canonical / robots / index 检查。

发布确认后，关键字段冻结，不能静默覆盖。

### 11.6 Fixed Retest

实验可以按 target Prompt scope 创建固定复测队列。

复测默认只排队，不自动立即执行，因为文心网页采集可能遇到登录或验证码。

复测完成后，人工挂载 validation runs，系统分析：

- baseline metrics
- validation metrics
- delta
- confidence note
- comparability status
- known environment audit

### 11.7 Human Conclusion

实验最终结论必须人工确认。

结论枚举：

```text
EFFECTIVE
PARTIALLY_EFFECTIVE
MIXED_RESULT
NO_MEASURABLE_EFFECT
NEGATIVE_EFFECT
INSUFFICIENT_EVIDENCE
```

## 12. 核心数据对象关系

```text
Organization
  -> Project
      -> Competitor
      -> Topic
      -> PromptCluster
      -> Prompt
          -> MonitoringBatch
          -> BrowserMonitorTask
          -> BrowserMonitorRun
              -> ReferenceSource
              -> RetrievalCandidate
              -> RunArtifact
          -> OptimizationEvidencePackage
          -> RecommendationIntelligenceSnapshot
              -> AnswerSemanticFact
              -> RecommendationEntity
              -> RecommendationClaim
              -> RecommendationReasonClaim
              -> DecisionSelectionCriterion
              -> BrandCapabilityClaim
              -> DecisionEvidenceAdoption
              -> DecisionGapDiagnosis
          -> TargetBrandCapabilityTruth
          -> OptimizationStrategyCandidate
          -> OptimizationIssue
              -> OptimizationAction
                  -> OptimizationExperiment
                      -> OptimizationHypothesis
                      -> ReleaseAuditRecord
```

Golden Case 证据对象：

```text
SourceDocument
AnswerClaim
AtomicClaim
PassageAlignment
```

## 13. 关键指标体系

### 13.1 回答级指标

- 品牌提及率：目标品牌在回答中出现的比例。
- 明确推荐率：目标品牌被回答作者正向推荐的比例。
- 选择空间率：回答中存在品牌、工具、平台或方案选择槽位的比例。
- 对比出现率：回答中出现对比或优劣判断的比例。

### 13.2 引用和候选指标

- 引用完整性：页面声明引用数量与解析引用数量是否一致。
- official_reference_rate：官方域名是否进入最终引用。
- target_page_retrieval_rate：目标 URL 是否进入检索候选。
- target_page_conversion_rate：目标 URL 进入检索候选后是否成为引用。
- retrieval_coverage_status：检索候选分母是否完整。

### 13.3 策略和实验指标

- primary_metric：实验主指标。
- secondary_metrics：辅助观察指标。
- baseline value：发布前锁定样本指标。
- validation value：发布后固定复测指标。
- delta_pp：百分点变化。
- comparability_status：前后结果是否具备可比性。

## 14. 当前产品状态

当前主线状态：

```text
SINGLE_PROMPT_LOOP_READY
```

系统已经具备完整的软件闭环能力：

- 文心真实采集。
- Prompt x Sample 独立采集。
- 原始回答、引用、检索候选保存。
- Evidence Package 确定性证据包。
- Recommendation / Decision Market 诊断。
- Answer Semantics、Reason、Citation Context、Product Truth 人工审核。
- Gap Diagnosis。
- StrategyCandidate。
- effective_payload 执行闸门。
- Issue / Action / Experiment。
- Release Audit。
- Fixed Retest。
- Experiment Analysis。
- Human Conclusion。

但这不等于真实实验已经完成。

PromptCluster / 集合级 Opportunity 仍未进入正式实现范围。下一阶段优先级是先跑通并验证单 Prompt 闭环，再扩展到多 Prompt 聚合。

真实业务实验仍必须经过：

```text
外部页面实际发布
-> 人工确认发布
-> 冷却期
-> 固定复采
-> 指标对比
-> 人工结论
```

## 15. 非目标与边界

当前阶段不做：

- 自动修改官网页面。
- 自动发布外部平台内容。
- 自动把竞品能力写成目标品牌策略。
- 未发布确认就进入 cooling。
- 未固定复采就宣称优化有效。
- 把 Citation Context 说成因果支撑。
- 把检索候选当作最终引用全集。
- 多平台大规模矩阵采集。
- 通用 SEO 大盘或泛 BI 趋势系统。

## 16. 典型完整操作流程

### 16.1 从问题到诊断

```text
1. 在问题配置中创建 Project、竞品、Prompt。
2. 创建采集批次，选择 single_independent。
3. 执行采集，得到 BrowserMonitorRun。
4. 在采集记录中检查回答、引用和候选质量。
5. 生成 Evidence Package。
6. 进入决策诊断，选择 Prompt 并生成诊断快照。
7. 审核答案语义事实、实体、推荐、理由、引用上下文和 Gap。
8. 补录或确认 Product Truth。
```

### 16.2 从诊断到策略

```text
1. 在决策诊断中点击送入最终策略。
2. 系统创建 StrategyCandidate。
3. 人工审核策略候选。
4. 必要时编辑 payload，明确 intervention_type、target_platform、target_asset 和 target_url。
5. Validator 通过后写入 effective_payload = VALIDATED。
6. 通过最终策略入口生成 Action / Experiment。
```

### 16.3 从策略到验证

```text
1. 锁定 baseline runs 和 baseline metrics。
2. 人工完成真实页面或内容发布。
3. 捕获 PRE / POST release snapshots。
4. 通过 Release Audit 确认发布。
5. 创建固定复测队列。
6. 执行复测采集。
7. 挂载 validation runs。
8. 分析实验指标和已知环境变化。
9. 人工确认最终结论。
```

## 17. 下一阶段建议

优先建议：

1. 将 `决策诊断` 和 `最终策略` 的跳转关系进一步显性化，显示来源 Snapshot、StrategyCandidate、Action、Experiment 编号。
2. 将 `引用资料` 的 Evidence Package 选择能力产品化，避免固定包视角。
3. 将 `证据标注` 中需要人工补录的状态做成更短、更明确的提示。
4. 补齐各页面状态枚举的中文 label，避免操作者理解英文内部状态。
5. 为完整操作链增加端到端冒烟测试：

```text
选择 Prompt
-> 生成 Evidence Package
-> 生成决策诊断
-> Product Truth 确认
-> 送入最终策略
-> 审核 StrategyCandidate
-> 生成实验计划
```

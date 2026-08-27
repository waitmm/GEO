# 09 Product Iteration Log

Status: ACTIVE

## 2026-08-27 Citation Decision V1.1 Phase 5 Decision Stability

### Product Decision

单 Prompt GEO V1 增加 Decision Stability 作为旁路观察指标。

它只描述：

```text
同一 Prompt 多次独立采样时，AI 的品牌/方案推荐结果是否稳定。
```

它不参与：

```text
证据资格
对标来源
缺口诊断
策略确认
执行动作
实验草案
Baseline
```

### Product Semantics

稳定性分数采用最简单透明的统计口径：

```text
主导推荐结果覆盖的 Run 数 / 有效 Run 数
```

并展示真实分子/分母：

```text
有效样本
品牌决策发生
推荐对象覆盖
推荐理由覆盖
observed_run_ids
```

它不是 LLM confidence，不是 Strategy confidence，也不是新的评分体系。

### UI

单 Prompt 主链页面和引用资料决策详情页展示：

```text
决策稳定性观察
只读观察
```

页面文案明确说明：

```text
该指标只描述多次采样里的推荐波动，不影响证据、对标、缺口、策略、动作或实验。
```

本次没有新增独立模块，也没有改变 1-8 主链。

### Prompt #40 Result

```text
valid_run_ids = [238, 239, 240, 253, 254, 255]
valid_run_count = 6
brand_decision_run_count = 6
dominant_recommendation_outcome = CO_DOMINANT_RECOMMENDATION_ENTITIES
co_dominant_entities = Bitly / 小码短链接 / 缩我短链接 / 轻松短链接
unique_dominant_entity = none
decision_stability_score = 100 / 100
stability_level = HIGH_STABILITY
```

产品语义修正：

```text
多个推荐对象同为最高覆盖
-> 共同主导
-> 不输出唯一 Top 推荐对象
```

共同主导不降低稳定性分数；Decision Stability 描述推荐结构是否稳定，
Recommendation Dominance 描述是否存在唯一主导推荐对象，两者不混用。

主链零影响：

```text
PRIMARY_BENCHMARK: 1 -> 1
CONTENT_GAP: 1 -> 1
StrategyCandidate #41: unchanged
Action #30: unchanged
Experiment #30: unchanged
```

### Current Boundary

当前状态：

```text
PHASE_5_DECISION_STABILITY_CHECKPOINT_READY
STEP_9_NOT_STARTED
```

下一步不是继续加新功能，而是进行单 Prompt V1 1-8 最终验收。

## 2026-08-27 Citation Decision V1.1 Phase 4 Execution Plan

### Product Decision

单 Prompt GEO 主链 V1 进入 Step 8 最小闭环：

```text
策略候选 + 策略确认
-> 人工确认执行渠道与资产
-> 创建实验草案
```

本次没有新增独立模块，也没有改变 8 步主链顺序。第 8 步仍属于：

```text
实验方案落地
```

### Preflight Result

现有模型可以承载 V1 最小需求：

```text
PageSnapshot
-> 已有品牌资产引用

OptimizationStrategyCandidate.effective_payload_json
-> Strategy 确认后的执行真值

OptimizationExperiment.intervention_variables_json
-> strategy_snapshot / selected_asset_ref / gap refs / action_snapshot

OptimizationExperiment.baseline_run_ids_json
OptimizationExperiment.baseline_metrics_json
-> 固定 Baseline
```

因此本阶段不新增 `BrandAssetInventory` 大体系，不新增平行 Strategy 表。

### Step 8 Semantics

正式拆分：

```text
channel = 在哪里
asset_operation = 更新已有资产或创建新资产
selected_asset = 已有 PageSnapshot 资产引用或 NEW_ASSET proposal
```

不是：

```text
官网已有页面 / 官网新页面 = 两个 channel
```

### Gate

后端锁死：

```text
ACCEPTED / ACCEPTED_WITH_EDITS
= Strategy 已确认

PENDING_HUMAN_CHANNEL_REVIEW
= Strategy 已确认，但 Step 8 执行方案待人工确认
```

所以：

```text
ACCEPTED_WITH_EDITS + PENDING_HUMAN_CHANNEL_REVIEW
-> 允许进入 Step 8

PENDING_REVIEW
-> 不允许进入 Step 8
```

Step 8 确认后才允许创建：

```text
OptimizationAction
OptimizationExperiment draft
```

仍不允许自动发布、自动复采或宣称实验有效。

### Prompt #40 Result

真实回归：

```text
strategy_candidate_id = 41
selected_asset_ref = PAGE_SNAPSHOT:3
channel = OFFICIAL_SITE
asset_operation = UPDATE_EXISTING
baseline_run_ids = [238, 239, 240, 253, 254, 255]
action_id = 30
experiment_id = 30
experiment_status = draft
release_blocked_reason = WAITING_FOR_RELEASE_AUDIT
```

Baseline 属于 Experiment，不绑定到 Action：

```text
brand_mention = 0/6
brand_candidate = 0/6
brand_recommendation = 0/6
target_reason_adoption = 0/6
brand_retrieval_presence = 6/6
brand_citation_presence = 0/6
selected_asset_retrieval_presence = 0/6
selected_asset_citation_presence = 0/6
```

### Current Boundary

当前状态：

```text
PHASE_4_EXECUTION_PLAN_CHECKPOINT_READY
STEP_9_NOT_STARTED
```

下一步若继续，应先把前端第 8 步接入新的 `execution-plan` API；不要再使用旧
`experiment-plan` 自动转换入口表达 Step 8。

## 2026-08-27 Single Prompt GEO V1 Phase 0/1 Handoff

### Product Decision

单 Prompt GEO 主链 V1 的 Phase 0/1 先冻结为审查文档，不继续直接开发业务代码。

最新审查文档：

```text
docs/SINGLE_PROMPT_GEO_V1_PHASE0_1_HANDOFF.md
```

### Main Chain

当前产品主链固定为：

```text
采集样本
-> 答案决策识别
-> 目标品牌事实
-> 引用证据
-> 对标来源
-> 缺口诊断
-> 策略候选 + 策略确认
-> 实验方案落地
```

第 7 步不是独立的“推荐动作确认”模块。第 7 步必须复用已有
`StrategyCandidate/effective_payload`，人工确认后才允许进入 Action/Experiment。

### Hard Boundaries

Phase 2 前必须守住：

```text
1. 优先复用 StrategyCandidate / effective_payload，不新增平行 Strategy。
2. Experiment 必须绑定确认时 effective_payload 快照。
3. DISCOVERABILITY_GAP 只能基于当前 Prompt/能力相关品牌资产。
4. EvidenceAlignment 必须验证完整 Run lineage，不只看 run_id 非空。
```

### Current Conflicts

本次审计确认当前实现仍有几个需要 Phase 2 先修的产品一致性风险：

```text
Citation Decision 确认路径仍可能直接创建 Experiment
旧 SUPPORTS 消费者未统一走 lineage / feature flag 过滤
品牌资产判断可能误用任意最新快照
前端第 7 步语义仍容易被理解为“确认推荐动作”
```

当前状态：

```text
PHASE_0_1_HANDOFF_READY_FOR_REVIEW
PHASE_2_BUSINESS_CODE_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Workflow Read Policy

### Product Decision

单 Prompt 主链路进入 Citation Decision V1.1 验收态：前端当前工作流显式读取
`use_answer_binding_v1_1=true` 的结果。

### Boundary

这不是全量 Phase 1 默认切换：

```text
后端默认 feature flag 不变
8 步主链路顺序不变
不新增 Citation Decision 独立模块
不绕过 Product Truth
不因 Benchmark 存在直接生成动作
单 Prompt 首页不直接提交动作确认，只跳转到执行策略详情
```

### Expected #40 State

Prompt `#40` 在 V1.1 读取下应显示：

```text
引用证据：已完成
对标来源：1 个核心对标
缺口诊断：卡在目标品牌事实
推荐动作：0 个
```

待人工确认目标品牌自己的具体能力：

```text
点击统计
自定义分享标题
营销场景使用
```

确认后再重跑链路；如果事实为 `NOT_SUPPORTED`，必须进入产品缺口，
不能生成虚假内容优化动作。

## 2026-08-26 Phase 1 Formal Result Audit Gate

> 2026-08-27 更新：本节记录的是首次 Phase 1 审计发现，已被后续
> `Citation Decision V1.1 Phase 1.1 Product Boundary` 修正。最新状态是：
> V1.1 ON 时 #40 有 1 个核心对标来源，但因缺少具体 Product Truth，推荐动作为 0。

### Product Finding

Prompt `#40` proves that Citation Decision V1.1 can formally consume
`AnswerUnit + AnswerDecisionBinding` without lowering the V1 evidence gate.

Current result:

```text
READY_FOR_HUMAN_CONFIRM
1 个核心对标来源
1 个推荐动作
1 个渠道机会
```

The promotion is evidence-based:

```text
formal EvidenceAlignment.relation = SUPPORTS
reason_source = ANSWER_DECISION_BINDING
formal_input_version = citation_decision_v1_1_formal_input.v1
```

It is not based on:

```text
引用显著性
标题同名
Shadow SUPPORTS
LEGACY_RELATED
```

### Product Gate

Do not approve full production switch yet.

The audit found three product-level risks:

```text
1. 6 条正式 SUPPORTS 当前全部来自 Run #238，
   不能表述为 6 个采集样本均完成正式证据支撑。

2. 当前 feature flag 是“生成输入开关”，不是“结果读取回滚开关”。
   已写入的 V1.1 EvidenceAlignment 仍会被 Citation Decision 读取。

3. 推荐动作聚焦到了更细的能力点，
   但 Product Truth 仍是较粗的“短链生成”。
```

### Next Product Requirement

Before expanding to 3-5 additional Prompts, finish:

```text
run-level coverage integrity
formal V1.1 read-path isolation or rollback
fine-grained Product Truth matching
single-case runner Layer3 doc_id_filter consistency
```

Current state:

```text
PHASE_1_FORMAL_INPUT_PROVEN_ON_PROMPT_40
READY_FOR_FULL_PRODUCTION_SWITCH = false
```

## 2026-08-26 Recommendation Explanation Scope Calibration

### Product Decision

Recommendation Binding is no longer limited to explicit `因为/所以` style
reasons. In a real recommendation answer, the explanation scope around the
recommended brand matters.

```text
推荐语境下，被推荐品牌说明作用域内的能力、优势、价格、效果、适用场景等，
默认视为推荐支撑主张；不要求答案显式出现“因为/所以”。

但默认 Binding 不等于无条件 Binding，
必须排除操作步骤、普通背景事实、其他品牌内容、限制性内容，
以及已经脱离推荐说明作用域的主张。
```

### Product Boundary

`DIRECT_REASON` remains stricter than `SUPPORTING_REASON`:

```text
SUPPORTING_REASON:
推荐品牌说明作用域内的能力、优势、价格、效果、适用场景等支撑说明。

DIRECT_REASON:
明确选择条件、明确因果、明确比较依据或需求匹配。
```

Evidence Chain 的长期触发点应从 `Recommendation Reason` 扩展到所有有分析价值的 `AnswerUnit`：

```text
AnswerDecisionBinding 判断“是不是推荐证据”
EvidenceAlignment 判断“引用正文有没有真正支撑它”
```

没有 Recommendation Binding 的 AnswerUnit 仍可在 Shadow 中形成：

```text
BRAND_CAPABILITY_EVIDENCE
PROCEDURAL_EVIDENCE
FACTUAL_EVIDENCE
```

但它们不能被误计为 Recommendation Evidence，不能进入正式 Benchmark。

### Prompt 40 Result

Prompt `#40` 已按新语义重跑 `ShadowRun #7`：

```text
Binding = 30
DIRECT_REASON = 0
SUPPORTING_REASON = 30
SUPPORTS = 18
recommendation_evidence_eligible = 18
formal_output_impact = NONE
```

这说明系统保留了 5 个推荐说明作用域内的能力 Binding，同时不再把缺少明确选择依据的能力描述升级为 `DIRECT_REASON`。

### Phase Boundary

This remains Phase 0 Shadow only:

```text
正式 Benchmark 不变
正式 Gap 不变
正式 Priority 不变
正式 Action 不变
正式 Strategy / Experiment 不变
READY_FOR_PRODUCTION_SWITCH = false
```

Phase 0 不再要求人工逐条审计 30 条同结构 Binding。只需要对代表
Run 做轻量 sanity check，并确认自动回归 Case 持续通过：

```text
Procedure Case
Brand-directed Case
Other-brand Scope Case
Implicit Reason Case
Limitation Case
```

Phase 1 小范围切换仍需要单独批准。

## 2026-08-26 Prompt 40 Shadow Audit Review Handoff

### Product Finding

Prompt `#40` has now completed a real V1.1 Phase 0 Shadow audit for the
recommended entity `小码短链接` across six Runs.

The Shadow chain proved that answer-side capability text can bridge the prior
V1 false negative:

```text
AnswerClaim
-> AnswerUnit
-> AnswerDecisionBinding
-> Retrieved Passage
-> Shadow SourceClaim
-> Shadow EvidenceAlignment
```

### Historical Audit Result

`ShadowRun #6` is the first positive Shadow audit. It is now superseded by
`ShadowRun #7` for Phase 1 gate review.

```text
SUPPORTS = 18
NO_SUPPORT = 234
CONTRADICTS = 0
recommendation_evidence_eligible_count = 18
```

The grounded SUPPORTS evidence is concentrated on the valid Xiaoma Zhihu source
`SourceDocument #345`, especially:

```text
答案能力：小码短链接自带点击统计
来源主张：小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据

答案能力：小码短链接自带自定义分享标题
来源主张：小码短链接提供自定义分享功能
来源主张：小码短链接的自定义分享功能支持设置标题和描述
```

### Product Boundary

This remains Phase 0 only:

```text
正式 Benchmark 不变
正式 Gap 不变
正式 Priority 不变
正式 Action 不变
正式 Strategy / Experiment 不变
```

Do not switch Phase 1 based on `ShadowRun #6`; use the `ShadowRun #7`
sanity-check gate above.

## 2026-08-26 Prompt 40 Binding Precision Gate

### Product Finding

`ShadowRun #6` proved the positive evidence path works, but it also showed why
the Binding semantics needed a scope calibration before Phase 1:

```text
30 Bindings / 6 Runs = 每 Run 5 个 Binding
```

The machine currently binds all five Xiaoma answer capability units:

```text
快速缩短
点击统计
二维码生成
自定义分享标题
营销场景
```

Only two units receive source SUPPORTS:

```text
点击统计
自定义分享标题
```

### Superseded Gate

This manual 30-row review gate has been superseded by `ShadowRun #7`.
The current Phase 1 gate no longer requires row-by-row review of all 30
same-structure Bindings. It requires:

```text
Representative Run sanity check
Procedure Case
Brand-directed Case
Other-brand Scope Case
Implicit Reason Case
Limitation Case
Formal V1 zero-pollution
```

The review artifact is:

```text
docs/PROMPT_40_SHADOW_RUN_7_BINDING_REVIEW.md
```

### Reverse Case Status

The historical deterministic reverse cases passed:

```text
Procedure Case: passed
Neutral Feature Case: passed
Implicit Reason Case: passed
```

Procedure evidence is allowed as `PROCEDURAL_EVIDENCE`, but it is not counted
as recommendation evidence and must not enter Benchmark eligibility.

## 2026-08-26 Citation Decision V1.1 Phase 0 Shadow Implementation

### Product Decision

Phase 0 is implemented as an audit-only Shadow chain, not as a formal workflow
state change.

The Shadow chain can test whether answer-side capability text can bridge an
empty `RecommendationEvent.reasons_json` into source passage retrieval and
semantic evidence alignment:

```text
AnswerClaim
-> AnswerUnit
-> AnswerDecisionBinding
-> Shadow Passage Retrieval
-> Shadow SourceClaim
-> Shadow EvidenceAlignment
-> Shadow Audit
```

### Product Boundary

Phase 0 must not change any user-facing formal decision result:

```text
formal Benchmark = unchanged
formal Gap = unchanged
formal Priority = unchanged
formal Action = unchanged
formal Strategy / Experiment = unchanged
```

Shadow evidence can be used for review and later Phase 1 evaluation only. It
cannot be used to upgrade a source into Benchmark support until Phase 1 is
explicitly approved.

## 2026-08-26 Recommendation Reason Alignment Bridge

### Product Finding

Prompt `#40` shows a valid V1 false-negative case:

```text
答案明确推荐竞品
引用来源中存在同实体文章
引用正文已经可用
但系统仍无法产生 Benchmark
```

This must not be solved by relaxing Benchmark gates. The correct interpretation
is:

```text
同实体引用 = 候选线索
正文可用 = 可进入语义分析
SUPPORTS EvidenceAlignment = 才能进入 Benchmark
```

### Product Decision

When a recommendation event has no extracted reasons, the product should allow
the system to derive candidate recommendation reasons from same-run answer
claims or the event answer span, then continue through the existing V1 evidence
path:

```text
AnswerClaim / answer_span
-> answer-derived Recommendation Reason
-> Reason-driven Passage Retrieval
-> Blind SourceClaimJudge
-> EvidenceAlignmentJudge
-> Benchmark
```

The derived reason is still answer-side evidence. It does not prove the source
supports the answer until a new V1 EvidenceAlignment says so.

### Phase 0 Shadow Boundary

Phase 0 must be an end-to-end Shadow Evidence Chain, not only an answer-binding
experiment:

```text
AnswerClaim
-> AnswerUnit
-> AnswerDecisionBinding
-> Shadow Passage Retrieval
-> Shadow SourceClaim
-> Shadow EvidenceAlignment
-> Shadow Evidence Classification
-> Shadow Audit
```

The current production chain remains unchanged:

```text
RecommendationEvent.reasons_json
-> current V1 Evidence Chain
-> current Citation Decision
```

Shadow results are only allowed to prove whether the new bridge works. They
must not change formal Benchmark, Gap, Priority, Action, Strategy, or Experiment
outputs during Phase 0.

### Product Boundary

Do not treat any of the following as Benchmark support:

```text
Citation Prominence HIGH
同名标题 / 同实体引用
历史 RELATED
Golden Case L5_UNRESOLVED
```

Product Truth continues to confirm only the target brand's real capabilities,
not whether a competitor article or competitor product has that capability.

## 2026-08-25 Single Prompt Evidence State Sync

### Product Decision

The single Prompt main workflow must recognize the latest Evidence Package and
Citation Decision result for the current Prompt on both `监测总览` and
execution-detail surfaces.

If the current Prompt already has a valid Evidence Package, step 4 `引用证据`
must not continue to show:

```text
待生成证据包
```

It should load or rerun Citation Decision V1 for the current context and then
show the real downstream state, including the valid zero-result case:

```text
0 个可信对标
0 个推荐动作
```

### Product Boundary

This is a state-integrity correction only. It does not change the main chain
order, does not create a new module, and does not make Citation Prominence or
legacy `RELATED` drive strategy generation.

## 2026-08-25 Browser-first Citation Body Refetch

### Product Decision

In `证据标注`, row-level `重抓` should use a browser-first acquisition path.

The operator expectation is:

```text
如果人工浏览器可以打开页面
-> 系统应优先尝试用真实浏览器抓取页面源码和正文
-> 只有浏览器抓取失败或正文仍不可用时，才提示人工补录
```

HTTP-only fetching is now a fallback, not the primary behavior for manual
refetch. When both browser and HTTP fetching fail, the UI should preserve the
combined failure reason so operators can decide whether to retry or supplement
manually.

## 2026-08-25 Citation Evidence Workflow Entry

### Product Decision

Single Prompt main workflow step 4, `引用证据`, must route to `证据标注`.

The operator job at this step is:

```text
抓取引用正文
-> 人工补录缺失正文
-> 查看正文状态
-> 建立或核对证据对齐
```

`引用资料` remains a source ranking / source structure page. It may be used as a
detail page for inspection, but it must not be the primary operation entry for
the main workflow's citation evidence step.

### Product Boundary

Changing a main workflow card from `证据标注` back to `引用资料`, or changing
`引用证据` into a ranking-first step, is a product-level workflow change and must
be explicitly recorded before implementation.

## 2026-08-25 Workflow State Integrity

### Product Decision

Single Prompt workflow must be one integrated product chain, not a set of
parallel modules:

```text
采集样本
-> 答案决策识别
-> 目标品牌事实
-> 引用证据
-> 对标来源
-> 缺口诊断
-> 推荐动作
-> 实验草案
```

Citation Optimization Decision V1 belongs inside this chain. It may have a
detail page for inspection and operations, but it must not appear as a separate
homepage module competing with the main workflow.

### State Ownership Rule

Each workflow card has exactly one primary fact source:

| 阶段 | 唯一主状态源 |
| --- | --- |
| 采集样本 | 当前 Prompt Runs |
| 答案决策识别 | RecommendationEvent / Answer Semantic |
| 目标品牌事实 | Product Truth |
| 引用证据 | 当前 Prompt Evidence Package + SourceDocument / EvidenceAlignment |
| 对标来源 | Citation Decision V1 Benchmark derived state |
| 缺口诊断 | Source Gap derived state |
| 推荐动作 | Current Gap -> Proposal |
| 实验草案 | Current human-confirmed Strategy / Plan / Experiment |

Legacy workflow outputs such as `continueResult` may be displayed as historical
execution context, but they must not mark the current Citation V1 chain as
complete.

### Context Identity Rule

Decision data must be bound to the current analysis context:

```text
project_id
prompt_id
evidence_package_id
analysis_version
```

The frontend must discard decision results whose `prompt_id` does not match the
current Prompt. Prompt switching must clear Prompt-scoped Citation Decision,
benchmark, proposal, channel, action, and experiment state before reloading.

### Change Warning Rule

Any future change that alters the main chain order, creates a new top-level
module, or changes a card's primary state source must be treated as a product
level change. It requires an explicit development-log entry and product
iteration-log entry before implementation.

### Answer Decision Repair Rule

The second workflow step, `答案决策识别`, must be repairable from the decision
diagnosis detail page when machine-recognized answer objects are blocked by
validation failure or unknown entity relationship.

The repair surface is not the generic empty review queue. It must show the
actual answer-decision objects and let the operator choose:

```text
确认为竞品
设为目标品牌
不进入决策
```

Only confirmed target-brand or competitor objects can count as valid
answer-decision events. Rejected objects are audit records, not valid choice
events, and must not advance Product Truth, Citation Evidence, Gap, Action, or
Experiment.

The workflow must distinguish:

```text
all_reviews_done
= 当前审核队列已清空

ready_to_continue
= 可以继续生成缺口和动作
```

A Prompt can have `all_reviews_done = true` while `ready_to_continue = false`
when the only detected answer objects are validation-failed or rejected. In that
case the UI must route the operator to answer-decision repair, not to Gap /
Action generation.

## 2026-08-25 Citation URL Display Normalization

引用资料页面和相关证据表格展示来源时，必须使用规范化 URL / 域名视角，避免把
`www.zhihu.com`、`www.baidu.com` 这类展示噪音当作独立来源。

采集和审计边界保持不变：

```text
original_url
= 原始观测 / 可点击审计链接

canonical_url / domain
= 引用资料分析、去重、Benchmark 和 Gap 使用的规范化来源身份

action_url
= 默认点击、人工补录和重抓使用的规范化操作链接
```

系统不得为了抓取成功率盲目给已存在的平台子域添加 `www.`。例如：

```text
zhuanlan.zhihu.com
baijiahao.baidu.com
jingyan.baidu.com
```

都不能被改写成：

```text
www.zhuanlan.zhihu.com
www.baijiahao.baidu.com
www.jingyan.baidu.com
```

但真实域名中间包含 `www` 的来源，例如 `gjzwfw.www.gov.cn`，不能被错误改写。

## 2026-08-25 Citation Refetch Feedback Contract

证据标注里的来源重抓不要求操作者看到浏览器窗口。只要后台浏览器抓取和可见浏览器抓取的最终效果一致，V1 默认以状态反馈为准：

```text
点击重抓
-> 当前行立即显示重抓中
-> 后端返回抓取方式 / 正文字数 / 成功或失败原因
-> 当前行保留本次结果
```

该交互用于避免“点了没反应”的误判。可见浏览器只应作为后续人工登录、验证码或复杂页面排障能力，不进入当前主链路默认动作。

## 2026-08-25 Single Prompt Citation Evidence Entry Contract

单 Prompt 主链第 4 步 `引用证据` 的默认动作必须能推进当前链路，不能只跳到正文补录详情页。

```text
没有 Evidence Package
-> 显示「待生成证据包」
-> 主按钮为「生成证据包」
-> 使用当前 Prompt 的有效 Runs 创建/复用证据包
-> 运行 Citation Decision V1
```

```text
已有 Citation Decision V1 结果
-> 显示「已完成」
-> 主按钮为「查看证据正文」
-> 进入证据标注详情页做补录、重抓和人工审计
```

这不是新增模块，也不改变主链顺序；它只是补齐第 4 步从“正文补录完成”到“证据包/引用证据链路运行”的操作口。

## 2026-08-26 Citation Decision V1.1 Phase 1 Input Contract

Phase 1 只批准“小范围正式 Evidence 输入切换”，不批准全量切换，也不改变单
Prompt 主链顺序。

允许的变化：

```text
正式 Passage Retrieval / EvidenceAlignment
可以在显式开关开启时读取
AnswerUnit + AnswerDecisionBinding
作为答案侧推荐理由输入
```

不允许的变化：

```text
Shadow SUPPORTS
-> 直接升级正式 Benchmark
```

```text
Citation Prominence / 标题同名 / legacy RELATED
-> 直接升级 SUPPORTS
```

```text
Phase 1 输入切换
-> 改变 Product Truth / Gap / Action / Strategy / Experiment 规则
```

正式链仍必须等新的正式 `EvidenceAlignment.relation = SUPPORTS` 形成后，
Benchmark / Gap / Action 才能自然消费该结果。所有 Phase 1-derived
alignment 必须保留 provenance，便于审计和回滚。

Prompt `#40` 小范围实跑结果已证明该合同成立：

```text
AnswerDecisionBinding
-> 正式 Passage Retrieval
-> 正式 SourceClaim
-> 正式 EvidenceAlignment
-> 对标来源
-> 推荐动作
```

推进原因必须解释为：

```text
正式 SUPPORTS 已形成
```

而不是：

```text
引用显著性高
标题包含同名实体
Shadow SUPPORTS 存在
```

本轮没有改变主链步骤，也没有新增独立入口模块。
## 2026-08-27 Citation Decision V1.1 Phase 1.1 Product Boundary

本轮产品目标不是新增主链模块，也不是进入多 Prompt Phase 2，而是收口
`Citation Decision V1.1` 正式链的三个基础条件：

```text
多 Run 证据稳定性
正式结果可回滚
推荐动作可信
```

保持不变的主链顺序：

```text
采集样本
-> 答案决策识别
-> 目标品牌事实
-> 引用证据
-> 对标来源
-> 缺口诊断
-> 推荐动作
-> 实验草案
```

本轮新增或强化的产品边界：

```text
1. 语义证据可以按能力去重，但必须保留 Run 覆盖。
2. V1.1 开关必须同时控制生成和读取，关闭时不删除数据但不消费。
3. 对标证据进入动作前，必须匹配具体 Product Truth。
4. 宽泛 Product Truth 不能放行细能力动作。
5. 有核心对标来源但 Product Truth 不足时，状态应显示“待补事实/待判断”，不能显示可执行动作。
```

Prompt `#40` 最新真实结论：

```text
V1.1 OFF:
  核心对标 = 0
  推荐动作 = 0

V1.1 ON:
  核心对标 = 1
  推荐动作 = 0
  阻塞原因 = 需要补齐目标品牌具体能力事实
  待确认能力 = 点击统计 / 自定义分享标题 / 营销场景使用
```

这意味着：

```text
V1.1 正式输入链路成立；
但 #40 目前还不能创建推荐动作或实验草案，
因为 Product Truth 还没有覆盖 Benchmark 暴露出的具体能力。
```

进入 Phase 2 前的产品 Gate：

```text
1. 补齐或确认 #40 的具体 Product Truth。
2. 重新运行 #40，验证 Gap / Action 是否来自具体 Product Truth。
3. 保持 V1.1 OFF/ON 可回滚。
4. 创建 checkpoint commit。
5. 再选择 3-5 个不同类型 Prompt 做泛化验证。
```

## 2026-08-27 Phase 2A：EvidenceAlignment Run Lineage 归属规则

本轮不改变单 Prompt GEO 主链顺序，不新增独立入口模块，也不进入
DISCOVERABILITY_GAP、Step 7、Step 8 或 Decision Stability。

本轮产品约束：

```text
SourceDocument / SourceClaim 是文档级事实，
可以跨 Run 复用；

EvidenceAlignment 是否能进入正式 V1 决策，
必须由完整 Run lineage 判断，
不能只看 run_id 非空。
```

正式 V1 消费资格必须同时证明：

```text
1. AnswerUnit 属于当前 Run。
2. AnswerDecisionBinding 属于当前 Run。
3. AnswerDecisionBinding 绑定的 RecommendationEvent 属于同一 Run。
4. 当前 Run 真实引用了对应 SourceDocument。
5. SourceClaim 属于该 SourceDocument。
6. EvidenceAlignment 对齐的是上述 AnswerUnit 与 SourceClaim。
```

产品上必须区分：

```text
文档被多次引用
≠
每个 Run 都形成了真实 SUPPORTS

payload 写了 observed_run_ids
≠
正式 Prompt 覆盖率
```

因此：

```text
observed_run_ids / run_coverage
只能从 eligible SUPPORTS 的真实 run_id 去重集合推导。
```

历史数据处理：

```text
历史 RELATED / 无完整 lineage Alignment 继续保留；
可用于 Legacy 查看；
不能进入新的正式单 Prompt V1 Benchmark / Gap / StrategyCandidate 证据链。
```

Prompt `#40` Phase 2A 审计结果：

```text
Evidence Package #15
Runs = [238, 239, 240, 253, 254, 255]

每个 Run:
  eligible SUPPORTS = 6
  eligible NO_SUPPORT = 5

历史 RELATED:
  LEGACY_RELATION_ONLY = 594

Prompt-level observed_run_ids:
  [238, 239, 240, 253, 254, 255]
  coverage = 6/6
```

这确认之前担心的情况已经被阻止：

```text
SUPPORTS 只实际落在一个 Run，
但 Prompt 层被 payload 或 SourceDocument 出现情况补成多个 Runs。
```

后续 Phase 进入前仍需保持：

```text
不因 Citation Prominence 升级 Benchmark；
不因标题同名直接 SUPPORTS；
不让 Legacy RELATED 进入 V1 支撑语义；
不把竞品 SourceClaim 自动升级成目标品牌 Product Truth。
```

## 2026-08-27 Citation Decision V1.1 Phase 2B Gap Diagnosis

### Product Decision

Phase 2B 只把第 6 步“缺口诊断”推进到 capability/reason-level，不进入
第 7 步策略候选或第 8 步实验草案。

缺口判断固定为最早失败层决策树：

```text
Product Truth
-> Relevant Asset Expression
-> RetrievalCandidate
-> Evidence Adoption
```

### Meaning

本阶段让系统能回答：

```text
对标来源支撑了哪些具体推荐理由？
目标品牌是否真实支持这些能力？
目标品牌相关资产是否已经表达这些能力？
相关资产是否进入当前 Prompt 的有效检索候选？
相关资产是否在当前答案中出现引用/采纳上下文？
```

最早失败层决定 Gap 类型：

```text
Product Truth 不支持        -> PRODUCT_GAP
缺同粒度 Product Truth      -> UNKNOWN
相关品牌资产表达缺失        -> CONTENT_GAP
相关品牌资产只有声明无证据  -> EVIDENCE_GAP
相关品牌资产未被有效检索    -> DISCOVERABILITY_GAP
检索到了但未被引用/采纳     -> EVIDENCE_GAP
检索和引用/采纳均具备       -> NO_GAP
```

### Hard Boundaries

```text
Evidence 只消费 Phase 2A eligible lineage；
Discoverability 只消费当前证据包 Run 内有效 RetrievalCandidate；
Relevant Brand Asset 必须可审计并冻结诊断快照；
不建设强制人工白名单；
不修改 Citation Prominence / Benchmark 评分公式；
不新增平行 Strategy / Experiment；
不开发 Step 7 / Step 8。
```

### Prompt #40 Regression

真实回归结果：

```text
核心对标来源：SourceDocument #345
缺口类型：CONTENT_GAP
最早失败层：RELEVANT_ASSET_EXPRESSION
Product Truth：TRUE
相关资产快照：PageSnapshot #3
资产覆盖：MISSING
检索状态：RETRIEVED
采纳状态：NOT_ADOPTED
```

解释：

```text
#40 当前不是 Product Truth 缺失；
也不是品牌资产完全没进入检索；
最早失败点是目标品牌相关资产没有覆盖对标来源暴露出的具体能力表达。
```

当前状态：

```text
PHASE_2B_CAPABILITY_GAP_READY_FOR_REVIEW
STEP_7_NOT_STARTED
STEP_8_NOT_STARTED
```

## 2026-08-27 Citation Decision V1.1 Phase 3 StrategyCandidate

### Product Decision

Phase 3 正式进入主链第 7 步，但第 7 步不是“确认推荐动作”。

第 7 步定义为：

```text
已完成缺口诊断
-> 生成 StrategyCandidate
-> 人工审核 / 编辑
-> 写入 effective_payload
-> Confirmed Strategy
```

第 8 步才处理：

```text
执行平台
目标资产
内容类型
Action
Experiment
Baseline / 发布 / 复测
```

### Capability-Level Strategy Input

策略候选不能直接消费一个 source-level `source_gap_type` 作为唯一真值。

正式输入是：

```text
capability_gap_items
```

每个 item 必须保留：

```text
能力/理由
Gap 类型
最早失败层
Benchmark Evidence
Product Truth
Relevant Asset
observed_run_ids / run coverage
```

这样多个能力缺口可以合并成一个候选策略，但合并后不能丢失每个能力的
证据链。

### Human Confirmation Meaning

人工确认的是：

```text
这个 Strategy 机制是否成立；
这些 capability/reason Gap 是否应该作为后续执行方案输入。
```

人工确认的不是：

```text
立刻创建 Action；
立刻创建 Experiment；
选择知乎/官网/百家号等发布平台；
生成正式内容任务。
```

如果 `effective_payload` 里仍有：

```text
target_platform = UNRESOLVED
target_asset = UNRESOLVED
target_content_type = UNRESOLVED
```

则状态保持：

```text
PENDING_HUMAN_CHANNEL_REVIEW
```

这表示 Strategy 已确认，但执行信息留给 Step 8。

### Prompt #40 Regression

真实回归结果：

```text
StrategyCandidate #40

Gap items:
  点击统计           CONTENT_GAP / RELEVANT_ASSET_EXPRESSION / 6 Runs
  自定义分享标题     CONTENT_GAP / RELEVANT_ASSET_EXPRESSION / 6 Runs
  营销场景使用       CONTENT_GAP / RELEVANT_ASSET_EXPRESSION / 6 Runs

review_status_before = PENDING_REVIEW
review_status_after = ACCEPTED_WITH_EDITS
effective_validation_status_after = PENDING_HUMAN_CHANNEL_REVIEW
```

执行对象没有被创建：

```text
OptimizationAction: 16 -> 16
OptimizationExperiment: 16 -> 16
```

### Hard Boundary

```text
PRIMARY_BENCHMARK 来自知乎
≠
Strategy 自动选择知乎发布
```

Benchmark Channel 只说明证据来源，不决定 Strategy Channel。

当前状态：

```text
PHASE_3_STRATEGY_CANDIDATE_READY_FOR_REVIEW
STEP_8_NOT_STARTED
```

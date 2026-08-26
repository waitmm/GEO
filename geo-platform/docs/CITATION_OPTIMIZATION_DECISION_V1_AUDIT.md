# Citation Optimization Decision V1 开发前审计

状态：Step 0-3 Foundation Semantic Layer READY；Step 4A Benchmark Decision Layer READY；Step 4B Source Gap / Priority / Action Route READY；V1 Vertical Slice Completion READY
日期：2026-08-24

## 1. 审计目的

本审计用于启动“引用资料优化决策 V1”前的最后校准。

V1 不新建一套平行 Citation Intelligence Platform，而是在现有链路上做语义收口：

```text
ReferenceSource
-> SourceDocument
-> Reason-driven Passage Retrieval
-> Blind SourceClaimJudge
-> EvidenceAlignmentJudge
-> Decision Support Level
-> Benchmark Tier
-> Source Gap
-> Priority
-> Action Route
-> Intervention / Experiment
-> Re-sampling
-> Recommendation Outcome
```

目标是把当前已经跑通的软件闭环变得更可信、更可解释，并避免三类误导：

- 把引用频率误当成内容质量。
- 把无正文来源误当成可语义分析来源。
- 把平台引用强度直接误当成发布策略。

## 2. 开发硬约束

### 2.1 SourceClaimJudge 必须继续盲评

最终链路必须保持：

```text
Answer Reason / Prompt
        -> 只用于 Passage Retrieval
        -> 候选 source passages
        -> Blind SourceClaimJudge
        -> Source Claims
        -> EvidenceAlignmentJudge
```

`Answer Reason` 可以决定“去正文哪里找”，但不能决定“正文应该说什么”。

禁止改成：

```text
Prompt + Answer Claims + SourceDocument -> SourceClaimJudge
```

职责边界：

- Reason-driven Passage Retrieval = Recall。
- SourceClaimJudge = Source Truth Extraction。
- EvidenceAlignmentJudge = Answer 与 Source 的关系判断。

### 2.2 历史 RELATED 不能升级为 PARTIAL_SUPPORT

现有 `EvidenceAlignment.relation` 包含：

```text
SUPPORTS
CONTRADICTS
RELATED
NONE
```

V1 目标枚举为：

```text
SUPPORTS
PARTIAL_SUPPORT
CONTRADICTS
NO_SUPPORT
```

兼容策略：

```text
SUPPORTS     -> SUPPORTS
CONTRADICTS  -> CONTRADICTS
NONE         -> NO_SUPPORT
RELATED      -> LEGACY_RELATED / PENDING_REJUDGE
```

`RELATED` 只说明主题相关，不能自动获得“部分支撑”的语义升级。

### 2.3 source_score 只能降级为 legacy

当前 `source_score` 混合了引用行为和元数据信号：

- citation frequency
- citation position
- Prompt-title overlap
- URL/domain
- freshness
- authority
- account identity
- content type

V1 不能只把 UI 名称改成 Citation Prominence。必须新增真正的：

```text
citation_prominence_level
```

其输入只允许来自可观察 Citation Behavior：

```text
run coverage
citation frequency
citation position
cross-run stability
```

旧字段保留为：

```text
legacy_source_score
deprecated = true
```

并不得继续驱动：

- Benchmark Tier
- Priority
- StrategyCandidate
- Experiment conclusion

## 3. 实体与字段映射

| V1 能力 | 当前承载 | 处理方式 | 说明 |
| --- | --- | --- | --- |
| Citation Discovery | `ReferenceSource` | REUSE | 已保存最终引用标题、URL、domain、reference_index。 |
| Retrieval Candidate | `RetrievalCandidate` | REUSE | 只作为辅助信号，不能默认当作 ReferenceSource 上游漏斗。 |
| Citation Prominence | `ReferenceSource` 聚合 / Evidence Package payload | EXTEND | 新增规则层输出 `citation_prominence_level`，不要复用旧 `source_score` 语义。 |
| Legacy Source Score | `source_score` / `raw_evidence_score` | DEPRECATE | 保留历史兼容与诊断展示，但不参与新决策。 |
| Citation Content | `SourceDocument.fetch_status` + `SourceQuality.content_quality_status` | EXTEND | 需要映射到 V1 四态。 |
| Content Unavailable Reason | `SourceDocument.failure_reason` | EXTEND | 可复用字段，但前端必须拆出“标记无法获取”动作和原因枚举。 |
| Answer Semantic | `RecommendationEvent` | REUSE | 已有 `speech_act`、`answer_span`、`reasons_json`、`review_status`。 |
| Answer Span Validation | `RecommendationEvent.raw_start/raw_end` | REUSE | 现有 `locate_span` 已做确定性定位。 |
| Source Claim | `SourceClaim` | REUSE | 已是盲评结构，保留。 |
| Source Span Validation | `SourceClaim.raw_start/raw_end` | REUSE | 当前 SourceClaim 已在 passage 内做 span grounding。 |
| Evidence Alignment | `EvidenceAlignment` | EXTEND | 需要 V1 relation 兼容层，不能把历史 RELATED 当作 PARTIAL_SUPPORT。 |
| Decision Support Level | `service.source_analysis` 派生字段 | EXTEND | 已做规则聚合 read model，不建表；只读取 V1 EvidenceAlignment。 |
| has_contradiction | `EvidenceAlignment.relation == CONTRADICTS` 聚合 | EXTEND | 单独输出 boolean，不能作为 Decision Support 互斥值。 |
| Benchmark Tier | `service.source_analysis` 派生字段 | EXTEND | 已进入 Evidence Package source analysis response；不驱动 Gap/Action。 |
| Product Truth | `TargetBrandCapabilityTruth` | REUSE | 现有状态比 V1 更细，V1 可映射 TRUE/FALSE/UNKNOWN。 |
| Existing Brand Asset | `PageSnapshot` / `OptimizationAction.target_url` / project website | EXTEND | V1 只分析当前指定资产，不做全站扫描。 |
| Source Gap | `service.source_analysis` 派生字段 | EXTEND | 已做来源级规则 read model；不写入 `DecisionGapDiagnosis`。 |
| Channel Opportunity | `channel_strategy.py` / `InterventionPlan` | EXTEND | 必须由平台级聚合产生，不允许单 Source 直接输出。 |
| Priority Label | `service.source_analysis` 派生字段 | EXTEND | 已用规则输出 `PRIORITY_HIGH/MEDIUM/NOT_PRIORITY/UNRESOLVED` 或 `null`。 |
| Action Route | `service.source_analysis` 派生字段 | EXTEND | 已用规则输出 `CONTENT/EVIDENCE/PRODUCT/NO_ACTION/UNRESOLVED` 或 `null`；不创建 Action。 |
| Human Review | `WorkflowConfirmation` / review_status 字段 | REUSE + EXTEND | 保留 `PENDING/CONFIRMED/REJECTED` 语义，避免 bool。 |
| Intervention Plan | `InterventionPlan` | REUSE | 已支持 Prompt 级计划和 channel experiments。 |
| Strategy Candidate | `OptimizationStrategyCandidate` | REUSE | `effective_payload` 仍是执行 single truth。 |
| Experiment | `OptimizationExperiment` | REUSE | 已有 baseline/validation/post/outcome 字段。 |
| Recommendation Outcome | `RecommendationEvent` + Experiment metrics | EXTEND | 实验主结果应看 candidate/recommendation/reason outcome，而不是只看 citation lift。 |

## 4. Content Status 映射建议

V1 对外只展示：

```text
CONTENT_PENDING
CONTENT_VALID
CONTENT_UNAVAILABLE
CONTENT_INVALID
```

当前字段映射建议：

| 当前状态 | V1 content_status | 说明 |
| --- | --- | --- |
| `SourceQuality.CONTENT_VALID` | `CONTENT_VALID` | 可进入 Prompt Relevance、SourceClaim、EvidenceAlignment、Benchmark。 |
| `SourceDocument.fetch_status = pending` | `CONTENT_PENDING` | 等待自动抓取或人工处理。 |
| `SourceDocument.fetch_status = FETCH_FAILED` | `CONTENT_UNAVAILABLE` | 需保留 failure_reason。 |
| `SourceDocument.fetch_status = MANUAL_EMPTY` | `CONTENT_UNAVAILABLE` | 只能表示人工确认不可获得，不能算补录成功。 |
| `SourceQuality.EMPTY` | `CONTENT_UNAVAILABLE` | 正文为空。 |
| `SourceQuality.NOISY` | `CONTENT_INVALID` | 验证码、登录墙、导航壳、CSS/JS 噪声。 |
| `SourceQuality.FETCH_FAILED` | `CONTENT_UNAVAILABLE` | 无可分析正文。 |

正文缺失的 Source 只能保留：

- Citation Prominence
- title/url/domain/platform
- run frequency
- citation position

禁止产出：

- Prompt Relevance
- Source Claim
- Evidence Alignment
- Content Gap
- Evidence Gap
- Primary Benchmark

如果 `citation_prominence_level = HIGH` 且 `content_status != CONTENT_VALID`，显示：

```text
HIGH_PROMINENCE_UNAVAILABLE
Benchmark = NOT_EVALUABLE
Priority = UNRESOLVED
```

## 5. 当前 API / Service 映射

| V1 步骤 | 当前入口 | 处理方式 |
| --- | --- | --- |
| 选择 Prompt + Runs | workflow / evidence package APIs | REUSE |
| AnswerSemanticJudge | `answer_semantic.py` / `/workflow/{project_id}/{prompt_id}/run-analysis` | REUSE |
| Citation Discovery | collector + `ReferenceSource` | REUSE |
| Citation Prominence | `service.source_analysis` / `ranking.py` | EXTEND |
| 正文获取 | `passage_service.py` / golden-case acquire/refetch/manual | EXTEND |
| Prompt Relevance | 暂无独立 judge | NEW |
| SourceClaimJudge | `source_claim.py` | REUSE |
| EvidenceAlignmentJudge | `evidence_alignment.py` | EXTEND |
| Decision Support Level | 暂无独立聚合 | NEW |
| Benchmark Tier | intervention benchmark checklist / evidence payload | EXTEND |
| Source Gap | `gap_action.py` / recommendation gap reads | EXTEND |
| Priority + Action Route | Strategy payload / workflow continue | EXTEND |
| Human Review | workflow review / StrategyCandidate review | REUSE |
| Experiment | workflow experiments / optimization experiments | REUSE |
| Outcome | experiment outcome API | EXTEND |

## 6. 前端影响面

优先影响页面：

- 引用资料：隐藏或降级连续分数，展示 Citation Prominence 标签。
- 证据标注：正文状态改为 V1 四态，并拆分“提交正文”和“标记无法获取”。
- 决策诊断：新增 Decision Support、Benchmark Tier、Source Gap、Priority、Action Route 的解释。
- 最终策略：只接收规则层产物和人工确认后的 `effective_payload`。
- Experiment：结果判断以 Recommendation Outcome 为主，Citation Lift 为辅。

现有前端明确需要调整的点：

- “引用资料分析”当前仍展示 `raw_evidence_score` 小数分。
- Golden Case 文档状态当前以 `SUCCESS/PARTIAL/MANUAL_EMPTY/FETCH_FAILED` 直出，需映射为中文 V1 状态。
- 当前“空页”不应被理解为补录成功，应改成“已标记无法获取”。

## 7. 测试缺口

建议最小新增测试：

1. Citation Prominence 只由 citation behavior 决定，不受 authority/freshness/title overlap 影响。
2. 高引用但正文不可得时，Source 为 `HIGH_PROMINENCE_UNAVAILABLE`，Prompt 仍继续分析其他有效 Source。
3. `MANUAL_EMPTY` 映射为 `CONTENT_UNAVAILABLE`，不能进入 SourceClaim。
4. 历史 `RELATED` 不会映射为 `PARTIAL_SUPPORT`。
5. `CONTRADICTS` 聚合为 `has_contradiction = true`，不吞掉正向 Decision Support。
6. `PRIMARY_BENCHMARK` 不由 Citation Prominence 决定。
7. `PRODUCT_GAP` 可以输出 `PRIORITY_HIGH`，但 Action Route 必须是 `PRODUCT`。
8. 单个强 Source 不会直接生成 `CHANNEL_OPPORTUNITY`。
9. Experiment outcome 不能用 Citation Lift 单独判成功。

## 8. 建议实施顺序与当前状态

### Step 1：Citation Prominence 收口

- 新增纯引用行为规则函数。
- 输出 `citation_prominence_level` 和可解释因子。
- 将 `source_score/raw_evidence_score` 标记为 legacy/deprecated。
- 前端不再展示伪精确分数作为主判断。

### Step 2：Content Status + 人工补录

- 建立 `content_status` 映射层。
- 前端拆分“提交正文”和“标记无法获取”。
- 空正文必须有 `unavailable_reason`。
- `CONTENT_UNAVAILABLE` 不阻塞整个 Prompt。

### Step 3：Evidence Semantic 收口

- 保留 Blind SourceClaimJudge。
- 新增 PromptRelevanceJudge。
- EvidenceAlignment 增加 V1 relation 兼容层。
- 历史 `RELATED` 映射为 `LEGACY_RELATED`，不进入支持语义。

状态：已完成并通过 Prompt #43 真实验收。

### Step 4A：Decision Support + Benchmark

- 聚合 Decision Support Level。
- 聚合 `has_contradiction`。
- 规则生成 Benchmark Tier。

状态：已完成，不生成 Gap、Priority 或 Action。

Step 4A 规则：

```text
decision_support_level:
  RECOMMENDATION_REASON
  CANDIDATE_OR_EVALUATION
  FACT_ONLY
  NONE

has_contradiction:
  true / false

benchmark_tier:
  PRIMARY_BENCHMARK
  SECONDARY_BENCHMARK
  REFERENCE_ONLY
  NOT_EVALUABLE
```

规则边界：

- `LEGACY_RELATED` / 历史 `RELATED` 不参与 Decision Support 聚合。
- 没有 `SUPPORTS` 时，不能产生 `RECOMMENDATION_REASON`。
- `CONTENT_UNAVAILABLE` 必须得到 `NOT_EVALUABLE`。
- `citation_prominence_level` 只做同 Tier 排序，不参与 Tier 判定。
- `has_contradiction` 独立于 `decision_support_level`。
- 允许 `PRIMARY_BENCHMARK = 0`。

Prompt #43 真实 smoke：

```text
runs = 6
source rows = 83
EvidenceAlignment.relation = RELATED x 1440
benchmark_tiers = REFERENCE_ONLY x 2, NOT_EVALUABLE x 81
decision_support_level = NONE x 83
PRIMARY_BENCHMARK = 0
```

结论：当前有效正文和新的 V1 Evidence Alignment 尚不足以证明任何来源真正参与 Recommendation Decision。系统接受 0 Primary，而不是强行找 Benchmark。

### Step 4B：Source Gap / Priority / Action Route

#### Step 4B-1：Source Gap

输入严格限定为：

```text
Benchmark Evidence
+ Brand Product Truth
+ Existing Brand Asset
```

输出只允许：

```text
CONTENT_GAP
EVIDENCE_GAP
PRODUCT_GAP
NO_GAP
UNKNOWN
```

规则边界：

- 没有 `PRIMARY_BENCHMARK` 或 `SECONDARY_BENCHMARK` 时，不进入 Gap Analysis。
- 未进入 Gap Analysis 时 `source_gap_type = null`，不能写成 `UNKNOWN`。
- `Product Truth = UNKNOWN` 或未匹配到人工确认能力时，输出 `UNKNOWN`。
- 品牌资产快照缺失或正文不足时，输出 `UNKNOWN`。
- `PRODUCT_GAP` 是高价值产品发现，不等于“不做”。
- `REFERENCE_ONLY` 不允许被拿来强行推导 Competitive Gap。

状态：已完成。

Prompt #43 真实 smoke：

```text
eligible_benchmark_count = 0
source_gap_type = null x 83
source_gap_precondition = NO_ELIGIBLE_BENCHMARK x 83
```

结论：当前没有可进入 Gap Analysis 的 Benchmark，系统暂不生成 Competitive Gap。

#### Step 4B-2：Priority + Action Route

输入严格限定为：

```text
benchmark_tier
+ source_gap_type
+ source_gap_precondition
```

输出只允许：

```text
priority_level:
  PRIORITY_HIGH
  PRIORITY_MEDIUM
  NOT_PRIORITY
  UNRESOLVED
  null

action_route:
  CONTENT
  EVIDENCE
  PRODUCT
  NO_ACTION
  UNRESOLVED
  null
```

确定性映射：

- `PRIMARY_BENCHMARK + CONTENT_GAP/EVIDENCE_GAP/PRODUCT_GAP` -> `PRIORITY_HIGH`。
- `SECONDARY_BENCHMARK + CONTENT_GAP/EVIDENCE_GAP/PRODUCT_GAP` -> `PRIORITY_MEDIUM`。
- `NO_GAP` -> `NOT_PRIORITY + NO_ACTION`。
- `PRIMARY/SECONDARY + UNKNOWN` -> `UNRESOLVED + UNRESOLVED`。
- `REFERENCE_ONLY + source_gap_type = null` -> `NOT_PRIORITY + null`。
- `NOT_EVALUABLE + source_gap_type = null` -> `null + null`。
- Citation Prominence 只能在同级内排序，不能改变 Priority 档位。

状态：已完成。

Prompt #43 真实 smoke：

```text
eligible_benchmark_count = 0
priority_level = NOT_PRIORITY x 2, null x 81
action_route = null x 83
```

结论：Prompt #43 未产生 `PRIORITY_HIGH` / `PRIORITY_MEDIUM`，也未进入 CONTENT / EVIDENCE / PRODUCT 路径。

#### Step 4B-3：Evidence-grounded Recommended Action / Vertical Slice

- `source_analysis` 行级输出 proposal-only 的 `recommended_action`。
- 仅 Primary/Secondary Benchmark 且存在 `CONTENT` / `EVIDENCE` / `PRODUCT` 路径时生成。
- `REFERENCE_ONLY`、`NOT_EVALUABLE`、`LEGACY_RELATED` 和 Citation Prominence 不能生成动作建议。
- `PRODUCT_GAP` 只生成产品机会说明，不自动创建内容发布实验。
- 同平台存在 Primary/Secondary Benchmark、且目标品牌未发现同平台资产时，输出 `CHANNEL_OPPORTUNITY`。
- 新增 `citation_decision_vertical_slice` 服务/API：
  `Source Analysis -> Recommended Action -> Channel Opportunity -> Human Confirmation -> StrategyCandidate -> InterventionPlan -> Experiment Draft`。
- 人工确认后只对 `CONTENT` / `EVIDENCE` 路径创建 StrategyCandidate 并复用 `effective_payload` 闸门和现有 `strategy_to_experiment_plan()`。
- Experiment 仍保持 draft / blocked 状态，发布、复测和最终结论继续走原有 Release/Retest/Human Conclusion Gate。
- `analyze_experiment()` 写入 Recommendation Outcome，比较 candidate、recommendation、target reason、citation 的 before/after 观察变化。

状态：已完成。

真实库只读 smoke：

```text
Prompt #43:
  no Evidence Package -> fail-closed，不生成 Proposal

Prompt #9 / Package #13:
  PRIMARY_BENCHMARK = 0
  recommended_action_count = 0

Prompt #19 / Package #12:
  PRIMARY_BENCHMARK = 2
  recommended_action_count = 0
  原因：仍被 Product Truth / Brand Asset / Source Gap Gate 阻断，没有绕过规则强行生成 Action

Prompt #16 / Package #11:
  PRIMARY_BENCHMARK = 0
  recommended_action_count = 0
```

### Step 5：接 Intervention / Experiment

- 将规则产物送入 StrategyCandidate / InterventionPlan。
- 人工确认后形成 executable payload。
- Experiment 主指标使用 Recommendation Outcome。
- Citation Lift 仅作为辅助指标。

## 9. 当前结论

V1 可以基于现有系统实现，不建议新建平行模型体系。

当前最小新增不是“大表重构”，而是：

```text
1. 规则 read model / payload 字段
2. 少量枚举兼容
3. 前端中文状态与边界提示
4. 回归测试
```

真正需要防止的是三件事：

```text
source_score 改名后继续驱动决策
RELATED 自动升级为 PARTIAL_SUPPORT
SourceClaimJudge 被 Answer Reason 污染
```

完成 Step 0 后，可以从 Step 1 开始做最小改造。

## 10. Prompt #40 推荐理由与引用对齐审计

日期：2026-08-26

本节用于解释 Prompt `#40` 在真实链路中的关键现象：

```text
答案里明确推荐了小码短链接
引用资料里也有一篇小码相关知乎文章
但 Citation Decision V1 仍显示 0 个核心/辅助对标来源
```

结论不是“答案没有推荐”，也不是“引用资料没有正文”。当前更准确的判断是：

```text
推荐事件已识别
引用正文已抓到
答案主张也已抽取
但 RecommendationEvent.reasons_json 为空
导致 Reason-driven Passage Retrieval 没有输入
进而没有 SourceClaim 和 EvidenceAlignment
最终 Benchmark 只能保守为 REFERENCE_ONLY
```

### 10.1 当前 V1 证据链如何工作

当前 Citation Decision V1 的正式语义链路是：

```text
BrowserMonitorRun.answer_text
-> AnswerSemanticJudge
-> RecommendationEvent
-> RecommendationEvent.reasons_json
-> Reason-driven Passage Retrieval
-> Blind SourceClaimJudge
-> SourceClaim
-> EvidenceAlignmentJudge
-> Decision Support Level
-> Benchmark Tier
-> Source Gap
-> Priority / Action Route
```

其中哪些地方使用 LLM：

| 环节 | 是否使用 LLM | 当前职责 |
| --- | --- | --- |
| `AnswerSemanticJudge` | 是 | 从答案中识别实体、推荐行为、推荐理由、选择标准。 |
| `AnswerClaim` 抽取 | 否，当前主要是规则切分 | 把答案正文切成可展示/可旧式对齐的主张。 |
| `SourceDocument` 抓取 | 否 | 抓取引用页面正文，浏览器/HTTP/人工补录。 |
| `SourceClaimJudge` | 是 | 盲评来源正文片段，只抽来源自己说了什么。 |
| `EvidenceAlignmentJudge` | 是 | 判断答案理由与来源主张之间是 SUPPORTS / CONTRADICTS / NO_SUPPORT 等关系。 |
| Benchmark / Gap / Priority | 否 | 基于 V1 EvidenceAlignment 和 Product Truth 做确定性规则判断。 |

关键边界：

```text
SourceClaimJudge 不能看答案
Answer Reason 只用于找正文片段
Benchmark 不能由标题相似、Citation Prominence 或历史 RELATED 强行生成
```

### 10.2 Prompt #40 当前真实状态

本地接口只读核对结果：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
source_run_ids = [238, 239, 240, 253, 254, 255]

Citation Decision V1 status = NO_EXECUTABLE_RECOMMENDATION
source_count = 68
primary_benchmark_count = 0
secondary_benchmark_count = 0
recommended_action_count = 0
channel_opportunity_count = 0
```

Workflow 同时显示：

```text
数据采集：完成，6 Runs
推荐行为分析：完成，4 组有效选择事件
目标品牌能力确认：完成，3/3 条已确认
证据分析：未完成，无支持对齐
```

这说明 #40 不是没有进入前置流程，而是卡在：

```text
推荐行为
-> 推荐理由
-> 来源正文主张
-> 证据对齐
```

这条桥没有建立起来。

### 10.3 小码短链接这条证据的状态

Decision Market 已识别并人工确认：

```text
entity_text = 小码短链接
relationship = CONFIRMED_COMPETITOR
speech_act = RECOMMEND
run_coverage = 6/6
review_status_counts = HUMAN_CONFIRMED x 6
reasons = []
```

答案主张也已经存在：

```text
小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题等功能，适合营销场景使用
```

该主张在 6 个 Run 中各出现一次，来源为：

```text
AnswerClaim.provenance = RULE_DERIVED
AnswerClaim.review_status = PENDING
```

对应知乎来源也已经抓到正文：

```text
title = 如何将长链接缩短-小码至营
original_url = https://zhuanlan.zhihu.com/p/938392385
canonical_url = https://zhuanlan.zhihu.com/p/938392385
action_url = https://zhuanlan.zhihu.com/p/938392385
domain = zhuanlan.zhihu.com
fetch_status = SUCCESS
content_status = CONTENT_VALID
clean_text_len = 1758
blocks_count = 18
```

但 Citation Decision V1 对这条来源的结果是：

```text
decision_support_level = NONE
benchmark_tier = REFERENCE_ONLY
citation_prominence_level = HIGH
source_gap_type = null
source_gap_precondition = NO_ELIGIBLE_BENCHMARK
priority_level = NOT_PRIORITY
action_route = null
supporting_alignment_ids = []
```

数据库只读核对：

```text
SourceDocument #345 source_claims = 0
SourceDocument #345 evidence_alignments = 0
小码短链接 RecommendationEvent.reasons_json = []
```

所以这不是“正文只有标题”导致的。正文可用，但没有被 V1 语义链消费。

### 10.4 为什么没有被识别成对标来源

当前 V1 不是按下面逻辑判 Benchmark：

```text
答案提到小码
+ 引用标题提到小码
-> 自动认为该来源支撑推荐
```

它必须走：

```text
答案里的推荐理由
-> 到来源正文里召回相关 passage
-> 盲评来源 passage 得到 SourceClaim
-> 判断 SourceClaim 是否 SUPPORTS 推荐理由
-> 才能进入 Benchmark
```

#40 的断点是：

```text
RecommendationEvent.reasons_json = []
```

于是：

```text
Reason-driven Passage Retrieval 没有 reason query
-> SourceClaimJudge 没有候选 passage
-> SourceDocument #345 没有 SourceClaim
-> EvidenceAlignmentJudge 没有可判对象
-> decision_support_level = NONE
-> benchmark_tier = REFERENCE_ONLY
```

当前输出 `0 Primary / 0 Secondary` 从规则角度是正确的，因为系统没有放松闸门，也没有拿 Citation Prominence 或标题命中冒充 SUPPORTS。

但从产品角度看，这是一个必须修的 false negative：

```text
系统已经有足够线索知道这是一条“推荐实体相关引用”
但没有把答案主张里的能力描述回填/桥接成 Recommendation Reason
```

### 10.5 不能用哪些方式修

禁止为了让 #40 出结果而做以下捷径：

```text
Citation Prominence = HIGH
-> PRIMARY_BENCHMARK
```

```text
标题包含推荐实体
-> SUPPORTS
```

```text
历史 PassageAlignment = RELATED / L5_UNRESOLVED
-> PARTIAL_SUPPORT
```

```text
竞品页面说自己有能力
-> 目标品牌 Product Truth 自动支持
```

这些都会破坏 V1 已经建立的可信边界。

### 10.6 建议修复方向

下一步应该补的是“推荐理由桥接”，不是降低 Benchmark 标准。

建议最小修复顺序：

1. 从同 Run 的 `AnswerClaim` / `answer_span` 中提取实体级能力描述。

   例如 #40 可得到：

   ```text
   小码短链接:
   - 支持长链接快速缩短
   - 自带点击统计
   - 支持二维码生成
   - 支持自定义分享标题
   - 适合营销场景使用
   ```

2. 当 `RecommendationEvent.speech_act = RECOMMEND` 且 `reasons_json = []` 时，使用同实体、同答案邻近主张生成候选 reason。

   建议标记来源：

   ```text
   reason_provenance = ANSWER_CLAIM_DERIVED
   ```

   这仍然是答案事实，不是来源事实。

3. 将同实体引用来源标成候选线索，而不是直接升级成支持。

   可以输出：

   ```text
   same_entity_citation_candidate = true
   ```

   或中文展示：

   ```text
   同实体引用线索，待正文主张对齐
   ```

4. 重新运行：

   ```text
   Reason-driven Passage Retrieval
   -> Blind SourceClaimJudge
   -> EvidenceAlignmentJudge
   -> Benchmark Tier
   ```

5. 只有新的 V1 `EvidenceAlignment.relation = SUPPORTS` 后，才允许：

   ```text
   RECOMMENDATION_REASON / CANDIDATE_OR_EVALUATION
   -> PRIMARY_BENCHMARK / SECONDARY_BENCHMARK
   ```

### 10.6.1 Phase 0 必须是端到端 Shadow Evidence Chain

Phase 0 不能只验证：

```text
AnswerClaim
-> AnswerUnit
-> AnswerDecisionBinding
```

否则只能证明答案绑定层看起来合理，仍然无法证明 #40 的真正断点已经被修复：

```text
AnswerDecisionBinding
-> Passage Retrieval
-> SourceClaim
-> EvidenceAlignment
```

因此 Phase 0 的最终定义必须是“双轨运行”。

正式生产主链保持不变：

```text
RecommendationEvent.reasons_json
-> 原 V1 Evidence Chain
-> 原 Citation Decision
-> 正式 Benchmark / Gap / Priority / Action 输出
```

旁路新增完全隔离的 Shadow V1.1：

```text
AnswerClaim
-> AnswerUnit
-> AnswerEvidenceBindingJudge
-> AnswerDecisionBinding
-> Shadow Passage Retrieval
-> Shadow SourceClaimJudge
-> Shadow EvidenceAlignmentJudge
-> Shadow Evidence Classification
-> Shadow Audit Output
```

Phase 0 只允许写入审计结果，不得改变任何正式输出：

```text
不写正式 PRIMARY_BENCHMARK / SECONDARY_BENCHMARK
不写正式 Source Gap
不写正式 Priority
不写正式 Action Route
不创建正式 StrategyCandidate
不创建正式 Experiment
```

如果 Shadow 结果需要复用现有表，必须有明确版本隔离：

```text
pipeline_version = citation_decision_v1_1_shadow
```

或者具备等价的 shadow run / shadow batch 标识。核心要求是后续审计时必须一眼区分：

```text
正式 V1 产物
vs
V1.1 Shadow 产物
```

否则 SourceClaim / EvidenceAlignment 多跑几轮后会混在一起，反而破坏当前已经建立的证据边界。

Prompt #40 的 Phase 0 验收分两层：

```text
第一层：Binding 验收

小码短链接 RecommendationEvent
<- AnswerDecisionBinding
<- AnswerUnit

至少出现 DIRECT_REASON 或 SUPPORTING_REASON
```

```text
第二层：Shadow Evidence Chain 验收

AnswerUnit
-> 当前 Run 已确认 Citation Source Pool
-> Shadow Passage Retrieval
-> grounded Shadow SourceClaim 或明确无可抽取主张
-> Shadow EvidenceAlignment
-> SUPPORTS / NO_SUPPORT / CONTRADICTS
```

第二层结果只能进入 Shadow Audit。只有 Phase 1 feature flag 小范围开启后，才允许正式 Citation Decision V1 开始消费 AnswerUnit / Binding 产物。

当前 Phase 0 落地为独立审计表：

```text
AnswerUnit
AnswerDecisionBinding
AnswerEvidenceShadowRun
AnswerEvidenceShadowResult
```

Shadow Run 会记录正式表运行前后的计数，用于验证：

```text
formal SourceClaim 未增加
formal EvidenceAlignment 未增加
formal Benchmark / Gap / Priority / Action 未改变
```

### 10.6.2 Prompt #40 Phase 0 Shadow 实跑结果

本地已执行 Prompt `#40` 的 6 Runs 真实 Shadow 审计：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
source_run_ids = [238, 239, 240, 253, 254, 255]
entity_filter = 小码短链接
shadow_run_id = 6
status = completed
```

本次仍为 Phase 0 Shadow 审计，不进入 Phase 1，不改写正式 V1：

```text
formal SourceClaim: 545 -> 545
formal EvidenceAlignment for Prompt #40: 0 -> 0
PRIMARY_BENCHMARK: 0 -> 0
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 0 -> 0
channel_opportunity_count: 0 -> 0
citation_status: NO_EXECUTABLE_RECOMMENDATION -> NO_EXECUTABLE_RECOMMENDATION
formal_output_impact = NONE
```

Shadow 结果汇总：

```text
AnswerUnit = 216
grounded AnswerUnit = 216
AnswerDecisionBinding = 30
DIRECT_REASON = 18
SUPPORTING_REASON = 12
Shadow Evidence Result = 252
Shadow SourceClaim grounded = 222
SUPPORTS = 18
NO_SUPPORT = 234
CONTRADICTS = 0
recommendation_evidence_eligible = 18
```

按 Run 分布稳定：

```text
Run #238: SUPPORTS 3 / NO_SUPPORT 39
Run #239: SUPPORTS 3 / NO_SUPPORT 39
Run #240: SUPPORTS 3 / NO_SUPPORT 39
Run #253: SUPPORTS 3 / NO_SUPPORT 39
Run #254: SUPPORTS 3 / NO_SUPPORT 39
Run #255: SUPPORTS 3 / NO_SUPPORT 39
```

逐级链路示例 1：

```text
AnswerClaim:
小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题等功能，适合营销场景使用

AnswerUnit:
小码短链接自带点击统计

Binding:
小码短链接 / RECOMMEND / DIRECT_REASON / HIGH

Retrieved Passage:
SourceDocument #345 / doc345:b13
小码短链接自带数据统计功能，可以在“我的链接”页面查看每个链接的访问量、点击次数等数据。

Shadow SourceClaim:
小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据

Shadow EvidenceAlignment:
SUPPORTS / RECOMMENDATION_EVIDENCE
```

逐级链路示例 2：

```text
AnswerClaim:
小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题等功能，适合营销场景使用

AnswerUnit:
小码短链接自带自定义分享标题

Binding:
小码短链接 / RECOMMEND / SUPPORTING_REASON / MEDIUM

Retrieved Passage:
SourceDocument #345 / doc345:b14
可以利用小码短链接的自定义分享功能，设置一个吸引人的标题和描述。

Shadow SourceClaim:
小码短链接提供自定义分享功能
小码短链接的自定义分享功能支持设置标题和描述

Shadow EvidenceAlignment:
SUPPORTS / RECOMMENDATION_SUPPORTING_EVIDENCE
```

本次实跑证明：

```text
#40 原 V1 断点确实是 RecommendationEvent.reasons_json 为空导致的桥接缺口；
AnswerClaim -> AnswerUnit -> Binding 可以提供可用的答案侧理由；
Shadow Evidence Chain 可以在不污染正式 V1 的前提下完成真实来源支撑判断；
SourceDocument #345 的知乎正文对“点击统计”和“自定义分享标题”形成了 V1.1 Shadow SUPPORTS。
```

当前仍不做正式 Benchmark 升级。是否进入 Phase 1，需要单独评审和明确批准。

### 10.6.3 Phase 1 小范围正式输入切换

在 `ShadowRun #7` 完成 scope 校准并通过反向 Case 后，Phase 1 获得小范围
批准。批准内容不是全量上线，而是：

```text
正式 Passage Retrieval / EvidenceAlignment
在显式开关开启时
消费 AnswerUnit + AnswerDecisionBinding
作为答案侧推荐理由输入
```

边界保持不变：

```text
不直接消费 AnswerEvidenceShadowResult
不把 Shadow SUPPORTS 直接升级为正式 Benchmark
不改变 Product Truth / Benchmark / Gap / Action / Strategy / Experiment 规则
不开开关时继续使用 RecommendationEvent.reasons_json 路径
```

正式 `EvidenceAlignment` 若来自 Phase 1 输入，必须记录：

```text
reason_source = ANSWER_DECISION_BINDING
formal_input_version = citation_decision_v1_1_formal_input.v1
answer_unit_id
decision_binding_id
```

这样后续可以审计：

```text
正式 V1 原始 reason 产物
vs
Phase 1 answer-binding-derived reason 产物
```

### 10.6.4 Prompt #40 Phase 1 小范围实跑结果

本地已对 Prompt `#40` / Evidence Package `#15` 执行 Phase 1 小范围正式
输入切换验证：

```text
run_ids = [238, 239, 240, 253, 254, 255]
shadow_run_id = 7
formal_input_enabled = true
formal_input_source = AnswerUnit + AnswerDecisionBinding
```

检索层结果：

```text
legacy_event_reasons = 0
answer_binding_candidates = 30
answer_binding_reasons = 5
unique_reasons = 5
passages_retrieved = 25
```

正式 SourceClaim 结果：

```text
unique_passages = 13
claims_created = 32
validation_failed = 0
empty_results = 2
DeepSeek ConnectError passages = 4
```

关键修正：

```text
SourceDocument #345 有正文但没有 SourceQuality 行；
正式检索层原先只看 SourceQuality.CONTENT_VALID，
导致 #345 没进入候选池。

Phase 1 已改为：
SourceQuality 优先
derive_content_status 兜底
```

正式 EvidenceAlignment 小范围结果：

```text
doc_id_filter = [345]
alignments_created = 50
competitor_context / RELATED = 60
SUPPORTS = 6
NONE = 5
RELATED = 99
errors = []
```

正式 SUPPORTS 均来自：

```text
reason_source = ANSWER_DECISION_BINDING
formal_input_version = citation_decision_v1_1_formal_input.v1
```

Prompt `#40` 的 Citation Decision V1 当前自然推进为：

```text
status = READY_FOR_HUMAN_CONFIRM
primary_benchmark_count = 1
secondary_benchmark_count = 0
recommended_action_count = 1
channel_opportunity_count = 1
```

这不是因为引用显著性、标题同名或 Shadow SUPPORTS 被直接升级，而是因为
SourceDocument `#345` 的正式 `EvidenceAlignment.relation = SUPPORTS`
已经形成。当前仍保持：

```text
Citation Prominence 不能决定 Benchmark
标题同名不能直接决定 SUPPORTS
LEGACY_RELATED 不参与 V1 支撑语义
Shadow Evidence Result 不被正式链直接消费
```

### 10.6.3 ShadowRun #6 Binding Precision Gate

`ShadowRun #6` 的 30 条 `AnswerDecisionBinding` 已导出为独立人工审计表：

```text
docs/PROMPT_40_SHADOW_RUN_6_BINDING_REVIEW.md
```

当前机器矩阵显示：

```text
小码短链接支持长链接快速缩短: Binding 6/6, SUPPORTS 0/6
小码短链接自带点击统计: Binding 6/6, SUPPORTS 6/6
小码短链接自带二维码生成: Binding 6/6, SUPPORTS 0/6
小码短链接自带自定义分享标题: Binding 6/6, SUPPORTS 6/6
小码短链接适合营销场景使用: Binding 6/6, SUPPORTS 0/6
```

这说明 Phase 0 正向链路已跑通。该 Gate 已被 `ShadowRun #7`
的 Recommendation Explanation Scope 校准替代，不再要求逐条人工审计
30 条同结构 Binding。

当前人工只需要做代表 Run sanity check：

```text
确认代表 Run 的原答案结构确实是：
小码短链接：
A / B / C / D / E
```

且没有出现：

```text
其他品牌内容串绑
操作步骤被当成正向推荐理由
话题切换后继续绑定
限制/弱项被当成正向 SUPPORTING_REASON
```

真正的过绑定风险交给 Procedure / Brand-directed / Other-brand /
Implicit / Limitation 自动回归 Case 防守。

### 10.6.4 ShadowRun #7 Recommendation Explanation Scope 校准

`ShadowRun #6` 证明正向链路跑通后，又暴露出 `DIRECT_REASON` 使用过宽的问题。当前已按 Recommendation Explanation Scope 重新校准并执行 `ShadowRun #7`：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
source_run_ids = [238, 239, 240, 253, 254, 255]
entity_filter = 小码短链接
shadow_run_id = 7
status = completed
```

本轮语义原则：

```text
推荐语境下，被推荐品牌说明作用域内的能力、优势、价格、效果、适用场景等，
默认视为推荐支撑主张，不要求答案显式出现“因为/所以”。

但默认 Binding 不等于无条件 Binding；
必须排除操作步骤、普通背景事实、其他品牌内容、限制性内容，
以及已经脱离推荐说明作用域的主张。
```

`DIRECT_REASON` 只保留给明确选择条件、明确因果、明确比较依据或需求匹配。普通推荐说明作用域内的能力描述默认是：

```text
SUPPORTING_REASON
```

`ShadowRun #7` 汇总：

```text
AnswerUnit = 216
grounded AnswerUnit = 216
AnswerDecisionBinding = 30
DIRECT_REASON = 0
SUPPORTING_REASON = 30
Shadow Evidence Result = 252
Shadow SourceClaim grounded = 222
SUPPORTS = 18
NO_SUPPORT = 234
CONTRADICTS = 0
recommendation_evidence_eligible = 18
```

与 `ShadowRun #6` 对比：

```text
Binding 总数：30 -> 30
DIRECT_REASON：18 -> 0
SUPPORTING_REASON：12 -> 30
SUPPORTS：18 -> 18
recommendation_evidence_eligible：18 -> 18
formal_output_impact：NONE -> NONE
```

能力单元稳定矩阵：

| AnswerUnit | Binding 覆盖 | SUPPORTS 覆盖 | Evidence Role |
| --- | ---: | ---: | --- |
| 小码短链接支持长链接快速缩短 | 6/6 | 0/6 | - |
| 小码短链接自带二维码生成 | 6/6 | 0/6 | - |
| 小码短链接自带点击统计 | 6/6 | 6/6 | RECOMMENDATION_SUPPORTING_EVIDENCE x6 |
| 小码短链接自带自定义分享标题 | 6/6 | 6/6 | RECOMMENDATION_SUPPORTING_EVIDENCE x12 |
| 小码短链接适合营销场景使用 | 6/6 | 0/6 | - |

正式 V1 仍保持零污染：

```text
formal SourceClaim: 545 -> 545
formal EvidenceAlignment for Prompt #40: 0 -> 0
PRIMARY_BENCHMARK: 0 -> 0
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 0 -> 0
channel_opportunity_count: 0 -> 0
citation_status: NO_EXECUTABLE_RECOMMENDATION -> NO_EXECUTABLE_RECOMMENDATION
formal_output_impact = NONE
```

`ShadowRun #7` 的 30 条 Binding 已整理为轻量 sanity check 文档：

```text
docs/PROMPT_40_SHADOW_RUN_7_BINDING_REVIEW.md
```

反向 Case 当前通过：

```text
Procedure Case
Brand-directed Neutral Case
Other-brand Scope Case
Implicit Reason Case
Limitation Case
```

验证命令：

```bash
.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py
```

结果：

```text
11 passed
```

当前 Phase 0 可收口，但仍不自动进入 Phase 1：

```text
PHASE_0_READY_FOR_REVIEW_CLOSE = true
READY_FOR_PRODUCTION_SWITCH = false
```

Phase 1 小范围切换需要单独批准。

### 10.7 前端应如何解释

当前前端不能只显示“0 个核心对标”，还应该解释为什么。

建议对这类来源展示：

```text
引用显著性：高
正文状态：正文可用
答案线索：答案推荐了同名实体
当前对齐：未形成 V1 SUPPORTS 对齐
未进对标原因：推荐理由为空或尚未完成来源主张对齐
下一步：补齐/重跑推荐理由对齐
```

这样操作者能理解：

```text
这篇不是没价值
也不是已经能作为 Benchmark
而是处于“有线索，待语义对齐”的中间态
```

### 10.8 验收标准

修复后，Prompt #40 应满足：

```text
小码短链接 RecommendationEvent 至少有一个实体级 reason
小码知乎 SourceDocument 能进入 reason-driven retrieval 候选
SourceClaimJudge 在正文中抽到可 grounding 的来源主张，或明确抽不到
EvidenceAlignmentJudge 给出 SUPPORTS / NO_SUPPORT / CONTRADICTS
```

在 Phase 0 中，上述 `SourceClaimJudge` / `EvidenceAlignmentJudge` 结果必须是 Shadow 产物，不能污染正式 V1 输出。

如果来源正文确实支持答案推荐理由：

```text
decision_support_level != NONE
benchmark_tier = PRIMARY_BENCHMARK 或 SECONDARY_BENCHMARK
```

该判断只适用于 Phase 1 之后的正式接入。Phase 0 即使 Shadow 判断支持，也只能记录：

```text
shadow_recommendation_evidence_eligible = true
```

不能直接改写正式 `decision_support_level` 或 `benchmark_tier`。

如果正文并不支持：

```text
benchmark_tier 继续为 REFERENCE_ONLY
但原因必须显示为“同实体线索未形成来源支撑”
```

无论哪种结果，都必须继续保持：

```text
Citation Prominence 不能决定 Benchmark
标题同名不能直接决定 SUPPORTS
LEGACY_RELATED 不能参与 V1 支撑语义
Product Truth 只确认目标品牌自己的真实能力
```

### 10.9 给后续开发者的核心提醒

这次 #40 暴露的是一个桥接缺口：

```text
AnswerClaim 中已有的能力描述
没有回流到 RecommendationEvent.reasons_json
```

不是 Citation Decision V1 整体规则错了。

正确修复是：

```text
补推荐理由抽取 / fallback
补同实体引用候选提示
再走现有 V1 证据对齐链
```

不要回退到旧逻辑：

```text
引用排名
-> 平台/标题相似
-> 直接推荐动作
```

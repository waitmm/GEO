# GEO Platform 当前状态事实快照（FORENSIC AUDIT）

**日期**: 2026-08-18  
**分支**: `main` @ `4a5da94`  
**性质**: 事实盘点，不含修复、不含重构、不含产品提案。  
**状态标注**: COMPLETE / PARTIAL / PLACEHOLDER / NOT_IMPLEMENTED / LEGACY / UNUSED

---

# 1. Executive Summary

GEO Platform 当前是一个**软件闭环完备、数据链部分跑通、真实实验从未执行**的阶段产物。

一句话概括：

> 系统已经能够采集真实文心回答、解析引用与检索候选、生成推荐市场快照、产出带决策空间信号的策略候选；但整条链路中没有任何一个真实 GEO 干预被发布、复测并得出结论。

核心事实：

- 唯一实验 Experiment #13 状态为 `READY_FOR_MANUAL_RELEASE` + `release_blocked=True`，从未发布。
- 34 个 Strategy Candidate 中 12 个 VALIDATION_FAILED，历史 9 个 BACKFILLED_UNVERIFIED，最新可审核的是 #31/#32/#33/#34（PENDING_REVIEW + VALIDATED）。
- 147 条 Recommendation Claims **全部 PENDING**，0 条人工审核。
- 推荐类型只有 `CANDIDATE`(105) 和 `MENTION_ONLY`(42) 两类——**没有任何 POSITIVE_RECOMMENDATION / TOP_RECOMMENDATION**。
- 八木屋二维码项目（Project #2）**没有任何** recommendation snapshot、strategy、experiment。
- Passage Alignment 136 条中仅 16 条 L1 精确匹配（AI 原样引用 B 站视频标题），120 条 UNRESOLVED。
- 多平台适配器只有文心真实实现；qwen/kimi/deepseek 是 `PlaceholderAdapter`（继承 MockAdapter）。

---

# 2. Current End-to-End Workflow

### 设计目标（来自 PRODUCT_FUNCTION_SPEC.md）

```
采集真实 AI 回答 → 解析回答/引用/检索候选 → 生成确定性证据包
→ 诊断品牌选择空间和推荐差距 → 生成待审核策略候选 → 人工审核
→ effective_payload → 创建动作和实验 → 人工确认发布 → 固定复采
→ 对比指标 → 人工记录效果结论
```

### 当前真实实现（逐段核实）

| 环节 | 真实状态 |
|------|---------|
| 采集真实 AI 回答 | ✅ COMPLETE（文心浏览器采集，151 runs） |
| 解析回答/引用/检索候选 | ✅ COMPLETE（4092 citations / 3113 candidates / 890 artifacts） |
| 生成确定性证据包 | ✅ COMPLETE（13 个 Evidence Packages） |
| 诊断品牌选择空间和推荐差距 | 🟡 PARTIAL（Recommendation Intelligence V1 已落地，147 claims 全未人工审核） |
| 生成待审核策略候选 | ✅ COMPLETE（34 个 candidates，最新 V9 含 decision_space） |
| 人工审核 | 🟡 PARTIAL（API/UI 齐全，实际 0 条核心审核完成） |
| effective_payload 闸门 | ✅ COMPLETE（fail-closed 逻辑 + 测试覆盖） |
| 创建动作和实验 | 🟡 PARTIAL（Action #13 + Experiment #13 存在，来自旧链路） |
| 人工确认发布 | ❌ NOT_IMPLEMENTED（release_blocked=True，从未发布） |
| 固定复采 | 🟡 PARTIAL（queue-retest API 存在，从未对 #13 执行） |
| 对比指标 | 🟡 PARTIAL（analyze API 存在，无真实 post-release 数据） |
| 人工记录效果结论 | ❌ NOT_IMPLEMENTED（0 条 release_audit_records） |

---

# 3. System Architecture

```
backend/
├── app/
│   ├── adapters/                 # 平台适配器（COMPLETE: wenxin; PLACEHOLDER: qwen/kimi/deepseek）
│   │   ├── base.py / mock.py / wenxin.py / registry.py
│   ├── api/v0.py                 # 基础 CRUD（COMPLETE）
│   ├── core/                     # config + database（COMPLETE）
│   ├── models/db.py              # 全部 ORM 模型（44 张表）
│   ├── modules/
│   │   ├── monitoring/           # 文心采集（COMPLETE）
│   │   │   ├── api.py            # 任务/队列/run/artifact/retry
│   │   │   ├── executor.py       # Playwright 执行器
│   │   │   └── collectors/wenxin/ # collector + reference_parser + selectors + url_normalizer
│   │   ├── analytics/            # 验证看板（COMPLETE）
│   │   └── optimization/         # ★ GEO 主链核心
│   │       ├── api.py            # 全部优化 API（70+ 端点）
│   │       ├── service.py        # 6561 行：Evidence/Strategy/Experiment
│   │       ├── recommendation.py # 4619 行：推荐市场情报 V1
│   │       ├── ranking.py        # Citation Ranking V0（冻结）
│   │       ├── passage_service.py    # Golden Case 流水线
│   │       ├── primary_content.py    # Primary Content Extraction V1
│   │       └── claim_extraction.py   # Atomic Claim Extraction
│   └── services/                 # extraction.py(58行) + monitoring.py + serialization.py
├── alembic/versions/             # 5 个 migration
├── tests/                        # 7 个测试文件，123 tests
└── scripts/                      # 28 个运维脚本
frontend/
├── src/App.tsx                   # 3264 行单文件 SPA，7 个页面
├── src/api/client.ts
└── src/types.ts
docs/                             # 36 个文档
```

**核心类 / Service 摘要**：

| 模块 | 关键函数 | 职责 | 状态 |
|------|---------|------|------|
| service.py | `create_evidence_package` | B1 证据包生成 | COMPLETE |
| service.py | `EvidenceDrivenStrategyProvider.generate_from_context` | V2/V9 策略生成 | COMPLETE |
| service.py | `_extract_answer_strategy_signals` | 答案信号提取（含 decision_space） | COMPLETE |
| recommendation.py | `run_recommendation_analysis` | 推荐市场快照生成 | COMPLETE |
| recommendation.py | `infer_prompt_decision_mode` | 决策模式规则推断 | COMPLETE |
| recommendation.py | `_assess_prompt_run_eligibility` | Run 资格判断 | COMPLETE |
| ranking.py | `run_citation_evidence_ranking_v0` | 引用证据排名 | COMPLETE（冻结） |
| passage_service.py | `run_golden_case_pipeline` | Golden Case 流水线 | PARTIAL |
| primary_content.py | `extract_from_html` | 正文抽取 | PARTIAL |

---

# 4. Database Model

44 张表。GEO 主链相关表盘点：

### 采集层
| 表 | 行数 | 用途 | 状态 |
|----|------|------|------|
| projects | 3 | 项目 | COMPLETE |
| prompts | 18 | 用户问题 | COMPLETE |
| prompt_clusters | 6 | 问题组 | LEGACY（不参与分析） |
| monitoring_batches | 23 | 采集批次 | COMPLETE |
| browser_monitor_tasks | 26 | 采集任务 | COMPLETE |
| browser_monitor_runs | 151 | 单次采集 | COMPLETE |
| reference_sources | 4092 | AI 最终引用 | COMPLETE |
| retrieval_candidates | 3113 | 检索候选 | COMPLETE |
| run_artifacts | 890 | 证据文件 | COMPLETE |

### 证据层
| 表 | 行数 | 用途 | 状态 |
|----|------|------|------|
| optimization_evidence_packages | 13 | B1 证据包 | COMPLETE |
| source_documents | 203 | 引用页面正文 | PARTIAL（73 FETCH_FAILED） |
| answer_claims | 2736 | AI 回答句子切分 | LEGACY（语义是句子不是 Claim） |
| atomic_claims | 288 | 原子主张 | PARTIAL（仅 Prompt #16） |
| claim_extraction_runs | 1 | 提取运行版本 | PARTIAL |
| passage_alignments | 136 | Claim↔Passage 对齐 | PARTIAL（16 L1 + 120 UNRESOLVED） |

### 推荐市场层（Recommendation Intelligence V1）
| 表 | 行数 | 用途 | 状态 |
|----|------|------|------|
| recommendation_intelligence_snapshots | 16 | 诊断快照 | COMPLETE |
| recommendation_entities | 4 | 品牌/竞品实体 | COMPLETE |
| recommendation_claims | 147 | 推荐判断 | PARTIAL（0 人工审核，仅 CANDIDATE/MENTION_ONLY） |
| recommendation_reason_claims | 44 | 推荐理由 | PARTIAL（全 UNREVIEWED） |
| recommendation_evidence_links | 89 | 推荐↔引用链接 | PARTIAL |
| decision_evidence_adoptions | 77 | 证据归因 | PARTIAL（evidence_status=UNCERTAIN） |
| answer_semantic_facts | 592 | 答案语义事实 | COMPLETE |
| decision_selection_criteria | 7686 | 选择标准 | COMPLETE（行数异常大，疑为每 Run 重复展开） |
| brand_capability_claims | 111 | 品牌能力主张 | PARTIAL |
| decision_gap_diagnoses | 17 | 差距诊断 | COMPLETE（UNREVIEWED） |
| target_brand_capability_truths | 2 | 产品真值人工确认 | PARTIAL |

### 策略/实验层
| 表 | 行数 | 用途 | 状态 |
|----|------|------|------|
| optimization_strategy_candidates | 34 | 策略候选 | COMPLETE |
| optimization_issues | 9 | 问题 | LEGACY（旧链路） |
| optimization_actions | 1 | 动作 | PARTIAL（仅 #13） |
| optimization_experiments | 1 | 实验 | PARTIAL（未发布） |
| optimization_hypotheses | 1 | 假设 | PARTIAL |
| release_audit_records | 0 | 发布审计 | NOT_IMPLEMENTED（无数据） |
| page_snapshots | 3 | 页面快照 | PARTIAL |

**关键 JSON 字段**：几乎所有分析表都有 `_json` 后缀的复杂 payload 字段（如 recommendation_claims.human_payload_json、answer_semantic_facts.human_labels_json、optimization_strategy_candidates.structured_payload_json 等）。

**状态枚举冗余**：`optimization_strategy_candidates.review_status` 与 `generation_status` 与 `effective_validation_status` 三套状态并存，历史数据中存在语义重叠（VALIDATION_FAILED 同时出现在 review_status 和 effective_validation_status）。

---

# 5. Collection Capability

### 平台支持现状（真实代码核实）

| 平台 | 真实采集 | 实现 | 状态 |
|------|---------|------|------|
| 百度文心/千帆 | ✅ 是 | `WenxinAdapter`（Playwright 浏览器采集） | COMPLETE |
| Mock | ✅ 是 | `MockAdapter` | COMPLETE（测试用） |
| 通义千问 | ❌ 否 | `PlaceholderAdapter(MockAdapter)` | PLACEHOLDER |
| Kimi | ❌ 否 | `PlaceholderAdapter(MockAdapter)` | PLACEHOLDER |
| DeepSeek | ❌ 否 | `PlaceholderAdapter(MockAdapter)` | PLACEHOLDER |

### 采集链路（Prompt #19 案例）

```
创建 Prompt → 创建 MonitoringBatch → 创建 BrowserMonitorTask
→ WenxinWebCollector 启动 Chromium（复用 profile）
→ 提交问题 → 等待回答 → 抓 answer_text/answer_html
→ 解析四层引用计数（ui_declared/dom/parsed/resolved）
→ 抓 retrieval candidates（searchresult-1.json）
→ 保存 artifacts（page.html + network.jsonl + 截图 + result.json）
→ ReferenceSource/RetrievalCandidate 落库
```

- 代码位置：`monitoring/collectors/wenxin/collector.py`、`monitoring/executor.py`
- 失败状态：failed / partial_success / blocked（captcha 等）
- 重试：✅ 支持（`POST /api/monitoring/runs/{run_id}/retry`，retry_count 字段）
- 稳定性：151 runs 中 87 success + 35 partial + 4 failed + 其余排队/未知

---

# 6. Run Metadata & Sampling

`browser_monitor_runs` 字段逐项核实：

| 字段 | 状态 |
|------|------|
| platform | YES（列 `platform`） |
| model_name / model_version | **NO**（无此字段） |
| surface | NO |
| network_enabled | NO |
| login_state | NO |
| client_profile | PARTIAL（`profile_identifier`） |
| browser_profile | PARTIAL（`browser` + `browser_version`） |
| ip / geo | PARTIAL（`network_region`，默认 unknown） |
| started_at / finished_at | YES |
| session_id | NO |
| conversation_id | YES |
| prompt_text | YES（`original_query`/`page_query`/`retrieval_query`） |
| prompt_variant | NO |
| collector_version / parser_version | YES |
| analysis_version | NO |
| sampling_mode | YES（INDEPENDENT_SESSION 37 / CONTEXTUAL_SESSION 87 / UNKNOWN 27） |

---

# 7. Answer Understanding

### Decision Space（真实枚举，代码 `recommendation.py:259`）

决策模式推断为**规则关键词匹配**（非 LLM）：

```
COMPARISON / PRODUCT_SELECTION / TROUBLESHOOTING / HOW_TO / NAVIGATIONAL / INFORMATIONAL
```

`recommendation_expected = mode in {PRODUCT_SELECTION, COMPARISON}`

### AnswerSemanticFact（Run 级语义事实）

事实类型（真实 DB 数据，Prompt #16）：

| fact_type | True 值分布 |
|-----------|------------|
| has_choice_slot | 12/13 ✅ |
| has_brand_mention | 0/13 |
| has_explicit_recommendation | 0/13 |
| has_comparison | 0/13 |

判定方式：`RULE_DERIVED`（`answer_semantic_fact.v1_rule_zh`），非 LLM。

### 结论

- Decision Space: **COMPLETE**（规则版）
- 品牌决策空间五分类（NO_BRAND_DECISION_SPACE 等）: **PARTIAL**（有 gap_diagnosis 类型分类，但无正式五分类枚举落库）

---

# 8. Recommendation Market

### 当前能回答的问题

| 问题 | 状态 | 依据 |
|------|------|------|
| 某 Prompt 下有哪些品牌被推荐？ | PARTIAL | recommendation_claims 有 105 CANDIDATE，但无 POSITIVE_RECOMMENDATION 类型 |
| 每个品牌多少次进入候选？ | PARTIAL | CANDIDATE 有 position/rank 字段，但无聚合 UI |
| 多少次明确推荐？ | **NO** | 无 POSITIVE_RECOMMENDATION 数据（147 条中 0 条） |
| Top1 多少次？ | NO | 无 TOP_RECOMMENDATION 数据 |
| 推荐位置是什么？ | PARTIAL | `position` 字段存在，多数为 NULL/1 |
| 推荐理由是什么？ | PARTIAL | 44 条 reason_claims 全 UNREVIEWED，reason_type 多为 'OTHER' |
| 不同 Run 是否稳定？ | NO | 无稳定性聚合 |
| 不同平台是否不同？ | NO | 单平台（文心） |
| 八木屋为什么输给竞品？ | **NO** | Project #2 无任何 recommendation 数据 |

### has_explicit_recommendation 判定方式

真实实现为**规则关键词**（`answer_semantic_fact.v1_rule_zh`），非 LLM Speech Act。具体抽取代码在 `recommendation.py` 的 fact 提取段。

---

# 9. Citation & Retrieval

### Citation 字段（reference_sources 实际列）

`id, run_id, reference_index, display_title, matched_title, url, canonical_url, domain, platform_name, resolution_method, match_confidence, evidence_path, relevance_label, quality_label, is_official_domain, is_competitor_domain, created_at`

- Citation 与 Answer 绑定: ✅（run_id）
- Citation 与 Claim 绑定: 🟡 PARTIAL（recommendation_evidence_links + passage_alignments，仅少部分对齐）
- Citation 与 Brand 绑定: 🟡 PARTIAL（decision_evidence_adoptions 77 条，evidence_status 全 UNCERTAIN）
- Citation 回溯到推荐理由: 🟡 PARTIAL（recommendation_evidence_links 89 条）

### Retrieval Candidate

- 3113 条，URL 完整率 ~99%
- 与 Citation 的 URL 重叠率约 3%（已知结论）
- **系统没有把 Retrieval → Citation 当漏斗**：`_build_source_relations` 明确标注 role=DIAGNOSTIC_METADATA，join_rate 仅作诊断

---

# 10. Document & Primary Content

### 抓取器（passage_service.py）

| 方式 | 状态 |
|------|------|
| urllib（requests 风格） | COMPLETE（fallback） |
| Playwright 浏览器 | COMPLETE（主方案，networkidle + 20s 超时 + 滚动 + 重试） |
| 人工 HTML 粘贴 | COMPLETE（POST /golden-case/documents/manual） |
| 人工正文粘贴 | COMPLETE |
| 登录态复用 | NO |

### 站点抓取现状（真实数据）

| 站点 | 状态 |
|------|------|
| 百度系（mbd.baidu.com 等） | PARTIAL（有正文，300-1500 字） |
| 搜狐 | PARTIAL（部分成功 1404 字，部分超时） |
| B 站 | PARTIAL（标题页可抓 1029-1725 字，视频页反爬） |
| 商加加 shangjiajia.com | STABLE（2036 字） |
| 摩尔视界 molelink.cn | STABLE（1825 字） |
| 知乎 | FAILED（登录墙，117 字骨架） |
| 抖音 | FAILED（超时） |
| 微信公众号 | FAILED |
| 百家号 | PARTIAL |

source_documents 统计：122 SUCCESS + 6 PARTIAL + 73 FETCH_FAILED + 2 MANUAL_EMPTY。

### Primary Content Extraction（primary_content.py）

Pipeline：PageType → Region Locator → Dense Blocks → Multi Extractor（Trafilatura/Readability-like/DOM Heuristic）→ Overlap Scoring → Boundary Repair → Sanity Gate。

状态：**PARTIAL**。可运行，但 50000 字符截断上限意味着部分页面 Readability 过度抽取；无 Golden Set 评估。

---

# 11. Claim Analysis

### AnswerClaim（2736 条）

- **语义实际是 AnswerSentence**：按中文标点切句，不是原子主张
- 字段：raw_text / claim_type（单标签中文）/ citation_anchor / citation_ids_json / epistemic_status / provenance / review_status / human_labels_json
- 14 个 Prompt 已提取；0 条人工审核（全 PENDING）

### AtomicClaim（288 条，仅 Prompt #16）

- 字段完整：claim_types[] / speech_act / epistemic_status / polarity / is_negated / verification_priority / geo_importance / machine_claim_text / human_claim_text
- RuleBasedClaimExtractionProvider（连接词切分 + 规则分类）
- 版本化：ClaimExtractionRun（1 次运行）
- 人工审核 UI：✅（Golden Case 页面）
- 当前状态：288 条全 PENDING

### Source Claim 抽取

**NOT_IMPLEMENTED**。没有把引用正文拆成 Source Claim 的模块。

### Source → Answer 语义关联

**NO**。PassageAlignment 只有 L1 精确匹配（16 条），无法建立"知乎文章说 X → AI 回答改编为 Y"的语义关系。

---

# 12. Attribution & Evidence

当前 Attribution 真实链路：

```
RecommendationClaim → DecisionEvidenceAdoption → ReferenceSource
```

- evidence_status: `UNCERTAIN`（77 条全此值）
- support_strength: STRONG（0.8，规则输出）
- 方法: `RULE_URL_TITLE_TEXT_MATCH`（URL+标题+正文规则匹配，非语义）
- Source Platform: ✅（domain → DOMAIN_PLATFORM_MAP）
- Source Content 分析: ❌（无正文级 Claim）
- 推荐理由绑定 Source: 🟡 PARTIAL（89 条 links）
- 多对多: 🟡 模型支持（claim_id ↔ citation_id 独立表），实际数据未验证

---

# 13. Competitive Analysis

**八木屋 vs 草料**：**NOT_IMPLEMENTED**。

Project #2（八木屋）无 recommendation snapshots、无 strategies、无 evidence。5 个二维码 Prompt 各有 5 个 runs，但从未进入推荐市场分析。

逐项：

| 能力 | 状态 |
|------|------|
| Recommendation Share | NO |
| Candidate Share | NO（模型支持，无项目数据） |
| Top1 Share | NO |
| Recommendation Reasons | NO |
| Citation Sources | PARTIAL（reference_sources 有，无分析） |
| Source Claims | NO |
| 产品能力 Claim | PARTIAL（brand_capability_claims 111 条，项目 3） |
| Stable Advantages | NO |

---

# 14. Opportunity & Strategy

### Opportunity

**NOT_IMPLEMENTED**。系统没有 Opportunity 评分模型。最接近的概念是 `decision_gap_diagnoses`（17 条差距诊断），其诊断基于规则（gap_diagnosis.v1_rule_zh）：

真实样例：
```
CANDIDATE_GAP, HIGH, 0.72 置信
candidate_capture_rate = 0/39
"当前回答存在方案槽位，但「爱短链」没有稳定进入候选。"
```

### Strategy Provider

`EvidenceDrivenStrategyProvider`（service.py），当前版本 strategy_prompt.v2：

- 输入: EvidenceActionContext + answer_strategy_signals（含 decision_space）
- 输出: option_a 字典（35 字段）
- 严格区分 FACT/INFERENCE/ACTION: ✅（inferences 字段带 supporting_fact_ids）
- 最新策略 #31 实测: intervention_type=UNRESOLVED, target_platform=UNRESOLVED, baseline=0/13, decision_space={choice 12/13, brand 0/13, rec 0/13}
- 决策空间信号: ✅ 已接入（本日提交 4a5da94）

### 平台选择逻辑（真实）

当前策略**不决定平台**（UNRESOLVED）。平台推荐来自 `answer_strategy_signals` 的 `platform_recommendations` 列表，按信号等级排序（答案明确推荐上下文 > 选择理由上下文 > 答案引用上下文 > 普通引用分布），仅作展示不作决策。

---

# 15. Action System

真实 Action Type（intervention_type 枚举，前端 App.tsx）：

```
CONTENT_ASSET / CITATION_ASSET / PRODUCT_PROOF / BRAND_POSITIONING / ANSWER_PATTERN
CONTENT_CREATE / CONTENT_UPDATE / PLATFORM_PUBLISH / TECHNICAL_INDEXABILITY
STRUCTURED_DATA / ENTITY_CONSISTENCY / INTERNAL_INFORMATION_ARCHITECTURE
PLATFORM_AUTHORITY_BUILD / RECRAWL_OR_REFRESH / UNRESOLVED / NO_ACTION
```

实际数据：1 条 Action（#13，content_update → /card，来自旧链路）。

---

# 16. Experiment System

完整状态机（真实枚举）：

```
OptimizationIssue: candidate → confirmed → in_action → validating → resolved
OptimizationAction: PLANNED → READY_FOR_MANUAL_RELEASE → RELEASE_CONFIRMED
OptimizationExperiment: draft → baseline_locked → cooling → validating → analyzing → completed
```

真实数据：1 个 Experiment（#13），状态 `READY_FOR_MANUAL_RELEASE`，release_blocked=True（WAITING_FOR_INTERVENTION_SELECTION），released_at=NULL，无 release_audit_records。

---

# 17. Human Review & Golden Case

### 审核入口盘点

| 入口 | 页面 | API | 状态 | 实际使用 |
|------|------|-----|------|---------|
| Answer Claim Review | golden | POST /golden-case/claims/{id}/review | COMPLETE | 0 条审核 |
| Atomic Claim Review | golden | POST /golden-case/atomic-claims/{id}/review | COMPLETE | 0 条审核 |
| Recommendation Claim Review | recommendation | POST /recommendation-claims/{id}/review | COMPLETE | 0 条审核 |
| Recommendation Entity Review | recommendation | POST /recommendation-entities/{id}/review | COMPLETE | 部分（entities 有 HUMAN_REVIEWED） |
| Reason Claim Review | recommendation | POST /recommendation-reasons/{id}/review | COMPLETE | 0 条 |
| Evidence Adoption Review | recommendation | POST /decision-market/evidence-adoptions/{id}/review | COMPLETE | 0 条 |
| Gap Review | recommendation | POST /decision-market/gaps/{id}/review | COMPLETE | 0 条 |
| Product Truth | recommendation | POST /target-brand-capability-truths | COMPLETE | 2 条 |
| Strategy Review | optimization | POST /strategy-candidates/{id}/review | COMPLETE | 0 条接受 |

### Golden Case

- 无正式 Golden Set 标注体系（此前 Prompt 要求的 30-50 人工标注未建立）
- PassageAlignments 136 条（16 L1 + 120 L5_UNRESOLVED）
- Source Documents 203 条（人工补录功能存在）

---

# 18. Frontend Pages

| 页面 | Route | 用途 | 状态 |
|------|-------|------|------|
| 监测总览 | validation | 品牌表现/引用完整度/采集质量 | CORE |
| 决策诊断 | recommendation | 答案结构/引用资料/品牌状态/差距 | CORE |
| 最终策略 | optimization | 唯一执行出口（证据包/策略/实验草案） | CORE |
| 引用资料 | ranking | 来源结构/页面价值 | SUPPORTING |
| 证据标注 | golden | 回答主张审核/引用正文/对齐 | SUPPORTING |
| 采集记录 | runs | 采集状态/原答案/引用详情 | SUPPORTING |
| 问题配置 | config | 项目/Prompt/问题组/批次 | SUPPORTING |

App.tsx 为 3264 行单文件 SPA，无路由框架，页面间为状态切换。

---

# 19. API Map

分类摘要（完整 100+ 端点见附录）：

- **Collection**: 11 端点（monitoring）
- **Analysis**: 3 端点（analytics dashboard + daily reports）
- **Recommendation**: 20+ 端点（recommendation-analysis, landscape, claims, entities, reasons, criteria, facts, adoptions, gaps, truth）
- **Citation**: 1 端点（citation-ranking）
- **Document**: 6 端点（golden-case documents/acquire/refetch/manual/extract-primary）
- **Evidence**: 6 端点（evidence-packages CRUD）
- **Strategy**: 5 端点（generate/generate-v2/review/experiment-plan）
- **Experiment**: 12 端点（hypotheses/lock-baseline/release/retest/analyze/conclusion）
- **Review**: 9 端点（各实体 review）
- **Golden Case**: 14 端点

---

# 20. Real Production Data Statistics

| 实体 | 数量 |
|------|------|
| Projects | 3 |
| Prompts | 18 |
| Runs | 151（87 success/35 partial/4 failed/其余） |
| Citations | 4092 |
| RetrievalCandidates | 3113 |
| Documents | 203（122 SUCCESS/73 FAILED） |
| AnswerClaims | 2736 |
| AtomicClaims | 288 |
| RecommendationClaims | 147 |
| RecommendationReasons | 44 |
| EvidenceAdoptions | 77 |
| EvidencePackages | 13 |
| StrategyCandidates | 34 |
| Actions | 1 |
| Experiments | 1 |
| ReleaseAudits | 0 |
| Outcomes | 0 |

---

# 21. Full Real Case Walkthrough — Prompt #19「抖音跳转链接」

```
Prompt #19「抖音跳转链接」✅
↓
40 runs（173-184 为正式基线 12 runs，另有旧 135-146）✅
↓
Answer: 542 字符固定答案（"抖音跳转链接涵盖生成制作和跨端跳转使用两大核心场景…"）✅
↓
Brand Analysis: brand_mentioned=0/12，爱短链零提及 ✅
↓
Recommendation Analysis: Snapshot #1-5 存在；147 claims 全 PENDING；仅 CANDIDATE/MENTION_ONLY，无 POSITIVE_RECOMMENDATION ✅/PARTIAL
↓
Gap: CANDIDATE_GAP（0/39 candidate_capture_rate，置信 0.72）✅
↓
Citation: 31/run，4092 总 ✅
↓
Retrieval: 30-32/run ✅
↓
Document: 大部分 FAILED（知乎/抖音反爬），部分成功（商加加 2036 字等）PARTIAL
↓
Primary Content: 122 docs 抽取成功 PARTIAL
↓
Claim: AnswerClaim 已提取；AtomicClaim 仅 Prompt #16，未覆盖 #19 STOP
↓
Evidence: 77 adoptions 全 UNCERTAIN STOP
↓
Strategy: #1-#30 历史；#31 为最新 PENDING_REVIEW（decision_space 接入后需重新生成）PARTIAL
↓
Hypothesis/Action/Experiment: Experiment #13 blocked STOP
↓
Outcome: 无 STOP
```

**链路断点**：#19 的 Atomic Claim 未提取；所有推荐判断未人工审核；实验从未发布。

---

# 22. QR Code Project Case（八木屋，Project #2）

**结论：STOP at Collection。**

- 5 个二维码 Prompt（#34-38），各 5 runs（25 runs 总）
- **零** recommendation snapshots、零 strategies、零 experiments
- 系统从未对八木屋做过任何推荐市场分析
- 无法回答"AI 推荐了哪些品牌、八木屋在哪、草料在哪"——该层数据不存在

---

# 23. Known Limitations（可证实的）

1. **多平台是 PLACEHOLDER**：qwen/kimi/deepseek 适配器继承 MockAdapter，无法真实采集。
2. **73 个引用 URL 抓取失败**：知乎/抖音/B站反爬。
3. **Candidate↔Citation URL 重叠约 3%**：负样本不可用，无法做 Cited vs Not-cited 对比。
4. **147 条推荐判断 0 审核**：Recommendation Market 数据全 UNREVIEWED。
5. **无 POSITIVE_RECOMMENDATION 类型数据**：当前推荐判断只有 CANDIDATE 和 MENTION_ONLY。
6. **推荐稳定性无法计算**：无跨 Run 稳定性聚合。
7. **Experiment #13 从未发布**：release_audit_records = 0。
8. **八木屋项目无分析数据**：全链路未启动。
9. **decision_selection_criteria 7686 行**：疑似每 Run 重复展开，可能有数据冗余。
10. **无 Control Prompt 机制**：实验不支持 Treatment/Control 对比。

---

# 24. Fake-Complete / Partial Capabilities

| 现象 | 证据 | 真实状态 |
|------|------|---------|
| Recommendation Market"已完成" | 147 claims 全 PENDING，无 POSITIVE_RECOMMENDATION | 表+API+页面齐全，数据链未人工闭环 |
| Evidence Attribution"已实现" | 77 adoptions 全 evidence_status=UNCERTAIN | 只有 URL+标题规则匹配，无语义证据 |
| "Answer Claim"系统 | 2736 条按标点切句 | 语义是 Sentence 不是 Claim |
| Experiment 闭环"已就绪" | Experiment #13 blocked，0 release audits | 状态机存在，从未真实跑通 |
| 多平台"已支持" | qwen/kimi/deepseek 是 PlaceholderAdapter | 只有文心真实 |
| Passage Alignment"已建立" | 136 条中 120 条 UNRESOLVED | 只有 16 条 L1 标题照抄匹配 |
| Gap Diagnosis"已完成" | 17 条全 UNREVIEWED | 规则生成，未人工确认 |
| "推荐理由"分析 | 44 条 reason_type='OTHER' | 未真正分类 |

---

# 25. Current Documentation

| 文档 | 状态 |
|------|------|
| PRODUCT_FUNCTION_SPEC.md | CURRENT |
| PRODUCT_CAPABILITY_MAP.md | CURRENT |
| HANDOFF_2026-08-12.md | CURRENT |
| CITATION_EVIDENCE_RANKING_V0.md | CURRENT（冻结 spec） |
| recommendation-market.md / citation-context.md / gap-diagnosis.md / product-truth.md / recommendation-reason.md / answer-semantic-analysis.md | CURRENT（V1 模块文档） |
| 00-11 系列（PROJECT_BRIEF 等） | PARTIALLY_OUTDATED |
| CURRENT_IMPLEMENTATION_AUDIT.md | PARTIALLY_OUTDATED |
| GEO_WENXIN_MONITORING_MODULE_SPEC.md | PARTIALLY_OUTDATED |

---

# 26. Appendix: Important Code Paths

| 能力 | 路径 |
|------|------|
| 策略生成 V9 | backend/app/modules/optimization/service.py:6083+（EvidenceDrivenStrategyProvider） |
| 答案信号提取 | service.py:5564 `_extract_answer_strategy_signals` |
| 决策空间判定 | service.py:5712+（decision_space 构建） |
| 推荐市场分析 | backend/app/modules/optimization/recommendation.py:434 `run_recommendation_analysis` |
| 决策模式推断 | recommendation.py:259 `infer_prompt_decision_mode` |
| 引用排名 | backend/app/modules/optimization/ranking.py |
| 正文抽取 | backend/app/modules/optimization/primary_content.py |
| Golden Case 流水线 | backend/app/modules/optimization/passage_service.py |
| 原子主张 | backend/app/modules/optimization/claim_extraction.py |
| 文心采集 | backend/app/modules/monitoring/collectors/wenxin/collector.py |
| 平台适配器 | backend/app/adapters/registry.py |
| 前端 SPA | frontend/src/App.tsx（3264 行，7 页面） |

---

# 能力矩阵

| 能力 | 状态 | 实现位置 | 有真实数据 | 当前可靠度 | 说明 |
|------|------|---------|-----------|-----------|------|
| Prompt Management | COMPLETE | api/v0.py | ✅ | HIGH | 18 prompts |
| Independent Session Sampling | COMPLETE | monitoring executor | ✅ | MEDIUM | 37/151 runs 独立 |
| Multi-platform Collection | PLACEHOLDER | adapters/registry.py | ❌ | LOW | 仅文心真实 |
| Answer Capture | COMPLETE | wenxin collector | ✅ | HIGH | 151 runs |
| Citation Capture | COMPLETE | reference_parser | ✅ | HIGH | 4092 条 |
| Retrieval Candidate Capture | COMPLETE | wenxin collector | ✅ | HIGH | 3113 条 |
| Decision Space | COMPLETE | recommendation.py:259 | ✅ | MEDIUM | 规则关键词 |
| Brand Mention | COMPLETE | brand_mentions 表 | ✅ | HIGH | 149 条 |
| Brand Candidate | PARTIAL | recommendation_claims | ✅ | MEDIUM | 105 CANDIDATE 未审核 |
| Explicit Recommendation | PARTIAL | answer_semantic_facts | ✅ | MEDIUM | 规则判定，0/13 无正样本 |
| Recommendation Strength | PARTIAL | recommendation_claims.recommendation_strength | ✅ | LOW | 字段存在，多为 UNKNOWN |
| Recommendation Position | PARTIAL | recommendation_claims.position | ✅ | LOW | 多为 NULL |
| Top1 | NOT_IMPLEMENTED | — | ❌ | — | 无 TOP_RECOMMENDATION |
| Recommendation Stability | NOT_IMPLEMENTED | — | ❌ | — | 无跨 Run 聚合 |
| Competitor Comparison | NOT_IMPLEMENTED | — | ❌ | — | Project #2 零分析 |
| Citation Platform Attribution | COMPLETE | DOMAIN_PLATFORM_MAP | ✅ | HIGH | domain 推断 |
| Citation Content Capture | PARTIAL | passage_service.fetch | ✅ | MEDIUM | 122/203 成功 |
| Primary Content Extraction | PARTIAL | primary_content.py | ✅ | LOW | 无 Golden Set 验证 |
| Answer Claim Extraction | PARTIAL | claim_extraction.py | ✅ | MEDIUM | 仅 #16 有 Atomic |
| Source Claim Extraction | NOT_IMPLEMENTED | — | ❌ | — | 引用正文不拆 Claim |
| Source→Answer Semantic Link | NOT_IMPLEMENTED | — | ❌ | — | 仅 L1 字面匹配 |
| Recommendation Reason | PARTIAL | recommendation_reason_claims | ✅ | LOW | 44 条全 OTHER/UNREVIEWED |
| Reason→Evidence Link | PARTIAL | decision_evidence_adoptions | ✅ | LOW | 77 条全 UNCERTAIN |
| Evidence Ranking | COMPLETE | ranking.py | ✅ | MEDIUM | scoring.v0 冻结 |
| Recommendation Gap | PARTIAL | decision_gap_diagnoses | ✅ | MEDIUM | 规则生成未审核 |
| Evidence Gap | NOT_IMPLEMENTED | — | ❌ | — | |
| Platform Opportunity | NOT_IMPLEMENTED | — | ❌ | — | |
| Strategy Generation | COMPLETE | service.py V9 | ✅ | MEDIUM | decision_space 已接入 |
| FACT→INFERENCE→ACTION | COMPLETE | service.py | ✅ | MEDIUM | 结构化分层 |
| Action Generation | PARTIAL | optimization_actions | ✅ | LOW | 仅 1 条历史 |
| Human Review | PARTIAL | 9 个 review API | ✅ | LOW | 0 核心审核完成 |
| Experiment | PARTIAL | optimization_experiments | ✅ | LOW | #13 blocked 未发布 |
| Control Prompt | NOT_IMPLEMENTED | — | ❌ | — | |
| Post-treatment Recapture | NOT_IMPLEMENTED | — | ❌ | — | queue-retest 有 API 无执行 |
| Recommendation Lift | NOT_IMPLEMENTED | — | ❌ | — | |
| Statistical Confidence | NOT_IMPLEMENTED | — | ❌ | — | 只有裸百分比 |
| Business Outcome | NOT_IMPLEMENTED | — | ❌ | — | 0 outcomes |

---

# 结论

## 当前系统最强的 5 项能力（有代码/数据依据）

1. **文心真实采集闭环**：151 次真实浏览器采集，四层引用解析，890 个证据文件，retry 机制。
2. **Evidence Package 确定性生成**：13 个版本化证据包，hash 去重，b1.v4/metric.v3 schema。
3. **推荐市场规则抽取 V1**：592 条语义事实 + 147 条推荐判断 + 17 条差距诊断，全链路有 schema/API/前端。
4. **策略执行闸门**：effective_payload fail-closed + 决策空间信号（值不值得做）+ 123 个自动化测试。
5. **Citation Ranking V0**：冻结的 scoring.v0，因子分解可追溯。

## 当前系统最明显的 10 个断点（有代码/数据依据）

1. 多平台适配器 3/5 是 Placeholder。
2. 推荐判断 147 条 0 人工审核，且无正推荐类型数据。
3. 八木屋项目全链路零分析数据。
4. Experiment #13 从未发布，release_audit_records=0。
5. Source Claim 抽取不存在，Source→Answer 语义链接无实现。
6. 73 个引用 URL 抓取失败（反爬）。
7. 引用正文抽取无 Golden Set 评估，质量未知。
8. 无 Control/稳定性/置信度统计。
9. Atomic Claim 只覆盖 Prompt #16，未覆盖核心 Prompt #19。
10. decision_selection_criteria 7686 行疑似数据冗余。

## 当前系统真正已经跑通到哪一层

**RECOMMENDATION_INTELLIGENCE_READY**（规则版）

理由：
- COLLECTION_READY ✅（真实采集数据充足）
- ANALYSIS_READY ✅（证据包/排名/推荐市场快照全部有真实数据）
- RECOMMENDATION_INTELLIGENCE_READY ✅（推荐判断/差距诊断/决策空间信号全部落地且有真实数据，虽然人工审核为 0）
- EVIDENCE_INTELLIGENCE_READY ❌（Source Claim 抽取和语义对齐缺失，证据层停在上一步）
- STRATEGY_READY ❌（策略从未被人工接受并转化为执行）
- EXPERIMENT_READY ❌（唯一实验 blocked）
- REAL_GEO_CLOSED_LOOP_READY ❌

---

# 附录 B：10 个真实 JSON 样例（脱敏）

## 1. Prompt（#19）

```json
{
  "id": 19, "project_id": 3, "title": "抖音跳转链接",
  "prompt_text": "抖音跳转链接", "prompt_group": "抖音功能",
  "intent_type": "supplier_recommendation", "importance": 3,
  "sample_count": 3, "enabled": 1
}
```

## 2. Run（#173）

```json
{
  "id": 173, "task_id": 42, "project_id": 3, "prompt_id": 19,
  "platform": "wenxin", "adapter": "wenxin_web_audit",
  "collection_mode": "single_continuous", "run_sequence": 1, "sample_index": 1,
  "status": "success", "original_query": "抖音跳转链接",
  "answer_char_count": 542, "expected_reference_count": 31,
  "resolved_reference_count": 31, "reference_complete": 1,
  "brand_mentioned": 0, "brand_mention_count": 0, "brand_recommendation_level": 0,
  "conversation_id": "562c64bc-…", "sampling_mode": "INDEPENDENT_SESSION",
  "collector_version": "wenxin-web-v1", "parser_version": "reference-parser-v1.8c-compatible"
}
```

## 3. Answer（#173 节选）

```
"抖音跳转链接涵盖生成制作和跨端跳转使用两大核心场景，以下是实用操作指南：
一、普通分享链接生成
打开抖音找到目标视频，点击右侧分享箭头
选择「复制链接」，即可生成可分享的抖音跳转短链，格式多为v.douyin.com/xxxx
二、合规跳转链接制作（引流/外链场景）
抖音跳转微信：可通过商加加外链等第三方工具…
（共 542 字，brand_mentioned=0）
```

## 4. Citation

```json
{
  "id": 2842, "run_id": 173, "reference_index": 1,
  "display_title": "抖音评论区里如何加进入橱窗的跳转链接?…#教程-福宝宝111111",
  "url": "http://bilibili.com/video/BV1mCxYzpEsN",
  "canonical_url": "http://bilibili.com/video/BV1mCxYzpEsN",
  "domain": "bilibili.com", "platform_name": "文心助手",
  "resolution_method": "dom-direct-url", "match_confidence": 1.0,
  "is_official_domain": 0
}
```

## 5. RetrievalCandidate

```json
{
  "id": 1524, "run_id": 173, "rank": 1, "title": "抖音链接跳转",
  "url": "https://www.aifabu.com/details/42089",
  "canonical_url": "https://aifabu.com/details/42089",
  "domain": "aifabu.com",
  "snippet": "遵守平台规则…抖音链接跳转功能是一个强大的营销和引流工具，企业和个人…"
}
```
（注：候选 #1 是爱短链官网页面 aifabu.com，但未进入最终引用。）

## 6. AnswerClaim

```json
{
  "id": 406, "run_id": 176, "claim_index": 1,
  "raw_text": "抖音跳转链接涵盖生成制作和跨端跳转使用两大核心场景，以下是实用操作指南：",
  "claim_type": "操作步骤", "citation_anchor": null,
  "epistemic_status": "FACT", "provenance": "RULE_DERIVED",
  "review_status": "PENDING"
}
```

## 7. SourceDocument（截断）

```json
{
  "id": 90, "url": "http://bilibili.com/video/BV1mCxYzpEsN",
  "domain": "bilibili.com", "source_type": "CITED",
  "fetch_status": "SUCCESS",
  "title": "抖音评论区里如何加进入橱窗的跳转链接？…_哔哩哔哩_bilibili",
  "clean_text": "\n抖音评论区里如何加进入橱窗的跳转链接？…\n@-webkit-keyframes bpx-animation…[truncated]",
  "clean_text_hash": "e3b0c44298fc1c14"
}
```
（注：此条 clean_text 以 CSS 动画代码开头，说明 Primary Content Extraction 对该页面未正确去除样式代码，正文质量存疑。）

## 8. DecisionEvidenceAdoption

```json
{
  "id": 1, "snapshot_id": 4, "project_id": 3, "prompt_id": 19,
  "run_id": 61, "citation_id": 986,
  "recommendation_claim_id": 30, "selection_criterion_id": 91,
  "evidence_status": "UNCERTAIN"
}
```

## 9. StrategyCandidate（#31，截断）

```json
{
  "id": 31, "project_id": 3, "evidence_package_id": 11,
  "prompt_version": "strategy_prompt.v2",
  "review_status": "PENDING_REVIEW",
  "generation_status": "GENERATED",
  "effective_validation_status": "VALIDATED",
  "structured_payload_json": {
    "intervention_type": "UNRESOLVED",
    "target_platform": "UNRESOLVED",
    "target_asset": "NEW_INFORMATIONAL_CONTENT",
    "target_content_type": "TUTORIAL",
    "observed_problem": "品牌「爱短链」在 13 次采样中的品牌提及率为 0/13…",
    "platform_direction": "基于当前答案信号分层，优先平台建议为：抖音（普通引用分布）…",
    "target_metric": "brand_mention_rate", "baseline_value": "0/13",
    "decision_capability": "CONTENT_DIRECTION_ONLY"
  }
}
```

## 10. Experiment（#13）

```json
{
  "id": 13, "action_id": 13,
  "status": "READY_FOR_MANUAL_RELEASE",
  "primary_metric": "target_page_retrieval_rate",
  "release_blocked": 1,
  "release_blocked_reason": "WAITING_FOR_INTERVENTION_SELECTION",
  "released_at": null,
  "baseline_run_ids_json": "[173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184]",
  "conclusion": ""
}
```

---

# Post-implementation Addendum（2026-08-19）

以下为审计文档定稿后的新增内容，不改写原始 FORENSIC AUDIT 结论。

## Single Case Evidence 管道落地状态

五层语义管道已实现并真实运行（DeepSeek deepseek-v4-flash）：

| Layer | 状态 | 真实结果 |
|-------|------|---------|
| L1 AnswerSemanticJudge | LIVE VERIFIED | 1 次 LLM（12 相同答案 hash 复用），12 事件（商加加 INCLUDE_AS_OPTION） |
| L2 Source Qualification | LIVE VERIFIED | 88 CONTENT_VALID / 35 NOISY / 7 EMPTY / 73 FETCH_FAILED |
| L3 Reason-driven Retrieval | LIVE VERIFIED | 3 unique reasons → 15 passages（BM25） |
| L4 Blind SourceClaimJudge | LIVE VERIFIED | 44 grounded claims，注入防护 RESISTED |
| L5 Evidence Alignment | LIVE VERIFIED | **10 SUPPORTS** + 114 COMPETITOR_CONTEXT |

## 关键业务结论（机器层）

- Gap 判定：**EVIDENCE_GAP（MEDIUM）**——爱短链能力（Product Truth SUPPORTED：抖音跳转微信/短链生成）真实存在，但 12 次答案 0 提及。
- Action：EVIDENCE_STRENGTHEN / FIRST_PARTY / UNRESOLVED 平台。
- 进入真实实验：**NO**（0 人工审核，target_platform 未定）。

## 修复的存量数据问题

- 商加加官网 4 文档为 SPA 壳（无正文），Playwright 重抓恢复真实内容（2035-3092 字）。
- 项目 #3 竞品列表补充商加加（shangjiajia.com）。

# CURRENT_IMPLEMENTATION_AUDIT

日期：2026-08-12

## 审计结论

本轮不新建第二套 AI Decision Market。现有 Wenxin 采集、Recommendation Snapshot、Decision Market read model、Evidence Package、Optimization Loop 可以继续复用，但必须把语义从“推荐统计页面”升级为：

```text
COLLECT -> UNDERSTAND -> EXPLAIN -> DECIDE -> VERIFY
```

核心修正是：先判断真实品牌选择空间，再解释谁进入选择、为什么被推荐、推荐理由伴随哪些 Citation Context，最后在不猜 Product Truth 的前提下输出 Primary Gap。

## 1. 当前已有 Model

- `Prompt`：一个 Prompt 就是一个用户问题，不能拆成多问题语义。
- `BrowserMonitorRun`：保存真实采集状态、原始问题、Answer、引用计数、品牌粗计数。
- `ReferenceSource`：最终 Citation / 引用资料，包含标题、URL、domain、reference index。
- `RetrievalCandidate`：检索候选集合，只能作为独立可观测集合，不能当作 Citation 上游全集。
- `AnswerClaim` / `AtomicClaim`：Golden Case 的回答主张和语义主张。
- `RecommendationIntelligenceSnapshot`：决策诊断快照父对象。
- `RecommendationEntity`：项目品牌和竞品实体，已扩展 `entity_role`、`is_choice_candidate`。
- `RecommendationClaim`：Recommendation / Candidate / Mention 事实，已扩展 span、offset、strength、choice candidate。
- `RecommendationReasonClaim`：绑定具体 Recommendation 的理由事实，已扩展 reason span、offset、extractor、review。
- `DecisionSelectionCriterion`：选择标准事实。
- `BrandCapabilityClaim`：AI Observed Truth 中的品牌能力识别。
- `DecisionEvidenceAdoption`：已改为 Citation Context / Evidence Status 语义，不再把共现等同 Evidence Support。
- `DecisionGapDiagnosis`：结构化 gap 诊断。
- `TargetBrandCapabilityTruth`：新增目标品牌 Product Truth 人工确认表。
- `OptimizationIssue / Action / Experiment / Hypothesis`：最终策略和复测闭环，历史对象不可重绑或篡改。

## 2. 当前 Schema

- Recommendation Snapshot 保存 source run ids、版本号、landscape、positioning、gap、intervention candidates。
- 新增 `answer_semantic_facts`：保存 `has_choice_slot`、`has_brand_mention`、`has_explicit_recommendation`、`has_comparison` 的 run-level 原子事实。
- 新增 `target_brand_capability_truths`：保存目标品牌能力事实状态，支持 `SUPPORTED / PARTIALLY_SUPPORTED / NOT_SUPPORTED / UNKNOWN`。
- 迁移文件：`backend/alembic/versions/20260812_03_answer_semantics_product_truth.py`。

## 3. 当前 Repository

项目当前没有独立 Repository 层，主要通过 SQLAlchemy Session 在 Service 中读写。P0 阶段继续沿用现有风格，避免为了抽象而重构。

## 4. 当前 Service

- `backend/app/modules/optimization/recommendation.py`
- 已完成：实体解析、Recommendation 抽取、Reason 抽取、选择标准、能力识别、Citation Context、Brand Opportunity Gate、Primary Gap、Product Truth summary、实验草案。
- 本轮修正：`solution_slot` 主语义升级为 `choice_slot`，旧字段保留兼容；`supports_claim` 不再由共现规则置为 true。

## 5. 当前 API

- `POST /api/optimization/projects/{id}/recommendation-analysis`
- `GET /api/optimization/projects/{id}/recommendation-landscape`
- `GET /api/optimization/projects/{id}/decision-market/{prompt_id}/summary`
- `GET /api/optimization/recommendation-claims`
- `POST /api/optimization/recommendation-claims/{id}/review`
- `GET /api/optimization/decision-market/answer-semantic-facts`
- `POST /api/optimization/decision-market/answer-semantic-facts/{id}/review`
- `GET /api/optimization/decision-market/selection-criteria`
- `POST /api/optimization/decision-market/selection-criteria/{id}/review`
- `GET /api/optimization/decision-market/capability-claims`
- `POST /api/optimization/decision-market/capability-claims/{id}/review`
- `GET /api/optimization/decision-market/evidence-adoptions`
- `POST /api/optimization/decision-market/evidence-adoptions/{id}/review`
- `GET /api/optimization/projects/{id}/target-brand-capability-truths`
- `POST /api/optimization/projects/{id}/target-brand-capability-truths`
- `POST /api/optimization/decision-market/snapshots/{id}/experiment-draft`

## 6. 当前前端组件

- 主入口：`frontend/src/App.tsx`
- 页面：`决策诊断`
- 已整合：Brand Opportunity Gate、答案语义事实、品牌阶段、品牌能力识别、Citation Context、Product Truth 人工核对、Primary Gap、送入最终策略。
- 用户可见文案保持中文；内部 API 和枚举允许英文，但需要有中文 label。

## 7. 可直接复用逻辑

- Wenxin 真实采集和 `BrowserMonitorRun` 原始事实。
- `ReferenceSource` final citation 解析。
- `RetrievalCandidate` 作为独立观测集合。
- Recommendation Snapshot 作为诊断快照父对象。
- Golden Case 的 `AnswerClaim / AtomicClaim / SourceDocument / PassageAlignment`。
- Optimization 的 Issue / Action / Experiment 草案能力。

## 8. 已扩展字段

- `RecommendationEntity.entity_role`
- `RecommendationEntity.is_choice_candidate`
- `RecommendationClaim.recommendation_span`
- `RecommendationClaim.start_offset`
- `RecommendationClaim.end_offset`
- `RecommendationClaim.recommendation_strength`
- `RecommendationClaim.is_choice_candidate`
- `RecommendationReasonClaim.reason_span`
- `RecommendationReasonClaim.start_offset`
- `RecommendationReasonClaim.end_offset`
- `RecommendationReasonClaim.extractor`
- `RecommendationReasonClaim.extractor_version`
- `RecommendationReasonClaim.review_status`
- `RecommendationReasonClaim.human_labels_json`
- `DecisionEvidenceAdoption.evidence_status`

## 9. 新增对象

- `AnswerSemanticFact`
- `TargetBrandCapabilityTruth`

## 10. 旧数据兼容

- 历史 `RecommendationIntelligenceSnapshot` 不重写。
- 历史 `OptimizationExperiment / Hypothesis / EvidencePackage` 不重绑。
- `solution_slot` 字段在 API 中继续保留兼容，但新逻辑以 `choice_slot` 为准。
- `DecisionEvidenceAdoption.supports_claim` 字段保留，但规则共现不再自动置真。

## 11. 本轮修改文件清单

- `backend/app/models/db.py`
- `backend/app/models/__init__.py`
- `backend/app/modules/optimization/recommendation.py`
- `backend/app/modules/optimization/api.py`
- `backend/alembic/versions/20260812_03_answer_semantics_product_truth.py`
- `backend/tests/test_recommendation_intelligence.py`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `docs/CURRENT_IMPLEMENTATION_AUDIT.md`
- `docs/recommendation-market.md`
- `docs/answer-semantic-analysis.md`
- `docs/recommendation-reason.md`
- `docs/citation-context.md`
- `docs/product-truth.md`
- `docs/gap-diagnosis.md`

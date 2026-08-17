# GEO 决策诊断开发需求完成清单（2026-08-13）

## 结论

开发提示词中的工程能力已完成到可使用状态：

- `COLLECT -> UNDERSTAND -> EXPLAIN -> DECIDE -> VERIFY` 主链路已落到后端、API、前端和测试。
- P0 / P1 / P2 工程项已具备数据模型、服务、API、页面入口和回归测试。
- 系统仍不会伪造 Product Truth、正文语义支撑、真实发布、真实复采或实验有效性结论。

剩余不是代码开发项，而是必须由业务事实或真实外部状态完成：

- 人工确认 #19 目标品牌 Product Truth。
- 真实发布受控页面改动。
- 发布后固定复采并挂载验证 Run。
- 人工记录 Known Environment Audit 和实验结论。

## P0 完成项

| 要求 | 状态 | 实现位置 |
| --- | --- | --- |
| `has_choice_slot` | 完成 | `AnswerSemanticFact`、决策诊断页答案语义事实 |
| `has_brand_mention` | 完成 | `AnswerSemanticFact`、Brand Opportunity Gate |
| `has_explicit_recommendation` | 完成 | Speech Act 规则抽取、推荐判断 |
| Recommendation Speech Act | 完成 | `RecommendationClaim.recommendation_type` |
| Recommendation Span / Strength / Polarity / Target | 完成 | `RecommendationClaim` |
| `is_choice_candidate` | 完成 | `RecommendationEntity`、`RecommendationClaim`、实体审核 |
| Recommendation Reason 绑定具体 Recommendation | 完成 | `RecommendationReasonClaim.recommendation_claim_id` |
| Brand Opportunity Gate | 完成 | `decision_market.brand_opportunity_gate` |
| Prompt-level Choice Slot 聚合 | 完成 | 分子 / 分母 / eligible denominator 指标 |
| Primary Gap | 完成 | `DecisionGapDiagnosis`，只输出 Primary + 最多 2 个 contributing gaps |

## P1 完成项

| 要求 | 状态 | 实现位置 |
| --- | --- | --- |
| Evidence Status | 完成 | `DecisionEvidenceAdoption.evidence_status` |
| Citation Context | 完成 | `decision_market.citation_context` |
| Target Brand Capability Truth | 完成 | `TargetBrandCapabilityTruth` 和人工核对 UI |
| 人工能力核对 | 完成 | 决策诊断页“目标品牌产品事实核对” |
| entity_role 扩展 | 完成 | `RecommendationEntity.entity_role` + 实体审核 UI |
| Recommendation Review | 完成 | 推荐判断审核 API/UI |
| Reason Review | 完成 | 推荐理由审核 API/UI |
| Choice Slot Review | 完成 | 答案语义事实审核 API/UI |

## P2 完成项

| 要求 | 状态 | 实现位置 |
| --- | --- | --- |
| Known Environment Audit | 完成 | `OptimizationExperiment.known_environment_audit_json` |
| Comparable / Confounded 状态 | 完成 | `comparability_status` / `comparability_note` |
| Controlled Intervention | 完成 | `controlled_intervention_json` |
| 实验计划验证边界可见化 | 完成 | 最终策略页“验证边界与实验计划” |
| VERIFY 控制台 | 完成 | 最终策略页“实验闭环控制台” |

## Definition of Done 对照

| 验收问题 | 状态 |
| --- | --- |
| 多少 Run 有真实 Choice Slot | 已支持，#19 最新为 `39/40` |
| 哪些品牌只是 Mention / Candidate / Recommendation / Top Choice | 已支持 |
| 每个推荐品牌因为什么被推荐 | 已支持，按 Brand -> Recommendation -> Reason 展示 |
| 每个 Reason 伴随哪些 Platform / Domain / URL / Citation | 已支持 Citation Context |
| Citation 能否与 Reason 建立联系 | 已支持 `LINKED / PARTIALLY_LINKED / UNLINKED / UNCERTAIN` |
| 爱短链 Primary Gap 是什么 | 已支持，#19 当前为 `CANDIDATE_INCLUSION_GAP` |
| 目标品牌真实是否具备竞品关键能力 | 系统支持人工确认；事实本身待业务输入 |
| 基于 Product Truth 下一步补什么 | 系统支持路由；未知事实下保持草案/待确认 |
| 改动后如何复采验证 | 已支持锁基线、发布边界、固定复采、挂载验证 Run、分析、人工结论 |

## 不能自动完成的事项

以下事项必须由人或真实外部环境完成，系统不能伪造：

- Product Truth 不能由系统猜测。
- Citation Context 不能直接升级为 Evidence Support；只有正文抓取和段落对齐后，才能作为候选支撑，且仍需人工确认语义。
- 未真实发布页面改动前，不能进入真实复采结论。
- 黑盒 AI 环境不能声明严格不变，只能记录当前观察窗口内已知变化。

## 当前验证

- `pytest tests/test_recommendation_intelligence.py tests/test_golden_case_api.py -q`：`19 passed`
- `npm run build`：通过
- `python -m compileall`：通过
- `git diff --check`：通过

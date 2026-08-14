# GEO 决策诊断工程交付报告（2026-08-13）

## 交付结论

本轮已将原“推荐市场”升级为以 `COLLECT -> UNDERSTAND -> EXPLAIN -> DECIDE -> VERIFY` 为主线的决策诊断工作台。

当前状态：

- P0 已完成：答案语义事实、品牌选择空间、推荐 Speech Act、品牌候选/推荐分层、推荐理由绑定、Brand Opportunity Gate、Primary Gap。
- P1 已完成：Citation Context、Evidence Status、Target Brand Capability Truth、Choice Slot / Entity / Recommendation / Reason Review 人工核对入口。
- P2 已完成最小闭环：Experiment 增加已知环境审计、可比性状态、受控干预边界；不声称黑盒环境严格不变。
- 仍需人工完成：#19 的目标品牌 Product Truth 需要业务侧逐项确认，确认前不得输出确定性最终策略。

## 核心代码变更

- 后端模型：新增 / 扩展 `AnswerSemanticFact`、`RecommendationReasonClaim`、`DecisionEvidenceAdoption`、`DecisionGapDiagnosis`、`TargetBrandCapabilityTruth`、`OptimizationExperiment`。
- 后端服务：新增决策诊断生成、历史快照、Citation Context、Product Truth、Experiment Draft、P2 环境审计字段。
- 前端页面：左侧能力区统一为“业务闭环 / 证据工作台 / 系统配置”，`决策诊断` 支持自动加载已有最新版本、历史版本切换、生成时间展示、中文化展示。
- 决策诊断新增“可审计决策链”：把品牌信号、推荐/候选理由、原答案片段、Citation Context、Primary Gap 和下一步动作放到同一张表中展示。
- 决策诊断新增“引用正文对齐”：从诊断快照的真实采样自动汇总 Answer Claim 与引用页面段落的 L1/L2/L5 对齐状态，明确提示文本对齐不是因果证明。
- 决策诊断新增人工审核闭环：答案语义事实、实体/候选边界、推荐判断、推荐理由、引用上下文、差距诊断、产品事实均可在页面核对。
- 最终策略新增“验证边界与实验计划”：策略候选必须先人工接受，再生成实验计划；页面展示计划状态、可比性边界、允许改动、禁止混改、环境审计和阻塞项。
- 最终策略新增“实验闭环控制台”：承接 Issue / Action / Experiment 草案，支持锁定基线、排队固定复采、挂载复采 Run、分析实验和记录人工结论。
- 文档：新增审计文档和 6 份语义规范文档。

## 数据库变更

新增迁移：

- `20260812_01_recommendation_intelligence.py`
- `20260812_02_decision_market_core.py`
- `20260812_03_answer_semantics_product_truth.py`
- `20260813_01_experiment_environment_audit.py`

P2 新增实验字段：

- `known_environment_audit_json`
- `comparability_status`
- `comparability_note`
- `controlled_intervention_json`

## #19 Golden Case 最新结果

最新快照：`#10`

Prompt：`抖音跳转链接`

样本：

- 有效采样：`40`
- 有选择空间：`39/40`
- 品牌出现：`8/40`
- 明确推荐：`0/40`
- 对比出现：`1/40`

品牌分层：

- `爱短链`：仅提及 `1` 次，未进入候选，未被明确推荐。
- `天天外链`：候选 `4` 次，仅提及 `3` 次。
- `微客外链`：候选 `1` 次。

推荐理由：

- `天天外链 -> 功能能力`：2 条。
- `天天外链 -> 其他选择理由`：1 条。
- `微客外链 -> 其他选择理由`：1 条。

Citation Context：

- 已生成 3 条引用上下文。
- 当前只表达“推荐/理由伴随了哪些外显引用来源”，不表达“引用支撑推荐”。

Primary Gap：

- `CANDIDATE_INCLUSION_GAP`
- 诊断：当前回答存在方案槽位，但 `爱短链` 没有稳定进入候选。
- 后置提醒：`RECOMMENDATION_GAP` 不是首要失败点，因为该问题属于信息/操作型，明确推荐率只能作诊断观察。

## 测试结果

已通过：

- `pytest backend/tests/test_recommendation_intelligence.py backend/tests/test_golden_case_api.py -q`：`19 passed`
- `python -m compileall`：通过
- `npm run build`：通过
- `git diff --check`：通过

新增回归：

- `test_strategy_experiment_plan_exposes_p2_verification_boundary`：确认最终策略候选转实验计划后，API 返回和实验记录都保留 Known Environment Audit、Comparability Status、Controlled Intervention。
- `test_decision_passage_support_summarizes_answer_claim_alignment`：确认决策诊断快照可以汇总回答主张与引用正文段落的精确对齐结果，并保留“文本对齐不是因果证明”的边界说明。
- `test_answer_semantic_fact_can_be_reviewed`：确认 Choice Slot 等答案语义事实可以逐条人工审核。
- `test_recommendation_entities_can_be_reviewed_without_losing_choice_boundary`：确认实体角色和 Choice Candidate 边界可以人工审核，且不会被后续规则生成覆盖。
- `test_recommendation_reason_claims_can_be_reviewed`：确认品牌级推荐理由可以独立审核。

已知提示：

- Vite 仍提示前端单包超过 500 kB，这是既有体积告警，不影响功能正确性。
- Python 3.14 / Pydantic 产生弃用 warning，非本轮功能失败。

## 仍需人工确认

Product Truth 不能由系统自动猜测。#19 下一步需要业务侧确认：

- 爱短链是否真实支持抖音跳转微信 / 私域承接场景。
- 是否支持合规边界说明。
- 是否支持数据统计 / 点击追踪。
- 是否有可公开引用的官方说明页、产品文档或案例。

确认前，系统只能生成实验草案，不能把竞品理由直接写成目标品牌确定性策略。

## 下一步

1. 在 `决策诊断` 中选择 #19，打开 `目标品牌产品事实核对`。
2. 人工确认关键能力：支持 / 部分支持 / 不支持。
3. 再点击 `送入最终策略：生成实验草案`。
4. 在 `最终策略` 中确认单一 Primary Gap 和受控干预边界。
5. 发布后固定复采，并补充 Known Environment Audit。
6. 根据可比性状态判断结果只能作为方向观察，还是具备较强可比性。

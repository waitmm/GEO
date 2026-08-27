# Single Prompt GEO V1 Phase 0/1 Handoff

状态：REVIEW_ONLY
日期：2026-08-27
范围：Phase 0/1 仓库现状映射、冲突点、复用/新增对象建议；不进入业务代码开发。

## 1. 本轮边界

本轮不是重新设计产品，也不是新增 GEO 架构，而是把已经确定的单
Prompt GEO 主链 V1 固化成可审查的实现边界。

本轮只交付：

- 仓库现状映射。
- 已发现冲突点。
- Phase 2 前拟复用、扩展、废弃和新增对象。
- 必须写入代码前的强约束。

本轮不交付：

- 不修改业务代码。
- 不调整前端工作流实现。
- 不创建新的正式 StrategyCandidate / Action / Experiment。
- 不把 Citation Decision V1.1 全量切到生产。

任何改变主链顺序、状态归属、执行闸门或 Experiment 创建路径的后续代码改动，
必须先写入 `08_DEVELOPMENT_LOG.md` 和 `09_PRODUCT_ITERATION_LOG.md`，
并在 PR/交付说明中标为强预警。

## 2. 单 Prompt GEO 主链 V1

正式主链只有一条，不新增独立 Citation 模块来替代它：

```text
1. 采集样本
2. 答案决策识别
3. 目标品牌事实
4. 引用证据
5. 对标来源
6. 缺口诊断
7. 策略候选 + 策略确认
8. 实验方案落地
```

第 7 步不是“直接确认推荐动作”。第 7 步必须落在现有
`OptimizationStrategyCandidate` 和 `effective_payload` 闸门上：

```text
Gap / Proposal
-> StrategyCandidate
-> Human Review / Edit
-> effective_payload = VALIDATED
-> Action / Experiment
```

第 8 步才允许创建 `OptimizationAction` 和 `OptimizationExperiment`。

## 3. 每步唯一事实来源

| 步骤 | 唯一主状态源 | 当前承载对象 | Phase 2 前要求 |
| --- | --- | --- | --- |
| 1. 采集样本 | 当前 Prompt Runs | `BrowserMonitorRun`, `ReferenceSource`, `RetrievalCandidate`, `RunArtifact` | 必须绑定当前 `prompt_id` 和当前 Run set。 |
| 2. 答案决策识别 | 答案语义事件 | `RecommendationEvent`, `AnswerUnit`, `AnswerDecisionBinding` | 只表达答案里发生了什么，不读取引用来源来反推答案事件。 |
| 3. 目标品牌事实 | 人工确认的 Product Truth | `TargetBrandCapabilityTruth` | 只确认目标品牌自己的真实能力，不确认竞品或引用文章能力。 |
| 4. 引用证据 | 当前 Evidence Package + 正文/对齐 | `OptimizationEvidencePackage`, `ReferenceSource`, `SourceDocument`, `SourceClaim`, `EvidenceAlignment` | Citation 只是来源信号；`SourceDocument` / `SourceClaim` 是可跨 Run 复用的文档级事实，Run lineage 由当前 Run 的引用实例指向文档建立。 |
| 5. 对标来源 | Citation Decision V1 派生读模型 | source analysis row fields | `PRIMARY/SECONDARY` 只能由有效 EvidenceAlignment 支撑。 |
| 6. 缺口诊断 | Benchmark + Product Truth + Brand Asset | source gap derived fields | Gap 是派生结论，不应写成不可追溯的孤立动作。 |
| 7. 策略候选 + 策略确认 | `StrategyCandidate` + `effective_payload` | `OptimizationStrategyCandidate` | 人工确认前只能是 candidate/proposal，不能创建实验。 |
| 8. 实验方案落地 | 已确认 effective payload 快照 | `OptimizationIssue`, `OptimizationAction`, `OptimizationExperiment`, `OptimizationHypothesis`, `ReleaseAuditRecord` | Experiment 必须绑定确认时的 effective payload 快照。 |

旧 `workflowData`、`continueResult`、历史 Experiment 可以展示历史记录，但不能反向决定当前主链状态。

## 4. Phase 0/1 现状映射

| 分类 | 对象 / 模块 | 现状判断 | 下一步处理 |
| --- | --- | --- | --- |
| REUSE | `OptimizationStrategyCandidate` | 已有 structured / human edited / effective payload 字段和 review status。 | 作为第 7 步唯一策略承载，不新增平行 Strategy 表。 |
| REUSE | `effective_payload_json` / `effective_validation_status` | 已被 `strategy_to_experiment_plan` 读取。 | Phase 2 必须继续 fail-closed，只消费 `VALIDATED`。 |
| REUSE | `OptimizationAction` / `OptimizationExperiment` | 已有 Action/Experiment 草案、Release gate、Retest gate 字段。 | 第 8 步复用，不让 Citation 详情页直接绕过。 |
| REUSE | `AnswerUnit` / `AnswerDecisionBinding` | Phase 0/1 已作为 V1.1 answer binding 输入。 | 继续作为答案侧理由桥，不作为来源事实。 |
| REUSE | `SourceDocument` / `SourceClaim` / `EvidenceAlignment` | 已能承载正式 V1.1 SUPPORTS。 | Phase 2 前补 lineage eligibility，避免旧 SUPPORTS 泄漏。 |
| REUSE | `RetrievalCandidate` | 已采集检索候选。 | `DISCOVERABILITY_GAP` 必须消费它，不允许凭感觉判断“不可发现”。 |
| EXTEND | `EvidenceAlignment.machine_payload_json` | 已出现 `reason_source`, `formal_input_version`, `observed_run_ids`, `run_coverage_count`。 | 增加完整 lineage 校验与读路径统一过滤。 |
| EXTEND | `OptimizationExperiment` | 当前没有专门的 effective payload snapshot 字段。 | Phase 2 可先写入 `intervention_variables_json`，若不够再加显式字段。 |
| EXTEND | Source Gap 派生逻辑 | 已有 `CONTENT_GAP`, `EVIDENCE_GAP`, `PRODUCT_GAP`, `NO_GAP`, `UNKNOWN`。 | 补 `DISCOVERABILITY_GAP`，且只基于当前能力/Prompt 相关资产。 |
| EXTEND | 前端单 Prompt 8 步 | 已有 8 步展示，但第 7 步语义仍偏“推荐动作”。 | Phase 2 只改为主链内嵌策略候选，不新增模块。 |
| DEPRECATE | Citation Detail 直接确认动作 | 当前 `confirm_citation_decision_vertical_slice` 可直接创建实验草案。 | 拆为创建 StrategyCandidate 与后续 effective payload 确认两步。 |
| DEPRECATE | 任意最新品牌资产作为 gap 输入 | `_latest_brand_asset_snapshot` 可回退到最新快照。 | 不能用于 `DISCOVERABILITY_GAP` 或能力覆盖判断。 |
| DEPRECATE | 旧模块直接查 `EvidenceAlignment.relation == SUPPORTS` | `gap_action.py`, `content_brief.py`, `intervention.py`, `workflow.py` 存在直接消费者。 | 必须统一走 lineage/版本合格过滤。 |
| NEW | 新正式 Strategy 表 | 当前不需要。 | 禁止新增，除非后续证明 `StrategyCandidate + effective_payload` 无法承载。 |
| NEW | 独立 Benchmark / Opportunity 表 | 当前不需要。 | 先作为 Evidence Package / source analysis 派生读模型。 |

## 5. 当前冲突点

### 5.1 第 7 步语义冲突

当前后端 `confirm_citation_decision_vertical_slice` 会在确认 Citation Decision
后创建 `OptimizationStrategyCandidate`，并在 `create_experiments=true` 时继续调用
`strategy_to_experiment_plan`。

这与主链定义冲突：

```text
第 7 步只能确认 StrategyCandidate/effective_payload
第 8 步才创建 Action/Experiment
```

Phase 2 需要拆开：

```text
创建策略候选
-> 人工审核 effective_payload
-> 创建 Action/Experiment 草案
```

### 5.2 Experiment 缺少明确 effective payload 快照

当前 `strategy_to_experiment_plan` 会把 effective payload 写入
`candidate.experiment_plan_json`，并把部分信息写入
`OptimizationExperiment.intervention_variables_json`。

Phase 2 硬约束：

```text
Experiment 创建时必须绑定确认时的 effective_payload 快照。
```

最小实现优先：

```text
intervention_variables_json.effective_payload_snapshot = {
  strategy_candidate_id,
  effective_payload_version,
  effective_payload_hash,
  effective_payload_json,
  confirmed_at,
  confirmed_by
}
```

如果审计证明 JSON 容器不足，再新增显式 DB 字段。

### 5.3 DISCOVERABILITY_GAP 输入不完整

`DISCOVERABILITY_GAP` 不能表示“随便找不到品牌任意资产”，只能表示：

```text
当前 Prompt / 当前能力 对应的品牌资产
没有进入当前 Run 的 RetrievalCandidate / Citation 可见链路。
```

必须同时满足：

- 有当前 Benchmark capability / AnswerUnit。
- Product Truth 显示目标品牌支持该具体能力。
- 已识别与该 Prompt / 能力相关的品牌资产。
- 当前 Evidence Package 的 `RetrievalCandidate` / `ReferenceSource` 未观察到该资产。

不能使用任意最新 `PageSnapshot` 或官网首页快照直接判断。

### 5.4 EvidenceAlignment lineage 不完整

Phase 2 前必须新增统一 eligibility checker。合格的正式对齐不能只满足：

```text
EvidenceAlignment.run_id is not null
```

必须能追溯并一致：

```text
Run
├── Answer / RecommendationEvent / AnswerUnit / AnswerDecisionBinding
└── ReferenceSource / CitationOccurrence
        ↓
    SourceDocument
        ↓
    SourceClaim
        ↓
    EvidenceAlignment
```

其中 `SourceDocument` 和 `SourceClaim` 不是 Run 子对象，也不应该为了
Run lineage 被重复创建。它们是文档级事实，可被多个 Run 的引用实例复用。

最低校验：

- 所有对象 `project_id`、`prompt_id` 一致。
- `EvidenceAlignment.run_id` 属于当前 Evidence Package 的 `source_run_ids`。
- `AnswerUnit.run_id == EvidenceAlignment.run_id`。
- `AnswerUnit.run_id` 和 `AnswerDecisionBinding.run_id` 与事件、Prompt 一致。
- `AnswerDecisionBinding.recommendation_event_id` 指向同 Run 的
  `RecommendationEvent`。
- 当前 Run 必须存在能通过 URL 或缺 URL 时的 domain/title 指向该
  `SourceDocument` 的 `ReferenceSource` / CitationOccurrence。
- `SourceClaim` 必须属于该 `SourceDocument`；但 `SourceClaim` 本身不需要、
  也不应强制增加 `run_id`。
- V1.1 正式输入必须有 `reason_source = ANSWER_DECISION_BINDING` 和
  `formal_input_version`，并受 feature flag 读写双向控制。

### 5.5 旧 SUPPORTS 消费者未统一过滤

仓库中仍存在直接读取 `EvidenceAlignment.relation == "SUPPORTS"` 的旧消费者，
包括 Gap/Action、Content Brief、Intervention、Workflow 等路径。

Phase 2 必须把这些读路径收敛到统一函数，否则 V1.1 写入的正式对齐可能绕过
feature flag 或 lineage gate，被旧链路当成可执行证据。

## 6. 四个新增强约束

### 6.1 StrategyCandidate / effective_payload 优先复用

正式策略不新增平行对象。第 7 步的主对象是：

```text
OptimizationStrategyCandidate
+ effective_payload_json
+ effective_validation_status
```

`recommended_action`、`channel_opportunity`、`action_route` 只能作为 proposal
输入，不是最终执行策略。

### 6.2 Experiment 必须绑定确认时 payload 快照

实验草案不是“重新读取当前 candidate 最新 payload”。创建 Experiment 时必须冻结：

```text
candidate_id
effective_payload_version
effective_payload_hash
effective_payload_json
confirmed_by
confirmed_at
source_evidence_package_id
```

后续 candidate 被编辑、重跑或修正时，不能静默改变已创建 Experiment 的实验假设。

### 6.3 DISCOVERABILITY_GAP 必须使用相关品牌资产

品牌资产必须和当前 Prompt / capability 有关：

```text
Benchmark capability
-> Product Truth capability
-> Brand asset candidate
-> RetrievalCandidate / ReferenceSource visibility
```

不能因为项目存在官网或任意品牌页面，就判断 discoverability 已满足或缺失。

### 6.4 EvidenceAlignment 必须验证完整 Run lineage

任何正式 Benchmark、Gap、Priority、Action 输入都必须消费“lineage-valid
alignment”，不能直接消费裸 `SUPPORTS`。

Run lineage 由 AnswerUnit / DecisionBinding / RecommendationEvent 的同 Run
关系，以及当前 Run 的引用实例指向可复用 `SourceDocument` 建立。禁止：

```text
按 Run 重复创建同一 SourceDocument
按 Run 重复抽取同一 SourceClaim
强制要求 SourceClaim 带 run_id
从 Prompt 下所有 Run 复制 observed_run_ids
```

如果 lineage 缺失，输出应为：

```text
decision_support_level = NONE
benchmark_tier = REFERENCE_ONLY / NOT_EVALUABLE
source_gap_type = null
```

不能降级成可执行策略。

## 7. Phase 2 拟开发顺序

用户确认本文件后，Phase 2 建议按以下顺序执行：

```text
1. 建立 EvidenceAlignment lineage eligibility checker。
2. 统一 Citation Decision / Gap / Content Brief / Intervention 的 SUPPORTS 读路径。
3. 将 use_answer_binding_v1_1 升级为生成 + 读取双向 feature flag。
4. 拆开 Citation Decision 确认路径：只创建 StrategyCandidate，不直接创建 Experiment。
5. Experiment 创建时冻结 effective_payload_snapshot。
6. 实现 DISCOVERABILITY_GAP，并限制为当前 Prompt / capability 相关品牌资产。
7. 前端单 Prompt 第 7 步改为“策略候选”，第 8 步改为“实验方案落地”。
8. 使用 Prompt #40 和 3-5 个不同类型 Prompt 做小范围回归。
```

Phase 2 仍不应新增 PromptCluster 级 Opportunity、集合级市场份额或新的大看板。

## 8. Phase 2 进入 Gate

进入 Phase 2 前必须由人工确认：

- 本文件中的 8 步主链顺序。
- 第 7 步复用 StrategyCandidate/effective_payload。
- Experiment effective payload snapshot 的最小承载方式。
- `DISCOVERABILITY_GAP` 的相关资产定义。
- EvidenceAlignment lineage eligibility 规则。
- 哪些旧 SUPPORTS 消费者第一批收敛。

确认前，本仓库状态是：

```text
PHASE_0_1_HANDOFF_READY_FOR_REVIEW
PHASE_2_BUSINESS_CODE_NOT_STARTED
```

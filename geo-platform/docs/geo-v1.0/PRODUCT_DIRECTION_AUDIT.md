# GEO 1.0 产品方向审计

审计基线：`850ca275a496ed863707c1e362cdbd982044f4d0`

审计范围：`525e152..850ca27` 及必要的冻结产品契约、正式 UI、持久化和真实验收记录。

方法：只读审计；未访问网络、模型、网页或生产数据库，未修改产品代码、测试、台账或 Git 引用。

## 1. 管理摘要

GEO 1.0 的产品方向仍与冻结范围一致：Project/Prompt → 采样 → Monitor → Optimize → 内容交付 → 持续采样 → Validate。核心工程主链、版本身份、项目隔离、append-only 和失败关闭原则已有较强实现证据；但完整用户价值尚未闭环。

结论：`AT_RISK`。

- 已验证：T00–T08、T19、T21、T22 台账为 DONE；Monitor、比较、纠错及交付约束存在正式代码和 UI 入口。
- 部分验证：UI 可进入主要页面，但没有一份覆盖首次使用到真实交付再到独立比较的完整真实浏览器/业务证据。
- 阻断：T09、T23 为 BLOCKED；T10、T24 依赖未解锁；T25 仍 IN_PROGRESS。
- 真实价值：T23 三个真实场景均未满足正式 Gate，不能把工程测试或局部真实请求写成完整交付。

审计来源限制：命名的《GEO_Platform_1.0_最终交付指令_2026-10-09》在当前 checkout 中未以该文件名出现。本报告使用用户当前指令、`docs/00_PROJECT_BRIEF.md`、`docs/01_PRODUCT_DIRECTION.md`、`docs/geo-v1.0/00_产品范围与交付基线.md`、`17_验收矩阵.md`、`acceptance_cases.json`、`tasks.json` 和真实 T09/T23 记录；不猜测缺失文件内容。

## 2. 方向状态

| 方向 | 状态 | 证据与判断 |
|---|---|---|
| 正式 V2 主链和冻结版本 | VERIFIED | `00_产品范围与交付基线.md` 的正式 release 主链要求；T00–T08、T19、T21、T22 DONE。 |
| Monitor | PARTIAL | `ObservationPanel.tsx`、Monitor 路由及 T06/T07 DONE；真实多 Prompt 全链路结果仍未替代局部证据。 |
| Optimize | PARTIAL | `AutomaticOptimizePanel.tsx`、后端交付/策略代码完整；T19/T19-02 已完成纠错与策略重投影切片，但真实无知识库、低匹配、事实缺失交付尚未完整通过，存在高风险。 |
| Execution 内容交付 | PARTIAL | `ManuscriptPreview.tsx`、稿件编辑和 QA 入口存在；T23 E1 Draft 被拒绝，不能宣称真实自动交付稳定，存在高风险。 |
| Validate | PARTIAL | `ObservationPanel.tsx` 有双范围和历史结果隔离；T21/T22 DONE，但 E2E-04 要求的持续真实采样比较仍未完成。 |
| 外部业务验收 | BLOCKED | T09 缺合法已审核重分析基线；T23 三类正式场景均未通过。 |

## 3. 原始需求追踪矩阵

| 需求 | 正式入口/实现 | 变更或台账 | 证据 | 用户效果 | 状态 |
|---|---|---|---|---|---|
| 创建项目、品牌、Prompt | `frontend/src/App.tsx`、正式 V2 API | T01 `49fa7c2`; T03 `d713872`; T04 `3c33ab8` | acceptance matrix；任务 DONE | 可进入配置和版本绑定流程 | PARTIAL |
| 固定采样范围、Run/Attempt 和恢复 | Monitor/V2 任务与状态 API | T02 `b924ea2`; T05 `3141a36`; T06 `50061d2`,`63bbf03`; T07 `6193a95`,`e0a84bb`,`c3b30a9`,`a360fdd`,`dcb4b64`,`c8dfaad`,`e6216b6` | T02–T07 工程/浏览器证据；真实 T05 已验收 | 可追踪冻结样本，完整恢复闭环仍需更多真实证据 | PARTIAL |
| Monitor 指标和趋势 | `ObservationPanel.tsx`、Monitor 页面 | T06 `50061d2`,`63bbf03`; T07 `6193a95`,`e0a84bb`,`c3b30a9`,`a360fdd`,`dcb4b64`,`c8dfaad`,`e6216b6` | 浏览器和专项 Gate | 用户可查看指标与范围 | PARTIAL |
| Optimize 诊断、策略、渠道和稿件 | `AutomaticOptimizePanel.tsx`、`automatic_delivery.py`、`delivery_revision.py` | T08 `5227839`; T19 `8da441c`,`bdebd14`,`a655f2f`,`4840973` | 工程 Gate、UI 入口；T23 真实交付失败 | 具备入口，但真实可用稿件闭环未证明 | PARTIAL |
| 答案/证据关系纠错 | `AnswerRelationCorrectionPanel.tsx`、`answer_relation_corrections.py` | T19 `8da441c`,`bdebd14`,`a655f2f`,`4840973` | 纠错专项测试和 UI | 可保存 append-only 纠错并显示影响范围 | VERIFIED |
| 来源正文和 Citation 刷新 | `SupplementalSources.tsx`、来源准备服务 | T09 `118de20`,`c3b30a9`,`25377fc`,`3ce1573`,`81b7597`,`90efdf4`,`2e32d42`,`076942c`,`ecc69af`; `850ca27` | URL 1/1、HTTP 200、23 passed | 新旧 Snapshot 可追踪，但未完成正式重分析 | PARTIAL |
| 三类真实自动交付 E2E | `run_t23_delivery_live.py`、`t23_real_e2e_acceptance.py` | T23 `73808ce`,`2083754`,`17ea90a`,`e06b972`,`2c00875`,`7736456`,`2061b80`,`726859c`,`beabee1`,`76194c1`,`3e563f6`,`04a9b08` | 4/9 ledger、真实 receipt 和 blocker | 没有一类完整达到正式 Definition of Done | BLOCKED |
| 持续采样和独立比较 | `ObservationPanel.tsx`、Validate API | T21 `1da0027`,`b132d5f`,`63bbf03`,`c3b30a9`,`a360fdd`,`dcb4b64`,`c8dfaad`,`e6216b6`; T22 `c2d0052` | 双范围工程/浏览器证据 | 可操作比较；缺完整真实新增采样业务证据 | PARTIAL |
| 真实发布或 CMS | 产品基线明确后置 | T20/发布用例 OUT_OF_SCOPE | acceptance matrix | 不属于 1.0 必需前置 | VERIFIED |

## 4. 完成度（不合并为综合百分比）

| 类别 | 计数 | 解释 | 状态 |
|---|---:|---|---|
| 代码任务台账辅助指标 | 12/26 DONE | T00–T08、T19、T21、T22 为 DONE；2 BLOCKED、2 WAITING_DEPENDENCIES、9 IN_PROGRESS、1 OUT_OF_SCOPE；这不是代码覆盖率 | PARTIAL |
| 独立需求实现/UI覆盖 | UNKNOWN/68 | 可枚举 68 个唯一需求 ID，但缺少逐 ID 的代码/UI 证据映射，因此 verified numerator 为 UNKNOWN | UNKNOWN |
| 验收用例辅助指标 | 20/69 PASS | `acceptance_cases.json` 另有 26 PARTIAL、19 NOT_RUN、4 OUT_OF_SCOPE；不是产品完成率 | PARTIAL |
| 真实业务验收 | 0/5 完整 E2E | E2E-01/02/03 被 T23 阻断；E2E-04、E2E-05 尚无完整真实闭环证据 | BLOCKED |
| Monitor→Optimize→Validate 完整闭环 | 0/1 | 三段主链都有工程入口，但没有一份真实证据证明从输入到交付再到独立比较完整收口 | BLOCKED |

辅助事实：`acceptance_cases.json` 当前为 20 PASS、26 PARTIAL、19 NOT_RUN、4 OUT_OF_SCOPE；这些是用例状态计数，不等同于全产品完成率。

## 5. 分模块审计

### Monitor

`ObservationPanel.tsx` 提供 Monitor/Compare 两种模式、固定范围、历史比较恢复和不可比较提示；`App.tsx` 提供正式导航。T06/T07 已 DONE。指标口径和失败/UNKNOWN 的工程保护较完整，但当前证据主要是本地/隔离浏览器和既有真实样本，不能证明所有新项目从零到真实多 Prompt 监测均可完成。因此为 `PARTIAL`，不是缺失入口。

### Optimize

`AutomaticOptimizePanel.tsx` 串接分析状态、事实纠错、答案/关系纠错、策略和稿件；后端已有固定诊断、策略、稿件身份及 QA Gate。T19/T19-02 的纠错与策略重投影切片已具备业务约束。但 T23 E1 的真实 Draft 因 `INVALID_DRAFT_EVIDENCE` 被拒绝，且 E2/E3 无法形成可用正式输入，故“代码存在”与“稳定交付”必须分开记为 `PARTIAL/AT_RISK`。

### Execution

`ManuscriptPreview.tsx`、稿件编辑和 Delivery API 有具体内容、来源和 QA 入口，支持 append-only 修订和局部影响范围。真实 T23 没有完成一条自动生成稿件的正式闭环；不能用历史单 Run 或 Mock 推导稳定交付。状态 `AT_RISK`。

### Validate

`ObservationPanel.tsx` 明确要求两个不同范围，支持刷新、历史结果隔离、不可比和 UNKNOWN 说明；T21/T22 DONE。根据验收矩阵，E2E-04 仍需要后续真实采样和同口径比较，当前只能 `PARTIAL`。

## 6. 五类 E2E

| 场景 | 正式要求 | 当前证据 | 状态 |
|---|---|---|---|
| E2E-01 充分引用自动交付 | 真实输入、Optimize、QA、具体可用稿件 | T23 E1 Answer prepare 通过，但 Draft 被 `INVALID_DRAFT_EVIDENCE` 拒绝，未形成 Delivery | BLOCKED |
| E2E-02 低匹配仍有行动 | 真实低匹配 Contribution、探索行动和稿件 | T23 得到 `SUPPORTS_PARTIAL/RELATED_ONLY`，不是 formal low-match；正确冻结 `NO_FORMAL_LOW_MATCH` | BLOCKED |
| E2E-03 部分未知仍交付 | 正式 UNKNOWN provenance，同时保留有依据内容 | T23 Answer 没有目标品牌能力 signal，正确冻结 `NO_FORMAL_UNKNOWN_SIGNAL`，未伪造 UNKNOWN | BLOCKED |
| E2E-04 持续监测与独立比较 | 新真实采样、Monitor 更新、两个固定范围比较 | T21/T22 代码和浏览器隔离证据；缺完整新增真实样本比较证据 | PARTIAL |
| E2E-05 运行和数据语义恢复 | 重复提交、查询、重启、归属与历史保持 | T02/T06 等有局部恢复、幂等和浏览器证据；未形成全部正式多项目真实闭环 | PARTIAL |

## 7. 偏离、缺失和过度建设

### 偏离或缺失

- T09 的真实 URL 刷新已完成，但正式重分析仍缺已完成、已审核、同范围的下游基线；将 T09 写成 DONE 会偏离验收矩阵。
- T23 有真实请求和可审计账本，但三类场景均未满足 Definition of Done；保持 BLOCKED 是正确行为。
- UI 入口存在不代表从新项目到真实稿件、再到独立比较已经可用；当前缺的是业务闭环证据而不主要是导航。
- 原始最终交付指令文件缺失，需求追踪存在来源可追溯性限制。

### 必要复杂度与疑似过度建设

- 必要：固定 Prompt/Project/Run/Result 身份、append-only 历史、预算账本、单在途请求、失败关闭、Citation/Truth 归属和恢复检查点。这些直接支撑冻结语义和数据安全。
- 现有身份、版本和预算账本不是 OVERBUILT，不能删减语义保护；但继续扩张专用 harness、恢复和审计设施而不先修复真实 UI 闭环，属于 `OVERBUILT（前瞻风险）/DEFER`，不是要求删除现有保护。
- 明确后置或不应扩张：多模型动态路由、复杂知识库/知识图谱、广泛 CMS 发布、复杂调度、计费/SSO、旧接力调度器。它们不应抢占当前闭环修复资源。
- T23 的预算和 prepare-freeze harness 是当前真实验收所需的工程安全设施，不应被误判为用户产品价值本身。

## 8. T23 三类失败根因

| 场景 | 根因分类 | 是否当前产品 P1 | 最小纠偏 |
|---|---|---|---|
| E1 | 当前 frozen 链 31 个 Citation 有 0 evaluations/0 bindings，Strategy `selected_evidence=0`；编排仍花 1 次请求进入 Draft；Provider 返回 4 个 `au-*` 非合法 `evidence_id` 的 `SOURCE_STATEMENT`，触发 `INVALID_DRAFT_EVIDENCE` | 否（无数据破坏/越权），但为高优先级产品交付阻断；输入/样本证据不足、编排未在必败前停止和生成语义质量共同导致，不是 transport/JSON parser 缺陷 | 先建立非空、精确、可归属的 `selected_evidence`，增加请求前不可满足检查；保留 append-only 失败记录，之后才可在既有授权额度内按新场景请求，不建议仅重试。 |
| E2 | 真实 Contribution 只有 `SUPPORTS_PARTIAL/RELATED_ONLY`，没有 formal low-match | 否，正式验收输入资格不满足；harness 正确拒绝 | 先准备可证明、同 Run、可归属的 low-match Contribution；没有资格时不调用模型，不改标签、不换样本冒充。 |
| E3 | 真实 Answer 没有目标品牌能力 signal | 否，正式验收输入资格不满足；harness 正确拒绝 | 先准备正式同项目/Prompt/Analysis provenance 的 UNKNOWN signal；没有资格时不调用模型、不创建任务。 |

## 9. 关键路径

1. 先保持 T23 BLOCKED，保留 4/9 ledger、receipt、Token 和历史证据，不追加新的模型请求。
2. 先形成合法 E1 可消费 evidence 并通过请求前必败检查；之后如仍有业务必要，可在现有授权和剩余预算内按新场景请求，重新通过正式 Draft/QA/Delivery Gate。
3. T09 在具备同范围已完成且已审核 Diagnosis/Result/Review 后，才进行正式重分析并重新验收。
4. T10 依赖 T02、T08、T09；T02 与 T08 已 DONE，但 T09 未 DONE，故不解锁。T23 DONE 后才解锁 T24。
5. 在真实 E2E 未收口前，优先补首次使用、真实交付、持续采样和恢复证据，不扩展新平台和发布能力。

## 10. 优先五项

1. `CORRECT` E1 的冻结 evidence 归属和 Draft admission，补一条不依赖伪造事实的真实可消费交付路径。
2. `CORRECT` T09 合法下游 Diagnosis/Result/Review 基线，完成同 Citation refresh 后的正式重分析验收。
3. `CORRECT` E2/E3 的正式前置数据准备或明确不可满足状态；不通过重标记或换样本强行完成。
4. `CORRECT` 补齐 E2E-04、E2E-05 的真实新增采样、刷新、恢复和历史隔离证据。
5. `CORRECT` 做一次新项目从创建到稿件、再到比较的端到端 UI 复核；把“组件存在”与“用户可完成任务”分开记录。

## 11. 应停止或推迟的活动

- `STOP` 新增 T23 外部请求，直到 E1 先具备非空、精确、可归属的冻结 evidence，并通过请求前必败检查；当前用户授权仍有效（T23 `4/9`、全局 `4/12`），停止原因是输入必败，不是授权不足。E2/E3 也必须先满足正式场景资格，不能靠模型调用探测。
- `STOP` 将 T09/T23 或下游依赖写成 DONE/解锁。
- `DEVIATED` 任何把 Mock、局部工程 Gate、历史样本或失败 Provider 输出改写为完整业务验收的做法。
- `DEFER` 多平台采集、复杂评分、动态模型路由、CMS 发布、完整知识库和旧接力调度器扩展。

## 12. 本批次变化日志

本审计批次对应 `525e152..850ca27`：

- T23 增加场景级 blocker、prepare-freeze 恢复、预算/身份保护和真实三场景记录；真实结果如实保持 BLOCKED。
- T09 增加同 Citation 的真实 Snapshot/Completion Manifest 刷新记录；正式重分析仍 BLOCKED。
- `tasks.json` 更新 T09/T23/T24 的当前 blocker 和 checkpoint，没有改变历史失败或 UNKNOWN 的语义。
- 新增 `live-acceptance-t09-t23-2026-10-19.md`，记录 URL、请求身份、ledger、失败原因和正式限制；未包含密钥、客户数据或生产数据。
- 本次审计未修改上述提交内容，仅新增本报告文件，且不提交 Git。

## 最终裁决

**AT_RISK / CORRECT**：当前工程方向和失败关闭行为基本正确，可以继续进行最小纠偏；不能宣布 GEO 1.0 完整交付，也不能将 T09/T23 标记 DONE。最小纠偏是围绕 E1 合法 evidence、T09 已审核下游基线、E2/E3 正式前置事实和 E2E-04/05 真实闭环补证据，不重建调度器、不扩大外部授权。

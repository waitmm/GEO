# RFC-GRADED-DELIVERY-001: Evidence-Graded Product Delivery

```yaml
rfc_id: RFC-GRADED-DELIVERY-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: NOT_IMPLEMENTED
authors: [Codex]
created_at: 2026-10-19
definition_approved_by: Product Owner
definition_approved_at: 2026-10-19
definition_approval_reference: GEO 1.0 graded-delivery Definition Freeze instruction / docs/semantics/approvals/RFC-GRADED-DELIVERY-001.definition-freeze.md
production_cutover_approved_by: Product Owner
production_cutover_approved_at: 2026-10-19
production_cutover_approval_reference: same instruction, conditional on the RFC Cutover Gate
affected_contracts: [SC-DELIVERY-001@1.0.0, SC-UNKNOWN-001@1.0.0, SC-AUTOMATION-001@1.0.0]
supersedes: null
```

## Problem

当前自动 Optimize 会把某一用途的 Evidence 不合格同时当作整个任务不能继续的条件。
这能阻止虚假事实，却也会抹除仍然可以合法交付的研究提纲、核验步骤和恢复动作。
交付是否有用户价值，与某条事实是否具备公开陈述资格，必须分轴表达。

## Classification

`SEMANTIC_CHANGE`：新增正式交付级别和各级完成语义，不修改 Evidence、Product
Truth、权限、预算或历史身份的硬约束。

## Current Semantics

- `SC-UNKNOWN-001` 禁止把 UNKNOWN 升级成事实。
- `SC-AUTOMATION-001` 已允许按用途独立资格判断，缺失依赖只影响对应用途。
- `SC-DELIVERY-001` 允许消费合格的部分输入，并要求保留 excluded/unknown 成员。
- 当前 `automatic_delivery` 在 Draft 请求前遇到缺少 Evidence 时把整个任务置为
  `BLOCKED`，没有形成独立、可恢复的低证据交付结果。

## Observed Failure

真实 E1 冻结范围包含 31 个 Citation。一次 Citation Contribution 响应因冗余身份
回显被整批拒绝并触发 fail-fast，最终投影为 0 Evaluation、0 Binding 和 0 Selected
Evidence。旧任务仍尝试生成要求 Evidence ID 的 Draft，得到
`INVALID_DRAFT_EVIDENCE`。即使最终确实没有合格 Evidence，现有任务也只能停止，
不能向用户交付受约束的行动或恢复结果。

## Proposed Semantics

新增确定性的 `DeliveryQualificationPlan.v1` 和
`DeliveryQualificationResult.v1`。它们不是综合置信分，也不是 Evidence Judge；只在现有
硬 Gate 之后决定当前固定输入允许哪种交付，以及实际输出是否被接纳。

正式字段是封闭枚举，不能从 UI 文案、Evidence 数量或另一个字段推导：

```text
workflow_terminal_state = RUNNING | WAITING_AUTHORIZATION | BLOCKED | COMPLETED | COMPLETED_WITH_LIMITATIONS
product_outcome = CONTENT_DELIVERED | RECOVERY_REQUIRED | NONE
planned_delivery_level = L1_FULLY_GROUNDED | L2_PARTIALLY_GROUNDED | L3_ACTIONABLE_WITHOUT_FACT_CLAIMS | L4_RECOVERY_PACKAGE
admitted_delivery_level = L1_FULLY_GROUNDED | L2_PARTIALLY_GROUNDED | L3_ACTIONABLE_WITHOUT_FACT_CLAIMS | L4_RECOVERY_PACKAGE | REJECTED | NOT_APPLICABLE
delivery_type = GROUNDED_DRAFT | BOUNDED_DRAFT | ACTION_PLAN | RESEARCH_BRIEF | INSTRUCTION_ONLY_DRAFT | RECOVERY_ACTIONS
evidence_qualification = FULLY_GROUNDED_FOR_SELECTED_BLOCKS | PARTIALLY_GROUNDED_FOR_SELECTED_BLOCKS | EVALUATED_NO_SUPPORT | SOURCE_UNAVAILABLE | NOT_EVALUATED | INPUT_UNAVAILABLE | INTEGRITY_BLOCKED
public_claim_eligibility = CONSUMABLE | VERIFY_FIRST | NOT_CONSUMABLE
publication_eligibility = ELIGIBLE_PENDING_BUSINESS_APPROVAL | VERIFY_FIRST | NOT_CONSUMABLE
```

`VERIFY_FIRST` 从不是发布许可；只有新 append-only 结果消费新合格 Evidence/Truth 并获得
独立业务授权后才能升级。producer 顺序固定为：

```text
exact input qualification
-> immutable Plan（请求前等级、schema、allowlist）
-> optional bounded Draft request
-> output admission + level-specific QA
-> immutable Result（接纳同级/更低级，或 REJECTED）
```

Plan 不读取尚未发生的 QA；Result 绑定精确 Plan。QA 不得升级等级，也不得把非法正文
原地改标 L2/L3 后保留。

Plan 阶段 `product_outcome` 始终为 `NONE`；只有 append-only Result 能产生实际产品结果：

| Planned level | 合法 admitted level | Result product_outcome | 合法 delivery_type | Evidence | Draft/QA |
| --- | --- | --- | --- | --- | --- |
| L1 | L1 / L2 / L3 / REJECTED | admitted 时 CONTENT_DELIVERED；rejected 时 NONE | GROUNDED_DRAFT，或经删除并重新验证后的更低级类型 | L1 必须 FULLY_GROUNDED_FOR_SELECTED_BLOCKS | 授权内允许 |
| L2 | L2 / L3 / REJECTED | admitted 时 CONTENT_DELIVERED；rejected 时 NONE | BOUNDED_DRAFT，或经删除并重新验证后的 L3 类型 | PARTIALLY_GROUNDED_FOR_SELECTED_BLOCKS | 授权内允许 |
| L3 | L3 / REJECTED | admitted 时 CONTENT_DELIVERED；rejected 时 NONE | ACTION_PLAN / RESEARCH_BRIEF / INSTRUCTION_ONLY_DRAFT | EVALUATED_NO_SUPPORT / SOURCE_UNAVAILABLE / NOT_EVALUATED，且 integrity PASS | 只允许 INSTRUCTION |
| L4 | L4 | RECOVERY_REQUIRED | RECOVERY_ACTIONS | INPUT_UNAVAILABLE | 禁止，0 调用 |

较低级 Result 只有在非法 block 已被确定性删除、剩余全文按较低级 schema 重新验证且形成新
Result hash 时才合法；不能保留失败正文。`highest_level/lowest_level` 只用于 UI 排序和摘要，
没有 Evidence 推断能力。

生命周期合法组合闭合如下：

| workflow_terminal_state | Plan | Result | product_outcome | 下游内容依赖 |
| --- | --- | --- | --- | --- |
| RUNNING | L1/L2/L3 | 尚无 | NONE | 不满足 |
| WAITING_AUTHORIZATION | L1/L2/L3 | 尚无 | NONE | 不满足 |
| BLOCKED | L1/L2/L3，或因 integrity 无 Plan | REJECTED 或尚无 | NONE | 不满足 |
| COMPLETED | L1/L2/L3 | 同级或合法较低级 admitted | CONTENT_DELIVERED | 仅按实际 admitted Result 判断 |
| COMPLETED_WITH_LIMITATIONS | L2/L3 | 同级或合法较低级 admitted | CONTENT_DELIVERED | 仅按实际 admitted Result 判断 |
| COMPLETED_WITH_LIMITATIONS | L4 | L4 recovery Result | RECOVERY_REQUIRED | 不满足 |

`WAITING_AUTHORIZATION` 和 `BLOCKED` 永远不能带 `CONTENT_DELIVERED`。L4 Result 保存于
task `objects.recovery_delivery`，包含自身 qualification ID/version/hash、缺失对象、固定范围、
恢复动作及重新进入条件；不得写入 `objects.deliveries`。

`INTEGRITY_BLOCKED` 不存在合法 L1–L4 内容交付组合，必须保持 `BLOCKED`。可以展示只读
恢复提示，但它不是 DeliveryQualificationResult。

L4 Plan 只允许在身份、权限、版本和固定范围 integrity 全部 PASS 后形成。若 L4 候选输入在
Plan 前或 Result 前发生 integrity failure，不得写入 Plan 或 Result，也不得将失败表示为
`L4 + REJECTED`；唯一合法状态是 `BLOCKED + product_outcome=NONE`，并保存独立错误记录。

### L1 — FULLY_GROUNDED

- `delivery_type=GROUNDED_DRAFT`
- 每个事实 block 都绑定当前固定范围内可消费的 Evidence 或 Product Truth。
- Strategy、Draft allowlist、实际 block ID 和 QA 范围完全一致。
- QA 必须逐 block 验证事实、主体、条件、数字、Evidence/Truth ID。
- L1 是 E1 / E2E-01 的必要非充分条件。E1 还必须有真实可取 Citation、同 Run
  Contribution/Binding、正文中的可定位来源以及正式 UI/QA 证据；只有 Product Truth 的 L1
  不能通过 E1。

### L2 — PARTIALLY_GROUNDED

- `delivery_type=BOUNDED_DRAFT`
- 只有独立通过硬 Gate 的事实可以写成事实 block。
- 未证明部分只能删除，或明确写成假设、待核验问题和补证动作。
- 每个 block 独立记录资格；不得给整篇稿件笼统标记“已有证据”。
- 真实 UNKNOWN 且仍存在其他可消费信息时，L2 可满足 E3 / E2E-03；全无信号不可冒充。

### L3 — ACTIONABLE_WITHOUT_FACT_CLAIMS

- `delivery_type=ACTION_PLAN | RESEARCH_BRIEF | INSTRUCTION_ONLY_DRAFT`
- 可输出问题现状、研究问题、编辑提纲、候选渠道核验步骤、补证清单和验证条件。
- 只允许不携带未经支持事实的 `INSTRUCTION` block；不得输出未经证明的定义、
  品牌能力、数字效果、平台规则、Citation 支持或渠道因果。
- `public_claim_eligibility=NOT_CONSUMABLE`，`publication_eligibility=VERIFY_FIRST`。
- E2 / E2E-02 只有在真实低匹配样本资格成立时才可由 L3 通过；普通 L3 不自动通过专项场景。

### L4 — RECOVERY_PACKAGE

- `delivery_type=RECOVERY_ACTIONS`
- 对无有效回答、缺失固定输入或当前无法分析的范围，确定性输出缺失对象、原因、
  采样/修复动作和重新进入条件。
- 外部模型调用为 0；不是 Strategy、Draft 或 QA PASS。
- 可正常形成技术终态 `COMPLETED_WITH_LIMITATIONS`，但产品目标状态必须明确为
  `RECOVERY_REQUIRED`，不能通过 E1/E2/E3。
- 不满足 Optimize 内容交付依赖，不进入 `deliveries` 或 current Delivery result，不解锁依赖
  Strategy/Draft/QA/Delivery 的任务。正式依赖状态源是 `product_outcome`，不是技术终态。

## Hard Gates

以下始终不可配置，也不能通过降级规避：

- UNKNOWN、失败或未评估结果升级为确定事实；
- 无 Evidence 的 `SOURCE_STATEMENT`；
- 无合格 Product Truth 的目标品牌能力声明；
- 虚构或跨 Project/Prompt/Run/version/hash 使用 Evidence ID；
- 原地覆盖历史 Result、Strategy、Draft 或 QA；
- 未授权外部调用、公开动作、费用或未知送达后的隐式重试。

只有标题、结构、动作优先级、证据充分度呈现和交付类型可以在上述 Gate 后配置。同一事实
Gate 覆盖 title、heading、summary、行动理由、渠道说明、modal 文案及正文；“可能/建议/探索”
不能洗白未经支持的事实命题。

## Affected Domain Objects

`DeliveryQualificationPlan.v1` 和 `DeliveryQualificationResult.v1`：

- identity：qualification ID/version/hash + automatic task ID + exact Analysis/Context + fixed Run
  set/hash + exact Diagnosis/Strategy/Contribution/Truth partition/Proposal result versions and hashes +
  `direction_id` + `proposal_id` + block allowlist/hash + qualification contract version；
- Plan Source of Truth：请求前当前精确版本的 per-use qualification 与冻结 Delivery input；
- Result Source of Truth：精确 Plan、接纳 Draft 与分级 QA；
- producer：Automatic Optimize 每个 direction/proposal 确定性产生一个 Plan 和可选 Result；
- consumers：正式任务 API、Optimize UI、Draft/QA caller；
- history：append-only 随任务/result 保存，旧结果不追溯重分类。

L4 是唯一无 direction 的例外：`direction_id/proposal_id=null`，因为不得虚构 Strategy/Proposal；
仍必须绑定 task/Analysis/Context/Run/hash 和自身 version/hash。任务聚合只保存各方向等级及
`highest_level/lowest_level/all_directions_l1`，一个 L1 方向不能升级其他 L2/L3 方向。

## Contract Diff

```text
old contract/version: SC-AUTOMATION-001@1.0.0 + implicit all-or-block task outcome
new contract/version: SC-GRADED-DELIVERY-001@1.0.0
allowed inference diff: independently qualified uses may form L2/L3; invalid input may form deterministic L4
forbidden inference diff: a lower level never upgrades factual/public eligibility or passes a higher-level E2E
unknown behavior diff: UNKNOWN remains non-consumable for facts but produces explicit verification/recovery actions
step boundary diff: no new workflow step; qualification projects the existing Strategy/Execution input before Draft
```

## Golden Cases

固定身份见 `docs/semantics/snapshots/CASE-GRADED-DELIVERY-001.manifest.json`：

- Real E1：精确隔离库、task、Analysis/Context、Run 2、Manifest、Contribution、Strategy、
  Proposal 与被拒缓存。安全回放证明 10 evaluations / 4 supporting bindings，但不是 E1 PASS。
- Synthetic L1：精确 direction/proposal/block allowlist、Evidence/Truth、grounded blocks、
  Plan L1、QA READY、admitted L1 和 CONTENT_DELIVERED；仍不冒充真实 E1。
- Synthetic L2：一个可消费 Evidence + 一个 UNKNOWN Truth；只允许支持 block 成为事实。
- Synthetic L3：formal low-match 形状、无可消费 Evidence、只允许 INSTRUCTION；不冒充真实 E2E-02。
- Synthetic L4：无可消费 Answer、0 外调、下游依赖不满足。
- Mixed：一个 L1 direction + 一个 L3 direction；task aggregate 不是全 L1。

## Counterexamples

1. Given 无合格 Evidence，when 模型返回 `SOURCE_STATEMENT`，expected 拒绝；forbidden 自动改标 L3 后保留正文。
2. Given Product Truth UNKNOWN，when 文本声明目标品牌具备能力，expected 拒绝；forbidden 改写成“可能具备”并声称事实。
3. Given L3 合法行动稿，when E1 验收，expected E1 仍失败；forbidden 用“流程完成”替代完整证据闭环。
4. Given identity/hash 不一致，expected 硬阻断；forbidden 生成 L4 来隐藏数据完整性错误。
5. Given L3 title/heading/行动理由夹带未经支持的平台规则，expected 拒绝；forbidden 因条件化措辞而保留。
6. Given L4 `COMPLETED_WITH_LIMITATIONS`，expected Draft/QA/Delivery 依赖仍不满足；forbidden 解锁 T23/T24。
7. Given 一个 L1 和一个 L3 direction，expected 分方向结果及非全 L1 聚合；forbidden 整任务标 L1。
8. Given QA 发现非法事实，expected Result=REJECTED；forbidden 原地改标 L2/L3 并保留正文。
9. Given planned L1 但 Draft/QA rejected，expected product_outcome=NONE；forbidden 提前写 CONTENT_DELIVERED。
10. Given E3 只有 Answer topic 且无可消费 Evidence/Truth，expected 最多 L3；forbidden 当作 L2 可发布事实。
11. Given Citation relation=RELATED_ONLY，expected 不满足当前 E2 谓词；forbidden 通过开放式 low-match 集合接纳。

## Identity / Scope Impact

不改变任何既有对象 identity。新增资格对象完整绑定固定任务和所有被消费结果版本。
新级别只适用于新任务/新结果；旧失败、历史 Evidence、Strategy、Draft 和 QA 保持原解释。

## UNKNOWN Semantics

UNKNOWN 永不升级为事实。它可以成为明确的核验问题、下一步动作或 L2/L3 限制，
但不能成为事实 block、已证明策略依据或发布资格。

## Specialized E2E Qualification Predicates

Delivery level 与专项场景资格互相独立：

- E1/E2E-01：admitted L1 + 真实 Citation URL/SourceSnapshot/Passage + 同 Run DONE 的
  `SUPPORTS_FULL|SUPPORTS_PARTIAL` Binding 被 Strategy 和最终 block 消费 + 精确版本/hash +
  READY QA + 正式浏览器证据。
- E2/E2E-02：真实成功且可归属的 Run；同 Run immutable Citation Contribution；目标 Citation
  terminal DONE 且 disposition=`NO_BINDING_FOUND_AFTER_SEARCH`；对应 terminal Evaluation DONE，
  relation 必须严格为 `NO_MATCH`（谓词版本 `e2e02-low-match.v1`）；该 Citation 无 supporting Binding；L3
  必须含非空、问题相关 INSTRUCTION、明确假设及验证条件。
- E3/E2E-03：同项目原子 Product Truth=`UNKNOWN`，绑定 source Diagnosis/result/signal 及 target
  Prompt/Analysis，同时存在另一独立可消费 Evidence 或 Product Truth 子集形成有用 L2 事实内容；
  Answer topic 只能用于 L3 的 INSTRUCTION/研究问题，不能独立支撑 L2。UNKNOWN ID 不得进入
  used evidence，仅待补清单不通过。

当前真实 T23 E2/E3 输入仍不合格，本 RFC 不重新标记它们。

## Step Boundary And Allowed Consumers

本 RFC 不增加 Step 9，不创建第二套 Optimize。现有资格投影仍生产 Strategy Direction
和内部 Execution Draft。DeliveryQualification 只选择同一主链的交付形式，并限制 Draft/QA
可消费的 block 类型。外部发布继续需要独立业务授权。

## Implementation Plan

1. 在现有资格投影和 Draft 预检中按 direction 确定性生成 Plan。
2. 复用现有 `RESEARCH_GUIDE_NOT_FACTUAL_ANSWER` 与 `INSTRUCTION` block；不新增推理主链。
3. L4 在进入任何模型调用前形成确定性恢复包。
4. QA 后追加 Result；API/UI 显示分方向等级、允许输出、限制、QA 和下一步。
5. E1/E2/E3 专项 Gate 与通用产品闭环 Gate 分开统计。

## Historical Compatibility And Migration

无 migration、无回填、无历史重分类。旧 `BLOCKED` 和失败调用保持原状态；修复后由
新 append-only 任务生成新资格与交付结果。回滚后已有分级对象继续只读展示为 frozen
historical result，不读取旧实现重新计算。

## Shadow Plan

对现有 E1 缓存、确定性 L2/L3 fixtures 和零回答 fixture 比较 current/proposed。
切换前确认无新事实、无 identity 漂移、无额外外调、E1 专项不会被低等级结果通过。

## Cutover Gate

- Definition Review APPROVED 且 Product Owner Definition Freeze 已记录；
- L1–L4 正负向测试和真实 E1 缓存回放通过；
- API/UI 刷新保持相同的分方向 Plan/Result 等级和固定 identity；
- 没有 P0/P1、没有开放冲突阻断本 RFC；
- Product Owner 已独立授权本次最小正式 cutover。

## Risks And Conflicts

- 与 `SC-UNKNOWN-001` 的风险：必须把“可继续”限定为交付行动，不是允许事实继续传播。
- 与旧 Step 7/8 人工确认路径的风险：L3/L4 不是已确认 StrategyCandidate、Action、
  Experiment 或 Publication。
- 当前未发现需要改写既有 FROZEN 对象身份的冲突；独立 Definition Review 决定是否登记 Conflict。

## Rollback

代码回滚恢复旧 all-or-block 行为；已经生成的分级结果仍保持 append-only，不删除、不升级。

## Approval Gates

1. Definition Freeze：独立 Definition Review 已通过，Product Owner 已于 2026-10-19 明确批准。
2. Implementation/Shadow：已授权按本冻结定义实施。
3. Production Cutover：仅限本 RFC 的最小单主链改造，由 Product Owner 当前“直接完成最小产品改造并集成”指令授权，须在 Gate 全部通过后生效。

## Definition Review

```text
Status: APPROVED
Contracts Referenced: SC-DELIVERY-001@1.0.0, SC-UNKNOWN-001@1.0.0, SC-AUTOMATION-001@1.0.0, SC-STRATEGY-001, SC-STEP7-001, SC-STEP8-001
Golden Snapshot IDs: CASE-GRADED-DELIVERY-001@2026-10-19, GRADED-L1-NORMAL
Blocking Issues: none
Category Error Audit: PASS; L4 exists only after integrity PASS. Integrity failure is BLOCKED + NONE with no Plan/Result.
Causal Audit: PASS; immutable pre-request Plan and exact post-admission Result binding remain separate.
Identity / Scope Audit: PASS; L1 qualification, Plan and Result IDs, versions and hashes are fixed and Result binds exact Plan.
Forbidden Inference Audit: PASS; L4 unlocks no content dependency and synthetic L1 is not real E1 acceptance.
Golden Cases: PASS; the L1 fixture fixes identity, Plan, Result, QA and product-outcome semantics.
Counterexamples: PASS; L4 + REJECTED is explicitly illegal.
Step Boundary: PASS; no second Optimize chain or workflow step.
Historical Compatibility: PASS; append-only new results, no historical reclassification.
Contract Gaps: none blocking
Freeze Recommendation: YES
```

## Product Owner Approval

Product Owner 于 2026-10-19 正式批准两项最终修订、Definition Freeze，以及 Cutover Gate
通过后的最小单主链实现与受控 integration 集成。批准不允许伪造 Evidence、降低身份/权限/
版本硬约束、回写历史或创建第二套 Optimize 主链。

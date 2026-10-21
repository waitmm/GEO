# RFC-MANUAL-RUN-IMPORT-001: Manual Observation Run Admission

```yaml
rfc_id: RFC-MANUAL-RUN-IMPORT-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: PRODUCTION
authors: [Product Owner, Codex]
created_at: 2026-10-21
definition_approved_by: Product Owner
definition_approved_at: 2026-10-21
definition_approval_reference: GEO M1 — MANUAL_IMPORT 窄语义契约批准
production_cutover_approved_by: Product Owner
production_cutover_approved_at: 2026-10-21
production_cutover_approval_reference: 同一批准指令；仅限本机 GEO M1 Beta
affected_contracts: [SC-DELIVERY-001@1.0.0, SC-HISTORY-001@1.0.0, SC-SCOPE-001@1.0.0, SC-GRADED-DELIVERY-001@1.0.0]
supersedes: null
```

## Classification

`SEMANTIC_CHANGE`：新增一种合法 Run 来源，不改变分析、Evidence、Product Truth 或分级交付语义。

## Definition

`MANUAL_IMPORT` 是用户把在指定 AI 平台实际观察到的完整回答和引用记录提交给 GEO 后，
由服务端重新验证 Project、Prompt、PromptVersion、ProjectConfigurationVersion、时间归属和
内容 hash 所形成的不可变 Run。它是“带人工来源声明的观测”，不是平台真实性的独立证明，
也不是 Playwright 自动采集。

## Admission

- 服务端验证访问权限、Project/Prompt 归属以及明确版本 ID/hash。
- `observed_at` 必须落在 PromptVersion 与 ProjectConfigurationVersion 各自的生效区间内；
  禁止使用 `latest` 回填或把旧回答绑定到观察时尚未创建的版本。
- 保存完整回答、引用记录、平台、导入人、服务端导入时间、不可变 hash 和
  `USER_ATTESTED_UNVERIFIED` 来源声明。
- 引用状态是封闭枚举：`COMPLETE`、`CONFIRMED_NONE`、`UNKNOWN`、`PARSE_FAILED`。
  未提供引用不能解释为零引用。
- 相同幂等键和相同 payload 返回原 Run；相同幂等键但不同 payload 或相同观测内容的重复
  计数请求必须拒绝。
- 合格 Run 可进入明确时间范围或 Run ID 选择，并通过现有冻结分析链消费。

## Forbidden Inferences And Actions

- 内容 hash 只证明本地内容未变，不能证明回答确实来自所声明平台。
- 不得把人工导入标记成浏览器自动采集，或把 `LEGACY_UNBOUND` 原地升级。
- 导入不得自动触发 Answer/Citation 语义分析、Optimize、Evidence Pack、Validate、抓取或模型调用。
- 不得改写历史 Run、AnalysisContext、ResultVersion、Truth、Review 或 Gate。
- Product Truth、Evidence 和 `SC-GRADED-DELIVERY-001` 的硬门槛保持不变。

## Identity And History

身份由 Project、Prompt、明确 PromptVersion/configuration version、observed_at、source platform、
answer hash、citation record hash、method=`MANUAL_IMPORT` 和 importer 共同构成。导入记录与 Run
追加保存；后续新采样或新版本不得改变它。消费者必须展示人工来源及未独立核验限制。

## Step Boundary

本契约只扩展 Step 1 的 Run 入口。服务端准入成功只表示该观测可被选择，不表示任何品牌、
推荐、引用支持、事实或交付结论成立。

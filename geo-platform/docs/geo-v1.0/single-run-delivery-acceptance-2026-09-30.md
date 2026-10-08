# 单 Run 正式交付链验收记录（2026-09-30）

## 1. 本轮结论

本轮按产品负责人调整后的优先级，选择一条真实、完整的既有 Run，在发布数据库中建立独立的
`1/1` Analysis，并通过正式 release API 推进到机器 Strategy、Execution Draft 和自动 QA。

本轮没有重新采样、没有新增外部模型调用、没有重抓网页，也没有修改原九条 Analysis。正文和
Citation Contribution 只在精确身份、内容 hash、passage hash 和合同版本兼容时复用。

当前真实停止点是用户业务确认，不是计算失败：系统已自动完成资产类型、建议承载渠道、条件式新建/更新
判断和可直接编辑的完整稿件；用户只需确认实际可编辑页面或新建位置、账号/栏目及权限。实际发布、
PublicationRecord、发布后新采样和 Validate 均未伪造。

## 2. 固定输入

| 对象 | 精确身份 |
| --- | --- |
| Project / Prompt | `1 / 1`，Prompt 为“抖音跳转链接” |
| 既有真实 Run | `1`，成功，746 字，19 条引用记录，18 个唯一来源 |
| Run fingerprint | `59db0bcc4fceb43b7b5a8f097f8f268029bf4b1ba9be503f03d4b7a3b1588935` |
| 新 Analysis | `925ef2dc-605f-467d-a025-52033a574d92` |
| Context | `ctx-5407fb2f-acd5-41ac-8ac7-41713a08a5aa` |
| Raw Result | `raw-v1:11dca9e4438bdecf` |
| Raw hash | `11dca9e4438bdecf66a86472f2e8a498f6f7067c3bcc4f9f3cfd381d2c9ebccb` |
| Sampling plan hash | `2744a60cd783ce60a4e8ea5f866d2f0d9f9a2529f4c27218d93cd8eaf4d97674` |

原九条 Analysis `19b0be0f-f794-4435-9fa7-2723257f26cc` 及其 Context、审核和结果均未修改。

## 3. 来源范围与快照

| 对象 | 精确身份 / 结果 |
| --- | --- |
| Source Preparation | `source-prep-b8af9f6d-8009-409a-afe3-eb86ca384cb9` |
| Citation Manifest | `citation-manifest-2c54878d-fe08-4781-ae5d-5a733761c67c` |
| Citation hash | `c0b5ad9c6924e04f117a901059adc4df10b19b9cc57fc05f1be36f833042ef35` |
| 来源守恒 | 18/18 READY，19/19 引用记录，0 WAIVED，0 PENDING |
| Source Completion | `source-completion-d49694de-76da-4ebf-a198-efb101fc1224` |
| Completion hash | `444719912b95cea6a03db1cfbf85196c4dd61e5b9b4772486d4b525e54fab1cf` |
| Passage 总数 | 451 |

18 个 Analysis-owned Snapshot：

1. `source-snapshot-236b1310-07cf-4b9a-a677-d184917da29d`
2. `source-snapshot-3ea3bff6-07ff-4668-9cee-2625f697c09d`
3. `source-snapshot-07e83570-db7a-47b3-a5a4-696a15508263`
4. `source-snapshot-5b057428-ff83-42b6-83cc-ede2ec9c4b63`
5. `source-snapshot-0e8ae8a1-f2d8-4794-91c5-4baad5fd994e`
6. `source-snapshot-78b2215f-2357-4173-b878-ebdc7fb50897`
7. `source-snapshot-a5949425-6801-4fc9-8eff-2760b71f8667`
8. `source-snapshot-6555669d-23d6-4be4-bf9b-e7dcc81f54df`
9. `source-snapshot-2a6619ec-53cd-4526-b850-05763c95a6d2`
10. `source-snapshot-2248a87a-7e81-4dfa-9e8c-03e6523887fa`
11. `source-snapshot-8313a78f-216c-4094-a41e-f8d4d28dfde9`
12. `source-snapshot-ecfc4e1c-86f6-4091-9d2f-4a94fc2fe023`
13. `source-snapshot-daa1f73a-333b-4483-9949-6ca8cede4d7f`
14. `source-snapshot-3953463a-855f-4e86-91b0-68f006a640b3`
15. `source-snapshot-1cd83452-45e3-4614-a20a-4c7071bc8d35`
16. `source-snapshot-ecc99c06-7381-437d-b520-ee46ae9838fa`
17. `source-snapshot-b0a7ad88-a7d6-4368-89e7-b6eecfed6119`
18. `source-snapshot-e80d869f-8372-4257-85e1-e621992f0019`

每个 Snapshot 都创建在新 Context 的 artifact 路径下，并记录 `reused_from_snapshot_id`。复用 Gate 比较
Project、Prompt、明确 Completion ID/hash、source key、canonical URL、content hash、artifact hash 和
passages hash；没有域名猜测或 `latest` 回退。冻结后 API 只返回 `VIEW`。

## 4. Answer 与 Citation Contribution

| 阶段 | 精确结果 |
| --- | --- |
| Diagnosis | `11d47cb9-3e56-4228-9101-55fdfec19d15` |
| Answer Result | `diag-v1:864a6924a61a3e8b` |
| Answer hash | `864a6924a61a3e8b373cff4b4763be25a3c9af49a9f634fb11464aa53fb3da4f` |
| Answer reviewable hash | `c50eccbe536f32a7aa4c2a9a159db2a00ad79be4ef8a2355eadfb46d2dbed990` |
| Answer 结果 | 1/1 ADMITTED，1 个“对号短链”弱选项事件，1 个 grounded reason |
| Answer 调用 | 0 次外部调用，1 次严格兼容缓存复用 |
| Contribution | `citation-contribution-ac2945d2-2737-4cc5-9c2e-40dcd906b530` |
| Contribution Plan hash | `3e80fdff2de5e60a88ad67cb32d7952e7cd084f038da71f53ee9885c252330cf` |
| Contribution input hash | `fb76a570bcaf36c4e908450720f08782c304becfb47c27e1eea1c267d4ba0642` |
| Contribution Result | `contribution-v1:be21567a6d114f4b` |
| Contribution hash | `0248892c21efdf4df4e26a42190a45e45c0099dde6b3178eda6db7a6b1b23ab3` |
| Contribution 结果 | 18 AnswerUnits，19 Citations，192 evaluations，22 bindings；16 DONE / 3 FAILED |
| Contribution 调用 | 0 次；由 `contribution-v1:dd80ec35eab9fe62` 精确兼容物化 |

本轮没有复制旧 Human Review。三条历史 Contract 失败继续是限制，未改写成 `NO_MATCH`。目标品牌“爱短链”
未出现在 Run 1 回答正文中；某条引用来自爱短链页面不能被提升为回答推荐目标品牌或生成因果。

## 5. 自动策略、完整执行稿与 QA

| 对象 | 精确身份 / 状态 |
| --- | --- |
| Qualification projection | `5651a90d8c8baa12e2bc7da78ac91cb9f79221f1f95d12ccf409a65e69289ca0` |
| Strategy | `strategy-ef6ac968-c400-4528-8913-634b4216eada` |
| Strategy Result | `strategy-v1:178f23f7c8de96a1` |
| Strategy hash | `178f23f7c8de96a1faa8d98a27138ae138212fafc45f89ae240ce07c381fe830` |
| Strategy authority | `MACHINE_QUALIFICATION`，不伪造人工 Review |
| Direction | `strategy-machine-40561c088482ff4d480d`，`DISCOVERY / ACTIONABLE` |
| Execution Proposal | `execution-proposal-43feb8f4-26b1-4eb2-b6c0-74298af17fb4` |
| 初始骨架 Result | `execution-v1:a7a640779ae7e104`（保持不可变） |
| 当前 Execution Result | `execution-v5:2121b5e21d0ac6df` |
| 当前 Execution hash | `2121b5e21d0ac6df1529d5f66d865a6f63fb63bb69646348e9382679a357a9f7` |
| Reviewable set hash | `e44886aca7a59781e11c753bbb65f76ed9fbfd7a9abd2bc3e70f5fddd4be37d2` |
| 正文 content hash | `a3ec35fd54f7a86965afcbcd2e9db6151eda45e0cd4ffef2e46bbefc00d2fd9e` |
| 当前状态 | `READY_FOR_BUSINESS_INPUT`；内容 `READY`，发布 `NEEDS_BUSINESS_CONFIRMATION` |

策略明确回答：本 Run 未观察到目标品牌，因此建立一份围绕“抖音跳转链接”的可核验问题解答资产，争取进入
后续答案候选；这不是“目标品牌没有能力”的结论，也不授权任何目标品牌公开能力声明。

系统自动选择 `HELP_DOC`，建议承载位置为爱短链官网帮助/资讯区域。资产清单不完整，因此没有把“数据库无
ManagedAsset”误判为资产不存在：当前结论是先核查已观察页面 `https://aifabu.com/details/42615`；确认
归属、编辑权限和内容适配后可 `UPDATE_EXISTING`，否则在完整核查后 `CREATE_NEW`。发布位置只是内容目的地，
没有反向修改上游 Strategy 的 `channel_key/channel_role = null`。

机器已生成完整稿《抖音跳转链接怎么选：场景、路径与上线检查》，而非只生成标题与三个结构块。正文覆盖
私信卡片、合规短链、直播间小风车、上线检查、爱短链关联和结论。每个方法段继续绑定 AnswerUnit、Citation
和 Contribution binding；`SUPPORTS_PARTIAL` 不会被升级为生成影响或目标品牌事实。

品牌关联只使用冻结一方 Snapshot 中确实存在的功能性原词：“短链接生成器”“智能链接缩短与追踪”
“抖音私信跳转卡片”“微信外链跳转”。规模、转化、防封、稳定等营销效果句未进入稿件。该段明确标为一方
页面当前表述，不表示独立验证，也不证明发布后会被 AI 引用。

实际文本 QA 为 `READY`：完整正文、Prompt 针对性、来源绑定、内部/公开内容分离、品牌归因、失败引用排除
和无依据效果承诺检查均通过。自动修复记录包括删除稳定跳转承诺、把直播目的地收窄到来源支持的小程序，
以及把目标品牌内容限制为归因陈述。外部模型调用和网页重抓均为 0。

三条历史失败逐项保留且不进入完成统计或稿件：`citation-run1-ref4`、`citation-run1-ref13` 为
`FAILED_NEGATIVE_SPAN`，`citation-run1-ref5` 为 `FAILED_SCHEMA`。当前均为
`CURRENT_NOT_CONSUMABLE / NOT_EVALUATED_CURRENT_CONTRACT`；只有未来交付确实依赖对应来源时才定点重评，
没有将其改写为 `NO_MATCH/NO_SUPPORT`。

## 6. 正式链阶段状态

| 阶段 | 本轮状态 |
| --- | --- |
| Monitor / 真实 Run | PASS，复用既有 Run 1 |
| 独立 1/1 Analysis | PASS |
| Citation / Source Completion | PASS，18/18 READY |
| Answer | PASS，1/1 合法结果 |
| Citation Contribution | PASS WITH LIMITATIONS，16 DONE / 3 FAILED |
| Truth | EMPTY/不参与公开声明；不阻断内部 Discovery |
| Strategy | PASS，正式不可变机器 StrategyResult |
| Execution Draft | PASS，完整正文、正式不可变 Result 和实际文本 QA |
| Execution Confirmation | NOT COMPLETED，需要确认资产分支与实际账号/栏目权限 |
| Publication | NOT COMPLETED，没有真实发布记录 |
| Retest | NOT STARTED，禁止复用 Baseline 冒充发布后样本 |
| Validate | NOT STARTED，没有发布后新 Run 可比较 |

## 7. 工程与回归证据

- release migration：`20260930_01`；应用实际 SQLite `3.51.3`，WAL。
- 迁移前 DB 在线备份：`/private/tmp/geo-single-run-acceptance-20260930/geo_release.pre_20260930_01.db`，
  SHA-256 `fb6347d8bb91bd591ab220d08356fd722c86fac7ba931d5704e209c7303e58f1`。
- 迁移前正文 archive：`/private/tmp/geo-single-run-acceptance-20260930/evidence.pre_20260930_01.tgz`，
  SHA-256 `653f9a8ed9253099d66a7a7cd49abb8073d7ae307b504294db506b731d997c15`。
- 本轮在线备份：`/private/tmp/geo-optimize-delivery-backup-20261001/geo_release.db`，
  SHA-256 `d9434acad392cda5907dd3dea9036607521cf86c4d55232e3be37885f7ac4538`，恢复副本完整性 `ok`。
- release first-slice + Optimize 专项：34 passed。
- qualification：6 passed。
- frontend production build：PASS；保留现有 bundle size warning。
- 扩展 strategy/execution/retest：32 passed，19 failed。19 个失败均为旧 fixture 固定 3 Runs 但只计算和
  审核 Run 101；正式 `FIXED_ANALYSIS_SCOPE_INCOMPLETE` Gate 正确拒绝。处置为 `REPLACE`，不放松 Gate，
  不作为本条 1/1 正式链验收前置条件。

## 8. 页面操作与下一真实步骤

release 页面与 API：`http://127.0.0.1:8021/`。

首页选择“抖音跳转链接”，在“已有分析”中找到单 Run 分析
`925ef2dc-605f-467d-a025-52033a574d92`，点击“查看方案与稿件”。
入口使用已保存的诊断、策略、方案及版本身份，不重新生成。进入分析后也保留该入口。
默认 `npm run build` 已改为 release 构建；旧版构建只能显式执行 `build:legacy`，
产物写到独立 `dist-legacy`，不覆盖发布页面。

选择 Project 1、Prompt 1 和 Analysis `925ef2dc-605f-467d-a025-52033a574d92` 后，执行区域展示：

1. 系统推荐的帮助文档、官网承载位置和选择理由；
2. 已观察品牌页面的核查结果，以及“可更新 / 应新建”的明确条件；
3. 可复制的完整公开稿、品牌关联依据、内部检查项和固定 Baseline；
4. 实际文本 QA、自动修复记录和三条未评估引用的当前处置；
5. 保存并重新校验、确认执行方案、登记实际发布、发布后复测入口。

下一步只需用户确认：已观察页面是否可编辑且适合更新；若不适合则新建帮助文档；以及真实账号、栏目和
编辑权限。实际发布后再登记 URL、时间和实际内容；之后需单独授权并取得新的真实
Run 才能 Retest/Validate。当前没有手工 SQL 绕过、`latest` 替换、跨项目事实、自动 Review、模拟发布或
Baseline 复用为 Retest。

## 9. 2026-10-08 稿件交付器修补

实现提交：`2109c3f`。原始数据库、正文 artifact、浏览器截图未提交 Git。受保护记录对比在 API 重启后再次通过。

### 9.1 授权、范围与任务映射

按本轮明确指令执行四项实现修补，不新建 RFC/任务体系。范围仍为第1节的 Project 1 / Prompt 1 / Run 1，Analysis `925ef2dc-605f-467d-a025-52033a574d92`，不改变九条分析。映射 T01（冻结输入）、T16（正文）、T17（文本 QA）、T18（页面）。T16/17/18 标 IN_PROGRESS，AC-EXE-01/02/03/04 仅 PARTIAL；未将一条路径标成整个模块完成。

### 9.2 新版本与冻结输入

- 正式 POST deliverable 由页面发起，保存 `execution-v6:851eeab2713cd944`，父版本 `execution-v5:2121b5e21d0ac6df`。
- 完整 output hash：`851eeab2713cd944546322599f0c8b2aee6fa89abd27d45b11ef610893ccd5ca`。
- reviewable set hash：`2f9fa06251f242effb2a5673253d238fe6ad323717dd6d9a001f44b4ea6686c3`。
- delivery input hash：`8ffccfb3c55077ceac2992866fe91e4de19894203f3f551f45599d5ce3e2b5a7`。
- 实际正文 hash：`161120690d1a6961516717f20692ec030bc3cbcb045dc79fb4f333cb4aa3c56c`。
- 新契约：`single_prompt_execution.optimize_delivery.v2`、`single_prompt_execution_deliverable.v2`、`single_prompt_delivery_input.v1`、`single_prompt_execution_text_qa.v2`；implementation `single_prompt_execution_deliverable.impl.v5`。
- 输入明确保存原始 Context/Raw、Prompt 原文和 hash、品牌快照和 hash、Answer/Contribution/Strategy 版本及 hash、Citation/Completion ID/hash、选定正文与 passage/artifact/hash、历史限制。生成器只接收 DTO，不接收 Session。
- 品牌页面只承接 v5 已记录的精确 URL/Snapshot/hash，复核属于当前 Completion；标明旧结果来源与归属/权限未核实，不查当前 Project 域名、不授权 UPDATE，不把来源观察变成 Truth。
- 复用现有 `validate_completion_for_evidence`、正文安全 Gate、精确策略资格、Baseline、版本 CAS 和正式 release API。删除业务场景固定段落及重复编译分支；没有新库迁移或第二主链。

### 9.3 实际 QA 与局部修复

本稿由固定策略的三个内容块驱动，逐块读取其准确 Binding/AnswerUnit/来源段落；另有一段来自已冻结品牌页面的资料观察，不冒充 Contribution Binding。最终4段原文归因检查通过，发现5项问题/不确定项，实际修改3块，均有 before/after/hash/复检：

| 内容块 | 实际发现 | 实际处理与复检 |
| --- | --- | --- |
| 私信卡片 | 候选没有保留来源的关键词触发与适用行业；改写等价性未证明 | 替换为完整来源段落，保留条件；PASS |
| 第三方工具 | 候选写“对号短链”及“稳定跳转”，该来源段落只有 guandan888.com 示例 | 不把来源能力转给对号短链，改为出处明确的原段落；PASS |
| 小风车 | 候选扩到“企微、小程序等”；来源仅述微信小程序商城 | 不猜测额外目标地址，保留该来源自己的说法；PASS |
| 品牌页面观察 | 初始即完整归因原文 | 未发生修复，无伪造 APPLIED |

“未证明等价”不等于断言每个原改写必然为假。规则检测只能可靠允许完整归因投影；不宣称已经实现自由自然语言语义判真。QA READY 只证明本文按固定材料保留了主体/条件，**不证明引文本身真实、时效有效或效果成立**。选择该保守内容角度，是本轮无新增 LLM 调用时的交付边界，不是以安全名义宣布通用稿件质量全部完成。

业务信息编辑会重新校验实际正文，改入新增数字/标题声明不能继承 READY；上版修复仍在上版，新版无新修复时 repairs 为空。当前无已核实目标品牌能力，未从竞品推导能力，未新增 Truth。

真实 QA 完整对象、修复全文与冻结输入见本机受控 [formal-result.json](../../backend/artifacts/delivery-recovery-2026-10-08/formal-result.json) 的 result.output。文件不提交 Git。

### 9.4 正式页面与数据检查

正式入口 `http://127.0.0.1:5173/`，选择爱短链 / 抖音跳转链接，在当前单 Run 分析点“查看方案与稿件”。系统建议 → 完整稿件 → QA/修改前后 → 发布前必要业务信息。后台允许 VIEW/REVISE，账号和权限缺失只阻止确认，没有隐藏稿件。读取期间显示加载状态，不将尚未到达的数据误报为需要重新生成。

- 隔离浏览器通过正式按钮由 v5 生成 v6；只发生该一次生成 POST，没有模型/采集/正文请求。
- 精确版本 URL 刷新、桌面与390px移动端检查；只读验证无业务 POST 和 JS 错误。验收脚本不使用用户登录会话，外网请求被拦。
- 同版重复 POST 返回同一 v6；旧版请求409；跨项目拒绝且不新增结果。
- 在线备份恢复完整性 ok；12张受保护表逐行比对不变，全部旧执行版本不变，18个固定正文文件 hash 不变。仅执行结果新增1份、proposal活动版本正常推进。
- 执行确认、Publication、Retest、Comparison 仍为0；外部模型/采样/抓取为0。
- 受控证据目录 `backend/artifacts/delivery-recovery-2026-10-08/`：before.db、before-manifest.json、formal-result.json、draft.md、integrity-check.json、browser-check.json，以及 draft/qa/business 截图。数据库、原始文件和截图不提交Git。

当前剩余业务项是资产最终选择、真实账号/栏目及权限；UPDATE 未启用仍明确拦截。没有真正发布，不进入发布后新采样。此前“只剩用户确认”不作为全部通用能力完成声明。

### 9.5 工程回归与历史失败逐项处置

本轮组合运行 Optimize / navigation / release first-slice / strategy：69 passed；最后补充“业务编辑不重报上版修复”后 Optimize 专项12 passed（包含在前述范围，不相加）。release前端构建通过，保留已有bundle大小警告。另一主题空气过滤器、错主体/99%/条件丢失、冻结后项目/Prompt变更、正文篡改、版本幂等均只在隔离测试发生。

旧 execution/retest 文件修复前后均 **19 failed / 3 passed**。逐条实际失败都是固定输入[101,102,103]只计算/审核[101]，在 _seed_accepted_strategy/create_strategy 的 `FIXED_ANALYSIS_SCOPE_INCOMPLETE` 409；并未执行到各自目标断言。没有删除、skip、放松Gate或增加历史字段兜底。处置仅登记，不冒充已修复：

| 测试 | 必须保留的业务断言 | 本次实际结果 | 去向 |
| --- | --- | --- | --- |
| `test_test_direction_without_primary_generates_create_new_and_exact_baseline` | TEST 无 PRIMARY 仍可生成及完整 Baseline | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_unconfirmed_strategy_cannot_create_proposal` | 未确认策略不得生成 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_strategy_capability_without_public_evidence_cannot_generate_public_content` | 无公开依据不得生成品牌声明 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_foundation_surface_does_not_create_strategy_channel_role` | Foundation 目的地不反写渠道 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_update_and_immutable_field_edits_are_rejected` | UPDATE 和不可变字段不可绕过 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_public_and_internal_content_are_separate_and_no_fake_url` | 公开/内部内容分离且无假 URL | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_partially_covers_stays_internal_and_never_becomes_public_claim` | 部分覆盖不得成为完整公开声明 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_baseline_rejects_tampered_run_scope_hash_or_manifest` | 篡改 Baseline 应拒绝 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_ready_revision_confirmation_and_idempotency_are_separate_from_publication` | 确认幂等且不等于发布 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_publication_requires_confirmation_and_insufficient_content_is_not_evaluable` | 无确认不可登记，材料不足不可评估 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_exact_content_version_matches_but_channel_deviation_is_preserved` | 精确内容匹配与偏差保留 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_get_is_read_only_and_stale_strategy_blocks_new_confirmation` | GET 只读及过期不可确认 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_frozen_retest_plan_does_not_read_live_prompt_or_project_and_is_idempotent` | 复测不读当前配置且幂等 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_retest_start_verifies_query_hash_and_does_not_expand_runs` | 复测核对 Prompt hash/Run 范围 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_missing_official_identity_and_semantics_are_not_zero` | 身份/语义缺失不是零 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_comparison_uses_frozen_context_and_preserves_temporal_limit` | 冻结比较及时间限制 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_retest_retry_reuses_planned_runs_preserves_success_and_can_finalize_failures` | 重试不新增计划 Run | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_historical_strategy_publication_remains_observable_but_cross_project_is_rejected` | 历史发布保留及跨项目拒绝 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |
| `test_observed_retest_condition_conflict_keeps_values_but_removes_delta` | 条件冲突保留值但不输出差值 | 前置范围 409；断言未到达 | REPLACE fixture，保留断言；本轮未修 |

JUnit：`/tmp/geo-delivery-before.xml`、`/tmp/geo-delivery-legacy-final.xml`（两次19失败同集合同Gate）；新回归 `/tmp/geo-delivery-final.xml` 与 `/tmp/geo-delivery-focused-final.xml`。不完整范围阻断的负例继续保留，本轮无需把这19个前置fixture全部重建。

### 9.6 本版完整正文

以下为 v6 实际保存正文；不是下一步建议，也不是模型新调用产物。选题取固定Prompt，段落取本次准确来源，品牌关联取已冻结页面观察；通用引导不新增产品能力/数字/效果承诺。其形式是有出处的资料解读，不宣称已完成所有资产类型的原创综合成稿。

```markdown
# 抖音跳转链接：资料解读与适用边界

围绕“抖音跳转链接”，下文按资料分别说明相关做法及适用范围。不同来源的主体和条件不能互相替换；所列内容是来源表述，不代表独立验证或效果保证。

## 资料：抖音跳转网页，从流量到转化的“黄金桥梁”构建指南

资料《抖音跳转网页，从流量到转化的“黄金桥梁”构建指南》记载：

> 为了让流量价值最大化，可以将跳转卡片与私信自动回复功能相结合。在抖音的创作者服务中心设置关键词自动回复，例如，当用户发送“资料”时，系统自动弹出包含跳转卡片的回复消息。你可以在视频中引导用户“私信我获取独家资料”，从而形成一个“内容吸引→私信触发→卡片跳转→私域沉淀”的完整闭环。这种方法尤其适合知识付费、咨询服务等需要深度沟通的行业。

来源：https://baijiahao.baidu.com/s?for=pc&id=1863176989275774378&wfr=spider

## 资料：抖音跳转微信链接怎么生成 - 知乎-知乎

资料《抖音跳转微信链接怎么生成 - 知乎-知乎》记载：

> 使用 短链生成器 （如 http://www. guandan888.com ）」生成加密短链，缩短微信二维码的原始链接。

来源：https://zhuanlan.zhihu.com/p/1908892156019585529

## 资料：2025年最新的抖音跳转微信的方法，你最想用哪一个？_网易订阅

资料《2025年最新的抖音跳转微信的方法，你最想用哪一个？_网易订阅》记载：

> 在抖音直播间通过“小风车组件”或口播提示，用户得以通过打开小风车跳转至微信小程序商城。例如，在活动期间进行强调，让用户了解到正在推行的活动，从而积极参与其中。

来源：https://163.com/dy/article/JR10I32D055696HI.html

## 资料：短链接生成器_在线短网址生成_批量API短链接工具[爱短链]

资料《短链接生成器_在线短网址生成_批量API短链接工具[爱短链]》记载：

> 粉丝点击卡片/链接一键跳转私域，实现抖音流量高效转化，免留资获取线索

来源：https://aifabu.com/details/42615

## 爱短链与这个问题

这份解读围绕“抖音跳转链接”整理可回查资料，供读者对照自身场景选择下一步。资料中其他工具的功能不代表爱短链具备相同能力；具体产品范围应以明确的产品说明为准。

## 如何使用这些资料

先确定自己的使用场景，再逐项对照来源中的主体、适用条件和操作前提。涉及实际操作时，先核对当前版本和权限，再在可控范围验证；不要把不同资料的片段拼成未经验证的承诺。

## 结论

对于“抖音跳转链接”，应保留各来源自己的适用边界。本文提供可回查的资料和使用次序，不把内容发布等同于效果已经实现。
```

### 9.7 尚未完成

自由综合改写的语义 QA、通用文章编辑与更多资产类型质量未通过本次证明；正式指标/效果未测量。本版来源中的建议也可能过时，归因引用并不替代事实独立核实。真实发布和新 Run 比较需要下一阶段真实业务信息与授权，不在本轮伪造完成。

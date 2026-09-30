# 单 Run 正式交付链验收记录（2026-09-30）

## 1. 本轮结论

本轮按产品负责人调整后的优先级，选择一条真实、完整的既有 Run，在发布数据库中建立独立的
`1/1` Analysis，并通过正式 release API 推进到机器 Strategy、Execution Draft 和自动 QA。

本轮没有重新采样、没有新增外部模型调用、没有重抓网页，也没有修改原九条 Analysis。正文和
Citation Contribution 只在精确身份、内容 hash、passage hash 和合同版本兼容时复用。

当前真实停止点是用户业务选择，不是计算失败：需要选择资产类型、计划发布位置、可操作账号和栏目，
然后确认执行方案。实际发布、PublicationRecord、发布后新采样和 Validate 均未伪造。

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

## 5. 自动策略、执行稿与 QA

| 对象 | 精确身份 / 状态 |
| --- | --- |
| Qualification projection | `5651a90d8c8baa12e2bc7da78ac91cb9f79221f1f95d12ccf409a65e69289ca0` |
| Strategy | `strategy-ef6ac968-c400-4528-8913-634b4216eada` |
| Strategy Result | `strategy-v1:178f23f7c8de96a1` |
| Strategy hash | `178f23f7c8de96a1faa8d98a27138ae138212fafc45f89ae240ce07c381fe830` |
| Strategy authority | `MACHINE_QUALIFICATION`，不伪造人工 Review |
| Direction | `strategy-machine-40561c088482ff4d480d`，`DISCOVERY / ACTIONABLE` |
| Execution Proposal | `execution-proposal-43feb8f4-26b1-4eb2-b6c0-74298af17fb4` |
| Execution Result | `execution-v1:a7a640779ae7e104` |
| Execution hash | `a7a640779ae7e10492a1b11b0c5fed1a83ee14bb9bbdff07c6d1738e5d072dbe` |
| 当前状态 | `NEEDS_HUMAN_SELECTION` |

策略明确回答：本 Run 未观察到目标品牌，因此建立一份围绕“抖音跳转链接”的可核验问题解答资产，争取进入
后续答案候选；这不是“目标品牌没有能力”的结论，也不授权任何目标品牌公开能力声明。

机器交付的标题为“抖音跳转链接：场景、方法与注意事项”，并给出三段来源绑定内容骨架：私信卡片跳转、
合规短链工具路径、直播间小风车。每段都绑定 AnswerUnit、Citation 和 Contribution binding；
`SUPPORTS_PARTIAL` 不会被升级为生成影响或目标品牌事实。

自动 QA 为 `READY_INTERNAL`：来源绑定、无 Truth 时不生成目标品牌声明、资产操作不被擅自推断均通过。
外部动作仍为 `NO`。发布前还必须完成：资产操作选择、资产类型、发布位置、账号/栏目和业务确认。

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
| Execution Draft | PASS，正式不可变 Proposal/Result 和自动 QA |
| Execution Confirmation | NOT COMPLETED，需要真实资产和账号选择 |
| Publication | NOT COMPLETED，没有真实发布记录 |
| Retest | NOT STARTED，禁止复用 Baseline 冒充发布后样本 |
| Validate | NOT STARTED，没有发布后新 Run 可比较 |

## 7. 工程与回归证据

- release migration：`20260930_01`；应用实际 SQLite `3.51.3`，WAL。
- 迁移前 DB 在线备份：`/private/tmp/geo-single-run-acceptance-20260930/geo_release.pre_20260930_01.db`，
  SHA-256 `fb6347d8bb91bd591ab220d08356fd722c86fac7ba931d5704e209c7303e58f1`。
- 迁移前正文 archive：`/private/tmp/geo-single-run-acceptance-20260930/evidence.pre_20260930_01.tgz`，
  SHA-256 `653f9a8ed9253099d66a7a7cd49abb8073d7ae307b504294db506b731d997c15`。
- release first-slice：33 passed。
- qualification：6 passed。
- frontend production build：PASS；保留现有 bundle size warning。
- 扩展 strategy/execution/retest：32 passed，19 failed。19 个失败均为旧 fixture 固定 3 Runs 但只计算和
  审核 Run 101；正式 `FIXED_ANALYSIS_SCOPE_INCOMPLETE` Gate 正确拒绝。处置为 `REPLACE`，不放松 Gate，
  不作为本条 1/1 正式链验收前置条件。

## 8. 页面操作与下一真实步骤

release 页面：`http://127.0.0.1:8021/`。

选择 Project 1、Prompt 1 和 Analysis `925ef2dc-605f-467d-a025-52033a574d92` 后，执行区域展示：

1. “新增可核验问题解答资产”方向；
2. 资产类型候选：产品页、功能页、帮助文档；
3. 对应发布位置、发布账号、栏目和账号可操作性；
4. 标题、三段内容骨架、内部检查项、固定 Baseline 和自动 QA；
5. 保存并重新校验、确认执行方案、登记实际发布、发布后复测入口。

下一步必须由用户提供真实选择。实际发布后再登记 URL、时间和实际内容；之后需单独授权并取得新的真实
Run 才能 Retest/Validate。当前没有手工 SQL 绕过、`latest` 替换、跨项目事实、自动 Review、模拟发布或
Baseline 复用为 Retest。

# GEO M1 内部试用项目总控

更新时间：2026-11-10（Asia/Shanghai）
当前阶段：`M1_1_WINDOWS_DEPLOYMENT_PENDING / M1_2_AGGREGATE_SCOPE_OFFLINE_ACCEPTED`
M1.1 稳定线：`codex/m1-1-windows-dev`（当前归档 SHA `c5f2dbbc`，目标机验收前不得宣称已部署）
M1.2 研发线：`codex/m1-2-multicontent`（以该分支最新已验收 HEAD 为准，不自动升级 M1.1）
C0 研究线：`codex/c0-second-platform-eval`（归档 SHA `13ecd983`；C1 未获授权，不启动真实平台采集）
Mac 归档安装：`/Users/bmwqr/Library/Application Support/GEO Beta`，最后版本
`geo-m1.1-lan-3fcad83`；Backend、Worker、局域网代理和自动启用标记均已关闭。

> 2026-10-30 部署决策：下一目标为 Windows 公司局域网机器。第一轮不迁移私有 CA、客户端证书
> 或旧邀请凭证，改用可信局域网 HTTP、Windows 防火墙私网限制和服务端管理员配置的登录密码。
> 该方案禁止公网暴露。完整交接边界见
> [Windows 迁移交接存档](M1_WINDOWS_HANDOFF_ARCHIVE_2026-10-30.md)。
>
> 2026-11-05 研发决策：M1.1 稳定交付与 M1.2 多内容研发并行但严格隔离。M1.2 采用
> `AgentResultVersion -> DraftArtifactVersion[]`，首批只支持 HELP_DOC 与 FAQ；开发完成、
> 真实业务验收通过、升级回滚通过是三个不同状态。C0 仅保留离线结论，不自动进入 C1。

## 1. 管理结论

GEO 已在 Mac 上完成“查看采样 → 冻结分析范围 → AI 优化 → 查看诊断/策略/正文/QA →
复制导出 → 反馈 → 历史/Validate”的内部 Beta 主流程。Mac 部署现已停止。A 线继续冻结统一
Windows 候选并迁移到受控公司机器；B 线在隔离分支和测试库中继续多内容研发，不直接进入试用环境。

当前不能写成“全部完成”：活动本机安装不是带完整文件 manifest 的干净候选；公司机器部署尚未
开始；Mac 服务、模型和采样开关均已关闭，历史授权不能自动转为公司授权；大范围 Evidence Pack 已证明需要
分批，但生产多批合并尚未获得语义契约批准。

## 2. 三个必须分开的状态

| 对象 | 当前状态 | 管控要求 |
|---|---|---|
| 开发源码 | M1.1 生命周期与离线 QA 已进入候选分支，容量 shadow 验收通过 | 以最终 manifest/SHA 冻结，不能直接等同已部署版本 |
| Mac Beta 归档 | 最后版本 `geo-m1.1-lan-3fcad83`；服务和端口已关闭；数据保留 | 不再提供访问；不得直接复制为 Windows 包 |
| Windows 公司机器 | 尚未部署 | 必须使用冻结 SHA、正式迁移、密码门禁、独立配置与恢复验收 |

Mac 历史运行曾保存 22 Run 真实 AI 优化结果，但服务、局域网入口和自动启用现均已关闭。
历史余额、本机授权和采集计划不得自动迁移成 Windows 公司日常授权。

## 3. 子需求完成情况

状态定义：`DONE` 已实现并有验收；`OFFLINE_ACCEPTED` 仅离线工程与隔离数据验收通过；
`PILOT_READY` 可试用但需真实反馈；`LIMITED` 有明确边界；`BLOCKED` 缺外部授权或契约；
`BACKLOG` 后续开发；`NOT_STARTED` 尚未实施。

| 领域 | 子需求 | 状态 | 当前结论 / 下一 Gate |
|---|---|---|---|
| 项目 | 项目、Prompt 选择及项目隔离 | DONE | UI/API 已存在；公司部署需复验多账号项目权限 |
| 品牌 | 品牌、别名、官网、事实、禁止表述 | PILOT_READY | 能进入分析；内容完整性由项目组维护，目标关联不能冒充 Product Truth |
| 数据 | Run 长期累积、原始回答/hash/引用保存 | DONE | 新数据不覆盖旧 Run；失败尝试与有效业务样本已区分 |
| 数据 | `MANUAL_IMPORT` 正式入口 | DONE | 固定版本、观察时间、导入人、hash；不宣称平台真实性已独立验证 |
| 采集 | Playwright 立即采集 | PILOT_READY（历史本机验收） | Mac 服务现已关闭；公司候选默认关闭，需独立许可与目标机验收 |
| 采集 | 定时采集、幂等、暂停/恢复 | PILOT_READY（历史本机验收） | Mac 计划和自动启用标记现已关闭；公司候选默认关闭，不继承历史计划 |
| Monitor | 回答、引用、状态、趋势与历史 Run | PILOT_READY | 可用于现有真实数据；未分析不能显示成品牌零表现 |
| 范围 | 7/14/30 天、自定义、指定/排除 Run | DONE | 最终冻结明确 Run IDs、版本及 hash，新采样不改变旧范围 |
| 范围 | 冻结范围的业务可读时间命名 | DONE | UI 显示北京时间、回答数和范围，不要求员工理解内部 hash |
| Optimize | Evidence Pack v3 单包生成 | LIMITED | 当前 22 Run 真实基线可用；容量取决于回答、唯一 URL 与正文长度 |
| Optimize | HELP_DOC + FAQ 多内容父子版本 | REAL_GATE_FAILED / V5_OFFLINE_ACCEPTED | 第三次真实父子版本保持失败；新 v5 只完成离线实施和受保护回放，不重标历史结果、不进入 M1.1。第四次真实复测尚未授权 |
| Optimize | 多内容结构与重复度质量 Gate | PROMPT_V10 / EXECUTION_V12 / VALIDATION_V5_OFFLINE | RFC 已批准并冻结；服务端构建精确 Evidence Set、计算品牌字面观察并验证封闭事实区及全输出总体品牌事实边界。117 项核心后端、40 项容量/试用保护回归、47 项前端测试及成功/部分成功浏览器场景通过，尚未发布 |
| Optimize | 引用平台/竞品渠道分析 | DONE | 基于冻结引用观察，不把 AI 推荐渠道伪装成已验证效果 |
| Optimize | 诊断、策略、渠道、完整正文、QA | PILOT_READY | 工程链可交付；必须用同事反馈评估品牌关联与内容采用价值 |
| Optimize | 证据、Truth 与分级资格 Gate | DONE | 生成失败或证据不足不伪装成功；草稿与通过资格分开 |
| 容量 | 大范围确定性分批规划 | DONE（SHADOW） | 22/50/100/300/1000 离线覆盖通过，不执行模型、不合并结果 |
| 容量 | 生产多批分析及结果合并 | BACKLOG | `GEO-CAP-001`；需批准多批结果语义后实施 |
| 结果 | 独立 AgentResultVersion、历史版本 | DONE | 不覆盖正式 V2 ResultVersion/Truth/Review/Gate |
| 结果 | 复制、Markdown 导出、刷新恢复 | DONE | 本机浏览器已验收 |
| 反馈 | 可用/需修改/不可用、采用与修改量 | DONE | 追加保存，不改变原结果或事实资格 |
| 任务 | 运行进度、失败原因、重试/恢复 | PILOT_READY | 已有 Worker 和状态展示；公司部署需做断电/重启复验 |
| Validate | 两个冻结范围比较 | PILOT_READY | 功能可用；需积累第二个真实范围后验证业务价值 |
| 运维 | 本机 launchd、SQLite、日志、备份 | DONE（本机） | 仅 `127.0.0.1:8032`，不是多人部署结论 |
| 运维 | 可重复安装/备份/恢复/升级/回滚 | DONE（离线） | 完整包 manifest、Online Backup、审计账本、队列/外键阻断、实例归属、隔离迁移、路径重定位和回滚专项通过；目标机待验 |
| 运维 | Windows 单机部署及同事访问 | NOT_STARTED | 当前下一里程碑；可信局域网 HTTP + 服务端密码 + 防火墙私网限制；禁止公网 |
| 运维 | 服务端账号额度/日常模型授权 | HISTORICAL（Mac）/ BLOCKED（公司） | Mac 历史授权已停用；公司由管理员独立配置，不恢复用户自填 Token/金额弹窗 |
| M2 | 八木屋同软件接入 | NOT_STARTED | 必须等爱短链第一轮试用反馈，不写死短链接业务 |

旧 `tasks.json` 仍记录正式 V2 的 26 项历史任务（12 DONE、9 IN_PROGRESS、2 BLOCKED、2
WAITING_DEPENDENCIES、1 OUT_OF_SCOPE），不再作为 M1 内部 Beta 的唯一完成度。正式 V2 历史状态不
回写、不伪装完成；本文件负责当前 Beta 交付管控。

## 4. 已登记问题

| ID | 优先级 | 问题 | 当前安全状态 | 后续完成标准 |
|---|---|---|---|---|
| GEO-DEP-001 | P0 | 活动安装标签与实际文件不完全一致 | 未覆盖活动数据库；新候选要求 manifest | 生成目标平台 prepared release 并在目标机核验 SHA/构建/迁移指纹 |
| GEO-OPS-001 | P0 | 公司机器尚未执行可重复安装验收 | 离线 install/backup/restore/upgrade/rollback 已通过 | 在目标机执行同一套命令并完成真实恢复演练 |
| GEO-AUTH-001 | P0 | 共享密码和多人访问尚未在目标机器复验；本阶段不具备可信个人身份 | 仍只监听 localhost；公司试用限爱短链单项目和可信局域网 | 两个独立浏览器会话完成密码门禁、并发读写、刷新恢复和密码撤换；独立账号/跨项目隔离留待正式多人版 |
| GEO-MODEL-001 | P0 | Mac 历史授权已停用，公司授权尚未建立 | 新安装强制关闭，防止继承历史权限 | 公司管理员配置独立额度并完成一次受控真实任务 |
| GEO-QUAL-001 | P0 | 内容业务价值缺真实同事评分 | 工程与历史结果可操作 | 2～3 人处理 5～10 个 Prompt，记录采用/修改/行动价值 |
| GEO-CAP-001 | P1 | 大范围 Evidence Pack 会因完整请求、唯一 URL 或正文增长超限 | 原始数据完整；生产 v3 小范围可用；shadow 分批不执行 | 批结果结构、locator、冲突、失败、汇总、请求数/Token 契约获批并实现 |
| GEO-COL-001 | P2 | 自动文心采集未获许可且未做长期真实验收 | 计划暂停、重试 0、人工导入可用 | 获明确许可后先单条联调，再单独批准定时计划 |
| GEO-VAL-001 | P1 | Validate 缺足够新增真实范围 | 不伪造趋势改善 | 有至少两个同口径真实冻结范围并由员工完成比较 |
| GEO-DOC-001 | P1 | 旧 V2/实验/Beta 文档并存，容易误读状态 | 历史文档保留 | 以本总控为当前入口，发布候选时同步 RUNBOOK/USER_GUIDE |
| GEO-MULTI-001 | P1 | 三次真实双稿均由 Provider 完整返回但未通过完整 Gate；v4 整节 aggregate 识别缺陷已用服务端结构化观察修复，但真实模型尚未按 v10/v12/v5 复验 | 三次原始结果、usage 与审计保留在受保护本地目录；v4 历史不变；v5 离线 Gate、22 条失败稿保护回放和隔离浏览器已通过，未发布、未调用模型 | 新授权下完成一次 v10/v12/v5 真实双稿；服务端 PASS 后仍需员工逐稿评价 |
| GEO-MULTI-UI-001 | P1 | RESOLVED：隔离浏览器已验收双成功及 HELP_DOC 成功/FAQ 失败的部分成功链路 | 失败资产禁止导出；成功资产可下载；反馈、历史版本和刷新恢复已验证；无授权时单篇重生成 fail-closed | 保留报告与失败证据；真实生成质量继续由 `GEO-MULTI-001` 管控 |
| GEO-TEST-001 | P2 | 两个 Agent 回归曾把 2026-10-22/26 价格核验日期写死，跨 7 天后固定失败 | RESOLVED；测试统一使用单次测试进程冻结的当前价格证据日，生产七天时效 Gate 未放宽 | 本轮 Agent 与子资产联合回归 84/84、容量回归 29/29 通过 |

### GEO-CAP-001 详细记录

- 真实 22 Run 基线经引用去重后约 44,350 字符，可以运行。
- 压力测试证明唯一来源多、来源正文长或完整回答累积都会再次触发限制；不存在统一的“最大 Run 数”。
- Shadow planner 对 22/50/100/300/1,000 Run 的三类分布保持 Run、Citation、Snapshot、
  Disposition 身份全覆盖。
- 当前生产仍限定单任务 1 次请求；多批模型结果合并属于语义变更，状态为
  `SEMANTIC_CONTRACT_REVIEW_REQUIRED:MULTI_BATCH_RESULT_MERGE`。
- 公司首轮试用可先使用业务上可解释的较小冻结范围；不得把 shadow 分批写成已上线能力。

详细证据见 [Evidence Pack 容量验收](EVIDENCE_PACK_CAPACITY_ACCEPTANCE.md)。

### GEO-MULTI-001 首次真实 Gate（2026-11-05）

- 冻结范围：爱短链 Project 1 / Prompt 1 的当前 22 条有效 Run；旧 Context 因历史 Run 漂移被
  fail-closed，验收只在隔离数据库副本中重新冻结当前精确身份，未改写原历史结果。
- 外部调用：DeepSeek `deepseek-flash`、`RESPONSES_TEXT`、关闭 thinking；仅 1 次请求，自动重试 0、
  补救调用 0。供应商状态 `completed`，38,947 输入 Token、4,581 输出 Token、共 43,528 Token，
  结算 ¥0.43528，耗时约 30.7 秒。
- 证据覆盖：22 条回答、634 次引用关系、85 个唯一来源全部纳入，0 个来源被静默省略。
- 真实阻断：`品牌表现与证据缺口` 有指标描述但没有本节 locator；其他章节的有效引用不能替代本节绑定。
- 校验误报与保守限制：8 组编号加粗问答未被旧 FAQ 语法识别，已在非代码区域按真实问答配对修复；
  “禁止使用某百分比措辞”的负向清单仍被数值 Gate 保守阻断。后者不新增文本豁免，避免混合正向
  价格/效果主张绕过 Gate；新 Prompt 改为禁止把该类内部检查清单写入最终用户正文。
- 业务结论：诊断与引用渠道分析有信息价值，但 HELP_DOC/FAQ 混入内部 Truth/Evidence 字段和编辑检查
  指令，不是可直接交付最终用户的两份正文；`VERIFY_FIRST` 与禁止事实资格保持不变。
- 安全边界：原始回答、Evidence、模型响应和正文只保存在 Git 忽略的受保护本地目录，未进入公开仓库。
- 离线收口：新增
  [RFC-EVIDENCE-PACK-QUALITY-GATE-001](../semantics/rfcs/RFC-EVIDENCE-PACK-QUALITY-GATE-001.md)，
  Prompt v8 不变，Execution v10 绑定 Validation v4。首次真实失败稿回放同时命中
  `INTERNAL_AUTHORING_INSTRUCTION_LEAK` 和 `BRAND_SECTION_EVIDENCE_RELEVANCE_REQUIRED`；回放只输出
  Gate 代码，没有打印或提交正文。随机有效 locator、回答截断 locator、单 Run 冒充总体结论和仅品牌名支撑
  推荐关系、截去否定上下文的片段以及无法确定的关系表述均 fail-closed；普通“核实官方来源”、界面
  “系统提示”和用户工具操作等业务措辞不会误杀。
- 兼容与范围：Execution v9 仍绑定 Prompt v8 / Validation v3，历史 v7/v9 输出不重算、不改写；新 Gate
  只是最低观察相关性检查，不替代 Product Truth 或对能力/因果的语义支持判断。新建单稿重生成请求
  同时冻结 Prompt / Execution / Validation 身份；缺失身份的历史排队请求在 Provider 前失败，不静默套用新版本。
- 离线回归：Agent + 子资产联合回归 84/84、容量回归 29/29 通过；Luna 与 geo_supervisor 最终均
  `APPROVE`。首次真实失败稿受保护回放仍命中两项新增 Gate，没有打印正文，也没有新增外部调用。
- 2026-11-06 真实复测：同一 22 Run / 同一 Evidence Pack 完成唯一一次请求，供应商 `completed`；
  39,097 输入、4,147 输出、共 43,244 Token，结算 ¥0.43244，耗时 29.164 秒。两份资产仍失败。
  原文有 23 个合法 locator，但均包在单反引号中并按既有防代码示例规则被屏蔽；品牌章节另以单回答
  表述总体范围，HELP_DOC 则有行动内容但缺契约步骤格式。Prompt v9 / Execution v11 已在不改
  Validation v4 的前提下明确三项输出要求；137 项离线专项通过。历史 v10 主结果保持原解释；旧 v10
  单稿重生成排队请求会在 Provider 前 fail-closed，不静默升级。完整脱敏记录见
  [真实复测结果](M1_2_REAL_QUALITY_RETEST_RESULT_2026-11-06.md)。
- 2026-11-09 第三次真实验证：Prompt v9 / Execution v11 / Validation v4 在同一 22 Run 上完成唯一请求；
  39,345 输入、3,608 输出、共 42,953 Token，结算 ¥0.42953，耗时 28.043 秒。16/16 locator 合法，
  HELP_DOC 步骤、FAQ、渠道、内部泄漏和双稿差异化均通过；唯一失败为 22 条总体观察只绑定 2 条完整
  回答。受保护回放另证明 v4 的 aggregate 触发依赖相邻限制说明，存在可绕过的确定性范围绑定缺陷。
  当前停止 Prompt 补丁和付费循环，进入 `SEMANTIC_CONTRACT_REVIEW_REQUIRED`；详情见
  [第三次真实验证结果](M1_2_REAL_QUALITY_THIRD_RESULT_2026-11-09.md) 和
  [结构化范围绑定提案](../semantics/rfcs/RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001.md)。
- 2026-11-10 Product Owner 批准并冻结结构化范围契约。Prompt v10 / Execution v12 / Validation v5
  已离线实现：服务端冻结完整回答集合并计算品牌字面观察，模型不能自定成员或事实值；相邻说明不再改变
  scope，额外推荐/能力/排名/因果断言继续阻断。第三次失败稿仅在本地副本回放：原 v4 失败保持，原稿
  在 v5 下因缺服务端观察失败，服务端渲染 22 条规范观察的 shadow 通过；没有改写历史或发起外部调用。
  详细证据见 [v5 离线结果](M1_2_AGGREGATE_SCOPE_V5_OFFLINE_RESULT_2026-11-10.md)。
- 2026-11-11 第四次真实验证：同一 22 Run、Prompt v10 / Execution v12 / Validation v5 完成唯一请求；
  42299 输入、3380 输出、共 45679 Token，账本 ¥0.45679，耗时 24.690 秒。Evidence Set、服务端
  Observation、canonical 事实区和双稿持久化均正确；唯一失败是 QA 再次复述已验证范围并附带不推导
  推荐/排名/因果的限制。v5 按冻结规则正确拒绝，不能重标 PASS。第五次调用未授权；新的服务端 QA
  组合规则已登记为 `SEMANTIC_CONTRACT_REVIEW_REQUIRED`，详见
  [第四次结果](M1_2_REAL_QUALITY_FOURTH_RESULT_2026-11-11.md) 与
  [RFC 提案](../semantics/rfcs/RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002.md)。
- 2026-11-13 Product Owner 批准 QA 服务端组合 Definition Freeze。Prompt v11 / Execution v13 /
  Validation v6 / QA Composition v1 已离线实现：Provider 原文不可变，只在 QA 中对与精确 Observation
  等价的安全冗余句做带偏移/hash/原因/证据身份的记录式排除，并由服务端生成范围说明；诊断、策略和
  双稿正文不做自动改写，能力/推荐/排名/因果及未知等价仍阻断。第四次保护库精确 shadow 保持历史
  v5 FAIL，同时 v6 PASS 且数据库前后 hash 一致。第五次调用及发布仍未授权。详情见
  [v6 离线结果](M1_2_SERVER_COMPOSED_QA_V6_OFFLINE_RESULT_2026-11-13.md)。

## 5. 下一里程碑：公司单机内部试用

### D0：冻结候选版本（P0）

1. 从当前集成分支选择唯一 SHA，禁止从 `/private/tmp` 或活动开发目录直接长期运行。
2. 合并/核对本机 Beta 自 `50a4a57` 之后的 UI、重试、时间、渠道、容量和审计修复。
3. 运行迁移、后端、客户端、release build、浏览器主路径和 `git diff --check`。
4. 生成候选版本号、变更清单、数据库 schema revision 与回滚点。

### D1：目标机器准备（P0）

需要记录：操作系统/架构、内存与磁盘、常开策略、局域网地址、访问用户、备份位置、浏览器、
Python/Node 版本和网络出口。使用专用运行目录和服务账号，不把源码工作树当数据库目录。

本轮访问方式已确定为可信公司局域网 HTTP。必须同时配置服务端密码和 Windows 防火墙私网限制，
不得监听或映射到公网。若未来涉及跨可信网段或公网访问，必须重新评估 VPN 或 HTTPS，当前批准
不能自动扩展到该场景。

### D2：数据与配置迁移（P0）

1. 对活动 SQLite 使用一致性备份，不复制打开中的 WAL 组合冒充备份。
2. 迁移必要数据库、Evidence/Result 文件和配置版本；日志可重新生成。
3. API Key、会话和账号凭证单独注入，不写入 Git、数据库导出或交接文档。
4. 历史实验账本只作审计，不自动成为日常模型额度。
5. 在数据库副本上执行 release migration、完整性检查和恢复演练。

### D3：部署验收（P0）

必须通过：

- Backend/Worker 启停、重启、健康、heartbeat、单并发和日志轮转；
- 项目/Prompt/Run、Monitor、范围冻结、历史真实结果、复制导出和反馈；
- 管理员额度关闭时只读功能正常，生成明确 fail-closed；
- 获独立日常额度后只执行一次受控 Optimize，保存 usage、结果和失败证据；
- 两个独立浏览器会话的共享密码门禁、并发写入、刷新恢复和密码撤换；反馈人仅作业务记录，不冒充认证身份；
- 数据库备份恢复后历史 AgentResultVersion 与反馈仍可读；
- 不触发自动文心采样、抓取、发布或正式 V2 写入。

### D4：同事试用（P0）

第一轮只安排 2～3 名爱短链同事，每人处理少量真实 Prompt。产品指标：

| 指标 | 记录方式 |
|---|---|
| 任务完成率 | 从选择范围到获得可审核结果，成功/失败均记录 |
| 内容采用 | 可直接作底稿 / 需修改 / 不可用 |
| 修改量 | 少量 / 中等 / 大量及主要原因 |
| GEO 行动价值 | 是否给出愿意执行的渠道和具体行动 |
| 事实问题 | 品牌能力、引用关系、VERIFY_FIRST 与未知项 |
| 操作问题 | 找不到入口、状态不更新、错误不可恢复、刷新丢失 |

试用期间只修 P0/P1 的真实问题，不扩展八木屋、自动发布、复杂协作或商业计费。

## 6. 后续开发顺序

1. **A / M1.1 公司单机部署**：完成 D0～D3，仅接收经过回归的试用 P0/P1 修复。
2. **B / M1.2 多内容研发**：完成 HELP_DOC + FAQ 离线纵向实现、真实质量验收及升级/回滚 Gate；未完成三项前不部署。
3. **M1.1 爱短链员工试用**：完成 D4，冻结第一轮反馈，优先修品牌事实、渠道依据、正文采用价值和状态恢复。
4. **C0 第二平台离线评估**：保持归档；获得平台采集许可和新阶段决策后才启动 C1。
5. **容量契约**：处理 GEO-CAP-001，不以提高 90,000 上限替代分批语义。
6. **M2 八木屋接入**：只通过项目/品牌/Prompt/数据配置接入同一软件。
7. **M3 通用化**：根据两个项目真实反馈再决定自动化、成本、团队和商业能力。

## 7. 变更管控

- 一个阶段只有一个发布候选分支、一个 HEAD、一个版本号和一份数据库 revision。
- P0 为部署/数据/权限/结果不可用；P1 为试用价值或常见流程问题；P2 为后续效率；P3 为体验优化。
- 每个任务必须有：负责人、范围、禁止项、验收命令、浏览器证据、数据迁移影响和回滚方式。
- 外部采样、模型调用、生产部署、网络暴露和正式语义契约分别授权，不能相互推导。
- 语义变化先走 Semantic Change Guard；shadow 或合成测试不能升级为生产能力。
- 完成定义不是“代码提交”：必须包含目标环境启动、实际 UI、刷新/重启、权限、备份恢复和已知限制。
- 每次候选发布后冻结功能，先收集反馈；没有 P0/P1 不进入新功能开发。

## 8. 当前立即行动清单

- [ ] 确定 Windows 目标机器版本/架构、固定私网地址、管理员和备份盘。
- [ ] 实现并验收服务端密码门禁；不迁移 Mac 私有 CA、客户端证书和旧邀请凭证。
- [ ] 冻结 M1.1 候选 SHA，并核对 `50a4a57..候选 SHA` 的迁移与变更。
- [ ] 创建活动数据库和 Evidence 文件的可恢复备份。
- [ ] 准备可重复安装/升级/回滚命令，不复制临时 worktree 作为安装包。
- [ ] 配置公司试用账号、项目权限和服务端日常模型额度。
- [ ] 在目标机器完成 D3 验收并保存机器可读报告。
- [ ] 安排 2～3 名同事试用，按统一反馈字段记录结果。
- [x] M1.2 离线实现 HELP_DOC + FAQ 父子版本、资产级状态/Evidence/QA/导出/反馈/重生成 lineage。
- [x] M1.2 增加 HELP_DOC 操作结构与双稿高度重复的确定性 Gate，并完成隔离浏览器验收。
- [x] 补齐 M1.2 资产级部分失败、导出阻断、反馈、历史版本和刷新恢复的隔离浏览器验收；未授权单稿重生成保持禁用并已验证 fail-closed。
- [x] M1.2 已完成首次独立授权的真实双稿生成；结果为真实 Gate 失败，未伪装成通过，外部调用已停止。
- [x] 前两次真实 Gate 均保留原始失败；第二次暴露的 Prompt—Validator 格式对齐问题已升为 Prompt v9 /
  Execution v11 并通过离线回归。任何后续真实生成仍必须重新获得独立授权，不能自动重跑。
- [x] 真实失败沉淀为受保护离线反例；Validation v4 已覆盖内部编写指令泄漏与品牌章节 locator 最低相关性，
  并保留 v9/v10 历史兼容。
- [x] Prompt v9 / Execution v11 第三次真实验证已完成且停止；结果仍为 Gate 失败，未自动重跑。
- [x] `RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001` 已批准并 Definition Freeze；Prompt v10 / Execution v12 /
  Validation v5 已完成离线实现、反例、历史兼容、受保护回放和隔离浏览器验收。
- [x] 第四次真实复测已按独立授权完成且保持真实 FAIL；未自动重跑或重标。
- [x] `RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002` 已批准并 Definition Freeze；v6 离线实现和第四次
  保护稿 shadow 已通过，历史 v5 与数据库不变。
- [ ] 第五次真实复测需新的独立付费授权；不得因 v6 shadow 通过自动调用模型或发布 M1.2。
- [ ] 在两份资产通过服务端 Gate 后安排员工逐稿质量评审；不得以首次失败稿或合成结果替代。
- [x] 当前 M1.2 候选已在 M1.1 只读数据副本上通过升级、备份、恢复和回滚演练；正式提升仍需真实质量与审批。
- [ ] 试用后再决定 GEO-CAP-001 的生产语义和八木屋接入时间。

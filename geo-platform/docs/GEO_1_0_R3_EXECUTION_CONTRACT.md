# GEO 1.0 R3 首批执行契约

Status: `ENGINEERING_IMPLEMENTED / REAL_POSITIVE_CHAIN_PENDING_AUTHORIZATION`
Date: 2026-09-20
Classification: `SEMANTIC_CHANGE / EXPLICIT_PRODUCT_OWNER_CUTOVER_AUTHORIZATION`
Scope: 首次交付的 Source Completion 与 Evidence 双输入 Gate

## 1. 本轮唯一交付

正式 1.0 路径为：

```text
AnalysisContext
-> immutable Citation Manifest
   |-> Answer Semantic -> exact Answer ResultVersion -> exact Review
   `-> Source Preparation -> immutable Source Completion Manifest
                                      |
                                      `-> Evidence exact-input Gate
```

本轮只交付上述来源准备与 Evidence 交接，不接 Strategy、Execution、
Publication 或 Retest。R2 与 R3 冲突时以 R3 为准。

## 2. 唯一业务所有权

V2 是发布路径唯一的 orchestration、persistence、review 和 UI truth。
V1/V1.1 代码只能作为显式 DTO 输入、纯结果输出的计算内核使用，不得：

- 查询旧工作流当前状态；
- 查询 latest Package、Candidate 或 Truth；
- 写旧工作流对象；
- 调用旧 Runner 接续业务流程；
- 依靠旧数据库或退役表启动。

代码所在目录不决定其资格，运行时数据依赖和副作用决定其资格。

## 3. 两份不可变 Manifest

`Citation Manifest` 固定本次 Context 里实际观察到的全部引用范围，保留
Run、引用位置、原始 URL 与去重来源的映射。`Source Completion Manifest`
固定每个来源的人工处置与选定正文快照。两者都不可由 latest 查询替代。

Answer Semantic 与 Source Preparation 在 Citation Manifest 冻结后独立推进。
Evidence 必须绑定同一 Context 的精确 Citation Manifest、Completion Manifest、
Answer ResultVersion 和审核该准确结果的 Review。

## 4. 来源处置语义

允许进入完成清单的终态只有：

```text
READY
WAIVED_WITH_LIMITATION
```

`READY` 仅表示正文身份、内容 Gate、不可变文件、hash 和 passages 合格，
不表示正文主张真实或支持某个 Reason。

`WAIVED_WITH_LIMITATION` 只能由人工显式提交，必须保存操作者、原因、时间和
影响。它只关闭处置项，不提供 SUPPORTS 或 NO_SUPPORT。抓取失败、验证页、
未授权和待人工正文都不能自动转成 WAIVED。全部来源被放弃时完成清单状态为
`NO_USABLE_SOURCE`，不得获得依赖来源证据的资格。

## 5. Evidence 双输入 Gate

Evidence 执行前必须确定性验证：

1. Analysis、Context 与 Project/Prompt 一致；
2. Citation Manifest 属于该 Context 且 hash 精确匹配；
3. Completion Manifest 覆盖相同 Citation Manifest 的全部来源；
4. 每个 READY 来源绑定指定的不可变 Snapshot、文件和 passage hash；
5. Answer ResultVersion 属于相同 Analysis/Context；
6. Review 精确绑定 Answer 结果 hash 与 reviewable set hash；
7. 实际消费输入保存到新 Evidence 结果版本，不动态读取 current/latest。

任一条件失败必须返回具体 blocker。合法零 Evidence 只能来自实际完成的评估，
未执行、失败、未召回和没有可用来源不得包装成零结果。

## 6. 发布数据库

首发形态固定为单主机 SQLite、一个 API 进程、一个业务 worker、重任务并发 1。
发布库只通过独立 Alembic release migration 初始化；应用启动只校验 revision、
表白名单、SQLite runtime 版本、外键和 WAL，不调用 `create_all()` 或补列逻辑。

SQLite runtime 必须包含 WAL-reset 修复：`>=3.51.3`，或官方回补版本
`3.50.7+` / `3.44.6+`。不满足时正式 release 入口拒绝启动。

## 7. 授权边界

本开发指令授权本地代码、测试、文档、独立新库迁移和工程验证。它不自动授权
浏览器采样、来源抓取、外部 LLM、人工事实确认、自动 WAIVE 或发布。授权不足
不阻塞离线工程工作，但真实消费必须明确标为待授权。

## 8. 首批验收

- 新空库经 release migration 建立且仅包含白名单表；
- 未迁移、错 revision、禁用表出现或 SQLite runtime 不安全时拒绝启动；
- 正式 API/UI 可冻结引用清单、人工补录同一来源正文、形成文件/hash/passages；
- 验证页、登录墙和错误正文不能 READY；
- 新正文创建新 Snapshot/Completion 版本，不改历史；
- Pending、错版、跨 Context、未审核 Answer 均阻断 Evidence；
- 合格输入由 Evidence 消费指定版本；
- GET 无业务写入；重启后对象、审核和文件绑定保持。

## 9. 2026-09-20 实施结果

- release revision：`20260920_02`；正式 schema 为 26 张白名单业务表，另含
  Alembic 自有的 `alembic_version`；
- release SQLite DBAPI：静态链接 SQLite `3.51.3` 的 `pysqlite3`；下载源和
  SHA-256 固定，运行时版本不安全时迁移/启动均 fail closed；
- 正式拓扑：一个 `app.release_main:app` API 进程和一个
  `scripts/release_worker.py` 串行业务 worker；API 不在请求线程或
  `BackgroundTasks` 中执行采样、Answer 或 Evidence；
- Analysis/Answer/Evidence 由 API 排队；queued 在服务重启后保留，只有正在
  执行且结果不确定的任务转为显式 `INTERRUPTED` / `EVIDENCE_FAILED`；
- Evidence 请求在排队前完成双输入 Gate，并把精确版本绑定写入队列；worker
  消费时再次校验相同绑定，不查询 latest；
- release frontend 只暴露“来源与证据主链”，不注册 Strategy、Execution、
  Publication、Retest 或 `/api/optimization`；
- 新空库已通过正式迁移脚本、API、worker 和页面启动验收；Snapshot、Review、
  Result 与正文文件的重启后绑定由迁移库专项测试覆盖。

首轮真实验收已在 release 库创建固定 Analysis/Context、38-source Citation
Manifest、1 个经正式补录入口形成的真实 Snapshot，以及 3/3 准入的 Answer
ResultVersion。其余 37 个来源和精确 Answer Review 尚待人工处置，因此 Completion
Manifest 与 Evidence 正向消费仍未发生；这项阻断符合本契约，不能用候选抓取
文件、自动 WAIVE 或 fixture 绕过。

实现 checkpoint：`9391be7`、`279c717`、`f421a95`、`7e657c9`、`d561363`、
`50f19f6`、`d150e17`。

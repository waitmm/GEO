# GEO M1.1 公司试用候选收口报告

日期：2026-10-29（Asia/Shanghai）  
候选版本：`geo-internal-beta.m1.1-rc1`  
阶段结论：`SOURCE_CANDIDATE_READY / COMPANY_PILOT_NOT_READY`

## 1. 一页结论

GEO 已有可实际使用的本机 Beta：Monitor、时间范围冻结、Optimize、完整结果、
导出、反馈和定时采集页面均可操作，2026-10-29 已保存一份新的 22 Run 真实
Evidence Pack 结果。当前 8032 服务来自
`/Users/bmwqr/Library/Application Support/GEO Beta`，其 `VERSION` 标记为
`068d379`，模型和采样能力开关均为 1；每日采集计划在页面中显示为运行中。

这不等于公司部署已完成。公司候选必须从当前受控分支重新生成同平台 prepared
release，不能复制现有活动安装，也不能把本机外部调用授权带到新机器。新安装、
恢复、升级和回滚均强制将模型调用与定时采样设为 0，待目标机安全验收后分别授权。

本轮变更分类为 `IMPLEMENTATION_CHANGE`。未改变 Evidence、Truth、分级交付、
Run 准入或多批结果语义；未调用文心、DeepSeek、来源抓取或发布接口。

## 2. D0：唯一版本

Git 关系已核实为线性祖先链：

```text
50a4a57 -> ... -> e7b09e6 -> ed23679 -> 60e7551 -> 8cdc696 -> 本报告提交
```

- `50a4a57` 是早期本机基线，不是当前公司部署候选。
- `e7b09e6` 是容量 shadow 与现有产品功能基线。
- `ed23679` 仅增加总控文档。
- `60e7551` 增加独立 M1.1 离线 QA。
- `8cdc696` 增加 fail-closed 安装、备份、恢复、升级和回滚能力。

活动本机安装不能作为 D0 身份依据：其版本标签与若干实际文件不完全对应。因此
公司包必须生成 `PREPARED_RELEASE_FINGERPRINT.json`，同时冻结源码 SHA、数据库
revision、OS、CPU 架构、Python、Node 构建版本及全部交付文件的路径、大小、权限与
SHA-256。`.env`、访问凭证、浏览器 profile 与运行数据不进入包；安装会在复制前后
复核完整文件 manifest。候选只承诺同
OS/架构使用，不宣称跨 macOS/Linux 或跨 CPU 可移植。

## 3. D1：安装、升级、回滚

唯一运维入口为 [`scripts/m1_beta_ops.sh`](../../../scripts/m1_beta_ops.sh)：

```bash
./scripts/m1_beta_ops.sh install HOME PREPARED_SOURCE RELEASE_ID SOURCE_SHA SCHEMA_REVISION
./scripts/m1_beta_ops.sh start HOME
./scripts/m1_beta_ops.sh status HOME
./scripts/m1_beta_ops.sh stop HOME
./scripts/m1_beta_ops.sh backup HOME NEW_BACKUP_DIR
./scripts/m1_beta_ops.sh restore BACKUP_DIR NEW_EMPTY_HOME
./scripts/m1_beta_ops.sh upgrade HOME PREPARED_SOURCE RELEASE_ID SOURCE_SHA SCHEMA_REVISION
./scripts/m1_beta_ops.sh rollback HOME BACKUP_DIR PREVIOUS_RELEASE_ID
```

已实现和离线验证：版本化 release 目录、原子 current 指针、启停与状态、停止写入方、
活动队列 fail-closed、升级前备份、隔离迁移、显式启动、保留旧状态回滚、Worker
单实例。升级和回滚完成后服务保持停止，避免自动恢复历史外部任务。

尚未完成：针对公司目标电脑的 prepared release、系统服务安装、局域网入口和实际
启动。目标机 OS/架构、常开策略、服务账号、磁盘、备份盘和网络边界尚未提供。

## 4. D2：数据保护与恢复

活动 SQLite/WAL 不再通过复制主 `.db` 文件备份。生命周期工具使用 SQLite Online
Backup，执行 integrity/foreign-key/hash 校验，并归档 Evidence 和 prepared source
文件。恢复只写入新的空 home，重新定位 prepared-source 路径并验证原 hash；不修改
回答、Truth、ResultVersion 或 Evidence 内容。

任何 Worker 可消费的 `QUEUED`、`RUNNING`、`retrying`、`EVIDENCE_QUEUED`、
`AUTO_FETCH_QUEUED` 或 `RESERVED_IN_FLIGHT` 记录都会阻断启动/备份/升级/回滚。
关闭模型和采样 UI 开关不能代替队列检查。数据库 integrity、外键违规或活动队列任一
不合格都会阻断。macOS 全局 launchd 标签还必须与目标 HOME 的数据库和工作目录一致，
否则拒绝停止、重启或查看，避免误操作另一安装实例。

内部模型预算账本随备份保留为只读审计材料，包含历史未知送达状态；恢复时不会放回
活动账本路径，也不会成为新机器授权。回滚额外要求 stopped marker、备份版本、schema
revision 和目标 release manifest 一致，并同步更新 `VERSION`。

离线证据：

- 运维 + Worker 生命周期保护：24 passed；
- 其他权限/容量/范围/导入/Agent 回归：88 passed；
- 前端：36 passed，Release build PASS；
- 数据库隔离迁移到 `20261022_01`，schema `READY`；
- committed WAL、跨根路径、升级、回滚、单实例、权限隔离均有专项测试；
- 外部调用 0。

活动本机 Beta 还完成了一次不写业务数据、不触发模型或采样的真实浏览器只读验收：

- [验收报告 JSON](acceptance/m1-1-local-readonly-20261029/report.json)
- [Monitor / Optimize / 历史结果验收截图](acceptance/m1-1-local-readonly-20261029/after-restart.png)
- [采样计划状态截图](acceptance/m1-1-local-readonly-20261029/sampling-enabled.png)

该验收确认当前本机页面、历史真实结果和导出链路可用；它不替代候选版本在公司
目标机上的 D3 验收。

活动本机数据库尚未执行本轮备份或升级；这是有意的数据保护边界，不将离线副本
演练伪装成真实迁移成功。

## 5. D3：公司机器验收

状态：`NOT_EXECUTED`。

当前访问控制对所有非 loopback 请求强制 HTTPS。公司多人访问不能通过把 Uvicorn
改成 `0.0.0.0` 实现；应保持应用监听 loopback，在受控 HTTPS 反向代理后配置
`GEO_RELEASE_ACCESS_CONFIG`，并验证可信代理、Host/Proto/客户端地址、两个普通
账号、项目隔离和撤权。未经目标网络授权与真实测试，本候选不是 LAN-ready。

D3 仍需在目标机完成：

1. prepared release 指纹与目标 OS/架构校验；
2. 独立数据库副本迁移、备份与恢复；
3. Backend/Worker 启停、重启、heartbeat 和单实例；
4. 两个普通账号的项目隔离、写入归属和撤权；
5. Monitor、范围冻结、历史 Optimize、导出、反馈和刷新恢复；
6. 独立授权后仅一次真实 AI 优化；
7. 明确确认自动文心采集仍关闭；
8. 保存浏览器、日志、数据库和回滚证据。

## 6. 容量问题与试用边界

`GEO-CAP-001` 继续为 P1。当前真实 22 Run 范围可生成结果，现有 v3 会在构建
Evidence Pack 时于 Provider 前拒绝核心超限，保持零模型调用、零结果版本；不会
静默截断、重复计费或伪装为证据不足。多批生成与结果合并仍是未批准语义，不在
M1.1 中接通。

首轮公司试用应选择业务上可解释的小范围。容量提示出现时缩小时间范围或明确
Run，不以提高 90,000 字符上限掩盖问题。

## 7. 当前发布决定

- 本机产品：`M1_LOCAL_BETA_IN_USE`。
- 源码与离线运维候选：`M1_1_SOURCE_CANDIDATE_READY`。
- prepared release：`BLOCKED_TARGET_PLATFORM_AND_BUNDLE`。
- 公司局域网部署：`NOT_EXECUTED`。
- 公司试用：`NOT_READY`，必须先通过 D3。
- 下一阶段范围：仅公司部署与 2～3 名爱短链同事试用；不进入八木屋，不扩建平台。

详细操作见 [M1 生命周期与迁移手册](M1_LOCAL_LIFECYCLE_RUNBOOK.md)，独立保护证据见
[M1.1 QA Guardrails](M1_1_QA_GUARDRAILS.md)，总项目状态见
[项目总控](PROJECT_CONTROL_2026-10-29.md)。

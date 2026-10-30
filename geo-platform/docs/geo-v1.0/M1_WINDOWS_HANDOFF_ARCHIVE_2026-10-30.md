# GEO M1 Windows 迁移交接存档

存档时间：2026-10-30（Asia/Shanghai）
变更分类：`IMPLEMENTATION_CHANGE`
源码基线：`codex/m1-server-budget-policy` / `f6d3f11cc964e1865cac79646a3ef90338faa868`
归档分支：`codex/m1-windows-handoff-20261030`

## 1. 当前结论

GEO M1 已结束 Mac 局域网试用部署，下一步迁移到一台 Windows 机器供公司局域网同事使用。
本次只改变部署目标和访问方式，不改变 Run、Evidence、Truth、冻结范围、AgentResultVersion、
正式 V2 隔离或分级交付规则。

截至本存档生成时，已现场核验：

- `com.geo.beta.backend`、`com.geo.beta.worker`、`com.geo.beta.proxy` 均未加载；
- TCP `8032`、`8443` 均无监听进程；
- `config/lan-enabled` 为 `0`；
- Mac 数据库、Evidence、历史结果、日志和备份均保留，未删除或改写；
- Mac 最后安装版本为 `geo-m1.1-lan-3fcad83`，对应
  `3fcad833a9c5fd3b0d9e701cd293061dade3e5a3`；
- 当前源码候选晚于最后安装版本，Windows 包必须从冻结源码重新构建，不能直接复制 Mac 运行目录。

状态定义：`MAC_DEPLOYMENT_STOPPED / WINDOWS_HANDOFF_PREPARED / WINDOWS_DEPLOYMENT_PENDING`。

## 2. 保留资产

Mac 归档根目录：

```text
/Users/bmwqr/Library/Application Support/GEO Beta
```

需保留并在迁移时重新核验的资产：

- `data/geo-beta.db` 及一致性备份；
- `evidence/`；
- `backups/`；
- 已保存的 AgentResultVersion、反馈与审计记录；
- 无密钥配置和版本清单；
- 必须由 Windows 重新注入的外部服务凭证清单，不在 Git 或交接包中保存密钥值。

Mac 的 `.venv`、launchd 文件、TLS 私钥/证书、旧邀请凭证和浏览器平台相关运行文件不迁移。
旧证书当前仅作为历史备份留存，不再参与访问控制；完成 Windows 数据恢复验收前不删除这些归档文件。

## 3. Windows M1.1 目标架构

第一轮只服务可信公司局域网内的 2～3 名爱短链同事：

```text
局域网浏览器
  -> http://<Windows 固定局域网 IP>:8032
  -> 服务端密码登录
  -> GEO Backend + 单实例 Worker
  -> 本机 SQLite + Evidence + 日志 + 备份
```

访问策略：

- 不部署私有 CA、客户端证书或用户侧证书安装流程；
- 使用一个由管理员在服务端设置和轮换的试用密码，不让员工填写 Token、金额或额度；
- 密码只保存不可逆哈希；会话 Cookie 使用 `HttpOnly`、`SameSite` 和有限有效期；
- Windows 防火墙仅允许 `LocalSubnet` 或明确的公司私有网段访问；
- 禁止公网暴露、路由器端口映射和跨不可信网络访问；
- HTTP 不提供链路加密，因此该简化方案只允许在可信公司局域网内试用；若未来跨网访问，必须重新评估 HTTPS 或 VPN。

## 4. Windows 目录与运行方式

建议目录：

```text
C:\ProgramData\GEO Beta\
├── app\
├── config\
├── data\geo-beta.db
├── evidence\
├── logs\
├── backups\
└── runtime\
```

目标管理入口：

```powershell
.\install.ps1
.\start.ps1
.\stop.ps1
.\restart.ps1
.\status.ps1
.\backup.ps1
.\restore.ps1
.\set-password.ps1
```

优先使用 Windows 任务计划程序注册 Backend 和单实例 Worker，设置为开机启动并写入独立日志。
运行时不依赖 Node；前端应在发布包构建阶段完成。Python 使用 Windows 上实际验收并锁定的版本，
不得复制 Mac 虚拟环境。

## 5. 迁移顺序

1. 保持 Mac 服务停止，使用 SQLite Online Backup 或现有生命周期工具生成一致性备份。
2. 冻结唯一 Windows 候选 SHA、数据库 revision、前端构建指纹和文件 manifest。
3. 复制数据库备份、Evidence 和无密钥配置；不复制打开中的 WAL 组合冒充备份。
4. 在 Windows 建立全新 Python 环境，安装锁定依赖并执行 Release Migration。
5. 在副本上校验 SQLite integrity、foreign key、历史结果、Evidence hash 和文件路径重定位。
6. 先只监听 `127.0.0.1` 完成本机验收，再配置服务端密码、固定私网地址和防火墙规则。
7. 完成启动、停止、重启、备份、恢复和回滚演练。
8. 使用两台局域网浏览器复验登录、项目隔离、Monitor、范围冻结、历史结果、导出、反馈和刷新恢复。
9. 公司 AI 优化额度和自动采样必须独立授权；不得继承 Mac 历史实验余额或运行开关。

## 6. Windows 部署 Gate

以下条件全部通过后，才可宣布 `COMPANY_PILOT_READY`：

- 唯一发布 SHA、manifest、数据库 revision 与运行日志一致；
- 未登录、错误密码和非可信网段请求均被拒绝；
- 两个普通浏览器会话能够登录且项目数据不串联；
- Backend/Worker 重启后任务和历史结果可恢复，Worker 保持单实例；
- 数据库备份恢复后 AgentResultVersion、Evidence、反馈仍可读取；
- 管理员关闭模型额度时历史功能可用，新生成明确 fail-closed；
- 超容量范围在外部调用前停止，不静默截断、不重复计费；
- 自动文心采样默认关闭；
- 服务未监听公网地址，Windows 防火墙规则仅覆盖批准私网；
- 浏览器主流程有真实验收证据，不能仅以单元测试或构建成功代替。

## 7. 当前未完成项

- Windows 发布脚本和共享密码门禁已完成离线实现，见
  [Windows 试用运行手册](M1_1_WINDOWS_PILOT_RUNBOOK.md)；尚未在目标 Windows 执行；
- 目标 Windows 的版本、架构、固定局域网 IP、管理员权限和备份盘尚未现场确认；
- Mac 数据尚未生成用于本次迁移的最终一致性快照；
- 公司模型额度、自动采样许可均未授权；
- `GEO-CAP-001` 生产多批合并仍是 P1，不纳入本次迁移扩建。

因此，本存档只证明 Mac 停服和 Windows 交接边界已经冻结，不宣称 Windows 已部署成功。

## 8. 恢复与回退

迁移失败时不得修改原 Mac 归档来“修复”Windows 数据。应删除失败的 Windows 测试实例，
从同一一致性备份重新安装。若必须临时恢复 Mac，仅能由管理员明确决定并重新启用服务；
旧证书方案不因保留历史文件而自动恢复。

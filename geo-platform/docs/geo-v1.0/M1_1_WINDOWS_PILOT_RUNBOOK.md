# GEO M1.1 Windows 公司试用运行手册

状态：`OFFLINE_IMPLEMENTED / TARGET_WINDOWS_NOT_VERIFIED`  
适用范围：爱短链 Project 1、可信公司局域网、2～3 人受限试用  
禁止范围：公网、跨不可信网段、继承 Mac 模型额度、自动文心采样

## 1. 安全边界

本候选不使用私有 CA、客户端证书或邀请凭证。Windows 服务直接监听一个明确的 RFC1918
固定地址，通过一个服务端共享密码登录，并由 Windows 防火墙把 8032 端口限制在指定公司私网。

HTTP 不提供链路加密。只有产品负责人明确接受可信局域网风险时才能启用；不得配置
`0.0.0.0`、公网地址、路由器端口映射或 Public 防火墙 Profile。共享密码只能证明当前会话
知道试用密码，不能证明员工个人身份。页面反馈人是业务记录，不是认证身份。

## 2. 准备条件

- Windows 10/11 x64，管理员 PowerShell；
- 固定或 DHCP 保留的 RFC1918 IPv4；
- Python 3.12 x64；
- 已构建 `frontend/dist` 的冻结源码包；
- Mac 停服后生成的完整 `m1_beta_ops.py backup` 目录（含 manifest、数据库、Evidence 和审计账本）；
- 离线 wheelhouse，或安装时明确使用 `-AllowDependencyDownload`；
- 足够存放数据库、Evidence、日志和至少两份备份的磁盘空间。

默认安装根：`C:\ProgramData\GEO Beta`。不要复制 Mac `.venv`、launchd、TLS 文件、浏览器
Profile 或旧邀请凭证。

## 3. 首次安装

以管理员 PowerShell 执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd <解压后的冻结发布包>\scripts\windows
.\install.ps1 `
  -Source <解压后的冻结发布包> `
  -RestoreBackup D:\geo-migration\full-backup `
  -ReleaseId geo-m1.1-windows-<短SHA> `
  -SourceSha <完整Git-SHA> `
  -PythonExe py.exe `
  -Wheelhouse D:\geo-migration\wheelhouse `
  -BindAddress 192.168.3.200 `
  -TrustedCidr 192.168.3.0/24 `
  -ProjectId 1
```

安装过程交互设置共享密码。密码不进入命令行、环境变量或配置明文；配置只保存随机 salt 和
scrypt verifier。安装结束状态必须是 `INSTALLED_STOPPED`，不会自动启动模型或采样。

只接受 `-RestoreBackup` 完整备份目录；`-DatabaseBackup` 裸数据库入口会明确拒绝，不能证明
Evidence 完整或历史费用审计保留。安装前先核验 integrity、外键、schema revision 和活动队列，
再按 manifest 校验内容 hash，直接恢复到最终 Home。已存在非空 Home 不得覆盖。

恢复会把来源文件绑定重定位到最终 `Home\evidence`，保留 `Home\backups\audit-ledgers`
和 `RESTORE_REPORT.json`。历史费用账本仅供审计，不成为新实例授权；UNKNOWN 记录原样保留。
任何安装阶段失败时保留现场并停机，不自动删除恢复目录或覆写重装。

## 4. 管理命令

```powershell
.\start.ps1
.\status.ps1
.\restart.ps1
.\stop.ps1
.\backup.ps1 -BackupOutput D:\GEO-Backups\2026-10-30
.\restore.ps1 -RestoreBackup D:\GEO-Backups\2026-10-30 -TargetHome D:\GEO-Restore-Check
.\set-password.ps1 -ProjectId 1
```

启动成功后显示实际地址，例如 `http://192.168.3.200:8032`。改密码会立即使已有会话失效。
Backend 和 Worker 分别由 Windows 任务计划程序管理，均禁止并行重复实例。

`restore.ps1` 只允许把完整备份恢复到一个新的或空的目录，用于恢复验收或故障恢复准备；它不会
覆盖 `C:\ProgramData\GEO Beta`、注册任务或启动服务。要重建正式实例，请使用第 3 节的
`install.ps1 -RestoreBackup ...` 并指定一个新的 Home。

## 5. 首次目标机验收

1. `status.ps1` 显示 Backend、Worker 已安装且运行。
2. Windows 本机打开站点，错误密码被拒绝，正确密码成功。
3. 同一私网另一台电脑可以访问；非允许网段和 Public Profile 不能访问。
4. 只显示 Project 1，不宣称具备可信个人身份或跨项目账号隔离。
5. Monitor、冻结范围、历史 Optimize、导出和反馈可以读取。
6. 刷新、重启后数据和任务状态保留。
7. `backup.ps1` 生成的备份通过 integrity、foreign key、Evidence hash 校验。
8. 模型调用和自动采样保持关闭。

未在实际 Windows 上完成以上步骤前，状态只能是
`OFFLINE_IMPLEMENTED / COMPANY_PILOT_NOT_READY`。

2026-10-30 离线修复：移除会产生失效绝对路径的临时恢复后搬移流程。合成 WAL 数据、
prepared-source hash、未知费用审计的恢复验收在隔离目录执行；PowerShell 目标机命令和
Windows ACL/防火墙仍须在实际 Windows 验证，不将静态检查当作部署通过。

## 6. 回退

目标机验收失败时停止两个任务并保留日志。不要修改 Mac 归档数据库来修复 Windows。
从同一份一致性备份重新建立一个干净 Windows Home；不要把失败实例的数据库覆盖回原备份。

# GEO 1.0 Release 运行手册

本手册记录当前正式入口，不代替[验收矩阵](17_验收矩阵.md)。业务边界、邀请权限和备份实现详见[运行与数据边界](15_运行与数据边界.md)。尚无最终完成声明。

新人工操作的审计身份由服务端访问会话记录，表单名字不能替换。没有邀请配置的本机访问统一记为 `local-owner`，不证明具体自然人；需要区分操作者时使用已有的独立邀请账号。旧记录保留原当时身份，不回填为当前账号。

## 环境与安装

已测主机为 macOS、Python 3.14.3、Node 24.14.0，单机一个 API、一个业务 worker。数据库及文件放本机持久磁盘；不要把 WAL 数据库放多机共享盘。2026-10-09 独立新虚拟环境已完成依赖安装、SQLite3.51.3构建、空库迁移03和API健康启动，54项隔离权限/来源/目录回归通过；临时API已关闭。证据见 `backend/artifacts/acceptance/20261009-clean-install/pytest.xml` 及开发记录，不代表所有操作系统或真实平台登录均已验收。

在仓库根目录依次运行：

```bash
python3 -m venv geo-platform/backend/.venv
geo-platform/backend/.venv/bin/python -m pip install -r geo-platform/backend/requirements.release-build.txt
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/bootstrap_release_sqlite.py
```

最后一步复用已有校验 SHA-256 的 SQLite 3.51.3 / pysqlite3 构建脚本，需要编译工具和访问其固定发行源，使用 certifi CA 校验证书。TLS或文件校验失败不得绕过。实际应用 DB-API 必须通过版本安全检查，系统 `sqlite3` 命令版本不能代替。

```bash
cd geo-platform/frontend
npm ci
npm run build:release
```

npm 使用现有锁文件。构建输出在 `frontend/dist`；版本标记 `geo-release-build.json` 必须存在。不要把 legacy 构建作为 release 发布。

## 配置与迁移

后端从 `backend/.env` 读取本机配置，不提交该文件、密钥或浏览器登录态。保持原有有效配置，不用示例覆盖。

| 配置 | 用途 |
| --- | --- |
| `GEO_RELEASE_DATABASE_URL` | API、迁移、worker 使用同一 SQLite 绝对路径，例如 `sqlite:////absolute/path/geo_release.db` |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | 只在授权任务内调用已核实模型；凭证存在不代表无限调用授权 |
| `GEO_RELEASE_ACCESS_CONFIG` | 远程受控邀请配置路径，权限0600；未配置时只允许本机访问 |
| `GEO_API_PROXY_TARGET` | 开发前端代理地址，默认由启动脚本设置 |

在 backend 工作目录，以同一数据库配置显式迁移：

```bash
.venv/bin/python -m alembic -c alembic.release.ini upgrade head
.venv/bin/python -m alembic -c alembic.release.ini current
```

代码目标 revision 为 `20261010_02`，本机正式库已部署版本见交付验收记录，不要假定源码更新会自动迁移。02仅新增追加式事实纠错表及不可变约束，不更新原事实；01新增补充公开资料表。应用启动只验证，不自动建表补列。已有库先按下节备份并隔离恢复，不清库、不导入旧工作流表。历史内容保持未知取证状态，不补造抓取证明。补充资料、纠错、请求授权随数据库备份；原来源文件仍须同时备份。

2026-10-12 本机已保护性部署02，见`deploy-truth-20261012/report.json`；46旧业务表和v7指纹保持，正式worker关闭。`truth-correction-20261012-before`及对应隔离恢复验证109来源绑定、5813文件。该证据不意味着其他机器已迁移。

## 启动与停止

仓库根目录开发入口：

```bash
./scripts/dev.sh
```

API 默认 `http://127.0.0.1:8021`，页面 `http://localhost:5173`。默认不启动 worker；页面排队不是计算已开始。外部操作范围及预算确认后，可显式 `MONITORING_WORKER=1 ./scripts/dev.sh`。不要启用退役的 `DAILY_SCHEDULER`。

部署构建后，可在 backend 分别运行：

```bash
.venv/bin/python -m uvicorn app.release_main:app --host 127.0.0.1 --port 8021
.venv/bin/python scripts/release_worker.py --interval 10
```

API 也可直接提供构建后的首页。一个 worker 处理采样计划及已授权任务，数据库旁文件锁防止重复进程。终端 Ctrl+C 正常停止；启动脚本只停止它自己启动的子进程。不要用批量 kill 关闭无关服务。远程部署需 HTTPS、明确代理可信边界及邀请配置，不能直接开放本机免登录模式。

## 健康、恢复与费用

- GET `/api/health` 检查 API 模式和 worker 心跳；GET `/api/release/status` 检查迁移和 SQLite 实际值。健康不代表业务任务成功。
- worker 独占启动后恢复中断状态；API 重启不抢占任务。先看准确任务和错误阶段，再恢复未完成部分。
- 预算、请求预留和完整响应 artifact 持久化。未知用量必须核实，不能按0计费、重启重置额度或自动重复请求。
- 模型别名可能由供应商改指向新版本。授权和审计记录 requested/effective/response model、计费依据和日期；需要改变已授权模型范围时停止相应调用。
- 2026-10-10 公开文档核对：[DeepSeek更新记录](https://api-docs.deepseek.com/updates/)说明旧`deepseek-v4-flash`已由V4.1-Flash提供服务，正式请求ID为`deepseek-flash`。这是供应商声明，不是本批实际响应身份；本批尚未调用，不能沿用旧结果的模型质量结论。已在待授权范围明确实际版本，未静默修改配置。
- 同日[官方人民币价格表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)所列Flash高峰价：缓存命中输入0.04、未命中输入2、输出8元/百万token。验收待授权方案使用10元/百万token保守预占、累计300万token/30元硬上限，不依赖低峰优惠，不冒充账单实扣；执行前仍需核对有效日期与供应商身份。
- 验证码、登录失效及独立会话失败停止相关采样，不绕过访问限制。正文不可读保留引用观察，禁止自动WAIVE。
- API/worker 日志不要公开；正文、模型完整响应、截图及 trace 作为受控 artifact 保存，不提交 Git。

## 备份与恢复

从 backend 使用 SQLite Online Backup API，并包括明确 artifact 根目录：

```bash
.venv/bin/python scripts/release_backup.py --database geo_release.db --output backups/new-backup --artifact-root artifacts
.venv/bin/python scripts/release_backup.py --output backups/new-backup --verify
.venv/bin/python scripts/release_upgrade_check.py --backup backups/new-backup --output backups/new-isolated-restore
```

输出目录必须不存在。文件复制过程中变化、hash或外键失败均应停止，不能报告恢复成功。停下相关写任务后重做完整备份。已有恢复证据校验相同部署路径下的正文和结果绑定；更换根目录后的路径重定位尚未验收。密钥和登录profile不自动归档，另用受控凭证流程维护。

## 验收命令

在 backend 执行 `.venv/bin/python scripts/delivery_acceptance.py --checks-only`，会运行适用测试、启动/客户端检查、release构建和八条隔离浏览器路径（配置、比较、空事实稿件、官方资料核实、BASIC资料、补充公开资料、单项事实纠错、权限隔离）。浏览器需已安装 Chrome；不会自动发起真实平台或付费模型调用。全套运行期间不要编辑源码或重建 dist；组合记录核对开始与结束指纹，变化则不能归为同一版本通过。

报告保存在 `backend/artifacts/acceptance/<batch>/report.json`。源码在验收中变化会判失败；`--skip-browser`、`--coverage-only` 不能代表产品完成。真实集成、模拟传输和缓存必须分开记录，未跑用例继续保留未通过。

同一工作区构建期间不要运行挂载dist的API/浏览器测试，Vite会暂时删除assets；浏览器验收与正式页面检查也顺序执行，避免机器争用干扰加载时限。失败报告保留，新结果使用独立目录，不覆盖原FAIL。

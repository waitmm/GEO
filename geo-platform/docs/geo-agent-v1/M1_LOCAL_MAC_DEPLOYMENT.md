# GEO M1 Beta 本机部署

长期运行副本安装在 `/Users/bmwqr/Library/Application Support/GEO Beta`，仅监听
`127.0.0.1:8032`。前端使用已构建的 release 静态文件，由 FastAPI 同源提供；后台同时启动
单并发 release worker。后端与 Worker 由当前 macOS 用户的 `launchd` 托管，关闭终端不会停止服务。
工作区中的 `runtime/geo-m1-beta/geo-beta` 是便捷入口，不承载活动数据库。

```bash
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta start
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta stop
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta restart
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta status
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta logs
```

网站地址：`http://127.0.0.1:8032/`

数据与运行文件（均相对于 `/Users/bmwqr/Library/Application Support/GEO Beta`）：

- 活动数据库：`data/geo-beta.db`
- 初始备份：`backups/geo-beta.initial.db`
- 历史实验预算审计副本：`evidence/historical-experiment-budget.sqlite3`
- Evidence Pack 与原始响应审计：`evidence/`
- 后端与 Worker 日志：`logs/`
- 进程 PID 与 Worker heartbeat：`run/` 和 `data/*.worker.*`

`GEO_AGENT_BETA_DAILY_MODEL_CALLS` 由部署管理员控制。启用后，员工只需点击“创建并运行 AI
优化”；模型、Transport、并发、重试和技术停止边界全部由服务端策略管理，页面不再要求员工
填写请求数、Token、金额、单价或计费依据。关闭时仍可查看、导出和反馈历史真实结果。

## 2026-10-20 本机验收

- Release migration：`20261020_01`
- 服务：backend 与单并发 Worker 经显式停止、重启后均为 `RUNNING`
- 数据：15 个 AgentExperimentRun、3 个 AgentResultVersion、1 条追加式反馈
- 浏览器：真实 Project 1 / Prompt 1 的 Monitor、Evidence Pack 六段结果、历史、复制、Markdown
  导出和反馈均通过；刷新与服务重启后数据保持
- 网络边界：仅 `127.0.0.1:8032` 监听
- 外部模型调用：0；新生成保持 history-only fail-closed
- 浏览器报告：`acceptance/after-explicit-restart/report.json`

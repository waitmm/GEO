# GEO M1 Beta 本机部署

本机安装目录默认为 `/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta`，仅监听
`127.0.0.1:8021`。前端使用已构建的 release 静态文件，由 FastAPI 同源提供；后台同时启动
单并发 release worker。

```bash
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta start
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta stop
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta restart
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta status
/Users/bmwqr/Desktop/python/GEO/runtime/geo-m1-beta/geo-beta logs
```

网站地址：`http://127.0.0.1:8021/`

数据与运行文件：

- 活动数据库：`data/geo-beta.db`
- 初始备份：`backups/geo-beta.initial.db`
- 历史实验预算审计副本：`evidence/historical-experiment-budget.sqlite3`
- Evidence Pack 与原始响应审计：`evidence/`
- 后端与 Worker 日志：`logs/`
- 进程 PID 与 Worker heartbeat：`run/` 和 `data/*.worker.*`

默认 `GEO_AGENT_BETA_DAILY_MODEL_CALLS=0`，因此可查看、导出和反馈历史真实结果，但不能
批准新的付费生成。开启新生成还需要独立日常预算账本、累计额度和逐任务硬上限；仅设置开关
不构成预算授权。

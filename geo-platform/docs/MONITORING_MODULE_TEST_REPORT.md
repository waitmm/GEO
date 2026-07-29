# 文心助手网页端监测模块测试报告

## 当前测试状态

本轮尚未实现 Playwright Collector，因此真实文心网页端集成测试未执行。

## 已验证基础链路

此前 V0 已通过：

```powershell
python -m compileall backend\app
python scripts\smoke_test.py
python scripts\wenxin_config_smoke.py
npm.cmd run build
```

说明：

- 后端基础模型和 API 可导入。
- Mock 监测可完成项目、Prompt、任务、观测、引用、指标链路。
- 文心 API 未配置凭证时可正常记录失败状态。
- 前端可构建。

## 本轮新增验证

```powershell
python -m compileall backend\app
python scripts\monitoring_module_smoke.py
python scripts\smoke_test.py
python scripts\wenxin_config_smoke.py
```

结果：

- monitoring 模块 Python 编译通过。
- `/api/monitoring/tasks` 可创建 `wenxin_web_audit` 任务。
- 每个问题可按 `run_count` 生成 queued runs。
- `/api/monitoring/runs` 可查询生成的 runs。
- 原 V0 Mock 监测链路仍通过。
- 文心 API 未配置凭证失败链路仍通过。

注意：

- 不要并行运行多个 SQLite TestClient startup 测试；当前无 Alembic，`create_all` 在并行建表时可能出现本地 SQLite 竞态。后续迁移到 Alembic/PostgreSQL 后解决。

## Phase 2 新增验证目标

```powershell
python scripts\monitoring_module_smoke.py
npm.cmd run build
```

预期：

- 无 Playwright 或无浏览器 Profile 时，run 标记为 `failed`。
- `error_stage`、`error_type`、`error_message` 可见。
- `collector_log` 写入 `artifacts/monitoring/<run_id>/collector.log`。
- 前端“文心网页审计”页面可创建任务并展示运行阶段。

## Phase 2 当前验证结果

已执行：

```powershell
python -m compileall backend\app
python scripts\reference_parser_smoke.py
python scripts\monitoring_module_smoke.py
python scripts\smoke_test.py
python scripts\wenxin_config_smoke.py
npm.cmd run build
```

结果：

- 后端编译通过。
- 引用解析 smoke 通过，覆盖 HTML entity、百分号、`\u0022`、linkUrl/linkTitle、候选源标题匹配和静态资源过滤。
- 文心网页审计任务创建通过。
- `execute_now=true` 会触发同步执行器。
- 当前环境未安装/未配置 Playwright 真实浏览器时，run 可进入 failed，并写入 collector 日志。
- V0 Mock 链路仍通过。
- 文心 API 未配置 Key 链路仍通过。
- 前端 TypeScript 与 Vite 构建通过。

生成证据：

```text
backend/artifacts/monitoring/<run_id>/collector.log
```

## 待新增测试

- linkUrl/linkTitle 解码单元测试。
- URL 规范化测试。
- 静态资源过滤测试。
- 品牌别名匹配测试。
- 推荐强度规则测试。
- reference_sources 与 retrieval_candidates 分表写入测试。
- artifact 保存测试。
- Profile 登录态检查测试。
- 文心真实问题 `谁是最好的二维码工具` 集成测试。

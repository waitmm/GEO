# Development Log

## 2026-08-04

### Prompt 每日监测与日报

- 新增 Prompt 每日监测字段：`daily_tracking_enabled`、`daily_schedule_time`、`daily_sample_count`、`last_scheduled_at`。
- 新增 `prompt_daily_reports` 表，用于保存单个 Prompt 每天的采集分析报告。
- 新增日报 API：查询历史日报、按 Prompt/日期生成日报。
- 新增每日监测队列 API：按已开启每日监测的 Prompt 生成当天 Batch/Task/Run 队列。
- 前端新增「Prompt 日报」页面，支持选择 Prompt 生成日报，并展示品牌出现率、引用域名、检索域名和优化建议。
- 审计配置页 Prompt 表新增每日监测开关，默认每天 `09:00`，默认 `Sample=1`。

### 检索资料解析

- 文心 collector 不再固定写入空 `retrieval_candidates`。
- 新增从页面 `all_net_search_result` / `searchResult` 卡片解析检索候选资料，落库到 `retrieval_candidates`。
- Run 详情页在「引用详情」之前新增「检索资料」表，和最终引用分开展示。

### 回滚提示

- 若需回滚日报功能，优先回滚：`PromptDailyReport` 模型、`Prompt` 每日监测字段、`analytics` 日报接口、`monitoring/daily-schedules` 接口、前端「Prompt 日报」页面。
- 若需回滚检索资料解析，优先回滚：`WenxinWebCollector._extract_retrieval_candidates` 调用和方法、Run 详情「检索资料」卡片。

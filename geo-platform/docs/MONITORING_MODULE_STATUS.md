# 文心助手网页端监测模块状态

## 当前状态

状态：Phase 2 主链路骨架已接入

已完成：

- 文心助手完整监测模块规格已归档为 `docs/GEO_WENXIN_MONITORING_MODULE_SPEC.md`。
- 已审计现有 V0 工程结构。
- 已明确 `wenxin_api` 与 `wenxin_web_audit` 需要分层。
- 已生成实施映射文档。
- 已新增 monitoring 模块目录。
- 已新增文心网页端监测模型。
- 已新增任务创建、任务列表、运行列表、运行详情、重试 API 骨架。
- 已新增 Collector 抽象接口和 WenxinWebCollector 占位实现。
- 已新增配置项和 artifact/runtime 目录。
- 已固化三维口径：`platform=wenxin`、`source_type=browser_audit`、`adapter=wenxin_web_audit`。
- 已新增同步版 `MonitoringTaskExecutor`。
- 已新增 `ArtifactService`。
- 已新增文心 Playwright Collector 主链路。
- 已新增 Profile 创建和登录态检查脚本。
- 已新增前端“文心网页审计”页面入口。
- 已新增引用 URL 解析基础模块：直接 URL、linkUrl/linkTitle 解码、候选源标题匹配、静态资源过滤。
- 已新增运行详情 API，返回真实引用源、检索候选源和证据文件。
- 前端运行详情已展示引用源、候选源和证据文件。

## 已有基础

- 项目管理：已有。
- 品牌配置：已有基础字段。
- 竞品配置：已有。
- Prompt 问题库：已有。
- Mock 监测：已跑通。
- 百度千帆 API Adapter：已有初版。
- 中文后台左侧导航：已有。

## 缺口

- 已声明 Playwright 依赖，并提供浏览器 Profile 脚本。
- 无异步 Worker 队列，当前为同步执行器。
- 已有基础运行状态机，真实页面选择器需继续基于样本微调。
- 已有网页端真实引用源表，尚未接入采集写入。
- 已有检索候选源表，尚未接入采集写入。
- 有证据表和目录，ArtifactService 尚未实现。
- 前端已有运行列表和展开详情，尚未拆成独立详情页。
- 有重试接口骨架，尚未接 Worker 执行。

## 推荐下一步

下一步进入 Phase 3：

- 安装 Playwright 浏览器依赖并创建真实文心 Profile。
- 使用真实问题 `谁是最好的二维码工具` 跑一次集成测试。
- 根据保存的截图和 HTML 微调选择器。
- 完善引用 URL P4 点击捕获和真实 DOM 属性提取。
- 将同步执行器迁移到 RQ/Celery。

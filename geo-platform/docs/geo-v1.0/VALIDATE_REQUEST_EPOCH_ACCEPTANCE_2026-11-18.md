# Validate Request Epoch Acceptance — 2026-11-18

## Result

`IMPLEMENTATION_CHANGE / OFFLINE_ACCEPTED / BUSINESS_COMPARE_NOT_REEXECUTED`

Validate 的比较请求现在绑定发起时的页面选择 epoch。用户在请求进行中修改基线、对照、回答版本、目标 URL、历史比较，点击刷新，或切换项目/Prompt/模块导致组件卸载时，旧请求立即失效；其后到达的成功、失败和 `finally` 都不能覆盖当前结果、错误、加载状态或地址栏结果版本。

本改动只修复前端异步投影竞态，不改变冻结范围、指标、Evidence、历史结果或后端比较语义。

## Evidence

- 客户端完整测试：`61 passed`。
- 新增延迟请求正反例：旧成功不覆盖新选择；旧失败不覆盖新结果或 loading；项目/Prompt 切换后的旧响应不能改写新页面 URL；全部可变输入、刷新与卸载均连接失效逻辑。
- release 前端构建：通过（仅保留既有大 chunk 警告）。
- `git diff --check`：通过。

未发起模型调用、外部采样或新的业务比较；该验收不冒充真实 Validate 业务价值或跨周期比较验收。

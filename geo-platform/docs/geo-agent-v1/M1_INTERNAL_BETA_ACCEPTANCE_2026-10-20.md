# GEO Platform M1 爱短链内部 Beta 验收记录

状态：`BETA_CANDIDATE / DEPLOYMENT_BLOCKED`

版本：`geo-internal-beta.m1-rc1`

分支：`codex/m1-aiduanlian-beta`

## 已完成的产品闭环

- 员工可在真实爱短链 Project 1、Prompt 1 和明确 Analysis/Run 范围查看 Monitor 数据。
- Optimize 默认进入“AI 优化”，展示已保存的真实 Evidence Pack 结果；历史结果不会显示为新任务成功。
- 结果按诊断、品牌证据缺口、策略与渠道、完整正文、QA、复测计划六个业务区块展示。
- 结果显示精确 AgentResultVersion、L2/L3 等级与 `VERIFY_FIRST`，并支持正文复制和完整 Markdown 导出。
- 品牌资料输入明确区分优化关联目标、项目组声明的能力、能力来源、待核实项与禁止表述。
- 反馈绑定精确 Project、Prompt、Run 与 AgentResultVersion，追加保存且数据库触发器禁止更新和删除。
- 无内部 Beta 日常模型额度时，新生成授权 fail-closed；历史实验余额不会自动转为日常授权。

## 真实数据与隔离

- Beta 数据来源：受控实验数据库
  `/private/tmp/geo-agent-real-comparison-20261019/autonomous-backup/database.after-autonomous.db`。
- 可部署副本：`/private/tmp/geo-m1-beta-rc1/aiduanlian-beta.db`，文件权限 `0600`，迁移版本
  `20261020_01`，Schema 状态 `READY`。
- 副本包含 15 个 Agent Run、3 个 AgentResultVersion、0 条预置员工反馈；反馈验收只写入另一个隔离副本。
- 已展示的成功真实结果：
  `agent-result-v1:agent-run-9e3d4fa8-825f-4d35-b989-ccb4db4392ae:2`，
  `L2_PARTIALLY_GROUNDED / VERIFY_FIRST`。
- 正式数据库在验收前后 SHA-256 均为
  `e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`；本轮没有正式 V2 写入。
- 本轮外部模型、采样、抓取、发布调用均为 0，费用为 ¥0。

## 验收证据

- 后端相关回归：77 passed。
- 前端客户端：24 passed。
- TypeScript 与 release build：通过；保留既有大 bundle 警告。
- Python compileall、`git diff --check`：通过。
- 隔离离线 Agent/Beta 浏览器回归：PASS，外部调用 0，桌面、审计对照、移动端均通过。
- 爱短链真实数据员工路径浏览器验收：PASS，页面错误 0，外部模型调用 0；覆盖：
  - 历史真实结果与新任务状态区分；
  - 六段完整报告和 `VERIFY_FIRST`；
  - 剪贴板复制及 Markdown 下载；
  - 反馈真实 POST、刷新后持久化；
  - 切换到第二个隔离项目后不显示爱短链结果；
  - 品牌目标与事实分离输入；
  - 390px 移动布局无横向溢出。
- 浏览器报告及截图：`/private/tmp/geo-m1-beta-browser-acceptance-v5/`。

## 尚未授权的外部条件

- 没有内部服务器、域名、HTTPS、受控网络与团队访问账户配置权限，因此不能提供团队可访问的内部地址。
- 没有内部 Beta 日常模型调用预算授权，因此候选版只开放历史真实结果；新生成按钮保持禁用。
- 上述两项是部署和日常运行阻塞，不影响本地可部署包、历史结果使用和离线产品验收。

## M1 冻结点

本候选版交给爱短链员工试用后收集采用率、修改量、品牌关联、事实准确性、策略泛化和正文质量反馈。
在新的阶段决策前，不进入 M2 八木屋功能开发，也不把 Evidence Pack 写入正式 V2 权威结果。

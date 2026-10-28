# GEO 1.0 小白视角真实交互体验审计

审计日期：2026-10-28（北京时间）  
产品入口：`http://127.0.0.1:8032/?release_view=releaseMonitor&v2_project=1&v2_prompt=1`  
代码分支：`codex/m1-server-budget-policy`  
修复提交：`d42945b`、`dbca783`  
部署版本：`geo-internal-beta.m1-ux-audit.2` / `dbca783`  
变更分类：`IMPLEMENTATION_CHANGE`（未改变冻结范围、证据归属、资格 Gate 或正式 V2 语义）

## 1. 一页结论

### 第一次打开是否知道下一步做什么

修复前：不知道。Monitor 先展示大量指标和旧回答，真正可用的“按时间范围选择分析数据”藏在页面下方折叠区；旧回答又因缺少 PromptVersion 被阻断，普通用户很容易认为系统不可用。

修复后：基本知道。页面首屏现在直接说明“从这里开始：选择一段时间内的回答”，按钮跳到默认展开的范围选择器；采集、人工导入和分析也明确分开。

### 能否通过正式 UI 完成核心流程

可以完成以下正式 UI 链路：

`Monitor 查看表现 → 选择时间范围和具体回答 → 冻结分析范围 → Optimize 查看/运行优化 → 阅读诊断、策略、正文和 QA → 复制/导出/反馈 → Validate 选择两个明确范围`

其中范围冻结、反馈保存和刷新恢复是在 8034 的隔离数据库副本上真实写入验证；8032 最终复验全部为只读，未修改现有 Beta 数据。没有调用文心、DeepSeek、网页抓取或付费 API。

### 最大的三个交互障碍

1. **起点不明确**：采集、导入、范围冻结三个入口并列，用户不知道分析必须先选回答。
2. **Optimize 历史难以使用**：默认拉取 20 条旧分析时首屏长时间停留在骨架屏，表格又暴露 PromptVersion、Analysis ID 等内部概念。
3. **交付结果不可读**：生成内容按原始 Markdown 和 `[[answer:...]]` 标记直接展示，样本数还显示成“按冻结范围 个 Run”，用户难以判断依据和交付完整性。

### 哪些问题会阻止用户得到实际优化结果

- 旧 `LEGACY_UNBOUND` 回答不能进入新分析是正确的安全阻断，但修复前没有把用户清楚引导到可分析的新范围。
- Optimize 历史加载过慢会让用户误以为没有分析或页面坏了。
- 原始技术标记和缺失样本数不会阻止后端生成，却会阻止业务人员理解、核验和采用结果。

### 当前产品判断

修复前更像需要开发人员解释的工程系统；修复后已经是**可由普通项目成员完成主要流程的本地 Beta 工具**。仍需真实员工使用来评价策略与稿件质量，且 Validate 在没有选定两个范围时仍需要用户理解“基线/对照”的含义，但这不再阻断核心 Monitor → Optimize 交付链路。

## 2. 按真实操作顺序记录

| 严重度 | 页面与操作 | 修复前实际体验 / 困惑 | 复现与证据 | 直接修复 | 用户价值与结果 |
| --- | --- | --- | --- | --- | --- |
| P1 | 打开 Monitor | 首屏只有指标和大量历史回答，没有明确起点；旧回答的版本阻断看起来像死路 | 打开指定 URL；见 [修复前 Monitor](evidence/product-ux-audit-20261028/01-monitor-before.png) | 增加首屏“从这里开始”说明和 CTA；范围选择默认展开并排到导入/采集之前；旧数据阻断文案指向正确入口 | 用户无需理解 PromptVersion，也知道先选 7/14/30 天或自定义范围 |
| P1 | Monitor → 选择范围 | 预览等待时只有按钮转圈，无法确认系统在做什么 | 展开“按时间范围选择分析数据”并点击预览 | 增加 `aria-live` 进度“正在按时间和版本整理可用回答…”；保留精确 Run、版本和 hash 冻结 | 用户能区分加载中、无数据与失败，不会重复点击 |
| P1 | 打开 Optimize | 默认历史接口逐条计算 20 条状态，实测约 20.9 秒；首屏停在骨架屏 | 点击 Optimize；见 [修复前 Optimize](evidence/product-ux-audit-20261028/02-optimize-before.png) | 首屏只取最近 10 条，保留明确选择、不自动打开 `latest`；最终浏览器从点击到“打开分析”可见为 0.968 秒 | 历史结果可被迅速发现，不牺牲冻结身份 |
| P1 | Optimize 历史表 | “问题版本、Analysis ID、来源准备计数”等内部术语占据主表 | 打开 Optimize 历史 | 改为“状态、数据范围、回答数、当前进度、创建时间、打开分析”；内部 ID 仅留在技术审计区 | 普通员工按时间范围识别分析，不需复制 UUID |
| P1 | 查看已有真实结果 | 原始 `###`、`**` 和 `[[answer:...]]` 直接显示；证据与策略关系不清 | 打开已有真实 Analysis；见 [修复前结果](evidence/product-ux-audit-20261028/04-result-before.png) | 新增安全业务 Markdown 渲染；标题、列表、表格正常显示；回答/事实/引用标记转为可读标签；增加阅读顺序说明 | 诊断、策略、正文、QA 可直接阅读，仍可追溯证据且未允许 HTML 注入 |
| P1 | 查看结果摘要 | 显示“当前样本 按冻结范围 个 Run”，没有数量 | 同上 | 当历史结果未保存 coverage 数时，使用当前冻结分析的有效回答数；统一称“条回答” | 用户能判断结果基于多少样本 |
| P1 | Monitor 趋势 | 页面写“UTC”，与本地产品统一北京时间的认知冲突；跨日样本可能归错日期 | 查看趋势标题和跨日测试 | 后端按 `Asia/Shanghai` 分组；前端统一显示“按日期观察（北京时间）” | 日期、范围命名和员工认知一致 |
| P1 | Validate 选择范围 | 下拉项显示 `范围 <context_id> · Runs ...`，难以知道比较的是哪段时间 | 进入 Validate；见 [修复前 Validate](evidence/product-ux-audit-20261028/03-validate-before.png) | 范围接口返回原始 Monitor 选择条件；UI 显示“北京时间起止 + N 条回答”，无明确时间时显示创建时间 + 数量 | 比较对象可读，同时继续传递精确 context_id |
| P2 | 移动端打开 Monitor | 首屏引导按钮挤压标题与说明 | 390×844 视口 | 720px 以下把 CTA 放到说明下方并占满可用宽度 | 本机窄窗口和移动端能看清第一步 |
| P2 | 品牌资料 | 字段较多，但业务目标、已核实事实、待核实能力已分开；首次填写仍需要领域知识 | 从侧栏进入品牌资料 | 本轮未重构表单；保持事实与目标的合同边界 | 不因追求简化而把品牌目标误当事实 |
| P2 | Evidence / Strategy | 已有结果的来源快照为 0 时，渠道建议只能是限定性建议，不能当成竞品渠道效果结论 | 读取真实结果“引用来源渠道观察”和限制 | 保留“引用观察不是渠道效果结论”的提示；证据标签只表达可回查关系 | 避免把来源频次或竞品引用误解为目标品牌事实 |
| P2 | Validate 空状态 | 没有选择两个范围时按钮禁用，页面说明存在但仍需要用户理解基线/对照 | 进入 Validate，不选择范围 | 范围名称已业务化；未伪造比较结果 | 仍建议在真实员工试用后评估是否增加示例说明 |

## 3. 专项检查

### 导航、标题和按钮

- Monitor、Optimize、Validate 的模块名称和副标题能解释用途。
- Monitor 新增唯一主 CTA；Optimize 不再承担采集或新增采样。
- “打开分析”替代模糊的“继续处理”。
- 桌面与 390px 视口均完成真实加载；最终移动端见 [移动端验收](evidence/product-ux-audit-20261028/14-monitor-mobile-after.png)。

### 项目、Prompt、时间范围和历史

- 顶部项目和 Prompt 选择保留，刷新后 URL 仍保存明确的 `v2_project`、`v2_prompt`、`v2_analysis`。
- 分析历史按北京时间范围命名；无范围元数据的旧项按创建时间和回答数命名，不使用 `latest` 补绑。
- 最终 Optimize 历史见 [修复后历史](evidence/product-ux-audit-20261028/11-optimize-history-after.png)。

### 空、加载、失败和权限状态

- 范围预览新增明确加载文案。
- 旧回答缺少版本时说明原因并给出可执行下一步。
- 外部执行服务、AI 生成授权仍由服务端状态决定；本轮没有修改或绕过权限。
- `UNKNOWN`、不可计算、合法零值和失败样本继续分开显示；未分析数据没有被显示成品牌未提及或 0%。

### Evidence、Strategy、正文和 QA

- 真实历史结果包含诊断、证据缺口、策略/渠道、完整正文、QA、复测计划。
- 原始证据 token 已转为可读标签，完整 token/哈希仍保留在技术审计层和后端对象。
- 明确提示阅读顺序及 `VERIFY_FIRST` 含义。
- 修复后完整结果见 [可读结果](evidence/product-ux-audit-20261028/12-readable-result-after.png)。

### 任务、错误恢复和历史版本

- 任务状态、阻断原因、停止入口、结果版本和反馈历史均存在。
- 隔离数据库上提交反馈后刷新页面仍能恢复；证据见 [反馈刷新恢复](evidence/product-ux-audit-20261028/05-isolated-feedback-after-refresh.png)。
- 历史结果不会被新任务静默替换，正式 V2 与实验结果身份仍隔离。

### Validate

- 基线和对照必须显式选择，不使用最新范围替代。
- 范围下拉显示北京时间范围及回答数，后端仍冻结精确 context/run/version/hash。
- 最终页面见 [修复后 Validate](evidence/product-ux-audit-20261028/13-validate-after.png)。

## 4. 浏览器与写入验收证据

### 第一轮真实发现

- 使用本地 Python Playwright + 项目已有 Chromium 访问 8032。
- 操作了 Monitor、Optimize、已有真实结果、品牌资料、问题配置、范围预览、Validate。
- 控制台与页面异常：0。
- 应用内浏览器控制器在本会话不可用，因此使用项目现有 Playwright/Chromium 作为明确 fallback；localhost 实际可访问，没有把静态分析当浏览器验收。

### 隔离写入验收

- 数据库：从当前 Beta SQLite 在线备份得到 `/private/tmp/geo-ux-audit-20261028/isolated/geo-beta.db`。
- 服务：`127.0.0.1:8034`，AI 每日调用为 0、定时采样关闭。
- 实际写入：预览并冻结 19 条回答；进入新 Analysis；提交反馈；刷新后恢复同一反馈。
- 未写入 8032 数据库，未触发模型、采样、抓取或发布。
- 机器可读报告：[isolated-acceptance-report.json](evidence/product-ux-audit-20261028/isolated-acceptance-report.json)。

### 部署后只读复验

- 版本：`geo-internal-beta.m1-ux-audit.2` / `dbca783`。
- 服务：后端与 Worker 均为 RUNNING，`/api/health` 正常。
- Optimize 历史可见耗时：0.968 秒。
- 浏览器页面/控制台错误：0。
- 最终机器可读报告：[final-acceptance-report.json](evidence/product-ux-audit-20261028/final-acceptance-report.json)。
- 修复后 Monitor 见 [桌面验收](evidence/product-ux-audit-20261028/10-monitor-after.png)。

## 5. 自动化回归

执行并通过：

```text
npm run build:release
npm run test:client                         36 passed
pytest test_observation_delivery.py
       test_collection_schedule_and_ranges.py  21 passed
git diff --check                           passed
```

额外浏览器验收覆盖：时间范围预览与冻结、正常导航、真实历史结果、证据标签、样本数、反馈保存与刷新、Validate 范围、390px 视口。

## 6. 本轮没有伪装成已验证的事项

- 没有新发起文心采样、DeepSeek 生成、网页抓取或付费 API。
- 没有用合成模型结果替代真实业务质量评估；内容阅读使用的是已保存的真实 Evidence Pack 结果。
- 没有生成新的 Validate 对比来假装业务指标改善。
- 本轮证明 UI 流程可操作、状态可恢复，并不证明生成策略一定优于 Workflow，也不证明长期 GEO 指标已经提升。

## 7. 剩余建议（非本轮阻断）

1. 让 2–3 名真实员工按当前入口处理 5–10 个 Prompt，记录完成率、采用率、修改量和行动价值。
2. 当积累至少两个可比较范围后，观察普通用户能否独立完成 Validate；若仍困惑，再增加一条业务示例，不改冻结语义。
3. 对真实内容重点评审品牌关联、事实错误、策略泛化和渠道依据；不要继续以增加工程步骤代替内容评审。

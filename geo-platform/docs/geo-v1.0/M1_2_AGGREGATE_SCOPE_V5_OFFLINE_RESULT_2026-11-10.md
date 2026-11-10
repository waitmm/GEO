# M1.2 Aggregate Scope v5 离线实施与验收结果

状态：`OFFLINE_ACCEPTED / REAL_RETEST_NOT_AUTHORIZED / NOT_RELEASED`

## 1. 范围与版本

本次属于已批准的窄范围 `SEMANTIC_CHANGE`，实施：

- Prompt `geo-evidence-pack-synthesis.v10`；
- Execution `geo.evidence-pack.execution.v12`；
- Validation `geo.evidence-pack.validation.v5`；
- Evidence Set `geo.evidence-pack.answer-evidence-set.v1`；
- Observation `geo.evidence-pack.brand-observation.v1`；
- 品牌字面识别规则 `geo.brand-literal-match.v1`。

历史 Prompt v9 / Execution v11 / Validation v4 及更早结果仍按原版本解释，不回填、不重验、
不改写状态。M1.1 数据库、正式 V2、Truth、Review、发布与 C1 均未修改。

## 2. 已实现的确定性边界

服务端从冻结输入构建唯一回答 Evidence Set，冻结 Project、Prompt、输入范围、PromptVersion、
ProjectConfigurationVersion、资格规则、完整回答 Run 成员/hash/locator、排除成员及原因、品牌配置
和识别规则。Evidence Set 与 Observation 使用两个独立 hash，模型不能提交或修改成员和事实值。

首个封闭观察仅支持 `BRAND_LITERAL_ABSENCE + FROZEN_VALID_SCOPE + ALL_VALID_RUNS`。只有非空、
身份完整且没有未决成员的全部有效回答都未命中冻结品牌名或别名时，服务端才生成已验证观察、
规范业务文字和 observation locator。一个回答出现品牌、一个成员无效、空范围、未知品牌、旧 hash、
跨项目/版本或成员漂移都会阻止总体缺席结论。

该观察只证明回答文本中的品牌字面出现情况，不能证明未推荐、产品能力、排名、竞品更优或因果关系。
`品牌表现与证据缺口` 是封闭的服务端事实区，模型必须逐字复用规范观察，不能在该区追加分析或
免责声明；其他章节也不能另写冻结范围内的总体品牌事实断言。该区以外仍可写策略、未来复测动作与
证据限制，但不能由缺席推出推荐/能力/排名/因果。相邻文字不再参与 scope 推断。v5 初始切片不接受 SAMPLE observation，单条
answer locator 不能冒充总体范围。

Pack 构建、locator 解析及 Prompt 渲染按版本隔离：v8/v9 Prompt 通过 SHA-256 字节基线，v11 在同一
输入上保持旧 Evidence Pack hash，且仍拒绝旧版本不认识的 observation locator。

## 3. 第三次真实失败结果受保护回放

回放只使用受保护本地数据库的一致性副本，没有打印或提交真实正文、Evidence、模型响应或凭证：

| 检查 | 结果 |
|---|---|
| 外部调用 | 0 |
| 原 v4 存储结果 | 保持 `FAIL`，原失败码保持不变 |
| 原稿直接进入 v5 | `FAIL / VERIFIED_BRAND_OBSERVATION_BLOCK_MISMATCH` |
| 服务端构建的 Evidence Set | 22 个完整回答成员 |
| 只读 shadow 中由服务端渲染规范观察 | v5 `PASS` |
| 原结果是否改写 | 否；回放前后存储 payload hash 一致 |

`shadow PASS` 只证明服务端结构化观察能替代 v4 对整章自然语言的范围猜测，不代表第四次模型请求会
遵守 v10，也不代表正文已通过运营采用评价。

## 4. 离线验收

- Backend Agent / Evidence Pack：`94 passed`；
- Backend DraftArtifact / 父子版本：`23 passed`；
- Backend 容量、内部 Beta 与 M1.1 保护回归：`40 passed`（与上述功能覆盖有重叠，不累计为产品功能数）；
- Frontend client：`47 passed`；
- Frontend release build：通过；
- 隔离浏览器双稿成功场景：`PASS`；
- 隔离浏览器 HELP_DOC 成功、FAQ 失败的部分成功场景：`PASS`；
- 浏览器外部调用：0；桌面、移动端、历史/反馈/导出和子资产隔离保持原行为；
- `git diff --check`：通过。

反例覆盖全部回答缺席、一个回答出现品牌、空/未决范围、身份缺失、少/多/重复成员、旧回答 hash、
错误 Project、PromptVersion、ProjectConfigurationVersion、伪造/篡改 observation、SAMPLE 冒充总体、
事实区增加免责声明、五类其他章节追加总体品牌事实、不同总体措辞、未来复测疑问动作不误伤且不能
在同句追加断言绕过、locator 放入代码标记，以及 v8/v9/v11/v4 历史兼容。

隔离浏览器证据位于 Git 忽略目录：

- `backend/artifacts/acceptance/agent-browser-success-20261110T134203Z/`；
- `backend/artifacts/acceptance/agent-browser-partial-20261110T134237Z/`。

## 5. UI 边界

v5 结果在 Optimize 主视图增加“本次品牌观察与证据范围”，只显示纳入/排除回答数量、业务可读观察
及“不能证明推荐、能力、排名或因果”的限制。Evidence Set ID、Observation ID 和内部 hash 不进入员工
主视图；locator 显示为“已验证范围观察”。旧结果没有 v5 对象时不显示该卡片，也不做补算。

父任务与 HELP_DOC / FAQ 的独立状态、QA、导出、反馈和重生成 lineage 未改变；共享范围校验失败仍按
共享问题处理，单资产正文问题继续支持真实部分成功。

## 6. 下一次真实复测预检

第四次真实复测仍需新的明确付费授权。获授权前只可准备以下静态预检：

1. 精确重新校验 Project 1 / Prompt 1 / 22 Run、PromptVersion、配置版本和输入范围；
2. 重新构建 v5 Evidence Pack 并记录新 hash，不能复用 v4 Pack hash；
3. 确认唯一服务端 Observation 与 22 个完整成员一致，0 个未决成员；
4. 使用 Prompt v10 / Execution v12 / Validation v5；
5. 保持一次请求、零重试、零补救、无新采样/抓取；
6. 即使服务端 PASS，仍需运营人员分别评价两稿的事实准确性、修改量、品牌关联与采用价值。

当前结论仅为 `OFFLINE_ACCEPTED`，不授权真实调用、M1.2 发布、main 合并或 M1.1 升级。

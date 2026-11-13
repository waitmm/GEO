# GEO M1.2 QA Composition v1 / Validation v6 离线验收

日期：2026-11-13（Asia/Shanghai）

分支：`codex/m1-2-multicontent`

基线：`c99b1d5ea2eb541393db81d2993364a65ab97b16`

状态：`OFFLINE_ACCEPTED / REAL_GATE_NOT_AUTHORIZED`

## 1. 决策与版本

Product Owner 已批准 `RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002` Definition Freeze。本次只实施
Prompt v11、Execution v13、Validation v6、QA Composition v1 的离线路径；没有第五次 Provider 请求、
模型重试、M1.2 发布、M1.1 数据迁移或 C1 采集。

服务端继续拥有 Evidence Set 和总体 Observation 的唯一解释权。Provider 原始响应保持不可变。只有
`QA 与事实限制` 中与精确 Observation 等价的安全冗余句可以在新版交付投影中被记录式排除；诊断、
策略和两份正文不允许自动删改。能力、推荐、排名、因果、数字和内部编写指令仍 fail-closed。

## 2. 第四次真实失败稿受保护 shadow

回放读取精确 idempotency key、固定 Run、input scope hash 和 result hash，不查询 `latest`；SQLite 以
只读模式打开，前后数据库 SHA-256 均为
`e16fbd6c5b5643b9294debe2621173d8f9ac5fb7ba764cf2d7868d85e20282d8`。

| 检查 | 结果 |
|---|---|
| 历史存储状态 | Validation v5 `FAIL`，issue 仍为 `UNSTRUCTURED_FROZEN_SCOPE_ASSERTION` |
| v5 shadow | `FAIL`，解释不变 |
| v6 shadow | `PASS`，0 issue |
| QA Composition | `COMPOSED`，只排除 1 个安全冗余片段 |
| 原始响应 | hash 保留，未修改 |
| 服务端说明 | 绑定原 Observation ID 与 Evidence Set ID |
| 数据库 | 前后 hash 一致，无写入 |

元数据回放工具：`backend/scripts/replay_m1_2_qa_composition_v6.py`。工具不打印 Provider 正文、Evidence
正文或业务资料，只输出身份、契约、issue、hash 和计数。

回放还确认剩余 QA 中“不得把引用共现改写成品牌提及因果”的表述属于明确的否定推断边界，不是新的
因果断言。对应边界已进入自动化正例；真正的正向或不确定能力、推荐、排名和因果断言仍被阻断。

## 3. 实现与审计

- `raw_markdown` 保存规范化 Provider 原文；`delivery_markdown` 保存 v6 交付投影。
- 组合 manifest 记录 Provider/QA/保留 QA/服务端说明/组合/最终交付 hash。
- 每个被排除片段记录 QA 章节、原文字符偏移、片段 hash、固定原因、Observation ID 和 Evidence Set ID。
- 服务端范围说明单独带 composition/template/Observation/Evidence Set 版本身份与 hash。
- UI 优先展示交付投影，并把“服务端验证的范围说明”与模型分析分开；技术详情仍可审计组合元数据。
- 子资产继续独立保存、QA、复制、导出、反馈、重生成与部分成功；父结果和历史子版本不原地改写。

## 4. 离线 Gate

- `tests/test_agent_experiment.py`：116/116 通过。
- 后端适用回归（共享预算、Agent Experiment、DraftArtifact）：155/155 通过。
- 前端测试：47/47 通过；正式前端构建通过（仅保留既有 chunk-size 警告）。
- Validation v6 定向正反例覆盖安全冗余、未经验证事实、内部指令、数字主张、因果边界、
  Evidence Set 身份、`VERIFY_FIRST` 原始资格与历史兼容，全部通过。
- Supervisor 追加的对抗反例已纳入回归：混合能力/内部指令、尾随“是否”、伪否定缺席、免责声明
  夹带因果、无关 Truth locator、代词能力、单一 Truth 冒充多项能力、量词扩张、省略主语、模糊连接词
  及第三方主体切换均按逐谓词/逐分句规则处理；未完整消费的目标品牌能力分句 fail-closed，历史 v5
  不新增 v6 字段。Supervisor 最终独立扩展 14 个案例并给出 `APPROVE`。
- 第四次真实稿元数据 shadow：v5 FAIL / v6 PASS，数据库不变。
- 隔离 Playwright 正式页面验收通过：展示独立“服务端验证的范围说明”，桌面与 390px 移动布局通过，
  外部调用 0。

所有测试均为离线；没有文心、DeepSeek、网页抓取或其他外部调用。

## 5. 结论与下一 Gate

结构化 QA Composition 已解决第四次真实稿的唯一安全冗余阻断，同时保留 v5 历史解释和所有原始
证据。shadow 中没有剩余真正的内容或事实 Gate 问题，但这不把历史 FAIL 重标为 PASS，也不等于新版
真实生成或运营采用验收已经完成。

下一次真实验收必须单独获得付费授权，使用新建的 v11/v13/v6 请求，并继续保留一次请求、费用、
重试和冻结范围限制。服务端 PASS 后仍需运营人员分别评价 HELP_DOC 与 FAQ 的事实准确性、可用性、
修改量和采用价值。

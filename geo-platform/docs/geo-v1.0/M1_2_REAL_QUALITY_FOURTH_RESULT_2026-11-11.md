# GEO M1.2 第四次真实双稿质量验收

日期：2026-11-11（Asia/Shanghai）

分支：`codex/m1-2-multicontent`

基线：`b18ec33a0632aeb98bd1df465cf1a4c0d3fd8520`

状态：`REAL_GATE_FAILED / SEMANTIC_CONTRACT_REVIEW_REQUIRED`

## 1. 执行边界

本次使用 Product Owner 明确批准的一次性授权：Project 1 / Prompt 1、第三次验收同一组 22 条有效
Run、Prompt v10、Execution v12、Validation v5、`deepseek-flash`、`RESPONSES_TEXT`、thinking
关闭，只生成 HELP_DOC + FAQ。请求、Token、费用、并发、重试和修复调用的硬上限分别为
`1 / 300000 / ¥3 / 1 / 0 / 0`；没有新采样、抓取或外部工具调用。

调用前另建保护数据库副本、响应归档目录和独立账本。父账本与 operation authorization 均为
`1 / 300000 / ¥3`，调用前 request rows 为 0。精确冻结范围 hash 为
`d35c80424f6985da93b16a037542e88d3a12e5ad6988dafeb19dfc83cc688e5a`，v5 Evidence Pack hash 为
`b8bdee0e6bcb8aa58f07a8463effd5c6956016fe09739a6d008ebb532e1ebbbc`。Evidence Set 有 22 个成员、
0 个排除、0 个未决、0 个字面命中；完整性检查为 0 问题。

请求序列化投影与实际 `DeepSeekClient.text_generate_sync` 一致：145952 UTF-8 bytes，保守预留
166432 Token / ¥1.66432，低于授权上限。Luna 与 geo_supervisor 在零外调前提下分别给出 GO。

## 2. 真实调用结果

| 项目 | 结果 |
|---|---|
| Provider 请求 | 1 次，已完成，之后 operation 和父账本剩余请求均为 0 |
| 耗时 | 24.690 秒 |
| 输入 / 输出 / 总 Token | 42299 / 3380 / 45679 |
| 保守账本费用 | ¥0.45679 |
| 原始响应归档 | 1 份，权限 0600，仅本机保护目录 |
| 父结果 | 已保存独立 AgentResultVersion |
| 子资产 | HELP_DOC 与 FAQ 均已保存独立 DraftArtifactVersion |
| Validation | FAIL，唯一 issue 为 `UNSTRUCTURED_FROZEN_SCOPE_ASSERTION` |
| 额外外部调用 | 0；本次授权已耗尽 |

真实正文、Evidence、Provider 原始响应、凭证和业务数据库未写入本文件，也不进入公开 Git 历史。
保护现场位于被 Git 忽略的
`backend/artifacts/live-quality/m1-2-real-quality-fourth-20261111-final/`。

## 3. 受保护离线回放结论

失败不是 Evidence Set 漂移、Observation 计算错误、locator 缺失、跨资产污染或相反事实：

- `品牌表现与证据缺口` 与服务端 canonical observation 逐字一致；set / observation integrity 为 0 问题。
- 唯一触发句位于 `QA 与事实限制`，重复说明已由服务端验证的 22 条回答字面缺席，同时明确限制
  该观察不能推出推荐、排名或因果。
- 该句没有产生新的产品能力事实，但它仍是事实区外的 frozen-scope 复述。当前已冻结 v5 明确禁止
  任何此类复述，所以 validator 按契约拒绝，并非实现误报。
- 仅在内存移除该句后，其余全部 Gate PASS；此检查没有修改数据库、历史结果或原始响应。

因此不能把本次结果重标 PASS，也不能直接放宽 v5 正则、静默删句或自动补引用。若产品决定允许由
服务端编译安全的范围限制，必须独立升版并通过新的 Definition Freeze。提案见
[`RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002`](../semantics/rfcs/RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002.md)。

## 4. 工程修复与回归

本次同时修复了真实执行前发现的控制问题：旧通用 autonomous 脚本的 provider 执行块不可达且绑定
历史授权，不能承担本次请求。新增专用一次性控制器，使用精确身份、独立账本、实际序列化投影、
受保护响应归档和仅元数据报告；生成正文不会被写入 Git 报告。共享账本只新增一个更严格的
`1 / 300000 / ¥3` 父配置，历史 `36 / 3000000 / ¥30` 配置保持兼容。

专项回归：`133 passed`（Agent、DraftArtifact、SharedBudget），另有既有依赖弃用警告；零测试外调。
Luna 与 geo_supervisor 独立确认：本次 FAIL 归因正确，历史 v5 不应改写。

## 5. 当前决定

1. 第四次授权已耗尽，不启动第五次模型请求或单篇补救请求。
2. 保留真实 FAIL、完整账本、双稿子资产和原始审计现场。
3. 不修改 M1.1 公司数据库、不合并 main、不发布 M1.2、不启动 C1。
4. 新的 QA 组合语义在 RFC 获批前只允许文档、调查和 shadow/replay，不进入正式 validator。
5. Windows A 线仍等待目标机器实测反馈；Mac 不伪造 Windows 验收。

# M1.2 真实双稿质量复测预检（未授权执行）

状态：`PREFLIGHT_READY / EXTERNAL_CALL_NOT_AUTHORIZED`

本文件只冻结下一次低频复测的建议边界，不构成模型调用或费用授权。

## 固定范围

- 爱短链 Project 1 / Prompt 1。
- 与首次真实 Gate 相同的 22 条有效 Run 冻结范围；执行前必须重新校验 Project、PromptVersion、
  ProjectConfigurationVersion、Run IDs、回答 hash、Evidence Pack hash 和权限。
- 只生成 `HELP_DOC + FAQ`，一次综合请求。
- Prompt `geo-evidence-pack-synthesis.v8`，Execution `geo.evidence-pack.execution.v10`，
  Validation `geo.evidence-pack.validation.v4`。
- DeepSeek `deepseek-flash`、`RESPONSES_TEXT`、`reasoning.effort=none`。
- 自动重试 0、补救请求 0、工具调用 0、单并发。

## 建议硬上限（待单独授权）

- 最多 1 次模型请求。
- 总 Token 保守上限 300,000。
- 人民币保守占额上限 ¥3。
- 若重新冻结后的输入身份或最坏费用不满足上限，必须在外部调用前停止。

## 调用前 Gate

1. 当前分支和候选 commit 明确，工作树无未审计改动。
2. 冻结范围与首次验收口径一致；新 Run 不得静默加入。
3. Evidence Pack 覆盖/省略记录、请求体大小和 Token 上界可审计。
4. 响应归档、usage 结算和 `incomplete` 生命周期回归保持通过。
5. 首次失败稿在 Validation v4 回放中命中内部指令泄漏和品牌章节证据相关性 Gate。
6. 真实 Evidence、正文、响应、数据库和凭证只进入受保护本地目录，禁止推送公开仓库。
7. 获得新的明确付费授权；历史实验余额不自动继承。

## 调用后验收

- 无论 PASS/FAIL，都保存原始响应、usage、耗时、版本身份和两份独立子资产结果；不得自动重试。
- HELP_DOC 与 FAQ 分别检查结构、Evidence、QA、事实限制和相互差异。
- 服务端 PASS 只证明确定性 Gate 通过，不替代运营评价。
- 运营人员逐稿记录：可用/需修改/不可用、事实准确性、修改量、采用价值和具体原因。
- 任一稿失败不删除另一稿；共享失败与资产失败必须准确区分。

## 当前未完成事项

- 尚未取得新的模型调用与费用授权，因此没有执行复测。
- Prompt v8 / Execution v10 的真实遵循率仍未知。
- M1.2 发布和 M1.1 数据库升级均未获授权。

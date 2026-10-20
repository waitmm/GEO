# GEO Evidence Pack incomplete 响应审计修复

日期：2026-10-20

分支：`experiment/geo-agent-v1`

变更分类：`IMPLEMENTATION_CHANGE`

外部模型调用：`0`

## 结论

本轮只修复首次真实 Evidence Pack 请求暴露的响应生命周期和生成配置问题，没有修改
GEO 业务语义、正式 V2、采样、抓取或发布链路。

历史响应只留下 `status=incomplete`、截断摘要和本地保守占额，没有保存完整 envelope。
因此无法恢复或推断当次 `incomplete_details.reason`、provider usage、reasoning token 数或部分正文。
`max_output_tokens=16,384` 被耗尽且大量额度用于 reasoning 是合理假设，但不是审计结论。

修复后的顺序为：

1. 接收并解析 HTTP response envelope；
2. 提取 response id、status、incomplete reason、error 状态、output 摘要、可见部分正文和 usage；
3. 先写入权限为 `0600`、目录权限为 `0700`、默认保留 7 天的受限审计归档；
4. 共享账本结算；
5. Agent Run 本地用量对账；
6. 最后执行 completed 判断、Markdown 业务校验和分级准入。

原始 provider envelope 和 reasoning 内容不进入产品前端、Agent Event payload 或共享账本；账本只保存
响应身份、状态、输出类型摘要、部分正文 hash/长度和 usage。

## 状态和结算语义

| Provider 结果 | 共享账本 | Agent 主故障 | 交付 |
| --- | --- | --- | --- |
| `completed` + 合法 usage | 按实际 usage 结算 | 后续业务校验结果 | 可继续校验 |
| `incomplete` + 合法 usage | 按实际 usage 结算 | `PROVIDER_INCOMPLETE` | 禁止成功 |
| `incomplete` + usage 缺失 | 保留全部保守占额 | `PROVIDER_INCOMPLETE`，附记 `USAGE_UNKNOWN` | 禁止成功 |
| 非 200 HTTP | 保留 HTTP 状态与错误类型；usage 未知时保留占额 | `PROVIDER_HTTP_ERROR` | 禁止成功 |
| 送达状态未知 | 保留全部保守占额 | `DELIVERY_UNKNOWN` | 禁止自动重试 |

结算现在支持同一请求、同一最终状态和同一 outcome 的幂等重放。进程重启后可用冻结
`operation_id + provider_payload_hash` 重建请求身份；不同 outcome 的重复结算 fail closed。
历史 `DELIVERY_UNKNOWN` 和首次 Evidence Pack 的保守占额均未修改。

## Thinking 配置升版

DeepSeek Responses API 官方文档当前列出 `reasoning.effort` 的
`none | low | high | max`，其中 `none` 关闭 thinking；未指定时使用默认 thinking 行为，且
`max_output_tokens` 同时覆盖 reasoning 与可见输出。响应的 `usage.output_tokens_details.reasoning_tokens`
用于区分 reasoning 消耗。参考：

- https://api-docs.deepseek.com/api/create-response/
- https://api-docs.deepseek.com/guides/responses_api/

新的 Evidence Pack 运行使用独立版本：

- execution：`geo.evidence-pack.execution.v2`
- prompt：`geo-evidence-pack-synthesis.v2`
- transport：`geo.deepseek.responses-text.no-thinking.v2`
- request：`reasoning.effort=none`
- `max_output_tokens=16,384`，未提高

旧的 execution/prompt/transport v1 仍按原身份解释，不覆盖历史输入、结果或授权。新 transport
在没有新的精确追加授权时继续 fail closed。

## 历史冻结输入规模

从保留的 `evidence-pack-preflight.json` 离线重建，Evidence Pack hash 仍为：

`21260f1074248ead7939be0161c9e9a2b500d82aa185a09fa99bff3e3335c515`

覆盖不变：1 个有效回答、19 个 citation occurrence、18 个 snapshot、451 个 passage 中 191 个
整段纳入、260 个逐项记录为 `TEXT_BUDGET` 省略、6 个 Product Truth、品牌上下文 `EMPTY`。

量化结果：

- prompt：624 字符 / 1,334 UTF-8 bytes；
- Evidence Pack 紧凑 JSON：186,127 字符 / 217,674 bytes；
- 纳入 passage 正文：11,383 字符；
- 纳入 passage 的非正文元数据约 90,388 字符；
- `selected_source_passages`：132,627 bytes，占各顶层值序列化体积约 61.01%；
- `coverage`（主要是 260 条 omission 记录）：63,759 bytes，约 29.33%；
- citations：8,398 bytes；source dispositions：5,663 bytes；Product Truth：2,909 bytes；
- 191 个纳入 passage 中有 4 个重复 passage hash/完全相同正文；全部 451 个中有 23 个重复 hash；
- 稳定 ID 前缀选择使 191 个 passage 来自前 7 个 snapshot，其余 11 个 snapshot 只有省略记录。

这些结果说明请求主要体积并非回答正文，而是来源元数据和可追溯省略记录。它是下一轮若仍失败时
评估证据包压缩的依据；本轮没有删除、重排或合并任何证据，避免改变冻结输入。

当前实现使用 UTF-8 request bytes + 4,096 的保守 admission 上界，不是供应商 tokenizer 的实际
input token 估算。历史 usage 缺失，因此实际 input token 数仍为 `UNKNOWN`。

## 下一次最小真实请求建议（未授权、未执行）

- 模型：`deepseek-flash`
- transport：`RESPONSES_TEXT / geo.deepseek.responses-text.no-thinking.v2`
- execution/prompt：上述 v2 版本
- `reasoning.effort=none`
- `temperature=0`
- `max_output_tokens=16,384`
- 请求 1 次，自动重试 0，修复调用 0，工具调用 0
- 同一 Project 1 / Prompt 1 / Run 1 冻结输入和已有 Workflow 基线

按当前序列化计算：request body 238,711 bytes，input admission 上界 242,807，连同输出上限的
最坏 token ceiling 为 259,191，按 ¥10/百万 Token 保守占额为 ¥2.59191。实际 provider input、
output、reasoning Token 和费用必须以下一次响应 usage 为准。

本轮没有追加 transport 授权；下一次真实调用必须取得新的明确授权，并对 v2 transport、精确运行、
模型、版本与单次子预算做追加式授权。

## 离线验收

针对性 suite：

```text
PYTHONPATH=. .../.venv/bin/pytest -q \
  tests/test_deepseek_generation_contract.py \
  tests/test_shared_model_budget.py \
  tests/test_agent_experiment.py
72 passed
```

包含正式 V2 自动交付与模型调用身份的联合回归：

```text
PYTHONPATH=. .../.venv/bin/pytest -q \
  tests/test_shared_model_budget.py \
  tests/test_agent_experiment.py \
  tests/test_automatic_delivery.py \
  tests/test_deepseek_generation_contract.py \
  tests/test_derived_model_call_identity.py
105 passed
```

覆盖 `max_output_tokens` / `content_filter`、部分正文、usage 有/无、非法 JSON envelope、业务解析失败前
归档、重复结算、进程重启、非 200 HTTP、显式 no-thinking 传输、旧 transport fail closed 和正式
V2 隔离。测试只使用 fake provider 与临时数据库，没有真实模型费用。

正式 release database 未写入，SHA-256 保持：

`e04aef36a7fae6ae385675b819827a810a194031fd38575c585d73109da854a3`

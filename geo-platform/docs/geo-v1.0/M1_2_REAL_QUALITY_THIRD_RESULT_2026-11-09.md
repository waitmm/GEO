# M1.2 第三次真实双稿质量验证结果（2026-11-09）

状态：`REAL_GATE_FAILED / SEMANTIC_CONTRACT_REVIEW_REQUIRED`

本记录只包含可公开的脱敏验收元数据。真实回答、Evidence、生成正文、供应商原始响应、数据库和凭证
仍位于 Git 忽略的受保护本地目录，未进入公开仓库。

## 授权与冻结身份

- 基线：`3fb550fb5b2fa9c5b6295e1b1ab9f0b773c5b269`。
- Project 1 / Prompt 1；沿用相同 22 条明确 Run，未加入新采样。
- `input_scope_hash=d35c80424f6985da93b16a037542e88d3a12e5ad6988dafeb19dfc83cc688e5a`。
- `evidence_pack_hash=a20ec642f9375b0e56e1e5f3cb57ae7b9a87800992b4574308aa506d4708f788`。
- Prompt v9 / Execution v11 / Validation v4；`deepseek-flash`、`RESPONSES_TEXT`、
  `reasoning.effort=none`。
- 授权边界：1 次请求、300,000 Token、人民币 ¥3，自动重试 0、补救 0、采样/抓取 0。
- 调用前保守预留 158,640 Token / ¥1.5864；Luna 与 geo_supervisor 均确认没有确定性必败项。

第一次执行命令在 Provider 前被本机日常额度开关阻断，外部请求、usage 和账本均为 0；随后将本次
显式授权绑定到隔离账本后执行唯一请求。该前置阻断不计为模型请求，也未产生费用。

## 真实执行

| 项目 | 结果 |
|---|---|
| 请求次数 | 1（授权已耗尽） |
| 供应商状态 | `completed` |
| 输入 / 输出 / 总 Token | 39,345 / 3,608 / 42,953 |
| 推理 Token | 0 |
| 本次账本结算 | ¥0.42953 |
| 耗时 | 28.043 秒 |
| 自动重试 / 补救 | 0 / 0 |
| 父结果 | 已追加保存，状态 `FAILED` |
| HELP_DOC / FAQ | 均追加保存；共享品牌证据 Gate 未通过 |

共享账本累计 3 次、129,725 Token、¥1.29725；结束时无在途请求。供应商原始响应和 usage 已按受限
归档保存。

## 通过项与唯一失败

- 16/16 个输出 locator 均为合法裸写；没有反引号包装、格式错误或范围外引用。
- 共享诊断、策略、引用渠道分析、Truth 引用和各节最低 Evidence 均未报错。
- HELP_DOC：5 个步骤小节、12 个有序步骤、11 个可执行单元、25 个操作动词，结构 Gate 通过。
- FAQ 结构通过；两稿差异化通过（containment 0.189247、Jaccard 0.068696）。
- 没有内部编写指令泄漏、无依据数值、跨资产污染或 Provider incomplete。
- 唯一失败码：`BRAND_SECTION_EVIDENCE_RELEVANCE_REQUIRED`。品牌章节表达 22 条回答的总体观察，
  但只绑定 2 条完整回答 locator；Validation v4 拒绝把 2 条样本当作 22 条总体证据是正确的。

Evidence Pack 本身并不缺证据：22 条完整回答 locator 均存在，全文目标品牌字面出现为零。该事实只
支持“冻结回答中未出现目标品牌”的观察，不能升级为“不推荐”、产品能力、因果解释或 Product Truth。

## Validation v4 的独立确定性缺陷

受保护回放同时发现，当前 v4 从整个品牌章节搜索 aggregate 词：

1. 真正包含 22 条范围的总体断言没有被 aggregate 正则识别；
2. 相邻的限制说明反而触发 aggregate；
3. 纯内存删除限制说明、保留总体断言与同样 2 个 locator 后，现有实现错误转为 PASS；
4. 独立合成反例也能复现“总体结论只引 1 条可通过，增加限制说明反而失败”。

因此，本次真实结果应保持失败，但不能继续依赖增加 Prompt 文字或原位修改一个正则。现状同时存在
模型证据覆盖不足和验证器范围绑定脆弱两项问题。

## 决策与停止条件

- 停止 Prompt v10/v11 补丁循环，不再自动付费复测。
- 不放宽、不删除总体观察全范围证据 Gate；不自动补引用，不重标本次或历史失败结果。
- 下一步分类为 `SEMANTIC_CHANGE`：引入显式观察范围与冻结证据集合绑定，并独立升版
  Prompt / Execution / Validation。
- 在新语义契约批准前，只允许 RFC、离线反例和影子验证；禁止实现切换、Provider 调用、M1.1 升级
  或 M1.2 发布。

提案见
[RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001](../semantics/rfcs/RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001.md)。

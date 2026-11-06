# M1.2 真实双稿质量复测结果（2026-11-06）

状态：`REAL_GATE_FAILED / PROMPT_V9_REMEDIATION_OFFLINE_ACCEPTED`

本记录只包含可公开的脱敏验收元数据。真实回答、Evidence、生成正文、供应商原始响应、数据库和凭证
仍位于 Git 忽略的受保护本地目录，未进入公开仓库。

## 授权与冻结身份

- 基线：`a20f60b7d546fb169eda93e36da9d4bf609f1951`。
- Project 1 / Prompt 1；沿用首次 Gate 的 22 条明确 Run，未加入新采样。
- `input_scope_hash=d35c80424f6985da93b16a037542e88d3a12e5ad6988dafeb19dfc83cc688e5a`。
- `evidence_pack_hash=a20ec642f9375b0e56e1e5f3cb57ae7b9a87800992b4574308aa506d4708f788`。
- Prompt v8 / Execution v10 / Validation v4；`deepseek-flash`、`RESPONSES_TEXT`、
  `reasoning.effort=none`。
- 授权硬边界：1 次请求、300,000 Token、人民币 ¥3，自动重试 0、补救 0、外部采样/抓取 0。
- 调用前保守预留 157,621 Token / ¥1.57621，未触及授权上限。

## 真实执行

| 项目 | 结果 |
|---|---|
| 请求次数 | 1（授权已耗尽） |
| 供应商状态 | `completed` |
| 输入 / 输出 / 总 Token | 39,097 / 4,147 / 43,244 |
| 共享账本结算 | ¥0.43244 |
| 耗时 | 29.164 秒 |
| 自动重试 / 补救 | 0 / 0 |
| 父结果 | 已追加保存，状态 `FAILED` |
| HELP_DOC / FAQ | 均追加保存，均未通过服务端 Gate |

共享账本保留首次真实请求和本次请求：累计 2 次、86,772 Token、¥0.86772；未重置历史用量，
结束时无在途请求。

## 质量结论

本次不是 Provider、usage、持久化或 Evidence Pack 容量失败。两份正文都已生成，且双稿相似度没有
触发重复 Gate；上次的内部编写指令泄漏和无依据数字主张也未复现。

真实失败由三类问题组成：

1. 原文实际输出 23 个逐项合法 locator，但全部用单反引号包裹。Validation v4 为避免代码示例冒充
   Evidence，会屏蔽 Markdown 代码内容，因此三节 Evidence 与渠道 citation 在正式解释中为 0。
   这属于 Prompt 与 Validator 的格式对齐不足，不能解释成模型完全没有引用。
2. 品牌章节只引用一条完整回答，却使用总体范围观察；Validation v4 要求总体结论覆盖冻结范围内的
   全部有效回答。该 Gate 合理，不能靠一条随机或无关 locator 放行。
3. HELP_DOC 含 5 个 H3、24 个操作动词和 7 个行动正文块，但没有符合契约的步骤标题或三个有序步骤；
   它不是空稿，仍不满足可操作结构 Gate。

纯内存影子诊断仅移除 locator 外层反引号后，三节 Evidence 与渠道 citation 缺失立即消失；品牌范围
覆盖和 HELP_DOC 步骤结构仍失败。影子结果没有保存、没有替代真实失败，也没有触发模型调用。

## 离线定向修复

本次分类为 `IMPLEMENTATION_CHANGE`：不改变 Validation v4 的允许/禁止推断、Evidence、Product Truth、
`VERIFY_FIRST` 或历史对象解释，只让新生成请求明确满足现有冻结 Gate。

- 保留 Prompt v8 / Execution v10 / Validation v4 的历史身份和解释。
- 新建 Prompt v9 / Execution v11，继续绑定 Validation v4。
- 明确 locator 必须裸写，不能放入单反引号、代码围栏或转义符。
- 明确总体品牌观察必须逐条覆盖对应全部回答；单 locator 只能表述为单样本观察。
- 明确 HELP_DOC 至少两个步骤小节或三个有序步骤，每步包含真实操作。
- 不扩大解析容错，不自动补引用，不改写本次结果，不降低任何 Gate。

离线专项通过：Agent、子资产、容量 115 项；内部 Beta 与共享预算 22 项；合计 137 项。`compileall`
和 `git diff --check` 通过。上述证据只证明定向修复和历史兼容，不证明 Prompt v9 的真实生成质量。

兼容边界：历史 v10 主结果和执行解释保持不变；已冻结为 v10 的旧单稿重生成排队请求不会静默升级到
v11，而是在 Provider 前以 `GENERATION_PROFILE_UNSUPPORTED` 失败。后续若需要恢复该类队列，必须按原
身份明确实现和验收，不能改用最新 profile 猜测执行。

## 当前 Gate

- 本次真实复测状态保持 `FAILED`，不得安排运营采用评价，不进入 M1.1 或公司数据库。
- 本次一次性授权已耗尽；禁止自动再次调用。
- Prompt v9 / Execution v11 仅为离线候选。后续若需要真实复验，必须重新取得独立付费授权。
- 即使未来服务端 PASS，仍需运营人员分别评价两稿的可用性、事实准确性、修改量与采用价值。

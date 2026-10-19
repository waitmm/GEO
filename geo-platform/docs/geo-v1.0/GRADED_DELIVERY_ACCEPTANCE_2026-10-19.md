# GEO 1.0 分级交付改造验收（2026-10-19）

## 结论

`RFC-GRADED-DELIVERY-001` 的 Definition Freeze 和最小单主链实现通过工程、UI、独立测试与 Supervisor Gate，
可以受控进入 `codex/geo-integration`。结论只覆盖分级交付机制，不把历史 E1 重新认定为通过。

## 正式行为

- L1：qualification、Plan、Result 分别固定 version/hash，Result 精确绑定 Plan、qualification 与当前冻结范围。
- L2：只允许固定 allowlist 中独立支持的事实块，其余内容删除或保留为待核验动作。
- L3：沿现有 Draft/QA 主链生成 `INSTRUCTION_ONLY_DRAFT`，不允许 Evidence ID、品牌能力、平台规则或数字效果声明。
- L4：仅用于身份、权限、版本均合法但输入不足的恢复交付；零模型调用，不进入 current delivery，也不解锁内容依赖。
- 任一 Project、Prompt、Analysis、Context、Run、Strategy、Proposal、Answer、Evidence、Binding 或 Truth provenance
  完整性失败均为 `BLOCKED`，不得形成 Plan/Result。

## 验收证据

| Gate | 结果 |
| --- | --- |
| 后端组合 Gate | 93 passed |
| 前端分级/准入/历史选择 Gate | 11 passed |
| Release build | PASS；仅保留既有 bundle size warning |
| 隔离 Chrome | `PASS_SCOPED_SIMULATED_INTEGRATION_NOT_REAL_MODEL` |
| Chrome 业务结果 | L3 / `INSTRUCTION_ONLY_DRAFT` / QA `READY` |
| 刷新恢复 | 精确历史 task/result 保持不变 |
| Luna 独立审核 | PASS，无 P0/P1 |
| geo_supervisor | GO，允许受控集成 |
| 外部调用 | 0 |

最终本地 Chrome 报告位于
`backend/artifacts/acceptance/browser-20261019T090939Z/report.json`（gitignored），SHA-256
为 `db2079b0d6423b1e110c6a7215da4e6dca7021cf875e014809f9ee3ea460a707`；桌面截图
`optimize-1440.png` 的 SHA-256 为
`b8a61fd0c91a48a315f153dbac4a434e381f0c5225d21f5bb183949708fa80b6`。

## E1 真实链路边界

历史 E1 task `optimize-3ca74641-940b-40d5-9f0b-1442936ab00e` 仍为
`BLOCKED / FAILED_PARSE`，没有被更新或重新解释。只读缓存回放基于隔离数据库 SHA-256
`0380e0e5499aee98b54adaa58adf9b87c13d8b47fc79899d8ff83945622e37c0` 和原始 artifact SHA-256
`5ff0251760f10f816b80a000433c5552797672d1fef159f8069ed55c08da00ef`，得到 10 条 Evaluation：
4 `SUPPORTS_PARTIAL`、2 `RELATED_ONLY`、4 `NO_MATCH`，可形成 4 个 supporting binding 候选。

这只证明真实冻结输入具有 L2 潜力；它没有持久化新 Binding，没有创建新正式 Task，没有运行真实 Draft/QA，
也不满足 E1 的完整 Evidence 验收。真实 E1 收口仍需新的 append-only 正式任务，并严格受现有明确外部调用授权与预算约束。

## 变更提交

- `1512152`：Definition Freeze、Golden Case 与语义注册。
- `9b1e225`：后端 L1-L4 资格、Plan/Result 与单主链接入。
- `db1745a`：正式 UI 分级、历史身份和结果反馈。
- `8509260`：部分证据、REJECTED 审计与 L3 中性文本收紧。
- `b224684`：L1 用户语义澄清。
- `5d099bf`、`d75b2ad`、`6976ef2`：通用身份、optional material 与 Truth provenance 硬 Gate。

`main` 未修改；未访问生产数据库，未发起真实模型、采集或发布请求。

# T09 / T23 真实验收记录（2026-10-19）

本记录只登记隔离测试环境中的真实外部操作、冻结身份、预算和正式 Gate 结果。它不包含密钥、完整模型输入、真实客户数据或生产数据，也不把失败结果改写为成功。

## T09：同一 Citation 独立刷新

- 授权 URL：`https://me-short-link.com/zh/page/guides/what-is-a-short-link`
- 顶层访问：`1/1`；HTTP 200；无重试、无重定向、无登录/验证绕过。
- 尝试 ID：`citation-refresh-ae491f30-f2d7-48dc-8323-5ed62be68a3f`
- 原 Snapshot：`source-snapshot-c1652a96-70f4-4c50-bb3d-faadc955200c`
- 新 Snapshot：`source-snapshot-d76d7c68-ed76-4525-9fd7-564b5a7d1828`
- 原正文 hash：`bbf3e581622c524d41f3e5a854304d33b3c9c1e50f9e5a70ac9088e6e426ff14`
- 新正文 hash：`6ef8df3d8fa6033094b6e5dd18a522919991109385b09ae78de287a4c08f5916`
- 新 Completion Manifest：`source-completion-25545091-dea2-49e2-a8ef-f846e2d76b27`
- 新 Completion hash：`513fdea8abfc09d996d2fc9150caf968e2df0753f81ca92f2173cac67737d8dd`
- append-only、原 v1 不变；专项 Gate：`23 passed`。
- 正式状态：`BLOCKED`。刷新隔离库没有同范围已完成且已审核的 Diagnosis/Result/Review，不能伪造重分析基线；T09 模型调用保持 `0/3`。

## T23：三类真实 E2E

冻结调用身份为 `provider=deepseek`、endpoint `POST https://api.deepseek.com/responses`、requested model alias `deepseek-v4-flash`、effective request model `deepseek-flash`、transport `RESPONSES_JSON_SCHEMA / semantic_llm.deepseek.responses_json_schema.v2`。所有请求使用隔离 Project 1 的指定 Prompt/Run；共享 ledger 无自动重试。

| 次序 | 场景 | 请求 ID | 状态 | Token | 保守预留 CNY | 正式结果 |
| --- | --- | --- | --- | ---: | ---: | --- |
| 1 | E2E-01 Answer prepare | `T23:E2E-01:prepare-answer:43012687-2a22-46a2-81d1-5301972a2b94:840bddcada42978662ee79e7` | FINISHED / ACCEPTED | 2611 | 0.18871 | Answer 可机器消费，但为合法零事件 |
| 2 | E2E-02 Contribution prepare | `T23:E2E-02:prepare:citation-contribution-c219e0c1-6fea-4508-be18-801a74138017:d936e5649c96b660f9b4ef84` | FINISHED / ACCEPTED | 3610 | 0.18292 | 得到 `SUPPORTS_PARTIAL/RELATED_ONLY`，不满足 low-match 场景；冻结 `NO_FORMAL_LOW_MATCH`，禁止换样本或重试 |
| 3 | E2E-03 Answer prepare | `T23:E2E-03:prepare-answer:ce6f7c34-df57-4000-8911-fc07e182385e:ec8133472f7b37e0602c22e9` | FINISHED / ACCEPTED | 3468 | 0.20810 | 目标品牌能力信号为 0；冻结 `NO_FORMAL_UNKNOWN_SIGNAL`，未伪造 UNKNOWN 或创建任务 |
| 4 | E2E-01 Draft | `T23:E2E-01:optimize-3ca74641-940b-40d5-9f0b-1442936ab00e:c996654b31f4e6e8b477bc07` | FAILED / REJECTED | 2918 | 0.19319 | Provider 返回 JSON 可解析，但 `SOURCE_STATEMENT` 使用非冻结 evidence ID，严格准入以 `INVALID_DRAFT_EVIDENCE` 拒绝；无 Delivery/QA 伪成功 |

汇总：T23 `4/9`，全局业务模型请求 `4/12`，Token `12607`，保守预留成本 `CNY 0.77292`。Provider 实际账单不可权威观测，记为 `UNKNOWN`。旧的本地 `DEEPSEEK_API_KEY 未配置` E3 结果有明确零发送证据，已 append-only 保留，并由确定性 superseding diagnosis 完成一次真实请求；没有覆盖旧结果或免费重试。

E1 当前冻结链没有可消费的 attributable evidence；机械恢复仍无法通过正式 Gate，因此停止新增请求。E2、E3 的真实结果也分别不满足正式场景条件。T23 保持 `BLOCKED`，不得解锁 T24/T25。

## 独立监督与本地 Gate

- `geo_supervisor` 在身份修复、E3 pre-send 恢复、E3 外调及 E1 外调前分别审核；最终结论为：代码 fail-closed 行为正确，停止新的外部重试，T23 不得登记 DONE。
- T23 专项：`22 passed`；真实 E1 失败后独立定向安全检查：`19 passed, 26 deselected`。
- T09 专项：`23 passed`。
- 未操作生产数据库，未发送真实客户数据，未充值，未合并 main。

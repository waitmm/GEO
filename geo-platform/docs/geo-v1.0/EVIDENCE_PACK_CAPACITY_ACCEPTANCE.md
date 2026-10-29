# Evidence Pack v3 离线容量与扩展性验收

状态：`SHADOW / OFFLINE ONLY`  
基线：`8dd6b62`  
模型、采样、抓取与付费调用：`0`

## 结论

本轮分类为 `SEMANTIC_RISK`。

- v3 的 URL 去重可以有效控制高重复来源，但不能解决 Run 与唯一来源持续增长。
- 当前 `90,000` Gate 计算的是字段值的逻辑字符，不是实际 Responses 请求 JSON；因此存在逻辑
  字符未超限、实际 JSON 已超限的情况。
- 15 组合成场景均可被确定性分成单批实际 JSON 不超过 90,000 字符、且 Run/Citation/Source
  身份覆盖完整的子包。
- 生产 `build_evidence_pack`、`geo.evidence-pack.v3` 与 execution v7 保持 `8dd6b62` 原样；
  内容版本和遗漏身份检查只存在于 shadow 模块。
- 但 300,000 Token 的任务级保守上限会先于很多大范围分析触发。分批“可构造”不等于在当前
  任务预算内“可执行”。
- 多批模型结果如何合并为一个诊断、策略、正文与 QA 会改变 Optimize 交付语义。本轮未接入
  生产执行器，明确保持 `SEMANTIC_CONTRACT_REVIEW_REQUIRED:MULTI_BATCH_RESULT_MERGE`。

## 方法

规模：22、50、100、300、1,000 Run。每个规模覆盖：

1. `HIGH_REPEAT`：大量 Run 反复引用 5 个 URL。
2. `HIGH_UNIQUE`：每个 Run 引用 2 个不同 URL。
3. `LONG_SOURCE`：约每 10 个 Run 一个长来源正文。

每个 shadow batch 同时满足：

- 实际 `json.dumps(evidence_pack, ensure_ascii=False)` 字符数不超过 90,000；
- Citation catalog 与 Source passage 无省略；
- 每个 Run 恰好进入一个 batch；
- 全部 Citation occurrence identity 和 SourceSnapshot identity 被覆盖；
- 单批按实际 Responses body 计算：
  `input_token_upper_bound = len(body UTF-8 bytes) + 4096`；
- 单批预留为 `input_token_upper_bound + max_output_tokens(16,384)`，不得超过任务上限 300,000；
- 同时记录所有 batch 合计预留，不能用“单批通过”掩盖任务总预算超限。

合成数据只验证容量与归属，不是业务内容质量证据。

## 实际矩阵

| 分布 | Run | 唯一 URL | v3 单包 | Shadow 批数 | 最大批 Run | 最大批实际 JSON 字符 | 合计保守 Token 预留 | Token 保守预留 |
|---|---:|---:|---|---:|---:|---:|---:|---|
| 高重复 | 22 | 5 | FIT | 1 | 22 | 21,835 | 62,021 | 通过 |
| 高重复 | 50 | 5 | FIT | 1 | 50 | 35,806 | 88,928 | 通过 |
| 高重复 | 100 | 5 | FIT | 1 | 100 | 60,748 | 136,970 | 通过 |
| 高重复 | 300 | 5 | CORE_EXCEEDS | 2 | 157 | 89,571 | 371,494 | 超限 |
| 高重复 | 1,000 | 5 | CORE_EXCEEDS | 7 | 157 | 89,853 | 1,253,823 | 超限 |
| 高唯一 | 22 | 44 | JSON_EXCEEDS | 2 | 21 | 88,732 | 208,344 | 通过 |
| 高唯一 | 50 | 100 | JSON_EXCEEDS | 3 | 21 | 89,409 | 434,602 | 超限 |
| 高唯一 | 100 | 200 | JSON_EXCEEDS | 5 | 21 | 89,410 | 849,752 | 超限 |
| 高唯一 | 300 | 600 | CORE_EXCEEDS | 15 | 21 | 89,410 | 2,564,386 | 超限 |
| 高唯一 | 1,000 | 2,000 | CORE_EXCEEDS | 50 | 21 | 89,993 | 8,621,665 | 超限 |
| 长来源 | 22 | 3 | FIT | 1 | 22 | 61,017 | 167,163 | 通过 |
| 长来源 | 50 | 5 | JSON_EXCEEDS | 2 | 40 | 85,941 | 299,929 | 通过 |
| 长来源 | 100 | 10 | JSON_EXCEEDS | 3 | 40 | 86,000 | 574,180 | 超限 |
| 长来源 | 300 | 30 | CORE_EXCEEDS | 9 | 40 | 89,785 | 1,867,608 | 超限 |
| 长来源 | 1,000 | 100 | CORE_EXCEEDS | 29 | 40 | 89,786 | 6,348,322 | 超限 |

上述所有场景的 Run、Citation occurrence、SourceSnapshot 与 SourceDisposition 身份覆盖率均为 100%。
该列仅判断 Token 保守预留；当前生产授权仍限定单任务 `max_requests=1`。任何 2 批及以上
的计划即使 Token 预留未超限，也没有实际执行授权；shadow planner 也未计算汇总模型调用或费用。

## 首先触发限制的数据

1. **唯一来源多**最早触发：22 Run / 44 URL 时，原始 v3 逻辑字符为 61,098，但实际 JSON
   已达 92,890。只观察旧 `estimated_text_characters` 会漏判。
2. **来源正文长**其次：50 Run / 5 个长来源时原始 v3 实际 JSON 达 91,728。
3. **URL 高重复**增长最慢，但 300 Run 时回答核心区仍超过 90,000。
4. 即使可以分批，任务级 300,000 Token 保守预留会在 50 条高唯一来源、100 条长来源或
   300 条高重复来源时阻断；50 条长来源的合计预留为 299,929，仍在边界内。不能静默扩大额度。

## 身份与正确性 Gate

- 原始 v3 生产投影不变；shadow audit 将 URL 只视为 Citation occurrence 目录键，不把 URL
  相同解释为正文相同。
- 同 URL 的多个 `snapshot_id/content_hash` 在 shadow audit 中全部保留，状态为
  `MULTIPLE_KNOWN_VERSIONS`。
- 任一 snapshot 缺少 `content_hash` 时内容身份保持 `UNKNOWN`。
- 被原始 v3 容量排除的 Citation catalog entry，由 shadow audit 恢复稳定 catalog identity、
  URL（若有）、Run IDs、occurrence IDs、出现次数和原因；不改写生产 pack。
- 无 URL Citation 使用 domain、title 与完整 occurrence IDs 形成稳定 identity/hash。
- 无 SourceSnapshot 的 FAILED/UNKNOWN/WAIVED disposition 作为全局清单进入每个相关 shadow
  batch 并参与 coverage/hash；UNKNOWN 保持 UNKNOWN，不升级。
- 单 Run 自身超过容量时进入 `blocked_runs`，不会静默丢弃或伪装为分批成功。
- Shadow plan 固定原始 scope hash、每批 Run/Citation/Source IDs、Evidence Pack hash 与
  batch hash，且同输入重复规划结果一致。

## 当前边界与下一步

当前可以确认：v3 的单包能力有限；确定性输入分区技术上可行；证据身份没有因分区丢失。

当前不能确认：多个独立模型输出如何合并为一个可信的 GEO 诊断、策略、正文和 QA，也不能在
任务级 Token 预留超限时自动执行。这两项需要单独定义：

1. 多批中间结果的结构、证据 locator 和冲突处理；
2. 汇总调用是否必要及其输入资格；
3. 全任务请求数、Token 与费用上限；
4. 失败/部分完成时是否允许交付及其分级；
5. 独立 Production Cutover。

在这些语义获得批准前，生产仍使用 v3 单包执行，shadow planner 只用于离线容量预检与设计证据。

## 复现

```bash
cd backend
python3 -m pytest -q tests/test_evidence_pack_capacity_scaling.py
python3 scripts/evidence_pack_capacity_smoke.py
```

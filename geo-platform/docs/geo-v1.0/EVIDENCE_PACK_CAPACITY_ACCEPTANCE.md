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

| 分布 | Run | 唯一 URL | v3 单包 | Shadow 批数 | 最大批 Run | 最大批实际 JSON 字符 | 合计保守 Token 预留 | 任务预算 |
|---|---:|---:|---|---:|---:|---:|---:|---|
| 高重复 | 22 | 5 | FIT | 1 | 22 | 23,065 | 63,341 | 通过 |
| 高重复 | 50 | 5 | FIT | 1 | 50 | 37,036 | 90,248 | 通过 |
| 高重复 | 100 | 5 | FIT | 1 | 100 | 61,978 | 138,290 | 通过 |
| 高重复 | 300 | 5 | CORE_EXCEEDS | 2 | 155 | 89,790 | 374,134 | 超限 |
| 高重复 | 1,000 | 5 | CORE_EXCEEDS | 7 | 155 | 89,791 | 1,263,063 | 超限 |
| 高唯一 | 22 | 44 | JSON_EXCEEDS | 2 | 19 | 89,790 | 219,994 | 通过 |
| 高唯一 | 50 | 100 | JSON_EXCEEDS | 3 | 19 | 89,790 | 461,093 | 超限 |
| 高唯一 | 100 | 200 | JSON_EXCEEDS | 6 | 19 | 89,791 | 928,591 | 超限 |
| 高唯一 | 300 | 600 | CORE_EXCEEDS | 17 | 19 | 89,791 | 2,775,376 | 超限 |
| 高唯一 | 1,000 | 2,000 | CORE_EXCEEDS | 58 | 19 | 89,792 | 9,360,552 | 超限 |
| 长来源 | 22 | 3 | FIT | 1 | 22 | 61,755 | 167,955 | 通过 |
| 长来源 | 50 | 5 | JSON_EXCEEDS | 2 | 40 | 86,925 | 301,249 | 超限 |
| 长来源 | 100 | 10 | JSON_EXCEEDS | 3 | 40 | 86,984 | 576,820 | 超限 |
| 长来源 | 300 | 30 | CORE_EXCEEDS | 9 | 40 | 89,776 | 1,876,343 | 超限 |
| 长来源 | 1,000 | 100 | CORE_EXCEEDS | 29 | 40 | 89,777 | 6,378,254 | 超限 |

上述所有场景的 Run、Citation occurrence 与 SourceSnapshot 身份覆盖率均为 100%。

## 首先触发限制的数据

1. **唯一来源多**最早触发：22 Run / 44 URL 时，逻辑字符为 66,148，但实际 JSON 已达
   103,748。只观察旧 `estimated_text_characters` 会漏判。
2. **来源正文长**其次：50 Run / 5 个长来源时实际 JSON 达 92,958。
3. **URL 高重复**增长最慢，但 300 Run 时回答核心区仍超过 90,000。
4. 即使可以分批，任务级 300,000 Token 保守预留会在 50 条高唯一来源、50 条长来源或
   300 条高重复来源时阻断，不能静默扩大额度。

## 身份与正确性 Gate

- URL 仅用于 Citation occurrence 目录去重，不再被描述为“正文相同”。
- 同 URL 的多个 `snapshot_id/content_hash` 全部保留，状态为
  `MULTIPLE_KNOWN_VERSIONS`。
- 任一 snapshot 缺少 `content_hash` 时内容身份保持 `UNKNOWN`。
- 被容量排除的 Citation catalog entry 现在显式记录 URL、Run IDs、出现次数和原因，不再
  只给出计数。
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


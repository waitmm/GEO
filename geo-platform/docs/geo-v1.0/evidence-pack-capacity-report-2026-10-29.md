# Evidence Pack v3 离线容量压力验收

日期：2026-10-29（Asia/Shanghai）  
基线：`8dd6b62`（Evidence Pack v3 / execution v7）  
测试文件：[test_evidence_pack_capacity.py](/private/tmp/geo-m1-budget/geo-platform/backend/tests/test_evidence_pack_capacity.py)

本轮只调用本地 `build_evidence_pack`，未访问文心、DeepSeek、外部来源，也未连接或修改 Beta 数据库。输入是可追溯的合成冻结 scope，不能作为真实业务内容质量结论。

## 测试定义

每种分布测试 22、50、100、300、1000 个 Run，每个 Run 3 条引用。

- `high_repeat_url`：8 个 URL 在所有 Run 间重复。
- `high_unique_url`：每条引用使用独立 URL。
- `long_source`：20 个 URL，每个 URL 有两个不同 `snapshot_id` 和 `content_hash` 的长正文版本；版本必须分别保留或分别记录省略，不能按 URL 合并成一个正文。
- 固定模型输入预算：90,000 字符。
- `raw` 是合成冻结 scope JSON 字符数；`pack` 是生成后完整 Evidence Pack JSON 字符数（不含系统 Prompt），用于发现“选材预算”和实际发送对象大小不一致的问题。

## 结果矩阵

| 分布 | Run | raw 字符 | pack 字符 | 唯一 URL | 引用次数 | URL 纳入/省略 | 来源 passage 纳入/总数 | 结果 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| high_repeat_url | 22 | 47,095 | 41,988 | 8 | 66 | 8/0 | 0/0 | PASS |
| high_repeat_url | 50 | 106,567 | 85,960 | 8 | 150 | 8/0 | 0/0 | PASS |
| high_repeat_url | 100 | 212,778 | — | 8 | 300 | — | 0/0 | CORE 139,992 > 90,000 |
| high_repeat_url | 300 | 639,778 | — | 8 | 900 | — | 0/0 | CORE 419,992 > 90,000 |
| high_repeat_url | 1,000 | 2,134,289 | — | 8 | 3,000 | — | 0/0 | CORE 1,399,995 > 90,000 |
| high_unique_url | 22 | 47,431 | 83,104 | 66 | 66 | 66/0 | 0/0 | PASS |
| high_unique_url | 50 | 107,707 | 142,566 | 150 | 150 | 61/89 | 0/0 | PASS* |
| high_unique_url | 100 | 215,718 | — | 300 | 300 | — | 0/0 | CORE 145,446 > 90,000 |
| high_unique_url | 300 | 649,918 | — | 900 | 900 | — | 0/0 | CORE 436,846 > 90,000 |
| high_unique_url | 1,000 | 2,181,629 | — | 3,000 | 3,000 | — | 0/0 | CORE 1,458,749 > 90,000 |
| long_source | 22 | 2,037,094 | 108,406 | 20 | 66 | 20/0 | 1/40 | PASS* |
| long_source | 50 | 2,096,806 | 103,626 | 20 | 150 | 20/0 | 0/40 | PASS* |
| long_source | 100 | 2,203,497 | — | 20 | 300 | — | 0/40 | CORE 140,206 > 90,000 |
| long_source | 300 | 2,632,297 | — | 20 | 900 | — | 0/40 | CORE 420,206 > 90,000 |
| long_source | 1,000 | 4,133,108 | — | 20 | 3,000 | — | 0/40 | CORE 1,400,209 > 90,000 |

`PASS*` 表示 `build_evidence_pack` 没有抛出容量错误，但不是“全部证据进入模型”：被预算排除的 URL/来源会出现在 `coverage.omitted_materials`。其中 high-unique 50 的完整 pack JSON 已达到 142,566 字符，超过 90,000；long-source 22/50 也分别为 108,406/103,626。也就是说，当前预算只约束了选材过程中的 `remaining`，没有保证最终发送对象（pack JSON + Prompt）不超过预算。

## 结论

1. v3 的 URL 去重有效保留了引用次数与 Run 归属：重复 URL 的 `occurrence_count` 总和等于全部引用次数，`run_ids` 覆盖所有 Run。
2. 当前真正的硬上限仍然是每个 Run 的完整 `answer_text` 被放入固定 core。合成答案长度与真实 22-Run 失败形状相近时，约 100 Run 已触发 `EVIDENCE_PACK_CORE_EXCEEDS_BUDGET`，无论 URL 是否重复。
3. 唯一 URL 增长会在 core 尚未阻断时先造成引用目录截断；50 Run / 150 URL 仅纳入 61 个 URL，但 89 个 URL 有明确省略记录。
4. 长正文会被确定性省略，但当前最终 pack 仍可能超过 90,000，说明“选材预算”与“实际请求体预算”还不是同一件事。
5. 两个相同 URL 的不同 source snapshot/content hash 未被合并；每个 snapshot passage 都有独立选择或省略记录。测试未发现归属丢失或静默删除。

## 是否已解决扩展性

尚未。当前 v3 对 22～50 Run 的常规范围可工作，但不支持稳定增长到 100+ Run；容量不足仍会在模型调用前失败。下一步应在现有 Optimize 主链内增加最小的确定性分批/汇总策略，或先把 Run 级回答改为有界摘要并保存完整原文索引，同时对最终序列化请求体执行预算检查。不能通过单纯提高 90,000 上限掩盖问题，也不能静默丢弃 Run、Citation 或不同正文版本。

## 回归证据

```text
PYTHONPATH=backend pytest -q backend/tests/test_evidence_pack_capacity.py -s
5 passed, 6 warnings
```

测试结果在当前工作树（基线 `8dd6b62` 加并行容量/版本识别改动）上得到；本报告不将合成测试结果当作真实 GEO 业务验收。

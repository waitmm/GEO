# Prompt #40 Citation Decision V1.1 Phase 1 正式结果审计

状态：待评审
日期：2026-08-26

## 1. 审计边界

本文件审计 `Citation Decision V1.1 Phase 1` 在 Prompt `#40` 上的第一次
小范围正式接入结果。

本次 Phase 1 只允许正式 Evidence Chain 在显式开关下消费：

```text
AnswerUnit
+ AnswerDecisionBinding
```

它不批准全量切换，也不改变主工作流顺序：

```text
采集样本
-> 答案决策识别
-> 目标品牌事实
-> 引用证据
-> 对标来源
-> 缺口诊断
-> 推荐动作
-> 实验草案
```

关键边界：

```text
不直接消费 Shadow Evidence Result
不因 Citation Prominence 进入 Benchmark
不因标题同名进入 Benchmark
不把 LEGACY_RELATED 当 SUPPORTS
不自动创建 StrategyCandidate / Action / Experiment
```

## 2. 当前正式输出

本地数据库与服务输出核对：

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
source_run_ids = [238, 239, 240, 253, 254, 255]

formal EvidenceAlignment for Prompt #40 = 110
SUPPORTS = 6
NONE = 5
RELATED = 99

formal SourceClaim for Project #3 = 577
formal SourceClaim for SourceDocument #345 = 22
```

Citation Decision V1 当前输出：

```text
status = READY_FOR_HUMAN_CONFIRM
source_count = 68
primary_benchmark_count = 1
secondary_benchmark_count = 0
priority_high_count = 1
priority_medium_count = 0
recommended_action_count = 1
channel_opportunity_count = 1
```

## 3. 这次推进是否来自 V1.1 输入

Prompt `#40` 的 `小码短链接` 推荐事件仍然没有旧版 reason：

```text
RecommendationEvent #62 / Run #238 / 小码短链接 / RECOMMEND / reasons_json = []
RecommendationEvent #66 / Run #239 / 小码短链接 / RECOMMEND / reasons_json = []
RecommendationEvent #70 / Run #240 / 小码短链接 / RECOMMEND / reasons_json = []
RecommendationEvent #74 / Run #253 / 小码短链接 / RECOMMEND / reasons_json = []
RecommendationEvent #78 / Run #254 / 小码短链接 / RECOMMEND / reasons_json = []
RecommendationEvent #82 / Run #255 / 小码短链接 / RECOMMEND / reasons_json = []
```

当前正式 `SUPPORTS` 的 payload 均来自：

```text
reason_source = ANSWER_DECISION_BINDING
formal_input_version = citation_decision_v1_1_formal_input.v1
```

因此结论是：

```text
#40 从 false negative 推进到 READY_FOR_HUMAN_CONFIRM，
确实来自 AnswerUnit + AnswerDecisionBinding 正式输入，
不是来自旧 reasons_json、Shadow SUPPORTS、标题相似或 Citation Prominence。
```

## 4. 6 条正式 SUPPORTS 粒度审计

重要发现：

```text
6 条正式 SUPPORTS 不是 6 Runs x 同一个能力点。
当前 6 条 SUPPORTS 全部落在 Run #238。
```

分布：

```text
Run #238: SUPPORTS 6 / NONE 5 / RELATED 99
Run #239: SUPPORTS 0
Run #240: SUPPORTS 0
Run #253: SUPPORTS 0
Run #254: SUPPORTS 0
Run #255: SUPPORTS 0
```

按 AnswerUnit 聚合：

| AnswerUnit | 覆盖 Run | SourceClaim 数 | EvidenceAlignment 数 |
| --- | ---: | ---: | ---: |
| 小码短链接自带点击统计 | 1/6 | 2 | 2 |
| 小码短链接自带自定义分享标题 | 1/6 | 1 | 1 |
| 小码短链接适合营销场景使用 | 1/6 | 3 | 3 |

这说明当前 6 条 SUPPORTS 更准确地表达为：

```text
Run #238 内 3 个答案能力单元
与 SourceDocument #345 的 5 个来源主张
形成 6 条正式 SUPPORTS
```

不能表达为：

```text
6 个采集样本都形成了正式 SUPPORTS
```

## 5. 正式链逐级审计表

### 5.1 推荐事件

```text
RecommendationEvent #62
run_id = 238
entity_text = 小码短链接
speech_act = RECOMMEND
review_status = HUMAN_CONFIRMED
reasons_json = []
```

### 5.2 AnswerUnit 与 Binding

| AnswerUnit ID | Binding ID | AnswerUnit | Binding 角色 |
| ---: | ---: | --- | --- |
| 1086 | 1030 | 小码短链接自带点击统计 | SUPPORTING_REASON |
| 1088 | 1032 | 小码短链接自带自定义分享标题 | SUPPORTING_REASON |
| 1089 | 1033 | 小码短链接适合营销场景使用 | SUPPORTING_REASON |

### 5.3 来源与正式 SourceClaim

```text
SourceDocument #345
title = 如何将长链接缩短-小码至营
url = https://zhuanlan.zhihu.com/p/938392385
domain = zhuanlan.zhihu.com
content_status = CONTENT_VALID
```

| SourceClaim ID | SourceClaim |
| ---: | --- |
| 813 | 小码短链接的自定义分享功能支持设置标题和描述 |
| 814 | 小码短链接的自定义分享功能能增加用户点击兴趣 |
| 816 | 小码短链接自带数据统计功能 |
| 817 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 |

### 5.4 正式 EvidenceAlignment

| EvidenceAlignment ID | AnswerUnit | SourceClaim ID | 关系 | Scope |
| ---: | --- | ---: | --- | --- |
| 14543 | 小码短链接自带点击统计 | 816 | SUPPORTS | PASS |
| 14544 | 小码短链接自带点击统计 | 817 | SUPPORTS | PASS |
| 14584 | 小码短链接自带自定义分享标题 | 813 | SUPPORTS | PASS |
| 14607 | 小码短链接适合营销场景使用 | 814 | SUPPORTS | PASS |
| 14609 | 小码短链接适合营销场景使用 | 816 | SUPPORTS | PASS |
| 14610 | 小码短链接适合营销场景使用 | 817 | SUPPORTS | PASS |

## 6. 为什么最终是 1 个核心对标来源

SourceDocument `#345` 满足当前确定性规则：

```text
content_status = CONTENT_VALID
decision_support_level = RECOMMENDATION_REASON
benchmark_relevance = DIRECT
```

因此：

```text
benchmark_tier = PRIMARY_BENCHMARK
```

服务输出的对标来源：

```text
source_document_id = 345
title = 如何将长链接缩短-小码至营
platform = zhihu
platform_label = 知乎
supporting_alignment_ids = [14543, 14544, 14584, 14607, 14609, 14610]
```

其他来源即使 `citation_prominence_level = HIGH`，但没有正式 `SUPPORTS`
对齐，因此仍为：

```text
benchmark_tier = REFERENCE_ONLY
priority_level = NOT_PRIORITY
action_route = null
```

这说明：

```text
Citation Prominence 没有把来源升级成 Benchmark。
```

## 7. 推荐动作审计

当前唯一推荐动作：

```text
route = CONTENT
priority_level = PRIORITY_HIGH
gap_type = CONTENT_GAP
product_truth_status = TRUE
product_truth_ids = [2]
```

动作标题：

```text
围绕「长链接缩短」补齐「数据统计功能 / 自带数据统计功能 / 每个链接的访问量、点击次数等数据」的直接说明、适用场景和限制条件。
```

计划变更：

```text
参考对标来源「如何将长链接缩短-小码至营」的表达方式，在目标品牌资产中新增可摘录段落：先直接回答用户问题，再说明 数据统计功能 / 自带数据统计功能 / 每个链接的访问量、点击次数等数据 的使用场景、边界、操作步骤和 FAQ。
```

动作不是：

```text
去知乎发布内容
```

也不是：

```text
因为有 Benchmark 就机械生成动作
```

它当前来自：

```text
RecommendationEvent
-> AnswerUnit / AnswerDecisionBinding
-> SourceClaim
-> EvidenceAlignment SUPPORTS
-> PRIMARY_BENCHMARK
-> Product Truth TRUE
-> CONTENT_GAP
-> PRIORITY_HIGH
-> CONTENT route
```

但这里仍有一个需要评审的产品事实边界：

```text
Product Truth #2 = 短链生成 / SUPPORTED
```

当前动作标题实际聚焦到了：

```text
数据统计功能 / 点击次数等数据
```

这比 `短链生成` 更细。Phase 2 前建议补齐更细粒度 Product Truth，
例如：

```text
点击统计能力
自定义分享标题能力
营销场景适用能力
```

避免用“短链生成”这个宽泛事实承接所有细能力动作。

## 8. 渠道机会审计

当前生成 1 个渠道机会：

```text
channel = zhihu
channel_label = 知乎
priority_level = PRIORITY_HIGH
recommended_content_types = [ARTICLE]
```

生成依据：

```text
同平台存在核心/辅助对标来源
对标来源具备推荐理由或候选/评价支撑
当前样本未发现目标品牌同平台资产
```

该机会仍要求人工审核：

```text
需要人工确认平台规则、账号可控性、内容适配和发布可行性。
```

## 9. Feature Flag 与回滚边界

当前开关：

```text
citation_decision_v1_1_formal_input_enabled = false
```

API / workflow 可显式传入：

```text
use_answer_binding_v1_1 = true
```

审计结论：

```text
该开关控制“生成正式 Evidence 时是否启用 Answer Binding 输入”。
它不是“读取结果时隐藏 V1.1 正式 EvidenceAlignment”的开关。
```

也就是说，一旦 Prompt `#40` 已经写入正式 V1.1 `EvidenceAlignment`：

```text
use_answer_binding_v1_1 = false
```

不会自动让 Citation Decision 读路径回到旧 V1 输出。

Phase 2 前建议补一个真正的小范围回滚策略：

```text
方案 A：读路径支持按 formal_input_version 排除 V1.1 alignments。
方案 B：保留 generation flag，同时提供清理/重算指定 Prompt 正式 alignments 的运维脚本。
方案 C：EvidenceAlignment 增加 active / disabled / pipeline cohort 标记。
```

不建议在未定义回滚边界前做全量历史重跑。

## 10. Phase 1 审计发现

### 10.1 已通过

```text
1. 正式链可以消费 AnswerUnit + AnswerDecisionBinding。
2. #40 的 false negative 得到修复。
3. Shadow SUPPORTS 没有被直接消费。
4. Citation Prominence 没有决定 Benchmark。
5. LEGACY_RELATED 没有参与 SUPPORTS 语义。
6. 推荐动作仍是 PROPOSAL_ONLY，没有自动创建实验。
```

### 10.2 Phase 2 前阻塞项

```text
1. run-level evidence coverage 被折叠：
   6 条 SUPPORTS 全部来自 Run #238，不是 6 Runs 均形成 SUPPORTS。

2. feature flag 只控制生成输入，不控制已写入结果的读路径。

3. Product Truth 粒度偏粗：
   当前用“短链生成”承接了“点击统计 / 自定义分享标题 / 营销场景”动作。

4. Layer3 工具脚本存在接口漂移：
   run_single_case_evidence.py 会把 doc_id_filter 传给
   run_reason_driven_retrieval，但当前函数签名不接收该参数。
```

## 11. 结论

当前状态建议定义为：

```text
PHASE_1_FORMAL_INPUT_PROVEN_ON_PROMPT_40
READY_FOR_FULL_PRODUCTION_SWITCH = false
```

可以确认：

```text
V1.1 正式输入路径在 #40 上有效。
```

但暂不建议进入 Phase 2 的 3-5 Prompt 扩展，除非先处理：

```text
run-level coverage 不可被折叠
V1.1 正式结果可回滚或可隔离读取
Product Truth 粒度与动作粒度一致
Layer3 doc_id_filter 接口漂移
```


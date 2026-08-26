# Prompt #40 ShadowRun #7 Binding Sanity Check

状态：Phase 0 可收口，等待是否进入 Phase 1 小范围切换的单独批准
日期：2026-08-26

## 1. 审计边界

本文件只用于评审 `Citation Decision V1.1 Phase 0 Shadow` 的语义校准结果，不批准 Phase 1，不改变正式 Benchmark、Gap、Priority、Action、Strategy 或 Experiment。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
shadow_run_id = 7
entity_filter = 小码短链接
source_run_ids = [238, 239, 240, 253, 254, 255]
formal_output_impact = NONE
```

正式链零污染结果：

```text
formal SourceClaim: 545 -> 545
formal EvidenceAlignment for Prompt #40: 0 -> 0
PRIMARY_BENCHMARK: 0 -> 0
SECONDARY_BENCHMARK: 0 -> 0
recommended_action_count: 0 -> 0
channel_opportunity_count: 0 -> 0
citation_status: NO_EXECUTABLE_RECOMMENDATION -> NO_EXECUTABLE_RECOMMENDATION
```

## 2. 本轮判断

本轮不再要求人工逐条审计 30 条 Binding。

原因是 `ShadowRun #7` 的结构已经足够稳定：

```text
6 Runs x 每 Run 5 个相同能力单元 = 30 Bindings
DIRECT_REASON = 0
SUPPORTING_REASON = 30
```

这符合已确定的语义：

```text
推荐语境下，被推荐品牌说明作用域内的能力、优势、价格、效果、适用场景等，
默认视为推荐支撑主张；不要求答案显式出现“因为/所以”。
```

真正需要防的是：

```text
其他品牌能力串绑
操作步骤被当成正向推荐理由
话题切换后仍继续绑定
限制/弱项被当成正向 SUPPORTING_REASON
```

这些由自动回归 Case 防守，而不是让人工重复确认 30 条同结构 Binding。

## 3. 代表 Run Sanity Check

人工只需抽看代表 Run，例如 `Run #238`，确认原答案结构确实类似：

```text
小码短链接：
支持长链接快速缩短，
自带点击统计，
二维码生成，
自定义分享标题，
适合营销场景使用。
```

若没有切换到其他品牌、操作教程、限制描述或新 section，则 6 个 Run 的同结构 30 条 Binding 可整体视为通过。

代表 Run `#238` 的 5 个 Binding：

| AnswerUnit | 机器角色 | 说明作用域 | SUPPORTS | 代表来源主张 |
| --- | --- | --- | ---: | --- |
| 小码短链接支持长链接快速缩短 | SUPPORTING_REASON/MEDIUM | SAME_SENTENCE | 0 | - |
| 小码短链接自带点击统计 | SUPPORTING_REASON/MEDIUM | SAME_SENTENCE | 1 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 |
| 小码短链接自带二维码生成 | SUPPORTING_REASON/MEDIUM | ENTITY_HEADING_SCOPE | 0 | - |
| 小码短链接自带自定义分享标题 | SUPPORTING_REASON/MEDIUM | ENTITY_HEADING_SCOPE | 2 | 小码短链接提供自定义分享功能 |
| 小码短链接适合营销场景使用 | SUPPORTING_REASON/MEDIUM | SAME_SENTENCE | 0 | - |

## 4. 能力单元稳定矩阵

| AnswerUnit | Binding 覆盖 | SUPPORTS 覆盖 | Evidence Role |
| --- | ---: | ---: | --- |
| 小码短链接支持长链接快速缩短 | 6/6 | 0/6 | - |
| 小码短链接自带二维码生成 | 6/6 | 0/6 | - |
| 小码短链接自带点击统计 | 6/6 | 6/6 | RECOMMENDATION_SUPPORTING_EVIDENCE x6 |
| 小码短链接自带自定义分享标题 | 6/6 | 6/6 | RECOMMENDATION_SUPPORTING_EVIDENCE x12 |
| 小码短链接适合营销场景使用 | 6/6 | 0/6 | - |

## 5. 与 ShadowRun #6 的差异

```text
Binding 总数：30 -> 30
DIRECT_REASON：18 -> 0
SUPPORTING_REASON：12 -> 30
SUPPORTS：18 -> 18
recommendation_evidence_eligible：18 -> 18
formal_output_impact：NONE -> NONE
```

这说明本轮没有为了降低 `DIRECT_REASON` 删除合理 Binding；只是把缺少明确因果、选择条件、需求匹配或比较依据的品牌说明收敛为 `SUPPORTING_REASON`。

## 6. 回归 Case 验收

Phase 1 前必须持续通过这些自动回归 Case：

| Case | 预期 |
| --- | --- |
| Procedure Case | 过程步骤不成为正向推荐理由；可作为 `PROCEDURAL_EVIDENCE`；不进入 Recommendation Evidence Eligible |
| Brand-directed Case | 直接问某品牌功能时不生成 Recommendation Binding，但可形成 `BRAND_CAPABILITY_EVIDENCE` |
| Other-brand Scope Case | 其他品牌 Feature 不绑定到当前推荐品牌 |
| Implicit Reason Case | 隐式场景理由可以绑定到推荐事件 |
| Limitation Case | 限制/弱项进入 `COUNTER_REASON`，不能进入正向 `SUPPORTING_REASON` |

验证命令：

```bash
.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py
```

当前结果：

```text
11 passed
```

## 7. Phase 1 Gate

当前状态：

```text
SHADOW_EVIDENCE_CHAIN_SCOPE_CALIBRATED_ON_PROMPT_40
PHASE_0_READY_FOR_REVIEW_CLOSE = true
READY_FOR_PRODUCTION_SWITCH = approved_for_small_scope_phase_1_input_switch
```

Phase 1 小范围切换的 Gate 改为：

```text
1. #40 ShadowRun #7 结构符合预期：
   5 Units x 6 Runs -> 30 SUPPORTING_REASON

2. SUPPORTS grounding 正常：
   点击统计、自定义分享标题有真实 source_span

3. Procedure / Brand-directed /
   Other-brand / Implicit / Limitation
   回归 Case 全部通过

4. 正式 V1 零污染

5. 用户单独批准 Phase 1 小范围切换
```

不再要求：

```text
人工逐条审完 30 条 Binding
```

## 8. Phase 1 小范围切换批准范围

用户已批准进入 Phase 1 小范围正式输入切换。批准范围仅限：

```text
正式 Passage Retrieval / EvidenceAlignment
在显式开关开启时
消费 AnswerUnit + AnswerDecisionBinding
作为答案侧推荐理由输入
```

仍不批准：

```text
直接消费 Shadow Evidence Result
全量开启 Phase 1
改变主链 8 步顺序
改变 Product Truth / Benchmark / Gap / Action / Strategy / Experiment 规则
```

Phase 1 smoke 应继续确认：

```text
旧 reasons_json fallback 保留
不开开关时正式链结果不变
开开关后正式 EvidenceAlignment 保留 provenance
Benchmark 只消费正式 SUPPORTS，不消费 Shadow SUPPORTS
```

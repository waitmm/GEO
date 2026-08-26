# Prompt #40 ShadowRun #6 Binding 人工审计表

状态：已由 ShadowRun #7 语义校准版替代
日期：2026-08-26

说明：本文件保留 `ShadowRun #6` 的原始审计结果，用于追溯第一版
Binding 语义。后续人工评审请以
`docs/PROMPT_40_SHADOW_RUN_7_BINDING_REVIEW.md` 为准；`#7` 已按
Recommendation Explanation Scope 规则将普通品牌说明默认校准为
`SUPPORTING_REASON`，不再把缺少明确因果/选择条件的能力描述判为
`DIRECT_REASON`。

## 1. 审计边界

本文件只用于评审 `Citation Decision V1.1 Phase 0 Shadow` 结果，不批准
Phase 1，不改变正式 Benchmark、Gap、Priority、Action、Strategy 或
Experiment。

```text
project_id = 3
prompt_id = 40
evidence_package_id = 15
shadow_run_id = 6
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

## 2. 能力单元稳定矩阵

| AnswerUnit | Binding 覆盖 | SUPPORTS 覆盖 | Evidence Role |
| --- | ---: | ---: | --- |
| 小码短链接支持长链接快速缩短 | 6/6 | 0/6 | - |
| 小码短链接自带二维码生成 | 6/6 | 0/6 | - |
| 小码短链接自带点击统计 | 6/6 | 6/6 | RECOMMENDATION_EVIDENCE x6 |
| 小码短链接自带自定义分享标题 | 6/6 | 6/6 | RECOMMENDATION_SUPPORTING_EVIDENCE x12 |
| 小码短链接适合营销场景使用 | 6/6 | 0/6 | - |

## 3. 30 条 Binding 人审清单

人审结论建议只填以下四类：

```text
正确 DIRECT_REASON
正确 SUPPORTING_REASON
不应该 Binding
角色应该调整
```

| # | Run | 实体 | AnswerUnit | 机器角色 | 支撑数 | 代表来源主张 | 人审结论 | 备注 |
| ---: | ---: | --- | --- | --- | ---: | --- | --- | --- |
| 1 | 238 | 小码短链接 | 小码短链接支持长链接快速缩短 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3213 |
| 2 | 238 | 小码短链接 | 小码短链接自带点击统计 | DIRECT_REASON/HIGH | 1 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 待人工审计 | AnswerClaim #3213 |
| 3 | 238 | 小码短链接 | 小码短链接自带二维码生成 | SUPPORTING_REASON/MEDIUM | 0 |  | 待人工审计 | AnswerClaim #3213 |
| 4 | 238 | 小码短链接 | 小码短链接自带自定义分享标题 | SUPPORTING_REASON/MEDIUM | 2 | 小码短链接提供自定义分享功能 | 待人工审计 | AnswerClaim #3213 |
| 5 | 238 | 小码短链接 | 小码短链接适合营销场景使用 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3213 |
| 6 | 239 | 小码短链接 | 小码短链接支持长链接快速缩短 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3227 |
| 7 | 239 | 小码短链接 | 小码短链接自带点击统计 | DIRECT_REASON/HIGH | 1 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 待人工审计 | AnswerClaim #3227 |
| 8 | 239 | 小码短链接 | 小码短链接自带二维码生成 | SUPPORTING_REASON/MEDIUM | 0 |  | 待人工审计 | AnswerClaim #3227 |
| 9 | 239 | 小码短链接 | 小码短链接自带自定义分享标题 | SUPPORTING_REASON/MEDIUM | 2 | 小码短链接提供自定义分享功能 | 待人工审计 | AnswerClaim #3227 |
| 10 | 239 | 小码短链接 | 小码短链接适合营销场景使用 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3227 |
| 11 | 240 | 小码短链接 | 小码短链接支持长链接快速缩短 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3241 |
| 12 | 240 | 小码短链接 | 小码短链接自带点击统计 | DIRECT_REASON/HIGH | 1 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 待人工审计 | AnswerClaim #3241 |
| 13 | 240 | 小码短链接 | 小码短链接自带二维码生成 | SUPPORTING_REASON/MEDIUM | 0 |  | 待人工审计 | AnswerClaim #3241 |
| 14 | 240 | 小码短链接 | 小码短链接自带自定义分享标题 | SUPPORTING_REASON/MEDIUM | 2 | 小码短链接提供自定义分享功能 | 待人工审计 | AnswerClaim #3241 |
| 15 | 240 | 小码短链接 | 小码短链接适合营销场景使用 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3241 |
| 16 | 253 | 小码短链接 | 小码短链接支持长链接快速缩短 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3255 |
| 17 | 253 | 小码短链接 | 小码短链接自带点击统计 | DIRECT_REASON/HIGH | 1 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 待人工审计 | AnswerClaim #3255 |
| 18 | 253 | 小码短链接 | 小码短链接自带二维码生成 | SUPPORTING_REASON/MEDIUM | 0 |  | 待人工审计 | AnswerClaim #3255 |
| 19 | 253 | 小码短链接 | 小码短链接自带自定义分享标题 | SUPPORTING_REASON/MEDIUM | 2 | 小码短链接提供自定义分享功能 | 待人工审计 | AnswerClaim #3255 |
| 20 | 253 | 小码短链接 | 小码短链接适合营销场景使用 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3255 |
| 21 | 254 | 小码短链接 | 小码短链接支持长链接快速缩短 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3269 |
| 22 | 254 | 小码短链接 | 小码短链接自带点击统计 | DIRECT_REASON/HIGH | 1 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 待人工审计 | AnswerClaim #3269 |
| 23 | 254 | 小码短链接 | 小码短链接自带二维码生成 | SUPPORTING_REASON/MEDIUM | 0 |  | 待人工审计 | AnswerClaim #3269 |
| 24 | 254 | 小码短链接 | 小码短链接自带自定义分享标题 | SUPPORTING_REASON/MEDIUM | 2 | 小码短链接提供自定义分享功能 | 待人工审计 | AnswerClaim #3269 |
| 25 | 254 | 小码短链接 | 小码短链接适合营销场景使用 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3269 |
| 26 | 255 | 小码短链接 | 小码短链接支持长链接快速缩短 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3283 |
| 27 | 255 | 小码短链接 | 小码短链接自带点击统计 | DIRECT_REASON/HIGH | 1 | 小码短链接可以在“我的链接”页面查看每个链接的访问量、点击次数等数据 | 待人工审计 | AnswerClaim #3283 |
| 28 | 255 | 小码短链接 | 小码短链接自带二维码生成 | SUPPORTING_REASON/MEDIUM | 0 |  | 待人工审计 | AnswerClaim #3283 |
| 29 | 255 | 小码短链接 | 小码短链接自带自定义分享标题 | SUPPORTING_REASON/MEDIUM | 2 | 小码短链接提供自定义分享功能 | 待人工审计 | AnswerClaim #3283 |
| 30 | 255 | 小码短链接 | 小码短链接适合营销场景使用 | DIRECT_REASON/HIGH | 0 |  | 待人工审计 | AnswerClaim #3283 |

## 4. 机器侧初步观察

这 30 条 Binding 还不能直接批准进入正式链，因为机器确实把每个 Run
中的 5 个小码能力点都绑定成了推荐理由或辅助理由。

其中来源支撑只覆盖：

```text
点击统计：6/6 SUPPORTS
自定义分享标题：6/6 SUPPORTS，每 Run 2 条支持主张
```

暂未形成来源支撑：

```text
快速缩短：0/6 SUPPORTS
二维码生成：0/6 SUPPORTS
营销场景：0/6 SUPPORTS
```

人工审计重点：

```text
1. 判断 5 个能力是否都真的是答案推荐小码的理由。
2. 判断 “快速缩短 / 二维码生成 / 营销场景” 是否应保留 Binding，
   还是应降为普通能力描述。
3. 判断 “点击统计 / 自定义分享标题” 的角色是否应为 DIRECT_REASON
   或 SUPPORTING_REASON。
```

## 5. 反向 Case 验收

当前已用确定性 fixture 跑过三类反向/边界 Case：

| Case | 预期 | 结果 |
| --- | --- | --- |
| Procedure Case | 过程步骤不成为推荐理由；可作为 `PROCEDURAL_EVIDENCE`；不进入 Recommendation Evidence Eligible | 通过 |
| Neutral Feature Case | 没有推荐事件时，普通能力描述不生成 Binding | 通过 |
| Implicit Reason Case | 隐式场景理由可以绑定到推荐事件 | 通过 |

验证命令：

```bash
.venv/bin/python -m pytest tests/test_answer_evidence_shadow.py
```

结果：

```text
7 passed
```

## 6. Phase 1 Gate

当前状态：

```text
SHADOW_EVIDENCE_CHAIN_PROVEN_ON_POSITIVE_CASE
READY_FOR_PRODUCTION_SWITCH = false
```

进入 Phase 1 前仍需：

```text
1. 人工审完本文件 30 条 Binding。
2. 未发现系统性 “FEATURE = Recommendation Reason” 过绑定。
3. Procedure / Neutral Feature / Implicit Reason 反向 Case 持续通过。
4. Shadow 正式链零污染继续成立。
```

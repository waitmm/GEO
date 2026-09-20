# Strategy Synthesis PR4 Checkpoint

状态：PR4-B PRODUCTION CUTOVER COMPLETE / AWAITING HUMAN STRATEGY REVIEW
日期：2026-09-07

## 1. 产品位置

PR4-A.1 位于 Step 7 已有 Strategy Opportunity 与 Channel Resolution 之后、人工策略确认之前。它只对
当前 StrategyCandidate 中已经确定的对象做受限综合，不改变 1-8 主链顺序，不替换 StrategyCandidate
真相源，也不创建 Step 8 的 Action、Experiment、URL、标题、section 或资产实例。

> DETERMINISTIC FIRST, LLM ONLY WHEN NECESSARY.

> LLM 不是策略真相引擎，只能处理确定性系统明确标记的局部结构歧义。

## 2. Closed World Contract

世界模型为 `CLOSED_WORLD`。输入仅限当前 Candidate Scope 内具有稳定 ID 的 Decision Reason、Product
Truth、Evidence Gap、Channel Resolution、Channel Evidence、Relevant Asset、Run Metric 与 Benchmark。

允许 `GROUP / SELECT / PRIORITIZE / SUMMARIZE / VERBALIZE`；禁止创建事实、能力、理由、Product Truth、
渠道、资产、URL、引用或指标，禁止改变 Channel Role、Product Truth、Evidence verdict、Benchmark
eligibility、Run coverage，禁止从观察推断因果。

硬原则：

```text
NO SOURCE ID -> NO FACTUAL CLAIM
NO ELIGIBLE OBJECT -> NO NEW OBJECT
UNKNOWN -> MUST REMAIN UNKNOWN
OBSERVATION != CAUSAL CONCLUSION
```

## 3. Deterministic First

- Reason identity/coverage、Theme coverage、Resolver role、eligibility、Product Truth、Gap、Run metric、唯一
  Theme/TEST priority 和 portfolio selection 均由确定性代码完成。
- 只有代码明确输出 `AMBIGUOUS_THEME_GROUPING`、`AMBIGUOUS_TEST_PRIORITY` 或
  `AMBIGUOUS_PORTFOLIO_SELECTION` 时，才允许发起 bounded LLM request。
- 每次 bounded request 只包含当前 ambiguity 的 Reasons 或 eligible TEST channels，不包含无关渠道、全部
  引用、其它 Product Truth 或完整 Strategy payload。
- Structural DeepSeek 参数为 `temperature=0.0`，prompt/schema/contract 均版本化。retry 不改变 contract、
  allowed ID set 或 schema。
- Presentation 当前由确定性 template 生成。没有真实表达歧义时，不为“更智能的文案”调用 LLM。

## 4. Validators 与回退

代码 Gate 包含 Strict Structural Schema、Business Rule、Provenance、Theme Coverage、Theme Title 和
Unsupported Claim Validator。

Theme coverage 严格定义为 member reason `observed_run_ids` 的集合并集，并保存
`theme_observed_run_ids`、`theme_observed_run_count` 与 `theme_coverage`。Theme title 当前只接受由 member
capability family 生成的 deterministic label，无法验证的抽象标题不进入正式结构。

未知 ID、新渠道、Role mutation、新能力/资产/指标、伪造 coverage、非法 Theme merge、因果断言和 malformed
JSON 均整次拒绝，不做宽松字段修复。最终返回 deterministic baseline 或明确 `needs_human_*`；LLM
timeout/invalid output 不会让 Strategy Opportunity 失败。

## 5. Shadow API

```text
GET /api/optimization/workflow/{project_id}/{prompt_id}/strategy-synthesis-shadow
```

`candidate_id` 可固定回放候选。即使设置 `use_llm=true`，无 ambiguity 时也返回
`SKIPPED_NOT_NECESSARY` 且 external calls 为 0；只有显式 ambiguity 才进入 bounded LLM。端点不写
Candidate、Workflow Confirmation、Action 或 Experiment。

## 6. #19 / #40 回放

#19 Candidate #56：

```text
5 atomic reasons -> 3 themes
T1 短链生成 = 13/15, P1
T2 加粉数据回传优化投放效果 = 13/15, P1
T3 抖音跳转微信 = 1/15, P2

PRIMARY = OFFICIAL_SITE
TEST P1 = BAIJIAHAO / ZHIHU
deferred TEST = BILIBILI / SOHU
OBSERVE = 43
```

#19 两个 `13/15` Theme 已逐 ID 验证为 member reason Run ID 的集合并集：T1 为
`[73, 173..184]`，T2 为 `[74, 173..184]`，均不是 member coverage 相加。

#40 Candidate #50 保持三个 6/6 Theme、OFFICIAL_SITE PRIMARY、ZHIHU SECONDARY、TEST none。

两个 replay 的六类 Validator 均为 VALID；`use_llm=true` 均检测为无歧义并跳过外部调用。Resolver role、
Benchmark signature、strategy basis 和 Candidate hash 不变，新增 Candidate/Action/Experiment 均为 0。

## 7. External Safety Replay

Synthetic/non-sensitive DeepSeek replay 已真实执行 1 次。provider 返回可解析 JSON，但同时返回
`decision=NEEDS_HUMAN` 与三个 `channel_keys`，违反 bounded semantic schema。代码将整次 proposal 判为
`LLM_SYNTHESIS_REJECTED`，external calls=1、deterministic fallback preserved=true、final structure valid=true。
这证明真实 provider 输出即使格式可解析但语义越权，也无法进入 Strategy Truth。

真实 #19/#40 外部 replay 未获数据出境授权，继续标记 deferred；本轮真实 DB replay 全部为只读且
external calls=0。

## 8. 验收边界

30 个专项测试覆盖正常结构和十类 adversarial output，全部验证非法 proposal 后最终 Strategy structure
等于 deterministic baseline。PR4 + PR3 Resolver + Step 7 组合测试 65 passed；全后端 414 passed，保留
五个与本轮无关的既有失败；`compileall app` 与 `git diff --check` 通过。

## 9. PR4-B Production Cutover

Shadow 与 Production 已抽取并共用同一个 Strategy Synthesis core。正式生成默认开启 Constraint-First，
默认关闭外部 Strategy LLM；六类 Validator 在旧 current Candidate 被 supersede 之前完成 Gate。正式 Candidate
保存 contract、input/output hash、原子 Reasons、Themes、portfolio、Decision View 与 Audit View。

#19 已创建 current Candidate #57；#56 payload 保持不可变并以
`SUPERSEDED_BY_VALIDATED_STRATEGY_SYNTHESIS_V1` 转为 `DEFERRED`。#57 的结构与本文件第 6 节完全一致，
Production/Shadow output hash 相同，external calls=0。#40 replay 与 #50 完全一致，因此不迁移。

#57 仍为 `PENDING_REVIEW`，没有 Experiment/Action，Step 8 为 `LOCKED`。PR4-B 到此停止，下一步只能进行
人工 Strategy Review，不得自动确认或进入 Step 8。

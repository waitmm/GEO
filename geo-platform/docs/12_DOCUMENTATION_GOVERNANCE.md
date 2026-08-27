# 12 Documentation Governance

状态：ACTIVE
日期：2026-08-27

## 1. 目的

本文件定义 GEO Platform 的产品与开发记录纪律。所有新开发必须让仓库文档成为事实来源，不能只依赖聊天记录、临时口头约定或前端临时文案。

核心目标：

```text
产品边界可追踪
开发变更可复盘
踩过的问题不重复踩
主链变化必须强预警
```

## 2. 必须维护的文档

### 2.1 产品迭代记录

文件：

```text
docs/09_PRODUCT_ITERATION_LOG.md
```

记录范围：

- 产品阶段是否进入、通过、冻结或停止。
- 主链步骤是否新增、删除、改名或调整顺序。
- 用户可见语义是否变化，例如状态、按钮、卡片、中文解释。
- Strategy、Action、Experiment、Baseline、Release Gate 的业务含义变化。
- V1/V2 边界变化。

每条记录至少包含：

```text
日期
产品决策
影响范围
不做什么
验收口径
后续边界
```

### 2.2 开发迭代记录

文件：

```text
docs/08_DEVELOPMENT_LOG.md
```

记录范围：

- 代码实现、迁移、脚本、API、前端入口、测试变化。
- 复用了哪些现有对象。
- 新增了哪些字段、payload 或服务。
- 验证命令和结果。
- 已知失败是否与本轮无关。

每条记录至少包含：

```text
日期
实现内容
触及文件或模块
数据影响
测试结果
是否需要 migration
是否改变正式链输出
```

### 2.3 踩坑与风险记录

文件：

```text
docs/09_OPEN_ISSUES_AND_RISKS.md
```

记录范围：

- 已经导致返工、误判、状态串线或用户困惑的问题。
- 尚未修复但不阻塞当前阶段的问题。
- 可能再次出现的工程风险。

每条记录至少包含：

```text
问题现象
根因
影响范围
当前处理
防复发约束
```

### 2.4 产品纲要

文件：

```text
产品纲要.md
```

定位：

- 面向业务和项目管理，描述当前产品核心链路、核心价值和阶段边界。
- 必须随产品阶段冻结、主链调整、核心入口变化同步更新。
- 不替代详细规格，但不能与 `docs/PRODUCT_FUNCTION_SPEC.md` 和 `docs/09_PRODUCT_ITERATION_LOG.md` 冲突。

## 3. 强预警规则

以下变化属于产品级变化，开发前必须先向用户明确预警并获得确认：

- 改变单 Prompt 主链步骤数量、顺序或阶段名称。
- 新增顶层模块，而不是融入既有主链或模块详情页。
- 改变任一卡片的唯一事实来源。
- 让 Citation Prominence、历史 RELATED、标题相似等信号进入正式 Benchmark / Gap / Strategy。
- 让未确认 Product Truth 生成确定性执行策略。
- 让 StrategyCandidate 跳过人工确认创建 Action 或 Experiment。
- 让 Experiment 不冻结 Strategy / Gap / Action / Asset / Baseline 快照。
- 默认把 Benchmark 平台当成执行发布渠道。
- 新增 Step 9、Prompt Cluster、跨 Prompt 聚合、自动内容生产或自动发布。

强预警格式建议：

```text
这是产品级变化，会影响：
- 当前主链：
- 用户操作：
- 数据语义：
- 回滚成本：

如果确认，我会先更新产品迭代记录，再开发。
```

## 4. 状态事实源纪律

单 Prompt 主链每一步必须有唯一主状态源：

| 步骤 | 主状态源 |
| --- | --- |
| 1 采集样本 | 当前 Prompt 的 BrowserMonitorRun / ReferenceSource / RetrievalCandidate |
| 2 答案决策识别 | AnswerSemanticFact / RecommendationEvent / AnswerUnit / AnswerDecisionBinding |
| 3 目标品牌事实 | TargetBrandCapabilityTruth |
| 4 引用证据 | Evidence Package / SourceDocument / eligible EvidenceAlignment |
| 5 对标来源 | Benchmark 派生结果 |
| 6 缺口诊断 | capability/reason-level GapDiagnosis |
| 7 策略确认 | OptimizationStrategyCandidate / effective_payload |
| 8 实验方案 | OptimizationAction / OptimizationExperiment / frozen snapshots / baseline |

旧 `continueResult`、历史 Experiment、历史 Evidence Package、ShadowRun 只能做历史展示或审计，不得反向决定当前主链状态。

## 5. 开发前后文档动作

开发前必须确认：

- 当前任务是否会改变产品语义。
- 是否需要先更新产品迭代记录。
- 是否触及 V1 冻结边界。
- 是否已有对应文档可复用。

开发后必须补齐：

- `docs/08_DEVELOPMENT_LOG.md`：实现与验证。
- `docs/09_PRODUCT_ITERATION_LOG.md`：如有产品语义变化。
- `docs/09_OPEN_ISSUES_AND_RISKS.md`：如发现新坑、历史坑或非阻塞遗留项。
- `产品纲要.md`：如影响用户理解的核心链路或阶段边界。

## 6. V1 冻结后的默认处理

当前状态：

```text
SINGLE_PROMPT_GEO_V1_FROZEN
STEP_9_NOT_STARTED
```

默认规则：

- V1 只接受 bugfix、文案澄清、状态一致性修复和验收补强。
- 新能力默认进入 V2 或后续 Phase，不得混入 V1 冻结主链。
- 如果确实需要改变 V1 主链，必须先记录产品决策并获得用户确认。

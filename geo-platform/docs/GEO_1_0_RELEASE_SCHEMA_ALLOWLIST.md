# GEO 1.0 首批发布表白名单

Status: `APPROVED_FOR_FIRST_SLICE`
Revision: `20260920_01`
Date: 2026-09-20

正式 release 数据库只允许本文件列出的业务表及 Alembic 自有的
`alembic_version`。后续切片必须通过新 migration 增量加入。

## 共享基础表

| 表 | 1.0 职责 |
| --- | --- |
| `organizations` | Project 所属组织 |
| `projects` | 目标品牌及项目身份 |
| `competitors` | 项目配置中的竞品身份，只作显式配置 |
| `topics` | Prompt 可选分类外键 |
| `prompt_clusters` | Prompt 可选分组外键 |
| `prompts` | 单 Prompt 身份和采样配置 |
| `monitoring_batches` | 采样批次的显式配置 |
| `browser_monitor_tasks` | V2 Analysis 所属采集任务 |
| `browser_monitor_runs` | 固定计划 Run 与真实采样结果 |
| `reference_sources` | Run 中实际观察到的引用 occurrence |
| `retrieval_candidates` | 可用时保存的 Retrieval observation |
| `run_artifacts` | 采样审计文件引用 |
| `recommendation_entities` | 项目内品牌/工具身份 |
| `target_brand_capability_truths` | 经独立流程确认的目标品牌事实 |

## V2 首批主链表

| 表 | 1.0 职责 |
| --- | --- |
| `single_prompt_analyses` | 单 Prompt 分析身份和采样状态 |
| `single_prompt_analysis_contexts` | 不可变 Raw Result / Context |
| `single_prompt_citation_manifests` | 不可变引用范围 |
| `single_prompt_source_preparations` | 来源准备执行状态 |
| `single_prompt_source_dispositions` | 每个去重来源的当前人工处置 |
| `single_prompt_prepared_source_snapshots` | Analysis-owned 不可变正文与 passages |
| `single_prompt_source_completion_manifests` | 不可变来源完成清单 |
| `single_prompt_diagnosis_executions` | Answer/Evidence 执行身份 |
| `single_prompt_diagnosis_results` | 不可变 Answer/Evidence 结果版本 |
| `single_prompt_diagnosis_reviews` | 精确结果的追加式审核 |

## 计算/物化表

| 表 | 1.0 职责 |
| --- | --- |
| `llm_call_cache` | 经当前 V2 准入重验的兼容计算缓存 |

缓存不是业务完成状态，也不继承人工审核。

## 退役的 V1 业务状态表

所有 `optimization_*`、`workflow_confirmations`、`prompt_analysis_runs`、
`intervention_plans`、旧 Recommendation workflow 与旧 SourceDocument/
SourceClaim/Alignment 业务状态表均不进入首批 release schema。纯计算函数可以
复用，但不得要求这些表存在。

旧 `single_prompt_source_snapshots` 也被排除：它由 Diagnosis 持有，与 R3 的
Analysis/Context/Citation Manifest 所有权冲突。

## 排除的 Runtime 与后续切片表

- 全部 Runtime persistence/projection 表；
- `single_prompt_strategy_*`；
- `single_prompt_execution_*`、`single_prompt_publication_records`；
- `single_prompt_retest_*`、`single_prompt_comparison_results`。

首批正式 app 不注册这些对象对应的业务路由或后台恢复任务。

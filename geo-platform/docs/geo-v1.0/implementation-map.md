# GEO Platform 1.0 真实实现映射（T00）

检查日期：2026-09-30  
检查范围：当前 `geo-platform` 仓库、`backend/geo_release.db`、release API/worker、前后端测试与构建入口。  
结论口径：文件或测试存在不等于 release 已交付；正式能力必须同时满足 release 路由、release 表白名单、真实持久化和产品入口四项。

## 1. 当前运行基线

| 项目 | 真实现场 | 结论 |
|---|---|---|
| 后端 | FastAPI + SQLAlchemy + Alembic；正式入口 `app.release_main:app` | 可复用 |
| 前端 | React 19 + TypeScript + Ant Design + Vite；当前为单页纵向工作台 | 技术栈可复用，信息架构需修复 |
| 发布数据库 | 单机 SQLite；`backend/geo_release.db`；revision `20260930_01` | READY |
| SQLite | 应用实际加载 `3.51.3`，WAL，foreign keys=1 | 满足当前单机发布边界 |
| Worker | `backend/scripts/release_worker.py`，业务重任务并发 1 | 可复用 |
| 正式路由 | `release_catalog` + `single_prompt_v2.release_api` | 已含 Execution、Publication、Retest；真实链当前停在发布确认前 |
| 当前真实数据 | 1 Project、1 Prompt、9 Runs、5 Analyses/Contexts、91 Source Snapshots、6 Diagnosis Results、0 Strategy Results、1 Critic Gold Review | 可用于回归，不代表完整闭环验收 |
| 外部模型 | DeepSeek 为主分析；SiliconFlow/Qwen 仅 Shadow Critic | 配置存在；T00 未外调 |
| 浏览器采样 | 文心 Playwright 采集器 + 持久 Run 池 | 核心可复用 |

2026-10-01 增量更新：migration `20260930_01` 已将 Execution Proposal、Publication、Retest、Comparison
表和正式路由纳入 release。表/路由接入不等于真实发布或复测完成；当前单 Run 只完成到完整执行稿与文本 QA。

## 2. 功能实现映射

| 功能编号 | 需求编号 | 分类 | 真实文件/函数/接口 | 当前行为 | 旧状态依赖 | 复用方式 | 真实缺口 | 关联任务 | 验证命令或操作 | 证据位置 | 检查日期 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BRD | BRD-001..004 | 需修复 | `backend/app/api/release_catalog.py`; `models/db.py::Project`; `frontend/src/App.tsx` | release 可创建/修改 Project，保存品牌名、别名、单一网站、行业/地区/语言 | 无 V1 workflow 依赖，但直接原地修改 Project | 保留 catalog CRUD 与 Project ID | 缺配置版本、多个官方域名/身份规则版本、变更历史；当前只有默认组织，缺真实租户授权 | T03 | release catalog API；AC-BRD-* 尚未执行 | `test_release_first_slice.py`; `release_catalog.py` | 2026-09-30 |
| PRM | PRM-001..004 | 需修复 | `release_catalog.py`; `service.py::create_analysis_from_runs`; `/api/v2/single-prompt/runs`, `/analyses/from-runs` | Prompt CRUD、Topic/Cluster、显式选择历史 Run、冻结 Analysis/Context 已有 | Prompt 编辑直接覆盖当前行；部分旧 analytics 仍按 current Prompt 读取 | 保留显式 `run_ids` 和不可变 Context | 缺 Prompt 版本；“继续旧分析/另建分析”产品入口仍混杂；目标标签与分析范围版本未统一 | T01,T04 | run-pool/from-runs 测试通过；AC-PRM-* 未完整执行 | `test_release_first_slice.py`; `service.py` | 2026-09-30 |
| SAM | SAM-001..004 | 需修复 | `monitoring/collectors/wenxin/collector.py`, `executor.py`, `services.py`; `release_api.py::retry_single_run`; Run pool UI | 文心独立采样、引用解析、Run 持久化、显式选样、单 Run 重试可用 | 采集器本身可窄入口复用；不得接回 legacy workflow Runner | 保留成熟采集器、artifact、Run pool | 缺取消；retry 新建物理 Run 但缺明确 logical_run/attempt 身份；WAITING_EXTERNAL/恢复语义未完全对齐新任务契约 | T05 | `test_monitoring_retry.py`; release run-pool tests | monitoring tests；真实 9 Runs | 2026-09-30 |
| SRC | SRC-001..004 | 可直接复用（核心）/需修复（范围） | `source_preparation.py`; `optimization/passage_service.py::fetch_page_playwright`; `/source-preparations/*` | Citation Manifest、自动抓取、人工补录、内容 Gate、不可变 Snapshot/passages、waive、Completion Manifest 已进 release | 已隔离 Diagnosis 所有权；抓取使用明确 preparation/context | 直接复用当前纵向切片 | 只覆盖 Citation Manifest 来源；缺补充来源/品牌官方来源角色；重抓与部分范围更新的产品入口不完整 | T09,T13 | release source-preparation tests 通过；真实 91 snapshots | `test_release_first_slice.py`; release DB | 2026-09-30 |
| MON | MON-001..004 | 需接入 | `monitoring/*`; `analytics/*`; `diagnosis.py`; 前端 `deriveDashboard` | Run 层已有 mention/recommendation 原始字段；旧 analytics 有聚合能力；release 页面有局部概览 | 完整 analytics router/表不在 release；前端存在本地派生 | 提取纯指标函数，以冻结 DTO 运行 | release 无权威 Monitor 指标版本；Mention/Option/Recommendation 分母、Macro/Weighted、机会规则未形成统一后端契约 | T06,T07,T08 | 现有 monitoring 测试；AC-MON-* 未执行 | `models/db.py::BrowserMonitorRun`; `frontend/src/App.tsx` | 2026-09-30 |
| OPT | OPT-001..004 | 确实缺失（编排层） | 现有阶段入口分散于 `release_api.py`; worker 分阶段消费 | 各阶段可单独创建/恢复，但没有产品定义的一次显式 Optimize 自动任务与统一状态 | 当前依赖多个人工 Review 才能继续；旧 Runner 不应复活 | 复用分析/来源/Citation/Truth/Strategy 内核，新增最小 V2 编排 | 缺唯一自动主链、阶段级预算/恢复、结果聚合；当前默认人工 Gate 与新产品“人工可选纠错”冲突 | T01,T02,T10 | 现有阶段测试不能代替 AC-OPT-* | `release_api.py`; `release_worker.py` | 2026-09-30 |
| ANS | ANS-001..004 | 可直接复用（安全内核）/需修复（产品契约） | `diagnosis.py::create_answer_diagnosis/compute_answer_diagnosis`; `llm_safety.py`; strict response models in `diagnosis.py` | 严格 Schema、完整 JSON、grounding、不可变结果、失败/零事件分离已实现 | 无需 legacy Runner；当前 Citation Contribution 的 AnswerUnit 只在特定 scope 内构建 | 复用 strict admission 与原文定位 | 事件协议与新 AnswerUnit/行为全集尚未统一；全链默认依赖人工 Answer Review；多 Run 覆盖曾出现 partial scope | T11 | V2 safety/diagnosis tests 通过；AC-ANS-* 未全量执行 | safety tests；真实 Diagnosis Results | 2026-09-30 |
| CIT | CIT-001..004 | 需接入 | `citation_contribution.py`; `evidence_plan.py`; `optimization/passage_retrieval.py`; Citation Contribution APIs | 多维 relation contract、冻结 Plan、artifact、human calibration 已实现；当前真实 P1 为 Run 1 | 旧 SourceClaim/Alignment 可作计算能力，不能恢复旧 workflow 状态 | 扩展现有冻结 DTO/Plan 到选定 Analysis scope | 当前 release 真实贡献分析只覆盖 Run 1，存在 16 DONE/3 FAILED；未完成全选定 Runs 自动路径；人工 calibration 仍是 Gate | T12 | contribution contract/release tests 通过；真实全范围未验收 | `test_citation_contribution_contract.py`; release DB | 2026-09-30 |
| TRU | TRU-001..004 | 需修复 | `diagnosis.py` truth projection; `/target-brand-truths`; `/truth-reprojections`; `models/db.py::TargetBrandCapabilityTruth` | 原子目标品牌事实、用途资格、独立重投影已有；不核验竞品 Truth | 当前多为人工 asserted；诊断冻结快照与项目当前事实并存 | 保留原子事实和 eligibility-by-use | 缺 EMPTY/BASIC ContextProvider；官方 Snapshot 到充分事实的自动路径未闭合；不应让 Truth 缺失全局阻断 Optimize | T13 | qualification/truth 测试；AC-TRU-* 未完整执行 | V2 tests；release API | 2026-09-30 |
| STR | STR-001..005 | 需修复 | `strategy.py`; `qualification.py`; strategy readiness/qualification/strategy/review APIs | Foundation/Channel 分离、方向 Gate、readiness、不可变 Strategy Result 已实现 | 旧 resolver/latest Package 已隔离；正式创建仍要求 Review/完整 scope | 复用纯方向计算和 qualification projection | release 当前真实 Strategy Results=0；有效输入可能返回无 Candidate；人工 Review 默认 Gate；与“非空具体行动、自动默认”未对齐；资产角色仍不完整 | T14,T15 | strategy/qualification tests 通过；真实 Strategy 未形成 | strategy tests；release DB | 2026-09-30 |
| EXE | EXE-001..005 | 已接入/当前切片可用 | `execution.py`; `release_api.py`; `App.tsx` | release 内生成不可变 Proposal/Result、资产与承载位置判断、完整正文、实际文本 QA、确认 Gate | 无 legacy DB/latest 依赖；旧 fixture 仍与 fixed-scope Gate 不兼容 | 复用版本/确认/公开内部分离；按 `SC-ASSET-001` 隔离过时的“空资产即新建”判断 | 单 Run 真实稿件已 READY；仍需业务确认资产分支和权限；全场景/多 Run 尚未验收 | T16,T17,T18 | Optimize/release 34 passed；frontend build PASS | `execution-v5:2121b5e21d0ac6df`; acceptance record | 2026-10-01 |
| PUB | PUB-001..004 | 已接入/未真实执行 | `execution.py::record_publication`; `release_api.py`; publication UI | append-only USER_REPORTED、版本和符合性入口已在 release | 必须绑定 ExecutionConfirmation | 保留现有 PublicationRecord 逻辑 | 当前 confirmation=0、publication=0；没有真实发布，不能验收实际稿差异与线上材料 | T20 | 当前单 Run 验证未越过发布 Gate | release DB；acceptance record | 2026-10-01 |
| VAL | VAL-001..005 | 已接入/未真实执行 | `retest.py`; release retest/comparison APIs; UI | 固定 baseline、retest plan、measurement identity、comparison version 已进 release | 必须绑定真实确认与 PublicationRecord | 保留不可变 plan/comparison 与采样接线 | 当前 retest=0；缺发布后新 Run 和真实比较，不能用 baseline 冒充 | T21,T22 | 当前单 Run 验证未启动 Retest | `retest.py`; release API | 2026-10-01 |
| COR | COR-001..004 | 需修复 | diagnosis revision、truth reprojection、strategy priority revision、execution revision | 多个对象已有 append-only revision，不覆盖旧结果 | 当前纠错分散且多数需人工 Review 后推进 | 复用各对象版本机制 | 缺统一影响清单、局部重算任务和“人工可选而非主链 Gate”行为；不存在跨阶段一致的 stale 投影 | T19 | 各模块单测；AC-COR-* 未执行 | release/non-release APIs | 2026-09-30 |
| OPS | OPS-001..004 | 可直接复用（基础）/需修复（交付） | `release_main.py`; `release_database.py`; `release_schema.py`; Alembic; `release_worker.py` | 独立 SQLite、显式迁移、schema allowlist、启动校验、恢复与单 worker 已有 | release 与 legacy DB 已物理隔离；部分非 release 模块仍引用 legacy Session | 保留 release 控制面和 allowlist | 缺真实组织/用户授权边界、任务取消、完整备份恢复验收；`settings.release_schema_revision` 仍为旧值且未作为权威；后半主链未进 allowlist | T00,T01,T02,T25 | schema validation READY；Alembic current/head；专项 tests | release schema/DB/worker | 2026-09-30 |

## 3. 组件级复用决定

| 组件 | 决定 | 原因 |
|---|---|---|
| 文心 Playwright 采集与引用解析 | RETAIN + ADAPT | 成熟真实能力；只补 logical attempt/cancel/status，不重写采集器 |
| Run pool、显式 `run_ids`、AnalysisContext | RETAIN | 已解决历史+新增选样与不可变分析范围 |
| Source Preparation/Snapshot/Passage | RETAIN | 已在 release 新库形成真实纵向链 |
| Answer strict admission/grounding/cache revalidation | RETAIN | 安全边界完整，继续作为统一入口 |
| Citation Contribution P1 | RETAIN + EXPAND SCOPE | 保留多维关系；从 Run 1 扩到选定范围，不恢复旧单字段 Evidence |
| Qualification/Strategy pure projection | RETAIN + ADAPT | 方向计算可用；移除默认人工 Gate 和空交付风险需另做产品接线 |
| Execution/Publication/Retest modules | ADAPT INTO RELEASE | 不能因未在 release 就重写；先修 fixed-scope fixture 和 release DB/route 接线 |
| legacy Package/Candidate/Runtime Runner | ARCHIVE FROM RELEASE | 含 latest/current 状态依赖，不作为 1.0 控制面 |
| 前端本地业务推导 | REPLACE WITH BACKEND PROJECTION | 页面不得自行推导 current/ready/指标口径 |

## 4. 真实优先缺口

1. **M0 状态统一**：当前 fixed-scope Gate、合法零结果、待授权、失败和 review eligibility 已在不同阶段出现过口径漂移；先完成 T01。
2. **真实发布断点**：Execution/Publication/Retest 已进入 release，但当前真实链尚未确认执行或发布，因此复测和 Validate 仍没有业务输入。
3. **自动 Optimize 缺失**：现有能力是多个人工阶段，不是产品文档定义的自动默认、可选纠错。
4. **Monitor 指标不权威**：采样数据存在，但 release 后端没有统一 Mention/Option/Recommendation 与 Macro/Weighted 计算版本。
5. **版本缺口**：Project/Brand/Prompt 仍是可变当前行，虽然 AnalysisContext 已冻结运行输入。
6. **Citation 全范围缺口**：真实贡献计算仅 Run 1；不能外推为 9 Runs。
7. **用户与权限边界缺口**：有 project ID 隔离检查，但无真实用户/组织授权控制。
8. **纠错影响缺口**：各阶段有 revision，尚无统一受影响对象清单和局部重算交接。

## 5. 调用与数据边界

- 浏览器采样只可由显式采样/重试 POST 启动；GET 不得采样。
- 来源抓取只可由显式 Source Preparation auto-fetch 启动；页面读取不得重抓。
- DeepSeek 只通过 V2 严格准入与授权/预算执行；T00 没有模型调用。
- SiliconFlow/Qwen 当前只写 Shadow Critic，不进入正式 Qualification；T00 没有模型调用。
- release API 与 worker 使用同一 `geo_release.db`；worker 并发固定 1。
- `backend/.env` 被 Git 忽略；T00 只核对变量是否配置，不读取或记录密钥值。

## 6. 本次验证

| 验证 | 结果 | 解释 |
|---|---|---|
| release schema inspection | PASS | revision `20260929_02`、SQLite `3.51.3`、WAL、FK、allowlist 全部满足 |
| Python compileall | PASS | `backend/app` 可编译 |
| 后端选定回归 | 151 passed / 19 failed | 19 个失败全部位于 `test_single_prompt_v2_execution.py`，由旧 fixture 只有 1/3 reviewed run、被新 fixed-scope Gate 拒绝引发；不能删除或放宽 Gate |
| 前端 release build | PASS | `npm run build:release`；存在 bundle >500KB 警告，不影响构建 |
| 69 功能场景 + 5 E2E | NOT RUN | 这些是后续任务验收清单，T00 不冒充软件已验收 |

回归命令：

```bash
cd backend
.venv/bin/python -m compileall -q app
.venv/bin/python -m pytest -q --tb=short \
  tests/test_release_first_slice.py \
  tests/test_single_prompt_v2.py \
  tests/test_single_prompt_v2_llm_safety.py \
  tests/test_single_prompt_v2_fixed_scope_coverage.py \
  tests/test_single_prompt_v2_strategy.py \
  tests/test_single_prompt_v2_execution.py \
  tests/test_single_prompt_v2_qualification.py \
  tests/test_citation_contribution_contract.py \
  tests/test_monitoring_retry.py

cd ../frontend
npm run build:release
```

## 7. T00 退出结论

T00 的原始核查已完成；2026-10-01 状态更新后，Execution/Publication/Retest 已进入 release，单 Run 的
完整执行稿与实际文本 QA 已形成真实结果。完整 1.0 仍未验收：自动 Optimize 编排、Monitor 权威指标、
真实发布和发布后 Validate 仍是明确未完成项。

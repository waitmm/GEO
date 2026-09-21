# GEO 1.0 首批来源与证据主链操作说明

Status: `RUN_POOL_AND_SOURCE_PREPARATION_AVAILABLE / EVIDENCE_INPUTS_PENDING`
Date: 2026-09-21

## 1. 当前交付范围

正式 release 路径只包含：

```text
Project / Prompt
-> Analysis / immutable Context
-> Citation Manifest
   |-> Source Preparation -> Source Completion Manifest
   `-> Answer ResultVersion -> exact Review
-> Evidence exact-input Gate -> immutable Evidence ResultVersion
```

不包含 Strategy、Execution、Publication、Retest，也不注册 legacy
optimization workflow。

## 2. 初始化与启动

首次环境先安装并构建安全 SQLite DBAPI：

```bash
cd geo-platform/backend
./.venv/bin/pip install -r requirements.release-build.txt
./.venv/bin/python scripts/bootstrap_release_sqlite.py
```

显式迁移独立 release 数据库：

```bash
cd /Users/bmwqr/Desktop/python/GEO
./scripts/release-migrate.sh
```

构建 release 前端并启动一个 API + 一个 worker：

```bash
cd geo-platform/frontend
npm run build:release

cd /Users/bmwqr/Desktop/python/GEO
./scripts/release-dev.sh
```

`build:release` 会生成 `frontend/dist/geo-release-build.json`。发布启动脚本必须验证该标记；
普通 `npm run build` 不能作为 release 页面启动，否则脚本会明确拒绝并提示重新构建。

默认地址：`http://127.0.0.1:8020`。启动不会执行 migration，也不会
`create_all()`；未迁移、错 revision、额外表或 SQLite 版本不安全都会拒绝启动。

## 3. 正式用户操作顺序

1. 在 release 页面创建/选择 Project 与 Prompt；
2. “新增采样”只创建新的浏览器 Run，必须已有对应外部操作授权；
3. 页面“采样记录池”分页展示该 Prompt 的全部历史 Run。用户可展开查看完整回答、引用、
   采样条件和限制，并明确勾选 `run_ids`；
4. “用所选 Run 建立分析版本”冻结精确 Run 集及每条输入指纹，不触发采样，也不修改旧
   Analysis/Context。用户也可以从“已有分析”继续原停止点；
5. Raw Result / Context 冻结后，点击创建来源准备；系统同时冻结 Citation Manifest；
6. 用户显式点击“自动获取正文”；单 worker 只处理该 Citation Manifest 内仍未完成的
   URL，复用既有浏览器渲染 + HTTP 兜底抓取内核；
7. 自动取得的正文经过验证页、登录墙、错误页、完整性和正文长度 Gate。合格内容由
   V2 生成不可变 Snapshot、正文 SHA-256、artifact 文件和 passages；
8. 自动获取失败或内容不合格的来源进入 `MANUAL_REQUIRED`，页面集中显示原因并允许
   人工补录；系统不会自动 WAIVE；
9. 无法取得的来源只能由用户明确填写原因与影响后 `WAIVED_WITH_LIMITATION`；
10. 所有来源处置完成后冻结 Source Completion Manifest；全部 WAIVED 时状态为
   `NO_USABLE_SOURCE`，不能进入 Evidence；
11. Citation Manifest 冻结后，Answer Semantic 可与来源准备独立推进；完成后
   用户审核精确 ResultVersion；它不需要等待正文完成，但 Evidence 需要两侧都完成；
12. 用户显式启动 Evidence；API 先校验同一 Analysis/Context 下的 Citation、
   Completion、Answer Result 与 Review，成功后仅入队；
13. release worker 对完全相同的版本绑定再次校验并消费，发布不可变 Evidence 结果。

## 4. 关键 API

- `POST /api/v2/single-prompt/analyses`
- `GET /api/v2/single-prompt/runs?project_id=...&prompt_id=...`
- `POST /api/v2/single-prompt/analyses/from-runs`
- `POST /api/v2/single-prompt/runs/{run_id}/retry`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/source-preparation`
- `POST /api/v2/single-prompt/source-preparations/{preparation_id}/auto-fetch`
- `POST /api/v2/single-prompt/source-preparations/{preparation_id}/manual-content`
- `POST /api/v2/single-prompt/source-preparations/{preparation_id}/waivers`
- `POST /api/v2/single-prompt/source-preparations/{preparation_id}/completion-manifests`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/answer-diagnoses`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/reviews`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/diagnoses/{diagnosis_id}/evidence-continuations`

所有 GET 只读。POST 返回 `QUEUED` 不表示计算完成；页面轮询后端状态，不能由
前端推断 ready/current。

## 5. 状态边界

- `READY` 正文只表示可定位、可校验、可复现，不代表正文主张真实；
- `WAIVED_WITH_LIMITATION` 只表示人工完成处置，不提供证据结论；
- `PENDING`、`AUTO_FETCH_QUEUED`、`AUTO_FETCHING` 或 `MANUAL_REQUIRED` 存在时
  Completion 不可冻结；
- 自动获取失败只产生人工补录待办，不产生 WAIVE、SUPPORTS 或 NO_SUPPORT；
- Answer 未审核、Review 错版、Manifest 错版、跨 Context 或全部来源 WAIVED，
  Evidence 均被后端阻断；
- Evidence 结果为零只有在实际评估完成且合法返回零关系时成立；未执行、失败、
  未召回或无正文不能写成零结果。

## 6. 2026-09-20 首轮真实验收

固定 Project `1`（爱短链）/ Prompt `1`（抖音跳转链接）已通过正式 release
入口建立真实链路：

- Analysis `a2d0c0ee-b62e-4f39-9fe9-1bc14efdea33`，Task `1`；
- Context `ctx-96357192-0f2d-45db-b70c-0b58c2987dcd`；
- Raw Result `raw-v1:c0918158fcea889c`，完整 SHA-256
  `c0918158fcea889ccff970e15f56bb1a98b3220daec8c9b57aff1f9d612bbfc3`；
- Citation Manifest `citation-manifest-fe0a0f19-2579-45ec-a5f3-f4b2eca2695d`，
  38 个唯一来源 / 87 条引用记录；
- Source Preparation `source-prep-626e2e6e-4cda-41a2-81b7-cc08a393198e`；
- 真实人工正文补录生成 Snapshot
  `source-snapshot-1a51fa9d-9c0a-4cea-85f2-db72a67db8d0`，正文/artifact
  SHA-256 `d163a7fe5f3a5140339a62df58da64032922ab020c4a05695667e030f7d99822`，
  passages SHA-256 `717fd262e71459d7f8257bb2e39db9c8912e29082f31e8e2eb2f0ab1d8fb470f`，
  20 passages；
- Answer Diagnosis `aac746f4-6b9b-4cda-b981-3487b5ef2f9b`，Result
  `diag-v1:69cb9884452deead` 的历史模型响应曾 3/3 通过当时的 Schema/Grounding
  准入并返回零事件；DeepSeek 外部请求 3 次、缓存命中 0、总 token 8,922。后续 DOM
  核查确认其固定输入混入了平台搜索/引用过程，因此当前只保留审计，不具备审核或
  Evidence 消费资格；零事件不能解释为纯最终回答没有推荐。

来源获取审计在每个唯一 URL 最多 2 次、串行、不递归的边界内完成：除已正式
READY 的 1 条外，形成 10 份待人工检查的正文候选、17 条内容复核项、8 条人工
补录项，另 2 条已达尝试上限。候选文件不属于正式 Snapshot，验证码页、JS 壳及
403/412/521 响应均未进入 READY。

本次只读获取审计保存在：

```text
backend/artifacts/release-acceptance/source-prep-626e2e6e-4cda-41a2-81b7-cc08a393198e/fetch-audit.json
```

审计文件 SHA-256 为
`d7394f769a32123ae4c65bcce995642681bacd4750639896fcbdab342ab83eea`；配套正文放在
同目录的 `unvalidated-candidates/`。两者都是人工处置材料，不是正式 Snapshot、
Completion 或 Evidence。

当前真实守恒为 `READY=1 / PENDING=37`，Completion Manifest 未生成；历史 Answer
Result 还因 `ANSWER_CONTENT_BOUNDARY_NOT_INDEPENDENT` 禁止审核和 Evidence 消费。
正式 API 已分别验证来源范围和审核 Gate；没有 Evidence Task、SourceClaim/Alignment
调用、WAIVE、Truth 或 Review 自动写入。服务重启后 Analysis、Snapshot、artifact
hash、Diagnosis 和 `review=null` 均保持一致。

精确页面入口：

```text
http://127.0.0.1:8020/?v2_analysis=a2d0c0ee-b62e-4f39-9fe9-1bc14efdea33&v2_project=1&v2_prompt=1&v2_diagnosis=aac746f4-6b9b-4cda-b981-3487b5ef2f9b&v2_diagnosis_result=diag-v1%3A69cb9884452deead
```

下一次新采样会将 Wenxin 搜索过程保存为独立只读 observation，并仅把最终 Markdown
冻结为回答正文；得到新的独立 Answer Result 后，用户才能完成精确 Review。来源侧仍需
逐条补录或明确 WAIVE 剩余 37 个来源。两侧均完成后才可冻结 Completion Manifest 并
执行 Evidence；当前正确状态是 Gate 真实阻断，不是 Evidence 正向消费完成。

## 7. 修正后重采样与自动正文获取验收

上一节对象保持不可变，仅作为首轮历史验收。本次通过同一正式入口创建了新的修正基线：

- Analysis `92bb12a5-edcc-43c7-b848-ca60267a2672`，Task `2`，Runs `4/5/6`；
- Context `ctx-79dcb9e0-a8fe-4c17-b584-01c240acdde2`；
- Raw Result `raw-v1:eb86358c452b1bc4`，完整 SHA-256
  `eb86358c452b1bc40038394c9243a13febef4f305c8f1a895ec78c3cd909f3d2`；
- Citation Manifest `citation-manifest-9ccde3db-5810-440a-aef8-836306c6db44`，
  hash `302a791df952f4683946327c183f12ac9c56d46160766c44df80dabfa5da09e9`，
  46 个唯一来源 / 87 条引用记录；
- Source Preparation `source-prep-25dbbbb2-b5ed-49c7-895c-8a8384a55afe`。

三个 Run 均提交原始 Prompt `抖音跳转链接`，没有把平台内部搜索词当成额外 Prompt；回答正文
分别为 908/879/938 字，引用为 30/27/30 条，三个会话均通过
`PRE_SUBMIT_ZERO_TURN_DOM_GATE`。本次没有失败 Run、重试或为结果表现追加样本。

自动正文获取按 Citation Manifest 串行执行并完成：`READY=30 / MANUAL_REQUIRED=16 /
WAIVED=0`。30 个 Snapshot 全部标记 `AUTO_FETCH`，文件均存在且 SHA-256 匹配，共形成
859 个 passages；既有质量规则复核均为 `CONTENT_VALID`。16 个待补来源的原因由后端保留，
包括验证/登录拦截、内容不完整和网络获取失败，不能解释为无证据或不支持。

重启后 preparation 汇总状态为 `MANUAL_REQUIRED`，30/16 子状态和文件绑定保持不变，未重新
抓取。Completion Manifest 仍为空，Evidence 未执行；Answer Semantic、Review、Truth、
SourceClaim、Alignment 和 Strategy 也未在本次操作中启动。

精确页面入口：

```text
http://127.0.0.1:8020/?v2_analysis=92bb12a5-edcc-43c7-b848-ca60267a2672&v2_project=1&v2_prompt=1
```

## 8. 从首页继续已有 Analysis

选择 Project 和 Prompt 后，release 页面会列出属于这一精确组合的 Analysis。点击“继续处理”
才会绑定对应的 `analysis_id`；列表排序只用于展示，系统不会自动把最新一条替换成当前输入。

进入来源准备后默认显示“待处理”来源。`READY` 和 `WAIVED_WITH_LIMITATION` 仍可通过筛选查看。
页面刷新或切换筛选不会抓取正文、补录、WAIVE 或冻结 Completion；这些仍必须通过对应的显式
操作完成。

## 9. 采样记录池与成熟能力恢复

release revision `20260921_01` 允许 Analysis/Context 不绑定新的 Browser Task，从而让用户用
历史 Run 建立新的不可变输入版本。Run 本身仍属于共享采样记录；一次 Analysis 冻结后不会因
后续新增 Run 自动变化。

| 能力 | 复用实现 | 退化点与处理 | release 入口 | 验收 |
|---|---|---|---|---|
| 文心采样 | `create_browser_task_from_frozen_prompt()`、`MonitoringTaskExecutor` | V2 继续拥有 Analysis/Context；不恢复旧 Runner | “新增采样” | 既有 9 个 Run 均可见 |
| Run 快照 | `_snapshot_run_rows()`（从既有 `_snapshot_runs()` 提取） | 去除“必须来自当前 Task”的限制，增加 scope/指纹校验 | `GET /runs`、`POST /analyses/from-runs` | 精确 run_ids，无新 Task |
| 单 Run 重试 | 同一 monitoring executor 与 task status 汇总 | 新 Task/Run attempt，原失败 Run 不覆盖 | `POST /runs/{id}/retry` | worker 只执行该 retry task |
| 正文自动获取 | `fetch_page_playwright()` + V2 `_snapshot_from_content()` | 不调用旧 `acquire_cited_sources()` 写旧 SourceDocument 状态 | Source Preparation 自动获取 | 30 READY / 16 MANUAL_REQUIRED |
| Passage/召回 | 既有 `retrieve_passages_for_reason()` | 仅消费固定 Snapshot passages | Evidence 双输入 Gate 后 | 隔离正向链通过 |
| 增量模型结果 | `LLMCallCache` 的语义输入/版本身份 + 不可变 ResultVersion | 缓存恢复仍经过 V2 准入；不迁入旧业务 materialization ledger | V2 Evidence | 重复精确绑定直接复用结果 |

非正式重复路径已经退出 release：旧 Evidence Package run 选择、旧 optimization Runner、
`acquire_cited_sources()` 的旧业务落库、任何 latest Package/Candidate/Truth 选择都未注册。

当前真实 release DB 有 9 个 Run 和四份保留的 Analysis。正式 `from-runs` 演示使用 Runs
`7/8/9` 创建了 Analysis `5ced1566-9e79-4c84-8bc8-1bccf58550a3`、Context
`ctx-456936cd-e32c-4901-9ae5-7e6a8d167cc3` 和 Raw Result `raw-v1:139f8b4a8797739f`；
该版本没有 Browser Task，也没有外部调用。主 Analysis
`92bb12a5-edcc-43c7-b848-ca60267a2672` 仍是 46 个唯一来源、30 READY、16
`MANUAL_REQUIRED`、0 WAIVED。当前库没有 DiagnosisExecution、DiagnosisResult 或 Review；
因此早期工单中的“3 个 DONE_ZERO_EVENTS”对象不在当前发布现场，不能冒充当前可审核结果。
接下来的人工作业是：处置 16 个来源，并在本 Analysis 上正式生成和审核 Answer Result；两侧
完成后才可排队 Evidence。

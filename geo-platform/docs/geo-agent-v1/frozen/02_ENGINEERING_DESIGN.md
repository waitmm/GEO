# 02 / 技术设计与增量接线规范

> 本文是**目标契约**，不是对真实仓库文件名、服务已存在或状态已完成的断言。Codex 必须先盘点代码，再给出实际实现映射。优先复用 FastAPI / SQLAlchemy / React-TypeScript / SQLite-WAL / Alembic 等仓库实际使用的组件，不为本实验改栈。

## 1. 系统边界：只新增一条 Lane

```text
                       GEO Platform (existing)

Project / Prompt / Brand Version / Context Provider
                    |
          Selected explicit Run IDs
                    |
              V2 scope freeze
                    |
        +-----------+--------------+
        |                          |
  Existing Optimize Lane     Agent Experiment Lane
  (unchanged, authoritative) (new, non-authoritative)
        |                          |
  V2 ResultVersion           AgentExperimentRun
  V2 Review/Truth             |  lightweight tool loop
  V2 Strategy/Execution       |  approved tools -> existing services
        |                      validator + AgentResultVersion
        +-----------+--------------+
                    |
      Compare by identical frozen input
                    |
           Shared Monitor / Validate
```

**最高优先级**：Agent 可以使用现有 V2 服务的正确 DTO 输出作为工具结果，但其自生成结论**不是** V2 正式 ResultVersion / Evidence Package / Product Truth / Review。Agent 不得改写正式主链数据，更不能为了跑通 Agent 调低正式 Gate。

`R3` 的严格 Evidence 双输入 Gate 约束的是正式 Evidence 消费；Agent 可以从冻结 Raw Run、Citation Manifest、既有合格快照和 Context 数据自行分析并生成**实验交付**，这不是利用 Agent 冒充正式 Evidence READY。旧规则与 2026-10-09 自动交付需求不一致时，沿现有正式决策处理；实验 Lane 不参与修改正式裁决。

## 2. 仓库盘点与复用映射（实施第一步）

检查而不是假设以下能力存在，填写实际代码路径、签名、复用方式及权限：

| 来源能力 | Agent 工具化目标 | 禁止的实现 |
|---|---|---|
| Project/Prompt/Brand/Run | 读取固定身份、版本与原文 | 通过全局 `latest` 查当前对象 |
| 冻结 Context / Citation Manifest | 固定 citation occurrence 与 Run 归属 | 从其他 Prompt 混取引用 |
| 来源快照与 passages | 读取可用片段及失败状态；可选受限新抓取 | 直接把 FAILED 或抓取页当 READY |
| ContextProvider / 用户资料 | 读有版本的品牌资料或 EMPTY | 把用户自述直接当官方已证实事实 |
| Product Truth | 只读已有事实及用途资格 | Agent 写 Truth / Review / WAIVE |
| Answer/Source 检索 | 可选复用确定性计算内核 | 重启旧 V1 Runner 或旧 ORM |
| Monitor/Validate | 读同口径观察和对照范围 | 新建不同口径的指标体系 |
| LLM client / usage ledger | 复用已批准模型、统一费用/Token 统计 | 绕过额度以独立 SDK 无限外调 |
| Work queue / worker / task status | 在既有 worker 下跑 Agent 任务 | 新建第二套常驻 Runtime 与调度系统 |
| 身份权限/日志/备份/迁移 | 沿用现有基础设施 | 自己绕过 API 获取其他租户数据 |

盘点后生成 `implementation-map` 的**增量附录**，有成熟可复用能力就直接适配，找不到才写小型替代 adapter。严禁仅凭记忆硬编码源码路径。

## 3. 精确输入冻结与运行身份

### 3.1 请求契约 `StartAgentExperiment`

```json
{
  "project_id": "<existing-project-id>",
  "prompt_id": "<existing-prompt-id>",
  "run_ids": ["<run-id-1>", "<run-id-2>"],
  "analysis_mode": "RAW_FIRST",
  "context_version_id": "<version-or-EMPTY>",
  "model_profile_id": "<approved-model-profile>",
  "budget": {
    "max_model_calls": 20,
    "max_tool_calls": 50,
    "max_total_tokens": 100000,
    "max_elapsed_seconds": 900,
    "max_cost": "<explicitly-authorized-positive-amount-in-project-currency>"
  },
  "regenerate": false
}
```

`max_*` 是**可配置上限的示例值**，不是用户已经同意消耗的费用；只有真实项目授权及预算匹配时才能外调。数据权限、开关和完整预算验证全部在后端完成。若没有授权/凭证，离线验证继续，外部调用记 `BLOCKED`（仅指该阶段验证），不伪造通过。

### 3.2 冻结输入具体项

- `project_id / prompt_id / prompt_version / brand_config_version / operator_scope`。
- 排序后稳定的 `run_ids`、每条 Run 的平台、采样方式、采样时间、raw answer ID、原文 hash、有效性与失败原因。
- `Citation Manifest`（包含 Run→occurrence→source 映射）版本/hash；没有引用是合法零，解析失败要单列。
- 明确选定的已有 Source Snapshot/Passage 版本；抓取失败/未抓取/过期不自动变为 NONE。
- `ContextProvider` 品牌知识版本（可为 `EMPTY`），正确的 Product Truth 版本或独立证据来源。
- 当前指标/实体解释规则版本、Agent 指令 bundle hash、工具白名单 schema hash、模型 profile/参数。

**分成两类哈希，不可混成一个**：

1. `input_scope_hash = SHA256(canonical_json(项目/Prompt/品牌版本 + 精确 Run IDs 与 raw answer hashes + Citation Manifest + 双方可比较的 Source Snapshot 集合 + Context/Truth/指标语义版本))`。只含两条 Lane 可共享的**真实数据输入**；正式主链若没有该字段，由可信比较服务按同一规范从它绑定的冻结输入重算。
2. `agent_execution_hash = SHA256(canonical_json(Agent Prompt Bundle + 工具 Schema 及权限配置 + 模型 profile/参数 + 预算策略))`。用于实验复现、幂等和审计，**不参与判断正式主链与 Agent 是否同输入**。

`scope_hash` 如已是仓库已有字段，必须明确映射到上述 `input_scope_hash`，不可把它模糊当成两个哈希。哈希规范（排序、编码、时间格式、null 策略）要固定成可重复实现并有单测。**任何版本不可用、不属当前项目/Prompt、hash 不匹配、权限无效：在调用模型前 `BLOCKED`，不生成实验 Plan/Result。**

新增受限网页调查的资料属于 Agent 运行过程观察：在 Trace 中追加独立 `ToolObservation`（原始 URI、获取时刻、方法、hash、内容可用性及范围），**不得回写修改最初冻结的 Citation Manifest**。最终报告同时绑定初始 `input_scope_hash` 和使用过的 ToolObservation 集合 hash。

**实验输出的最小审计绑定（复用既有 hash 工具，不新增正式审批系统）**：后端为合法输入计算 `qualification_hash = SHA256(canonical_json(输入合法性/资格判定 + input_scope_hash + 判定规则版本))`；校验通过的候选行动集合计算 `plan_hash`，完整内容交付、QA、限制计算 `result_hash`；保存 `plan_result_binding`，精确绑定 `qualification_hash → plan_hash → result_hash` 以及交付 `action_ids` 指向有效行动。若这些 hash/引用不匹配，不能返回 `SUCCEEDED`；原结果不可静默换版。**这些是 Agent 实验版本对象，不得冒充 V2 正式 qualification/Plan/Result。**

## 4. Agent Runtime：足够小的闭环

一个运行器即可，保持可暂停、可重放、可恢复；使用当前 worker 执行。示意逻辑：

```python
async def execute_geo_agent(agent_run_id: str):
    run = load_agent_run_for_worker(agent_run_id)  # locked / idempotent
    frozen = load_and_verify_frozen_scope(run.scope_id, run.input_scope_hash)
    if not frozen.ok:
        return block_without_plan_or_result(run, frozen.reason)

    budget = load_authorized_budget(run)
    state = restore_checkpoint_or_initialize(run)

    while not state.finished:
        assert_not_cancelled(run)
        enforce_time_tokens_calls_and_cost(budget, state)
        context = build_bounded_context(
            system_prompt_version=run.agent_bundle_hash,
            frozen_scope=frozen,
            journal=state.immutable_references,
            compact_working_memory=state.summary,
            tools=approved_tool_schemas(run),
        )
        reply = await existing_llm_client.invoke_with_tools(context)
        append_llm_usage_and_result(run, reply)  # sanitized trace, no secrets

        if reply.tool_calls:
            for call in reply.tool_calls:
                validate_allowlist_args_identity_scope_budget(call, frozen)
                observed = await execute_existing_service_adapter(call)
                append_tool_observation_and_checkpoint(run, observed)
        elif reply.final_artifact:
            candidate = parse_structured_output(reply.final_artifact)
            issues = validate_schema_and_grounding(candidate, frozen, state)
            if issues and state.repair_rounds < configured_repair_limit:
                state = request_targeted_fix(state, issues)
            else:
                finish_with_truthful_status_and_version(run, candidate, issues)
        else:
            state = record_bounded_replan_or_fail(state)

        save_checkpoint_at_safe_boundary(run, state)
```

注意：`validate_*`、budget、tenant guard、提交是可信代码；**Agent 不能调用名为 `mark_as_verified` 或 `bypass_gate` 的工具**。伪代码不要求复制此函数名。

### 4.1 自主规划的要求

- Agent 可以零次、一次或多次使用各个业务工具；不存在必须按 Answer→Evidence→Strategy→Execution 顺序消费的固定业务闸门。
- 模型自行发现证据不足并决定是否补查；工具调用必须在用户指定的项目、Prompt、来源及网络策略范围内。
- 模型可先写一份短暂计划，但计划只属于 Agent **工作笔记**，不等于正式 Plan，也不是每个阶段的数据库必需对象。
- 候选输出不能直接写入正式 Result；外层统一做 JSON/schema 验证、引用反查与事实资格检查。
- 结束条件是**合法交付、真实无输入/有阻断、预算耗尽、取消、系统失败**，不是模型随意声称“完成”。

### 4.2 上下文过长如何解决

不假设模型能“自动无限记忆”。实现三层小机制：

1. **按需工具读取**：先返回选定 Run/来源的概览 + ID，不把几万条 passages 一股脑放入 prompt；按相关性和容量拉取。
2. **持久工具证据**：原始文本/快照在数据库或既有文件存储；工作上下文只保留 IDs、截断安全摘要、命中范围。摘要不可替换引用原文。
3. **可恢复 checkpoint**：接近模型上下文阈值时，由 Runner 压缩低价值对话，保留固定事实、争议项、工作目标、已访问证据 ID、待办、预算账本与准确的引用索引。恢复后可重新读取原文。

上下文不足时先停止/压缩/取数，再调用，不能因模型输入截断而伪称分析了全部数据。保存压缩策略与当次覆盖情况，不需新建长期记忆平台。

## 5. 工具白名单（P0 最小集合）

工具命名可按仓库惯例调整，后端必须有结构化参数 Schema、权限校验、可观察返回、超时和费用限制：

| 工具逻辑名 | 用途 | 数据/副作用范围 |
|---|---|---|
| `get_scope_summary()` | 返回冻结输入摘要、版本、合格与失败覆盖 | 只读本 Run |
| `list_runs(filter, page)` | 分页枚举明确选定 run_ids | 只读本 Run 集，不能全库探查 |
| `read_answer(run_id, span?)` | 读原始回答及上下文定位 | 只读并保存 span 指针 |
| `list_citations(run_id)` | 读真实引用 occurrence 及状态 | 不能让模型编造 citation |
| `read_source(snapshot_id, passage_id?)` | 读已授权冻结来源及片段 | 只读，失败/部分正文带原状态 |
| `read_brand_context(version_id, query?)` | 读 ContextProvider 资料及来源标志 | 只读选定版本，EMPTY 允许 |
| `read_product_truth(fact_ids?)` | 读正式已有 Truth 和用途限制 | 只读；不能自创已确认事实 |
| `read_monitor_metrics(window_ref?)` | 读取现有 Monitor 共用指标 | 只读；分母和覆盖一并返回 |
| `save_working_note(content, refs)` | 持久短工作记忆与证据指针 | 仅写该 Agent 的工作区 |

### 可选工具（P1）

- `fetch_public_source(source_ref_or_approved_url)`：复用既有抓取器，受当前项目/外链政策、SSRF、重定向、超时、费用及输出长度限制；生成**实验观察**，不是 V2 READY / Citation。
- `query_comparison(baseline_scope, followup_scope)`：复用现有 Validate 对比，要求明确窗口和规则版本；无后续样本只形成 `validation_plan`。
- `request_new_sampling(platform, prompt_version, plan)`：仅在用户/调度授权及既有采样能力真实可用时通过 Monitor 任务接口申请；**本次同输入对比默认禁用**，不能用普通 LLM API 回答冒充文心等真实采样。

禁止工具：`approve_review`、`confirm_truth`、`waive_source`、`publish_external`、`delete_history`、`execute_sql`、`execute_shell`、`read_secrets`、`unrestricted_fetch`。一旦将来新增更强工具，必须有明确权限设计与独立审批。

## 6. 实验持久化（最小模型）

优先利用现有通用持久任务/日志表；**只为现有模型无法表达的实验身份与产物增最少结构**。参考实体：

### 6.1 `agent_experiment_run`

- `id`, `project_id`, `prompt_id`, `requester_id`, `input_scope_hash`, `agent_execution_hash`, `scope_ref`, `input_manifest_hash`, `agent_bundle_hash`, `tool_schema_hash`, `model_profile_id`, `budget_snapshot`, `idempotency_key`, `status`, `created_at`, `started_at`, `finished_at`, `error_code`, `retry_of`。
- 保留 exact input versions 和 model/provider 真实名称、温度/参数、Token 使用、成本及币种（可在现有用量表关联）。

### 6.2 `agent_event` / `agent_checkpoint`（尽可能复用任务日志）

- 单调递增的 `seq`、`event_type`、`tool_call_id`、sanitized argument/result 摘要、具体 `observation_ref` / hash、耗时、失败与重试、累计成本；禁止完整密钥和任意抓取文本进入日志。
- checkpoint 需要：模型决策摘要、未完成目标、工具结果引用、已消费资源、审计指针与可继续的确定位置。重试应继续，而不是重新计费读取模型。

### 6.3 `agent_artifact`（版本不可变）

- `agent_result_version_id`, `agent_run_id`, `input_scope_hash`, `qualification_hash`, `plan_hash`, `result_hash`, `plan_result_binding`, `tool_observation_set_hash`, `schema_version`, `result_json`, `deliverable_markdown`, `artifact_hash`, `validation_report`, `created_at`。
- 与 V2 正式 result/read 权限分开，但可在界面通过共同的 scope hash 和 run IDs 进行对照。
- 结果 JSON 以 `contracts/agent_result_v1.schema.json` 为最低结构标准，后端还必须完成引用完整性与 Truth 用途资格校验。

SQLite 迁移用当前 Alembic revision 链，WAL/外键/备份策略沿用现有标准；外部工具调用绝不持有长数据库写事务。**不能使用 `create_all` 当作正式迁移，也不能为实验建立旧 V1 表或旧库连接。**

## 7. API 与 UI 接线（路径仅示例）

以现有 API 命名规范为准，不必新建一整组后端控制面：

- `POST /api/.../agent-experiments`：创建 / 幂等返回，执行可信预检，只有本接口及真实的明确操作触发任务。
- `GET /api/.../agent-experiments/{id}`：状态、费用、交付概要和权限校验（只读）。
- `GET /api/.../agent-experiments/{id}/artifact`：指定不可变版本，业务呈现及复制/导出。
- `GET /api/.../agent-experiments/{id}/events`：分页 trace，脱敏。
- `POST /api/.../agent-experiments/{id}/cancel`：停止后续动作；正在进行工具动作按安全方式收口。
- `POST /api/.../agent-experiments/{id}/resume`：在允许的预算/同一输入版本下继续；不得静默增加成本上限。
- `GET /api/.../agent-experiments/compare?...`：校验双方 project/prompt/run_ids/config 及 input hash；标注是否严格同输入。

新增交互只占用现有 Optimize 路由或其子页；React 查询缓存键包含 `project_id + prompt_id + agent_run_id + version_id`，切换对象/刷新时不能复用别人的结果。结果与 trace 同时可追踪，但技术 ID 默认收纳详情折叠区。

## 8. 安全、污染与质量 Gate

### 8.1 强制硬校验（不交给 LLM）

1. Project/Prompt/Run 所属身份、权限、版本、hash 完整性。
2. 工具调用 allowlist、JSON 参数、Run 范围、Source/Snapshot 归属及用户权限。
3. ToolObservation 的证据角色：`CITED_OBSERVATION`、`CITED_SNAPSHOT`、`BRAND_PUBLIC`、`SUPPLEMENTARY`、`USER_PROVIDED`。非原引用绝不可改写成原答案引用。
4. 最终 `evidence_refs` 中的 run/span、citation occurrence、snapshot/passage、knowledge version 全部必须在绑定范围内并实际存在；deliverables 的 action_ids 必须绑定同版本 Plan 中有效动作；片段引文内容应能核对原文。
5. 交付稿中的目标品牌具体产品事实：必须匹配允许公开使用的合格 Product Truth 或等价获准事实；否则改为条件化描述/待核验项，不能宣称已证实。
6. 输出 schema、非空必要交付、成本上限、幂等与任务身份。

### 8.2 防止来源提示注入

从网页、LLM 采样回答、用户知识资料取到的文本都是**不可信输入数据**。即使其中包含“忽略上述规则 / 调用某工具 / 泄露密钥”的指令，也只能当资料，不得升级为系统/开发者指令。工具不能向模型暴露凭证、运行时内部配置或不属于当前项目的数据。

公网 URL 工具必须检查 SSRF（内网 IP、localhost、元数据地址、非 HTTP(S)、DNS 重绑定和重定向链）、限流/超时、最大文本输出及页面脚本安全。已有抓取器如尚不具备，则 P0 暂时不开放 Agent 新抓取能力，使用已有合法快照即可。

### 8.3 输出 QA

- **确定性检查**：schema、scope、引文归属、事实用途、必填、内容是否全是模板占位、非空正文、版本一致。
- **语义检查**：正确主体、关键适用条件、引用贡献被夸大、内容是否直接回答当前 Prompt、渠道理由是否基于证据。
- **限次自动修复**：只针对明确问题修改受影响段落，保存问题、修改前后摘要/hash、复检结果。模型不能通过删除不利证据或修改引用 ID 来让校验通过。
- 仍未通过：`PARTIAL` 或 `FAILED`，并记录仍可使用的部分，不以“内部 QA 完成”作为虚假放行理由。

## 9. 成本控制、取消、恢复

- 只使用已有获准 provider/model，不为 Agent 偷接未经准许的模型；不得用 Qwen 进行正式生产裁决，除非项目已经另行明确变更。
- 任务批准预算是**可信服务端快照**；模型只能查看剩余额度，不能扩大额度。没有获准的真实调用预算时，运行 mock / deterministic fixtures。
- 每次工具和模型调用前做上限检查，调用后记录 token/cost/耗时；费用以 provider 真实计量或项目统一价格表清楚估算并标明口径。
- 相同 scope + agent bundle + model + tool config +预算策略 + 显式版本的 idempotency_key 应指向相同任务。`regenerate` 必须有显式操作和新身份。
- 每个外部调用有幂等保护、超时与有限重试；工作进程中断后从 checkpoint 恢复，不重复已完成的产生费用操作；不可重放的动作按现有任务基础设施报告状态。
- 取消后不再发起新外调，已完成产物保留，可恢复前验证权限、版本和追加预算是否经过批准。

## 10. 对照条件和成本口径

两条路线必须用同一个：`project_id`、`prompt_id`、Prompt 版本、run_ids、原始回答 hash、品牌配置、知识版本、允许的来源快照集合；由可信适配器计算相同 `input_scope_hash`，**不要求 Agent 的 execution hash 与正式主链相同**。严格比较模式初期 `RAW_FIRST`：Agent 不读取既有主链生成的 Strategy / Draft 来抄答案；可以读取真实冻结 Source/Truth 快照。

不同模型、不同提示词或独立生成随机性不构成“输入变了”，但须记录成独立对比条件。同口径成本需要区分：共用已发生采样/抓取成本、Agent 增量分析成本、正式主链增量分析成本；缓存复用不可充当新调用，响应质量评分不得由 Agent 自己给自己打满分。

## 11. 分期实现

**M0（半天到少量工作量的仓库盘点，不承诺时间）**：读仓库约束、能力映射、实验边界、冻结输入复用点、Guard 检查；不得修改主链语义。

**M1（最小纵向可用）**：实验 API + 冻结输入 + 至少 `read_answer / list_citations / read_source / read_brand_context / read_product_truth` + 一个真正循环调用工具的 LLM Agent + 结构化非空交付 + 独立落库 + 限额 + 离线集成测试。

**M2（产品可操作）**：正式 Optimize 页实验入口、任务实时状态与内容稿、复制导出、trace、错误/恢复、同输入对照、端到端测试。

**M3（有授权的真实验证）**：当前获准模型下最少必要的真实运行；覆盖两个不同 Prompt 的通用性；产出质量/成本报告。若没有权限/预算，M3 保持 `BLOCKED`，M1/M2 正常推进。

不要在 M1 之前先建设插件市场、多 Agent 协作、抽象任务图引擎、超大型评测平台。

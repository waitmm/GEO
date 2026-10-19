# GEO Agent V1：现有 GEO 平台中的独立实验线路

> 版本：2026-10-19 / Draft for implementation  
> 目标读者：拥有真实 `geo-platform` 仓库访问权限的 Codex / 开发负责人  
> 交付性质：**实现需求与验收基准，不代表代码已经实现、测试已经通过或获得外部调用授权**。

## 先说结论

在现有 GEO 项目中新增 `Agent (Experiment)`：**同一个项目、同一个 Prompt、同一批冻结的 Run 输入，分别走既有 Optimize 主链和新的 Agent 路线**。Agent 自主决定如何分析、补充证据、制定策略、组织稿件、修复 QA；用已有采样/来源/资料/指标工具执行；结果独立落库，能够并排对比实际质量、费用和耗时。

**本轮不是重写 GEO 平台、不是接入一套通用 Agent 产品，也不是把原来的各个步骤逐个包装成 Agent 节点。** 要检验的假设是：在可信数据工具和约束不变时，一个自主规划的 Agent 是否可以用更少的固定业务编排实现同等或更好的 GEO 实际交付。

## 唯一推荐实施方式

1. 保留现有 V2 正式主链与 Monitor / Optimize / Validate 的既有业务所有权。
2. 新增独立 `AgentExperimentRun` / `AgentArtifact` 命名空间；不能将 Agent 输出假冒原主链的 `ResultVersion`、`Evidence READY`、Review 或官方状态。
3. 复用现有冻结 Run、引用观察、来源快照、ContextProvider、Truth、模型客户端、成本账本及权限工具；通过范围受限 DTO / service 接口适配。
4. 新增一个**有工具调用循环的轻量 Agent Runner**，而非第二套大而全 Workflow / Runtime。
5. UI 放在现有 Optimize 页面下的实验入口；有完整交付、调用记录、费用和与正式主链的对照。
6. 初次对比使用完全相同的 Run IDs 与输入版本，默认不主动新增采样；真实平台采样仍由现有 Monitor 完成。后续变化验证复用现有 Validate，而不强制依赖发布。

## 文件说明（按照顺序阅读）

| 文件 | 用途 |
|---|---|
| `01_PRODUCT_REQUIREMENTS.md` | 产品目标、范围、操作流程、交付件、UI、状态及业务规则 |
| `02_ENGINEERING_DESIGN.md` | 接线、Agent 循环、工具契约、数据隔离、预算与安全 |
| `03_AGENT_OPERATING_CONTRACT.md` | Agent 决策权与不可突破的业务不变量、证据资格、上下文管理 |
| `04_ACCEPTANCE_AND_COMPARISON.md` | 功能/负向/真实测试、A/B 对照、通过门槛 |
| `05_CODEX_IMPLEMENTATION_ORDER.md` | Codex 直接执行指令、实施顺序、提交与回报要求 |
| `agent/AGENT_SYSTEM.md` | Agent 运行时系统指令参考；放在专用配置位置，**不要覆盖仓库根 AGENTS.md** |
| `agent/GEO_PLAYBOOK.md` | GEO 分析决策指引（非固定执行步骤） |
| `agent/DELIVERY_QA.md` | 交付件和 QA 行为规范 |
| `contracts/agent_result_v1.schema.json` | Agent 结果的最小机器可校验结构（须加后端跨引用校验） |
| `config/geo_agent.example.yaml` | 实验配置示例；默认关闭外部调用 |
| `examples/agent_request.fixture.json` | 隔离测试用途的请求形状示例，**不是可直接运行的真实 ID** |
| `PASTE_TO_CODEX.md` | 将文档包放入真实仓库后，可直接复制给 Codex 的起始指令 |
| `ALL_IN_ONE_FOR_CODEX.md` | 以上主要说明的合订版，适合只上传一个 MD 文件 |

## 项目既有约束及优先级

- 以真实仓库当前 `AGENTS.md`、代码、数据库迁移、已冻结需求和变更守卫为准。此前文档不构成“实际已实现”的证据。
- 2026-10-09 的 GEO 1.0 交付边界：Monitor 持续采样；Optimize 自动完成诊断/策略/可用稿件；Validate 比较样本变化；人工审核、资料输入和发布登记不得一律成为交付前置。
- V2 仍是**正式** orchestration / persistence / review / UI truth；老 V1/V1.1 仅可通过有效 DTO 复用计算内核。Agent 试验结果是独立实验数据，不授予正式结果身份。
- 正确采样与历史版本不得丢失；错误派生产物可精确废弃重算，不为坏历史添加永久兼容路径。
- `Semantic Change Guard` 若阻止修改正式契约，**不得绕过**。实验代码应使用独立对象与接口，不偷改被保护的 L1/L3/L4 或正式 Gate。
- 任何文中路径、技术栈细节和既有能力实现情况，Codex 必须通过真实仓库核实；不得为了匹配文档而虚构实现。

## 成功判定一句话

**在有合法有效答案的情况下，选择相同冻结 Run 范围，点击一次启动 Agent，自动生成可核查、有针对性的 GEO 诊断 + 行动 + 至少一份具体内容交付 + QA；明确记录不确定性与成本，且不影响 V2 既有结果；能与同范围正式工作流对比。**

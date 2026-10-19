# 可直接复制给 Codex 的执行指令

请在我当前的 GEO 平台**真实仓库**中实施一个独立的 `GEO Agent Experiment V1` 线路，复用现有项目、Prompt、Run、引用、来源快照、ContextProvider、Product Truth、已有模型服务、任务执行基础设施以及 Monitor/Validate 指标。

完整冻结需求、技术方案和验收契约已放在 `GEO_Agent_Parallel_Experiment_V1_2026-10-19/` 目录。**按 `00_START_HERE.md` → `01_PRODUCT_REQUIREMENTS.md` → `02_ENGINEERING_DESIGN.md` → `03_AGENT_OPERATING_CONTRACT.md` → `04_ACCEPTANCE_AND_COMPARISON.md` → `05_CODEX_IMPLEMENTATION_ORDER.md` 顺序读取，再使用 `agent/*.md` 作为运行时 Agent 指令。** 如果我只提供 `ALL_IN_ONE_FOR_CODEX.md`，则直接以合订版为依据，不需要重新生成需求文档。

这次不是重建 GEO，也不是改掉现有 V2 正式主链。请在现有 Optimize 中新增独立实验入口和实验数据命名空间，以**同一个 Prompt、同一批明确 run_ids 和冻结输入**同时支持原 Workflow 与新 Agent 对照。新 Agent 是真 Agent：通过模型决定后续工具调用、按需补证据、分析、生成方案和稿件、自检与修订；**不是把旧 Step 1-8 固定 API 顺序改名为 Agent**。

强制保证：

1. 复用现有成熟采样/抓取/知识/Truth/指标与模型客户端；只新增最小 Agent 工具适配与运行循环，不建第二套 Runtime、采样或复杂工作流。
2. 原 V2 的 Analysis/ResultVersion/Review/Truth/正式 Gate 完全独立且不被覆盖；Agent 结果只以 `AgentExperimentRun/AgentResultVersion` 落库。遵守 Semantic Change Guard，不能因实验绕过受保护契约。
3. Project/Prompt/Run/版本/hash/权限由服务端冻结并逐次校验；身份错先 BLOCKED 且零模型调用、零 Plan/Result。未知/失败/合法零分开；真实引用与后取资料分开。
4. 知识库 EMPTY、0 引用、品牌未提及或部分来源不可读时，如有有效答案，Agent 必须尽可能给出**证据限定、当前问题相关的具体诊断、行动、完整稿件、QA 和复测方案**，不制造成功空稿；没有效答案则 NEEDS_INPUT，不造假。
5. 严格工具白名单、预算/调用/Token/时间上限、任务幂等、checkpoint、有限修复、可取消。模型无自行批准 Truth/Review/WAIVE、写正式库、执行 shell/SQL、发布或查看密钥权限。
6. 在原 Optimize 页面完成 Agent 入口、结果、费用、trace、复制/导出和同输入对照；GET 只读；前端项目切换不串数据。
7. 执行离线/API/数据库/浏览器/正式主链回归验收；实际调用外部模型/采样/网页抓取前必须确认项目已有授权与预算，未获授权时跳过这部分真实调用并明确 BLOCKED，其余开发照常完成。

**立即开始编码，而不是只回复方案。** 先核查 git status、AGENTS.md、近期提交与现有实现，并在保护未提交改动的前提下使用独立分支/worktree。先完成 `冻结输入 → 工具 → 真正的 Agent 多轮循环 → 输出验证 → 独立持久化` 最小纵向切片，再接 UI 与对照，最后跑验收。普通实施细节自行选择并持续推进；报告实际完成的位置、SHA、命令、测试结果、真实/模拟调用费用与精确阻塞，不将文档、build 或一个 mock 样例当产品交付。

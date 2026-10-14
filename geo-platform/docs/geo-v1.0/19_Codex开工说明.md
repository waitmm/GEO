# Codex 开工与单任务执行说明

## 2026-10-14 单层官方沙箱修复

本节是当前执行隔离约定，替代下文历史记录中的额外 `agent.sb`/`gate.sb` 包裹；不改变模型、任务、预算、权限目标或产品范围。分类 `IMPLEMENTATION_CHANGE`，仅 T25 开发工具。调度器必须从普通宿主 Terminal 启动，不从另一个 Codex 沙箱内启动。

- Codex 子进程直接启动，工具由官方 Permission Profile `geo-relay` 隔离，不再外包 `sandbox-exec`。本地验收命令单独通过 `codex sandbox -P geo-relay --include-managed-config` 运行，仍是单层。
- 配置固定 `gpt-5.6-sol / medium / default / approval_policy=never`、`default_permissions=geo-relay`；MCP/Hook 继承检查及 multi_agent/goals/apps/plugins/web_search 禁用检查保留。不修改用户级或 IDE 配置。
- Profile 继承 `:workspace`，`:root=deny`、`:minimal=read`、`:slash_tmp=deny`。工作树和唯一 scratch 可写，`TMPDIR` 也固定到该 scratch。Git 元数据、共享依赖、当前 Python 系统运行库只读；用户 `.codex/.ssh/.aws/.config` 不可读。工作树内环境文件、数据库、PEM、auth.json 的 deny glob 覆盖后创建文件；工具网络 `enabled=false`，本轮连隔离测试端口也不自动放行。
- Codex 宿主客户端仍需读取自己的登录状态和连接模型服务，这不是工具网络授权。模型不得通过工具读取宿主登录文件。当前没有发起该模型服务连接验证。
- **不能混用旧模式**：不传 `--sandbox`，不设置 `sandbox_mode`/`sandbox_workspace_write`；只读 `config/read` 若发现任何旧模式或权限表不一致，停止而不降级。官方[Permission Profiles](https://learn.chatgpt.com/docs/permissions)明确说明旧模式会覆盖新配置。路径表通过一整张 TOML 表传入，避免 CLI dotted-key 拆坏包含点或 glob 的路径。
- 批次保存 `permissions.json` 和 `effective-permissions.json`。无模型离线检查跳过 model/list；未来真实运行仍须核查目录且无自动模型替换。账户请求成功、服务档位实际计费与节省效果仍未验证。

### 本轮安全与回归证据

`backend/artifacts/acceptance/codex-single-sandbox-20261014/probe-07/report.json`：macOS 宿主上的真实 CLI 0.162.1，11项探针通过，0 exec / 0模型调用。覆盖工作树读写、scratch SQLite、模拟生产密钥/数据库拒读、SQLite只读打开拒绝、软链接绕行拒绝、Git元数据只读、后创建环境文件拒写、回环网络 EPERM/EACCES。宿主先连接同一监听端口成功，排除“端口没开”的假阳性。只使用假秘密和假数据库，没有读取真实生产凭证/数据库。

早期 probe-01..06 保留为修复证据：先修正权限表路径序列化及 CLI 返回的未设置 null 字段，再增加 Python 系统运行库的精确只读路径，最后消除 TMPDIR 与 scratch 同路径 deny/write 冲突。运行库未加载导致的异常不算安全负例通过。没有通过放宽 root、网络、凭证或生产路径访问取得成功。

专项及原 harness 回归共 **80 passed，0 failed，0 skipped**，见同目录 `regression-final.xml`；包含71项接力测试和9项原harness检查。这些是工具工程验收，不是 GEO 产品或真实接力任务验收。原模型、阈值、重试、CAS集成、receipt和整组终止逻辑保留；`main` 不修改。

### 启动与停机条件

```bash
cd /Users/bmwqr/Desktop/python/GEO
# 默认预演，仍仅原 T25 文档单元；不启动任何 Codex 进程。
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_relay.py --max-tasks 1 --max-repairs 0 --session-seconds 600 --token-threshold 30000 --codex /Users/bmwqr/.local/bin/codex
# 宿主 Terminal 离线重验；输出目录必须全新，不覆盖已有证据。
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_isolation_probe.py --codex /Users/bmwqr/.local/bin/codex --output /private/tmp/geo-single-sandbox-new-check
```

**当前真实启动仍被未复核 receipt 阻止。** 本轮发现后续失败批次 `20261013T222348-732b92c4`：exec启动后0.131秒失败、空JSONL、`accounting_complete=false`。其receipt、报告、旧沙箱文件和未知用量原样保留；没有自动归档、清零或 `--resume`。本轮没有授权再执行一批，也没有改任务排队状态。dry-run的1项不代表receipt已解除。

下面仅为**后续复核旧批次并明确批准新批次后**的单任务真实冒烟命令；本轮不执行，现在直接执行会被receipt保护拒绝。须确保控制器工作树干净，修复提交已快进到 `codex/geo-integration`，且integration未被检出。禁止删除receipt绕过复核，禁止合并main。

```bash
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_relay.py --execute --max-tasks 1 --max-repairs 0 --session-seconds 600 --token-threshold 30000 --codex /Users/bmwqr/.local/bin/codex
```

## 2026-10-13 有界接力入口（优先于旧的无限续跑描述）

历史准备记录：`TERMINAL-SMOKE-20261013-01` 是用户当时授权的独立Terminal批次，后续已失败并保留receipt，以2026-10-14节为准。以下保留当时过程，不是当前可重试授权。原任务和未知用量不改；新单元 `T25-RELAY-USAGE-SMOKE-TERMINAL-01` 仅复用原T25文档目标、文件范围与Gate。指定独立CLI `/Users/bmwqr/.local/bin/codex`，仍为5.6-sol/medium/default、1任务/0修复/600秒/30000软阈值。

### 新Terminal批次与读取基线

- 调度器通过脚本文件位置计算ROOT，再读取该工作树的 `tasks.json`，不是按shell当前目录寻找台账，也不是直接读取integration分支。当前控制器分支为 `codex/relay-smoke-prep`；执行代码工作树仍从 `codex/geo-integration` 创建，准备提交需先快进到integration。
- `live_execution_authorized_this_round=false` 保留，因为本轮代理不得执行真实调用；当前选择器不检查此元数据，旧空队列的直接原因是BLOCKED。新批次的Terminal授权和固定参数单独记在同一台账的 `terminal_smoke_batch`，并未更改调度器。
- 原单元保持BLOCKED；原报告的 `accounting_complete=false` 与UNKNOWN用量不改。原活动receipt逐字节保存在旧批次目录 `retained-receipt-before-terminal-batch.json`，并保存复核记录；它不是已验收、已结算或可resume状态。新30000只是新授权的会话后软阈值；历史总量仍UNKNOWN，不能宣称累计余额已重置。
- 本机终端只运行下述新批次命令，不加 `--resume`，不恢复产品任务。所有旧沙箱和权限校验保留；本轮不验证CLI真实配置、模型可用性、额度或EPERM是否解决。
- 准备验证：从 `/private/tmp` 调用仓库脚本，dry-run仍读取控制器工作树台账，恰好返回1个新单元、max_sessions=1、external_calls=0。5项定向测试通过、55项未选（不是全量重跑）。原任务、验收条件、旧报告与归档receipt逐字节校验不变。证据：`backend/artifacts/acceptance/codex-relay-terminal-prep-20261013/`。独立CLI链接指向0.162.1发布目录，仅核实文件存在与可执行属性，没有启动CLI。

```bash
cd /Users/bmwqr/Desktop/python/GEO
# 先核对输出为 codex/relay-smoke-prep，且 git status --short 为空。
git branch --show-current
git status --short
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_relay.py --max-tasks 1 --max-repairs 0 --session-seconds 600 --token-threshold 30000 --codex /Users/bmwqr/.local/bin/codex
# 仅在本机Terminal执行；本轮代理不会执行下一行。
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_relay.py --execute --max-tasks 1 --max-repairs 0 --session-seconds 600 --token-threshold 30000 --codex /Users/bmwqr/.local/bin/codex
```

此前一轮只交付开发工具，挂现有 T25，未运行真实 `codex exec`。产品仍 INCOMPLETE。正常研发从本文件和 `tasks.json` 当前检查点恢复，不把整段聊天或历史开发日志不断搬进每次任务。AGENTS 的必读契约及权限约束不减少；用目录/标题检索定位相关段落，避免反复输出整个历史日志。

入口：`backend/scripts/delivery_codex_relay.py`；专项：`backend/tests/test_delivery_codex_relay.py`，由既有 delivery harness 的 `test_delivery*.py` 自动发现。没有引入新调度服务或第二套产品任务台账。小任务写入原 `tasks.json.codex_relay.units`，必须绑定现有 `task_id`、`requirements`、依赖、精确允许修改文件、外部验收命令和不可改的预期文件。当前只登记一个文档用量说明任务，原离线空队列证据保留。

### 核心执行流程

1. 默认仅预演，输出队列、配置和预算，不启动任何 Codex 进程，不建工作树、不修改 Git。
2. 显式执行前要求工作区干净；单实例文件锁；上一批 receipt 未处理则不能偷偷重跑。默认1项、最多3项；每项最多初次执行加2次定向修复。
3. 唯一连续基线为 `codex/geo-integration`。从该分支创建隔离工作树；每项通过独立 Gate 后由控制器提交、CAS 快进 integration。后项必须以此前已集成的提交启动。禁止自动合并/推送主分支，也禁止代理自行提交。integration 被检出或被外部移动时停止。
4. 每次独立 `codex exec` 显式覆盖为 `gpt-5.6-sol / medium / default`，关闭多 Agent、goals、apps、plugins 和 shell 外网；审批为 never，使用单层 `geo-relay` Permission Profile。不改全局配置，不跳过已有安全规则，不授权 GEO 业务外调。CLI协议规定default为标准速度，目录中的serviceTiers可能只列额外加速档，不据此否认标准档；实际请求结果单独验证。
5. 首次模型执行前用只读 `app-server` 的 initialize/config-read/model-list 核验实际配置与可用模型；无 thread/start 或 turn/start。High、Priority、模型不可用、启用的外部 MCP/Hook 或隔离失败都停止，不偷偷降级模型或绕过权限。本轮该协议由本地 Mock 验证，不代表账户已确认可用 Sol。
6. 工作树不复制 `.env`、业务 DB、账号 profile。环境清除继承的业务凭证，使用隔离 SQLite、scratch、临时端口和 offline 标记。官方单层 Profile 拒绝工具读取生产数据、凭证和未授权路径，工具网络默认全部关闭，依赖目录只读复用。不再给Codex宿主进程外套Seatbelt。无可用隔离机制就拒绝执行，不支持无保护降级。
7. 冻结队列及验收预期；变更超白名单、修改 Gate 预期、HEAD 异常、无用量、进程失败或超时立即停止。只有正常模型结束且 Gate 失败才允许有限修复。子进程结束/超时/中断均清理整个进程组，包括忽略 TERM 的后代。
8. 原子保存每次调用前、用量后、Gate 后和 integration 更新前后的检查点。恢复不重置预算/重试；已验收任务不重复执行；模型已结束而 Gate 中断只重跑本地 Gate；integration 已更新但状态未落盘时补记账。调用中断且用量不明必须人工核对，不能自动再调用。

### 用量口径与边界

- 活动量 = `input_tokens + output_tokens`；cached 是 input 子项，reasoning 是 output 子项，均不再相加。缺 reasoning 字段允许；缺必要用量则 UNKNOWN 并停机。
- 默认批次活动量停止阈值100,000，单会话15分钟（可设置1..1800秒）。这是**会话结束后阈值**，不是单次请求硬上限；JSONL 用量无法保证中途准确限额，超时断连也不能保证远端立即停止计费。
- JSONL、stderr、Gate 日志、耗时、提交和检查点保存在忽略目录 `backend/artifacts/codex_usage/`；不记录密钥，也不将活动 Token 换算为 ChatGPT 套餐额度或宣称节省比例。
- Gate 通过仅表示该小任务的程序化检查通过，不自动将 T25 或产品标记 DONE。集成分支供后续任务复用，主分支合并及产品验收仍独立。

### 命令（从仓库根目录）

```bash
# 安全预演；本次曾选中1项，当前已阻塞故返回0项；不会启动模型。
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_relay.py --max-tasks 1 --max-repairs 0 --session-seconds 600 --token-threshold 30000

# 离线专项，不调用真实 Codex。
cd geo-platform/backend
.venv/bin/python -m pytest tests/test_delivery_codex_relay.py tests/test_delivery_acceptance.py -q
```

本次5.6 Sol实际执行过的入口（已停止，不要直接重试）；准备提交和 integration 在调用前固定，运行环境为允许创建子沙箱的本机终端：

```bash
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_relay.py --execute --max-tasks 1 --max-repairs 0 --session-seconds 600 --token-threshold 30000
```

同一批恢复须显式加 `--resume` 且预算参数完全一致；先审查停机原因，用量不明不能再调用。新批次必须先核对并归档上一批 `unreviewed-batch.json`，将已验收单元在原台账标记 ACCEPTED，保留报告及提交。不得通过删 receipt、清零用量或重建工作树来自动绕开停机原因。本次只授权一批一项，完成或停止后均不自动开始下一批。

### 本轮证据与未验证事项

`backend/artifacts/acceptance/codex-relay-offline-20261013/`：本地 Mock/静态专项、既有 harness 回归、dry-run 和本地隔离探针。不包含真实 Codex Token 消耗、真实模型质量或 GEO 功能验收。macOS Mock 探针发现并修正 SBPL 的 localhost 地址语法，随后验证 Mock 生产文件不可读、未授权 Mock 端口不可连、隔离目录可写；没有访问真实生产数据。

本轮最终定向结果：65 passed，0 failed，0 skipped（其中接力专项56项、原 harness9项）。
`dry-run.json` 返回 DRY_RUN、空队列、max_sessions=0、external_calls=0；
`isolation-probe.json` 返回 exit_code=0、MOCK_ISOLATION_PASS。这里的零调用指测试未启动
真实 Codex 子会话，不代表当前人机对话本身没有消耗 Token。

当前 Codex 外层沙箱禁止嵌套 sandbox-exec，探针在独立受审查的本地进程执行；不能据此称当前嵌套运行已可用。实际账户模型可用性、真实 CLI 端到端及用量/质量收益依用户要求未测试。当前 IDE 会话和用户级配置没有被切换；以上覆盖只用于此入口创建的会话。

### 后续单次冒烟结果（2026-10-13）

- 准备提交 `51fbab0` 在独立 `codex/relay-smoke-prep`；integration 由 `5846acd` 快进至该提交。冒烟期间 main 始终为 `5846acd`，没有自动合并。
- 非空预演选中 `T25-RELAY-USAGE-SMOKE`，max_sessions=1，external_calls=0。文档 Gate 在修改前未通过，独立预期不是空跑。65项离线回归本次重新通过，28.82秒。
- 唯一 `--execute` 入口生成隔离工作树后停在配置预检：`Requested model/effort unavailable; never fall back automatically`。检查点 `attempts=[]`、`accepted={}`，真实 `codex exec` 子会话0次，文档未由子会话完成，没有子任务提交或集成。
- CLI `0.153.0` 的 `config/read` 接受 `gpt-6.1-sol / medium / default` 和原沙箱约束；`model/list` 包含 `gpt-5.6-sol`，不含 `gpt-6.1-sol`。后续只读元数据核查没有 thread/start、turn/start 或 exec。配置接受不等于服务端执行成功，目录返回也不证明不可列出的模型永远不可用；当前保守 Gate 不允许继续。
- 目录各模型的 `serviceTiers` 只列 `priority`。它可能仅列可选档位，因此不能断言标准档不存在；也不能把 `default` 的配置回显当作已验证的标准档位请求。本轮不改 Gate、不绕过隔离、不偷偷换模型。
- `backend/artifacts/acceptance/codex-relay-smoke-20261013/` 保存非空预演、原文档Gate失败和65项JUnit；`backend/artifacts/codex_usage/20261013T155241-e2186ed6/` 保存停止报告、隔离参数和非敏感配置目录审计。保留 `unreviewed-batch.json` 与工作树，单元 BLOCKED，不清零或自动再试。
- 四项真实验证：配置读取及不符停止有现场证据；真实模型请求档位、JSONL用量、子任务提交集成仍 NOT_RUN。报告中活动量0只因为未启动模型，不是节省额度的测量，更不是当前IDE对话免费。
- 收尾发现额外集成隐患：控制器创建的 `geo-platform/frontend/node_modules` 复用软链接出现在 Git 未跟踪列表，当前白名单检查会拒绝它。这不是模型修改，工作树没有 tracked diff；保留现场，不把离线测试覆盖称为实际集成通过。本轮未改调度器，后续首次重试前需局部处理。只读进程检查未发现本次 app-server/exec 残留；台账/harness复检9项通过，与65项有重叠、不相加。
- 下一步只需明确 CLI 可用的目标模型并核实其标准档位语义，再审查原receipt及冻结队列；不得直接 `--resume` 重置本次授权。GEO业务开发继续暂停，实际额度收益 NOT_MEASURED。

### Sol5.6 单次重试结果（2026-10-13）

- 用户明确选择5.6 Sol后，提交 `14ab455` 修复默认模型、标准档目录误判、精确依赖软链接忽略与指向保护。另修复文档Gate的转义错误，以独立正确/错误假设样例验证，不修改业务断言。69项离线通过，0失败、0跳过。
- 原 `20261013T155241-e2186ed6` 的0次exec预检receipt经核对归档在原目录，原报告与工作树不删。新批次 `20261013T171626-16900909` 为1任务、0修复、600秒、30,000软阈值；main未变，integration=`14ab455`。
- 新批次CLI预检确认 `gpt-5.6-sol / medium / default / never / workspace-write`，无High/Priority继承。**exec进程启动1次，但0.144秒即失败**：stderr为 `Error: Operation not permitted (os error 1)`，JSONL为空。没有正文变更、用量完成事件或子任务提交。
- `accounting_complete=false`，用量 **UNKNOWN**。报告里的初始活动量0不能当作实耗0；attempt保留RUNNING表示没有完成记账，不表示进程仍在运行。没有匹配的子进程残留，receipt保留、任务BLOCKED，不允许自动resume或再试。
- 无模型权限探针证明同一额外沙箱下版本/帮助/app-server启动与完整config/read成功；第一个提前关闭stdin的RPC探针无结果，未算通过。具体exec启动受限操作还未定位。这是本地运行兼容问题，不是已证明账户无权限或需要新业务凭证。
- 当前工作树Git干净，软链接不再误报，且离线改指向负例仍被拒绝。实际模型请求档位、真实JSONL记账、任务提交集成及节省效果仍未验证。下一步先无模型定位启动错误，保留双层保护；不以绕过沙箱换取成功。
- 证据：`backend/artifacts/acceptance/codex-relay-sol56-smoke-20261013/` 与 `backend/artifacts/codex_usage/20261013T171626-16900909/`。没有继续GEO功能开发或切换当前IDE会话模型。

## 正确开工方式

先把本包的 docs/geo-v1.0 纳入真实项目仓库。阅读仓库 AGENTS.md、现有产品/架构文档与当前未提交改动，再执行 T00。仓库中的代码现状需要验证；本包没有提供任何已经核实的真实接口、表结构或实现路径。

产品范围按 00_产品范围与交付基线.md；共用语义按 16_共用契约与状态.md；功能行为按各 PRD。后续实际代码设计应把业务要求映射到已有模块，不要按文档标题逐一创建新服务。

## 首条可直接使用的开工指令

请在当前 GEO 项目仓库执行 docs/geo-v1.0/18_项目管理与任务.md 中的 T00。先阅读 AGENTS.md、当前架构与运行说明，检查工作区改动，保留用户已有工作。

本轮产品范围已确定为 Monitor → Optimize → Validate。不要重新讨论顶层定位，也不要把这次任务执行成完整重写。

请逐项核查本包十五个功能 PRD，生成 docs/geo-v1.0/implementation-map.md：每项能力给出真实文件/函数或接口位置、现有输入输出、状态依赖、已有验证证据，并分类为“可直接复用、需接入、需修复、确实缺失”。如果有旧状态依赖，指出可以提取的窄显式入口；不能因为旧业务主链不保留，就丢掉已正确的计算能力。

同时核查实际运行环境、数据库和迁移、任务恢复、已有采样与模型配置、外部调用边界以及可用验证命令。不要输出密钥。此前历史描述只作查找线索，不能当作本次检查结果。

按真实差距更新 tasks.json 的实施位置、依赖和工作量；保留产品需求与验收编号。若现有任务已经满足，提供证据后标记，不再重复开发。不能把“文件存在”当作验收完成。

T00 完成后，继续处理依赖满足且属于既有授权范围的任务。每项任务提交具体改动与验证记录；遇到无法自行解决的真实阻断时说明精确对象及所需信息，其他不受影响任务继续推进。当前没有仓库访问时只报告缺失入口，不虚构核查结果。

## 单任务指令模板

执行任务 <task_id>。先读任务关联 PRD、需求与验收用例，以及 implementation-map 中对应现有能力。说明本次复用入口和最小改动范围，然后直接实现。

必须保持：显式 run_ids 与结果版本；非空针对性行动；无知识库/无人工审核仍可运行；事实限制局部生效；真实故障不冒充成功；GET 不触发业务写入；不串项目；生成稿资格绑定实际版本。

完成后报告：改了什么、为何需要、实际验证命令/操作与结果、仍有何限制、变更文件与提交。更新任务台账。不要只返回计划或建议，也不要为通过测试修改任务的业务目标。

## 输出与变更纪律

- 先查已有能力再写代码。正确逻辑直接复用，需要隔离的依赖提取窄接口。
- 禁止为错误中间产物无限增加兼容分支；明确标废并按正确契约重算，保留必要只读审计。不能无差别删除原始采样、用户资产或发布实验。
- 先固定接口交接和输入身份，再接入前后端；不使用另一 Prompt 的 latest 结果填空。
- 自动调用在既有授权与预算内运行；不把每次分析设成人工批准流水线，也不把本文当成新的无限外调授权。
- 仅增加与真实风险相关的验证，复用已有测试；不写只镜像实现、没有业务区分能力的测试。
- 模拟调用可验证故障路径；真实闭环验收须使用真实样本和实际发布/复测证据，清楚标识两者。
- 功能完成后停止无目标的重构、扩模型、扩平台和反复文档讨论。

## 实现映射必需列

功能编号、需求编号、真实文件/函数/接口、当前行为、旧状态依赖、复用方式、缺口、关联任务、验证命令或操作、证据位置、检查日期。

## 阻断处理

缺少配置、平台限流、资料不可取、预算不足、程序异常各自记录。资料不完整应按产品规则调整行动；程序异常应修复或恢复，不能换成泛泛文章来假装主链成功。需要真实发布权限时准备好完整可审阅稿件再处理授权，不让这一点阻断其他已授权开发。

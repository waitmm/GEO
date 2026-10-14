# Codex 开工与单任务执行说明

## 2026-10-14 接力工具最终收口

本轮仅 `IMPLEMENTATION_CHANGE`，修复下述三项工具问题。不执行Codex模型调用，不领取产品任务，不改历史批次、receipt、UNKNOWN或T25-03正文，不合并main。

1. Git范围检查使用 `git diff --no-renames --name-only -z HEAD` 和 `git ls-files --others --exclude-standard -z` 的原始字节，按NUL分隔、文件系统编码解码。中文、空格、制表符、换行不再被转义误判；改名的源与目标均须在白名单，越界修改、软链接逃逸和Oracle变更仍拒绝。
2. 每个模型尝试在启动前保存 `returncode=null`、`exit_reason=RUNNING`、`timed_out=false`、`observed_usage=null`、`accounting_complete=false`。退出/超时/中断后保存真实退出码（可获时）、原因、耗时、已观测用量及完整性。超时/止损清理整个进程组后记录终止码；启动失败或控制器被强杀无法取得退出码时保留未知，禁止自动恢复调用。仅NORMAL_EXIT、returncode=0、非超时、有效完整JSONL用量及独立Gate全部通过才能集成。恢复Gate、付费修复及pending integration也检查退出记录，不能用旧缺失字段补造成功。
3. 允许修改文件全部为 `.md` 的文档单元默认每子会话最多10个命令、32000个累计命令输出字符，可在冻结unit中配置 `stream_limits`，例如 `{"max_commands": 8, "max_output_chars": 24000}`。字段必须为正整数；非文档单元不启用此限制，原超时/Token/修复预算不变。dry-run显示实际阈值，检查点保存本次阈值和已观测计数。

命令按JSONL `command_execution` item ID计数，不把一条shell脚本中的每个命令单独计数；started/updated/completed不重复计数，累计输出快照按每个ID的最大字符长度增量计数。超过阈值即终止整个子进程组，保存原JSONL、stderr、工作树及检查点，不继续Gate、修复或下一任务。未完成JSON行另有字节缓冲保护。监测以50ms轮询和日志实际可见内容为界，可能超出阈值；这不是Token硬上限，也不能保证远端立即停止计费。

### 离线验收证据

- 专项及既有harness最终完整回归 **134 passed**，见 `backend/artifacts/acceptance/relay-final-20261014/regression-host.xml`。覆盖特殊路径、改名越界、真实本地假进程退出/信号/超时/止损、忽略TERM后代清理、未知用量、失败恢复、旧检查点缺退出证据拒绝、原权限及Git集成保护。
- 中间失败日志保留：一次Mock进程启动超过测试0.3秒，改为充足启动余量而不放宽止损原因断言；一次外层执行环境返回killpg EPERM，随后宿主查询无该测试残留进程，在普通宿主环境重新跑完整回归通过。另补确定性清理失败负例：仍保存真实退出码、CLEANUP_FAILED及原终止触发原因，禁止继续。未关闭Codex沙箱或修改业务权限。
- T25-03原工作树与原Oracle哈希经新Guard检查通过；原文档Gate及9项用量测试只引用已有日志哈希，不重新生成正文或重新运行历史Gate。
- 实际JSONL仍为653211活动Token。新文档默认止损在第16条事件触发OUTPUT_LIMIT，当时41595字符、4个命令；单独命令阈值回放在第30条事件、第11个命令触发COMMAND_LIMIT。真实进程清理使用本地Python Mock验证，不调用Codex。
- 2865份历史文件哈希保持不变。旧T25-03退出码仍未知、STOPPED/receipt/UNKNOWN原样保留；修复后新Guard通过不等于旧任务自动接受或真实节省效果已验证。
- `replay.py`、`replay-report.json`、`dry-run.json`保存在同一证据目录。预演1单元、0外部调用、600秒/30000软阈值/0修复，未真实执行。旧章节保留当时核查含义；这次修补不授权下一次真实尝试。

## 2026-10-14 T25 上下文与用量离线修补

仅 `IMPLEMENTATION_CHANGE`：按任务读取指令与JSONL判定修补，不扩产品、调度架构、模型或预算。根目录AGENTS不再要求每次通读八份产品资料；项目AGENTS保留正式主链、数据保护、冻结身份、证据归属和语义变更门禁。纯T25文档单元只读控制器冻结的任务定义、目标章节及必要指令；真实依赖仍须跟进。全局AGENTS为空，历史工作树指令不改，新规则仅对新基线有效。

- `inspect_usage` 分开返回 `observed_usage` 和 `accounting_complete`。没有有效用量时前者为null，不把初始化0说成实耗0；部分已完成turn的用量是已观测下界，不能代表未完成调用的全部费用。
- 仅识别 `Reconnecting... n/m (...)` 为可恢复提示，必须随后有有效 `turn.completed`；`turn.failed`、未知错误、坏JSON、缺失/非法用量或最后仍未完成均阻断。非零退出和超时仍停止，不自动重试；新检查点显式保存退出码和观测值。
- 活动量只加input与output，cached/reasoning不重复相加。批次 `activity_tokens` 与 `observed_activity_tokens` 是已观测累计；只有 `accounting_complete=true` 才是完整JSONL记账，仍不是套餐账单或任务验收。成功结束还须通过原范围、不可改预期及独立Gate。超过软阈值不领下一任务、不进行付费修复。
- 实际JSONL离线回放：input647278 + output5933 = **653211**；cached585088、reasoning1803为子项；四次重连后完成。历史报告的STOPPED、RUNNING尝试标签和UNKNOWN记账原样保留，不改DONE、不resume。
- 原T25工作树仅目标章节新增16行；冻结文档Gate通过，用量专项9 passed/70 deselected。新工具与harness回归 **107 passed**。2865份历史文件逐字节哈希不变，包括receipt及工作树内容。
- **尚未完成真实集成**：旧检查点没有保存进程退出码，不能从turn.completed臆造exit0；另发现 `changes()` 用Git非NUL路径输出，中文文件名被转义后使 `guard` 误报越界。独立NUL路径核对证明实际只改允许文件，但不代替生产Guard。此缺陷登记待单独修复，不在本轮两项范围内扩大修改。

### 流式止损评估（未启用新限制）

本次日志有25次命令调用、292904字符命令输出。离线按item ID去重：假设32000字符门槛，第16条事件已观测41595字符；假设10次命令门槛，第28条事件触发。数字仅用于比较候选止损方式，本轮没有新增运行参数或偷偷改变任务预算。输出通常到item.completed才可计数，单条命令仍可能超限；工具数量也不约束无工具推理消耗。未来若采用流式止损，应复用进程组清理并保留部分用量/UNKNOWN，不能宣称Token硬上限或远端立刻停止计费。

证据：`backend/artifacts/acceptance/relay-usage-replay-20261014/` 下的 `replay.py`、`replay-report.json`、`regression.xml`、两份 `historical-gate-*.log` 和 `history-before.json`。回放只调用本地Python Gate，不启动Codex或产品服务。本轮新Codex进程/模型调用均0；不代表当前IDE对话免费，也不证明节省额度。

## 2026-10-14 Codex 自身执行路径修复

本轮仅修复 T25 工具的可执行文件路径与单文件只读权限，分类 `IMPLEMENTATION_CHANGE`。保留此前单层官方沙箱，不改模型、预算、队列和Git集成规则；不调用真实exec或模型，不恢复产品开发。

现场软链接链：`~/.local/bin/codex` -> `~/.codex/packages/standalone/current/bin/codex`，其中 `current` -> `releases/0.162.1-x86_64-apple-darwin`。最终文件为 `/Users/bmwqr/.codex/packages/standalone/releases/0.162.1-x86_64-apple-darwin/bin/codex`。版本号仅是本次观察值，实现没有硬编码：使用PATH查找和 `Path.resolve(strict=True)` 解析文件及目录软链接，要求普通可执行文件，失效/循环链接、目录及不可执行文件拒绝。

- 控制器先解析，再用真实路径启动CLI和其自执行探针；保存请求路径及最终路径。
- 生成的权限表只新增最终程序文件 `read`。`~/.codex=deny` 不变，不授权别名路径、`current`目录、版本目录或bin目录；因此没有为解决软链接问题扩大目录可读范围。既有auth.json、凭证、数据库和网络保护不变。
- 预检不再仅执行 `/usr/bin/true`：必须在实际生成的官方沙箱中成功执行该Codex文件 `--version` 并返回CLI标识，否则在模型调用前停止。没有 `project_doc_max_bytes=0`、danger-full-access、sudo或关闭沙箱。

### 本次验证与因果边界

证据目录：`backend/artifacts/acceptance/codex-self-exe-20261014/`。

- `comparison.json` 四组离线对照：别名+旧权限=71；真实路径+旧权限=0；别名+新增单文件权限=71；真实路径+新增权限=0。**本机关键修正是启动路径规范化，不能声称仅添加read权限就解决了别名自执行问题。** 最初将“真实路径+旧权限”预期为失败的检查不成立，原日志保留，四组结果纠正该假设。
- `probe-02/report.json`：16项真实CLI离线检查全部通过。包括沙箱内Codex版本、`debug prompt-input`本地渲染成功且含项目AGENTS正文、项目文件读取、工作树写入、scratch SQLite、模拟密钥/auth.json/生产DB拒读、软链接绕行拒绝、工作树外非授权写入拒绝、Git只读、后创建环境文件拒写和网络拒绝。debug命令由宿主启动，其文件helper自行应用Profile，不嵌套Seatbelt；未发起模型生成，网络代理指向不可用本地端口。
- `regression.xml`：88 passed，0 failed，0 skipped（79项工具测试+9项原harness检查）。新增动态两级软链接、无效程序路径、精确单文件授权及自执行失败提前停止的回归。
- 与上游 [#41493](https://github.com/openai/codex/issues/41493)、[#38286](https://github.com/openai/codex/issues/38286) 报告的helper自执行路径症状一致；它们是参考，不代表所有版本上游缺陷已修复。本次修复由本机探针验证。

最新历史失败批次为 `20261014T103915-c2664ed2`，其receipt及UNKNOWN用量继续保留；本轮不归档或resume。`history-before.json`记录修改前48份历史文件的hash，收尾逐项复核。队列、授权和产品状态不改。真实模型调用、子任务集成与节省效果仍未验证，不能凭离线通过自动开始下一批。

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

此前一轮只交付开发工具，挂现有 T25，未运行真实 `codex exec`。产品仍 INCOMPLETE。按AGENTS任务路由读取本文件相关章节和控制器冻结的单元定义；没有提供定义时才定位 `tasks.json` 对应条目。不把整段聊天、完整台账或历史日志搬进每次任务；纯文档任务无须通读产品契约，适用契约与权限约束仍必须遵守。

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

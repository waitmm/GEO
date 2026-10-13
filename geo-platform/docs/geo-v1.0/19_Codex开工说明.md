# Codex 开工与单任务执行说明

## 2026-10-13 有界接力入口（优先于旧的无限续跑描述）

最新授权：离线工具 OFFLINE_ACCEPTED，真实冒烟 REAL_SMOKE_PENDING。只运行 T25-RELAY-USAGE-SMOKE 文档任务，最多1任务、0修复、600秒、30,000活动Token软阈值；配置或运行异常即停，不换模型、不自动重试、不扩调度器或领取产品功能。此前65项离线验收记录保留，不等于真实节省额度。真实结果见下方后续记录；没有结果就不能推定成功。

此前一轮只交付开发工具，挂现有 T25，未运行真实 `codex exec`。产品仍 INCOMPLETE。正常研发从本文件和 `tasks.json` 当前检查点恢复，不把整段聊天或历史开发日志不断搬进每次任务。AGENTS 的必读契约及权限约束不减少；用目录/标题检索定位相关段落，避免反复输出整个历史日志。

入口：`backend/scripts/delivery_codex_relay.py`；专项：`backend/tests/test_delivery_codex_relay.py`，由既有 delivery harness 的 `test_delivery*.py` 自动发现。没有引入新调度服务或第二套产品任务台账。小任务写入原 `tasks.json.codex_relay.units`，必须绑定现有 `task_id`、`requirements`、依赖、精确允许修改文件、外部验收命令和不可改的预期文件。当前只登记一个文档用量说明任务，原离线空队列证据保留。

### 核心执行流程

1. 默认仅预演，输出队列、配置和预算，不启动任何 Codex 进程，不建工作树、不修改 Git。
2. 显式执行前要求工作区干净；单实例文件锁；上一批 receipt 未处理则不能偷偷重跑。默认1项、最多3项；每项最多初次执行加2次定向修复。
3. 唯一连续基线为 `codex/geo-integration`。从该分支创建隔离工作树；每项通过独立 Gate 后由控制器提交、CAS 快进 integration。后项必须以此前已集成的提交启动。禁止自动合并/推送主分支，也禁止代理自行提交。integration 被检出或被外部移动时停止。
4. 每次独立 `codex exec` 显式覆盖为 `gpt-6.1-sol / medium / default`，关闭多 Agent、goals、apps、plugins 和 shell 外网；审批为 never，sandbox 为 workspace-write。不改全局配置，不跳过已有安全规则，不授权 GEO 业务外调。
5. 首次模型执行前用只读 `app-server` 的 initialize/config-read/model-list 核验实际配置与可用模型；无 thread/start 或 turn/start。High、Priority、模型不可用、启用的外部 MCP/Hook 或隔离失败都停止，不偷偷降级模型或绕过权限。本轮该协议由本地 Mock 验证，不代表账户已确认可用 Sol。
6. 工作树不复制 `.env`、业务 DB、账号 profile。环境清除继承的业务凭证，使用隔离 SQLite、scratch、临时端口和 offline 标记。macOS 额外 sandbox 拒绝读取原仓库业务数据、写入原仓库及连接未分配本地端口；模型进程仅额外允许 HTTPS/DNS，测试 Gate 不允许外网。依赖目录仅只读复用。无可用隔离机制就拒绝执行，不支持无保护降级。
7. 冻结队列及验收预期；变更超白名单、修改 Gate 预期、HEAD 异常、无用量、进程失败或超时立即停止。只有正常模型结束且 Gate 失败才允许有限修复。子进程结束/超时/中断均清理整个进程组，包括忽略 TERM 的后代。
8. 原子保存每次调用前、用量后、Gate 后和 integration 更新前后的检查点。恢复不重置预算/重试；已验收任务不重复执行；模型已结束而 Gate 中断只重跑本地 Gate；integration 已更新但状态未落盘时补记账。调用中断且用量不明必须人工核对，不能自动再调用。

### 用量口径与边界

- 活动量 = `input_tokens + output_tokens`；cached 是 input 子项，reasoning 是 output 子项，均不再相加。缺 reasoning 字段允许；缺必要用量则 UNKNOWN 并停机。
- 默认批次活动量停止阈值100,000，单会话15分钟（可设置1..1800秒）。这是**会话结束后阈值**，不是单次请求硬上限；JSONL 用量无法保证中途准确限额，超时断连也不能保证远端立即停止计费。
- JSONL、stderr、Gate 日志、耗时、提交和检查点保存在忽略目录 `backend/artifacts/codex_usage/`；不记录密钥，也不将活动 Token 换算为 ChatGPT 套餐额度或宣称节省比例。
- Gate 通过仅表示该小任务的程序化检查通过，不自动将 T25 或产品标记 DONE。集成分支供后续任务复用，主分支合并及产品验收仍独立。

### 命令（从仓库根目录）

```bash
# 首次冒烟预演，安全默认；计划1个会话，实际启动0个。
geo-platform/backend/.venv/bin/python geo-platform/backend/scripts/delivery_codex_relay.py --max-tasks 1 --max-repairs 0 --session-seconds 600 --token-threshold 30000

# 离线专项，不调用真实 Codex。
cd geo-platform/backend
.venv/bin/python -m pytest tests/test_delivery_codex_relay.py tests/test_delivery_acceptance.py -q
```

首次真实冒烟的授权命令，需先提交准备检查点并快进 integration，在允许创建子沙箱的本机终端运行。命令列在这里不代表已通过真实验证：

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

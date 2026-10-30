# C0：第二消费者 AI 平台限时研究

日期：2026-10-30（Asia/Shanghai）  
研究基线：`6714b10`；分支：`codex/c0-second-platform-eval`  
结论：`C0_RESEARCH_COMPLETE / C1_NOT_AUTHORIZED / AUTO_COLLECTION_NOT_READY`

本次仅增加研究文档、合成 fixture 和离线测试，生产代码、采样开关、数据库与 A/B 工作区未改动。
分类：测试/文档为 `IMPLEMENTATION_CHANGE`；第二平台准入与引用投影存在 `SEMANTIC_RISK`，
只调查、回放，不据此切换生产。依据 SC-RUN-IMPORT-001、SC-RUN-RETRY-001、
SC-EVIDENCE-001/003、SC-UNKNOWN-001 和现有精确版本范围规则。

## 1. 决策摘要

**研究优先级推荐腾讯元宝，豆包为备选；两者目前都不能直接开启自动采样。**
这是基于信源覆盖差异的产品判断，不是对采集许可、稳定性或效果的保证。
元宝官方应用介绍明确包含公众号、视频号，可验证现有文心之外的来源归属场景；
并不意味着它一定引用目标品牌，或微信渠道一定更有效。[元宝开发者发布的应用介绍](https://apps.apple.com/cn/app/id6480446430)

关键实施缺口：

1. 当前 registry 只有 `wenxin_web_audit`；人工导入 API 与服务也仅接受 `wenxin`。
2. 通用 executor 存在空引用元数据被解释为完整零引用、引用平台名称硬编码文心的反例。
3. 尚无获授权、完整、带页面版本/观察时间的豆包或元宝实际样本；不能编造 DOM selector。
4. 元宝官方用户协议正文在本研究工具中两次读取超时；当前规则不能宣称已完整核实。
5. 云 API 不等于消费者平台：腾讯云元宝搜索 FAQ 明确暂不提供公众号内容，而消费者应用介绍
   包含公众号。购买或调用 API 不能验收消费者元宝采样。[腾讯云 FAQ](https://cloud.tencent.com/document/product/1806/121804)

不因研究阻断而改回“只支持人工导入”的产品目标；人工导入只是获合法样本后的辅助路径。
本次未扩大平台名单、未购买 API、未建设通用采集框架。

## 2. 公开证据与可信度

只将官方条款、官方文档、由产品开发者发布的商店说明用作实质判断。
搜索命中腾讯云社区的个人文章并不等于腾讯官方承诺；第三方 GEO 营销文章不用于推断引用偏好。
以下记录是阅读摘要，不是法律意见或完整条款副本，实际接入前须由责任人核对适用规则。

| 编号 | 公开来源与本次核对结果 | 能支持 / 不能支持的结论 |
|---|---|---|
| D1 | [豆包用户协议](https://www.doubao.com/legal/terms)，页面更新 2026-09-10、生效 2026-09-17；本次可读 | 2.2.2 描述联网搜索及来源展示；2.9、2.11、6.1–6.3、9.4 有许可、使用及内容利用限制。不能据此主张 GEO 批量自动访问已获准；也不能将输出权属与自动采集许可混为一谈。 |
| D2 | [豆包付费服务协议](https://www.doubao.com/legal/ey01)，页面日期 2026-05-20；本次可读 | 3.1 列明消费者官网 `www.doubao.com/chat/`。本轮未访问该对话入口、未确认登录态或可用次数。 |
| Y1 | [元宝 App Store 开发者介绍](https://apps.apple.com/cn/app/id6480446430)，发布者 Tencent Technology (Shenzhen) Company Limited；本次可读 | 开发者说明含联网搜索、公众号和视频号信源。仅引用开发者说明，未采用用户评论；不能据此保证网页版当前引用面板结构。 |
| Y2 | [元宝用户服务协议官方链接](https://rule.tencent.com/rule/202403110001)，本轮两次超时 | 当前有效日期、自动化条款全文：`NOT_VERIFIED`。链接由[第三方法律研究的文献脚注](https://www.icourt.cc/prac-document/677.html)定位；该转载线索不是当前官方规则验证。不能把腾讯其他产品协议移植为元宝许可。 |
| Y3 | [腾讯云元宝搜索 FAQ](https://cloud.tencent.com/document/product/1806/121804)，更新 2026-10-09；本次可读 | API 的公众号覆盖限制与消费者应用不同；仅为区分产品，不构成 API 购买建议。 |
| Y4 | [腾讯云产品动态](https://cloud.tencent.com/document/product/1806/121792)，本次官方搜索结果可读 | 记录 2026-10-09 联网搜索 API 更名。名称相似不能证明与消费者页面观测等价。 |

消费者元宝官网候选为 `https://yuanbao.tencent.com/`；入口在本轮没有打开。
网址定位有[公开产品介绍线索](https://developer.cloud.tencent.com/article/2496538)，但该社区文章
不作为协议权威或当前 UI 验证；C1 应由平台官方入口/当前官方说明再次确认。

## 3. 候选比较与测试边界

| 项目 | 腾讯元宝 | 豆包 |
|---|---|---|
| 当前业务研究价值 | 可检验公众号/视频号及普通网页来源差异；推荐优先研究 | 可检验另一消费者搜索来源展示；备选 |
| 回答、引用公开证据 | 官方应用介绍证明搜索信源能力；当前网页版编号、卡片、目标 URL 展开方式未知 | 用户协议描述搜索来源与相关内容展示；不代表所有来源均是支持具体语句的引用 |
| 实际 UI/流式结束/登录态 | 未验证 | 未验证 |
| 自动化可用许可 | 尚未核实当前官方全文，也无平台许可材料 | 已见内容利用/许可限制，无本项目书面许可材料 |
| C0 允许 | 官方公开文档研究、合成 envelope、现有拒绝边界测试 | 同左 |
| 当前不允许 | 登录、消费者提问、自动 DOM 采集、验证码处理、付费调用 | 同左 |

即使未来取得合法人工样本，也必须标 `MANUAL_IMPORT`、导入人/时间及
`USER_ATTESTED_UNVERIFIED`；hash 只证明完整性，不证明平台真实性。人工复制也不是规避内容权利
限制的通行证。不得使用混元/火山模型 API 回答冒充相应消费者产品。

## 4. 现有接口与最小字段映射

审计位置均相对 `geo-platform/`，不新建生产适配层：

| 观察 / 身份 | 现有承载点 | C1 必须保留的约束 |
|---|---|---|
| Project / Prompt / PromptVersion / 配置版本 | `single_prompt_v2/service.py` 版本 binding；`manual_import.py` 时间归属检查 | 明确 ID/hash；观察时间处于版本生效区间；禁止 latest 回填；服务端权限校验 |
| 平台、方法、parser / collector 版本、时间 | `models/db.py::BrowserMonitorRun`，`CollectorResult.environment` | 平台不能伪装文心；人工样本方法不伪装自动；内部未暴露模型修订保持 UNKNOWN |
| 原始回答 / HTML | `CollectorResult.answer_text/answer_html` → `BrowserMonitorRun` | 按实际完成边界保存；回答 hash 与原始 artifact 留存；不要把推理/搜索过程混入正文 |
| 答案实际引用及出现次数 | `CollectorResult.references` → `ReferenceSource` | Run ID + reference_index + 原始/规范 URL + evidence_path；同 URL 重复出现仍保留 occurrence |
| 搜索候选 | `CollectorResult.retrieval_candidates` → `RetrievalCandidate` | 与 final references 分开；“搜索到 N 篇”不自动变成 N 条答案引用 |
| 可见引用计数 / 完整性 | `metrics` 和 Run 的四种 count / `reference_complete` | 未提供、不显示、解析失败均不能默认为已确认零；当前共享 executor 需补 C1 Gate |
| raw artifact / 原始 hash | `RunArtifact` 与既有 artifact 存储 | 账号/令牌/隐私脱敏；限制路径和权限；保留可回放来源与内容 hash；不下载链接正文 |
| 模型选择 / 联网模式 / UI版本 | 现有环境 artifact、冻结配置 | 当前 Run 没有通用 model/search-mode 强类型字段；不能假设放进 environment 就都会持久化；C1 明确冻结载体并做回读验收 |
| 时间范围、Monitor、分析冻结 | `observation_api.py::_range_preview` / `freeze_analysis_range` | 已按平台、adapter、版本等分组；仍需验证不同模型/联网配置不会混组；最后冻结确切 Run IDs/hash |
| 人工导入 | `observation_api.py::ManualObservationImportCreate` + `manual_import.py` | 两层均限定 wenxin；C0 不改白名单，不把平台名改成 wenxin 绕过；未来仅批准平台可扩展 |

采样原始回答不是 `AnswerUnit`：后者由用户手动发起的语义分析产生。
来源引用也不是自动成立的 Product Truth、SUPPORTS 或渠道有效性结论。
既有 executor 的 `analyze_brand` 是规则投影而非模型调用；其推荐词命中不可冒充正式语义指标。

### 发现的接入风险

- `collectors/registry.py::get_collector` 只注册文心；`scheduling.py` 和 `service.py` 的采样 plan
  也固定文心。不能只加一条 registry 注册就宣称第二平台接入完成。
- `executor.py::apply_result` 在 `metrics={}`、`references=[]` 时推导 `ui_count=0`，继而
  `reference_complete=True`，足够长的回答可被标成 success。此行为不能继承给未知引用状态的新平台。
- `executor.py::_save_references` 当前固定 `platform_name="文心助手"`。直接复用会污染平台归属。
- `service.py::_semantic_region_projection` 专门识别 `wenxin_semantic_regions`；第二平台应提供明确
  对应的原始区域边界/兼容版本，不得把文心字段名换壳后假定语义一致。
- 引用链接可能只得到包装 URL、不可见目标或无稳定 URL；保留原始值和 unresolved，不额外联网解析、
  不猜目标、不去抓正文；若无法准确区分候选与引用，应阻断该关系的确定性准入。

## 5. 离线证据与结果

合成数据：`backend/tests/fixtures/c0_second_platform_observations.json`。
明确 `SYNTHETIC_CONTRACT_PROBE`、`actual_platform_capture=false`、`production_admission=false`；
仅含 `.invalid` 示例 URL。没有人工真实样本，也没有从任何消费者页面抓取的 DOM。

测试：`backend/tests/test_c0_second_platform_probe.py`。覆盖：

- 两平台字段 envelope 序列化回放、回答 hash、重复 occurrence、候选/引用分离；
- 当前自动 registry 和人工导入 schema 对未支持平台 fail-closed；
- COMPLETE、CONFIRMED_NONE、UNKNOWN、PARSE_FAILED 的现有人工引用校验；
- 两个 `strict xfail` 保留当前共享 executor 的已知 C1 反例：UNKNOWN → 零引用、平台名串成文心。

执行命令（仅复用已安装依赖，不安装/下载任何包）：

```bash
cd /private/tmp/geo-c0-platform-eval/geo-platform/backend
/Users/bmwqr/Desktop/python/GEO/geo-platform/backend/.venv/bin/python \
  -m pytest -q tests/test_c0_second_platform_probe.py --disable-warnings -rx
```

结果：**10 passed、2 xfailed，4.15 秒**。既有 `tests/test_manual_run_import.py`
独立回归 **3 passed，10.69 秒**。`git diff --check` 通过。
合成 fixture SHA-256：`04c588872742ff434aaa71f5a58c5031d58827132d6bf138969962611df4607e`。
`xfail` 明确代表尚未修复的接入阻断，不能计作 C1 功能通过。
这些测试没有证明页面 selector、真实登录、真实内容质量或第二平台生产准入已完成。

## 6. C1 最小 Gate（提议，不是本次授权）

1. **权限先决**：责任人确认当前适用条款、用途/留存/团队展示权利与自动化使用许可；元宝须先补齐
   当前官方协议核验。项目拥有者同意测试不等于平台授权。无许可则仅继续离线。
2. **明确授权与范围**：只选一个平台、一个 Project/Prompt/精确版本；单条尝试、单并发、重试 0；
   不自动开启每日计划，不请求付费权益，不调用模型分析或下载引用正文。
3. **最小适配**：沿现有 BaseCollector/Run/Attempt；只补该平台必要 parser、白名单及 provenance；
   修复上面两个共享映射反例，但不降低文心、人工导入或 Evidence/Truth 资格。
4. **先离线后真实**：取得获授权的真实脱敏样本与显式观察时间；人工取得的样本仍标
   MANUAL_IMPORT，不包装成自动采样。先验完整/合法无引用/未知/解析失败/超时/登录失效/重复 URL。
5. **成功判据**：一次独立会话的真实回答、实际引用观察、版本时间/hash、Run/Attempt 审计均回读一致；
   CAPTCHA、登录失效、限流直接阻断并转人工，不规避访问控制，不自动换账号/代理。
6. **隔离与回归**：不同平台、Prompt/配置/模型模式不静默混组；旧 AnalysisContext 不变；验证采样
   不创建 AnalysisContext、Evidence Pack、Optimize、Validate 或任何模型请求。
7. **独立准入结论**：单条真实采样通过只证明此路径可行；定时、多样本、日常授权及生产切换另行决定。

C0 到此停止。公开文档检索/阅读：有；消费者提问、登录、真实采样、模型、正文抓取、发布：均为 0。

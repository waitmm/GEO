# GEO Platform M1 爱短链内部 Beta

状态：`BETA_CANDIDATE`

版本：`geo-internal-beta.m1-rc1`

变更分类：`IMPLEMENTATION_CHANGE`

## 产品边界

M1 只把已经隔离的 Evidence Pack 结果线路接入员工可操作的产品闭环：

```text
真实项目 → Prompt / Run → Monitor → AI 优化 → 诊断 / 策略 / 正文 / QA
         → 历史版本 → 复制 / 导出 → 追加式反馈
```

Evidence Pack 继续只写 `AgentExperimentRun`、`AgentResultVersion` 和内部反馈表，
不会写入正式 V2 Analysis ResultVersion、Truth、Review 或 Gate。正式流程仍作为备用
和质量对照。任何把实验结果提升为正式权威结果的决定，仍需单独的语义契约审批。

## 员工使用指南

1. 在左侧选择“爱短链”项目，并在 Monitor 选择要处理的真实问题。
2. 查看当前回答、品牌提及、推荐和引用表现，点击“分析这些回答”冻结明确 Run 范围。
3. 在品牌资料页新增资料版本。必须分别填写：
   - 希望建立的品牌关联：只是优化目标，不是产品事实；
   - 项目组声明为已核实的能力及来源：仍需 Product Truth 和来源资格校验；
   - 待核实能力、禁止表述、可用资产和渠道。
4. 进入 Optimize 的“AI 优化”，选择本次要冻结的品牌资料版本。
5. 若部署环境尚无日常模型额度，只能查看已保存的真实结果，不能启动新生成。
6. 查看诊断、品牌证据缺口、策略、完整正文、QA 和复测计划。
7. `VERIFY_FIRST` 表示必须先核实，不代表内容可直接发布。
8. 复制正文或导出完整 Markdown 报告，完成编辑审核后再由员工人工使用。
9. 对精确结果版本提交“可用 / 需修改 / 不可用”、原因、采用状态和修改量。
   反馈只追加，不覆盖原结果，也不会改变 Product Truth 或审核状态。

## 历史结果与新生成

- 历史成功结果显示为“已保存的真实模型结果”，读取它不会创建新任务。
- 新任务必须绑定新的冻结执行身份；系统不会把历史结果显示成新生成成功。
- 无部署级日常调用授权时，`GEO_AGENT_BETA_DAILY_MODEL_CALLS` 默认为关闭，授权
  接口 fail-closed。历史实验账本余额不能作为内部日常使用授权。

## 部署准备

从隔离的成功实验数据库制作 Beta 数据副本：

```bash
./scripts/prepare_internal_beta.sh /absolute/path/source.db /absolute/path/aiduanlian-beta.db
```

启动只读历史结果试用：

```bash
GEO_RELEASE_DATABASE_URL=sqlite:////absolute/path/aiduanlian-beta.db \
GEO_RELEASE_ACCESS_CONFIG=/absolute/path/access.json \
./scripts/dev.sh
```

远程内部访问必须配置 0600 权限的邀请账户文件、HTTPS 反向代理和受控网络。
没有服务器与证书权限时，不得把本地地址描述为团队可访问地址。

日常模型生成还需要单独批准预算与共享账本后，才可在 worker 环境显式设置：

```text
GEO_AGENT_BETA_DAILY_MODEL_CALLS=1
```

该开关本身不替代逐任务预算、供应商凭证或共享预算账本。

## M1 验收重点

- 项目切换后旧项目结果立即清空，不跨项目显示。
- Monitor 使用真实 Run，失败与 UNKNOWN 不按合法零值展示。
- AI 优化默认采用 Evidence Pack；历史工具循环不出现在员工主操作面。
- 结果显示精确版本、证据等级和 `VERIFY_FIRST`。
- 复制、导出和反馈调用实际 API；GET 路径保持只读。
- 反馈绑定精确 Project、Prompt、Run 与 AgentResultVersion，且数据库禁止更新/删除。
- 正式 V2 表与历史结果不被实验或反馈改写。

## M2 八木屋接入清单（M1 试用后再启动）

1. 用现有项目配置创建八木屋，不增加八木屋专用代码分支。
2. 配置品牌名、别名、官网、视频二维码、文件二维码和二维码生成器相关 Prompt。
3. 录入已核实能力、待核实能力、禁止表述、内容资产与渠道版本。
4. 用同一 Monitor → AI 优化 → 反馈流程完成至少一个真实范围。
5. 检查 Evidence Pack、Prompt 和 UI 中不存在爱短链、抖音或短链接硬编码。
6. 验证项目权限、数据、结果、反馈和品牌资料版本完全隔离。
7. 只根据爱短链试用反馈和八木屋真实差异抽象通用能力。

## 已知限制

- M1 已保存的单场景真实结果证明一次交付可行，不证明跨 Prompt 稳定性。
- 当前真实结果的品牌关联仍偏弱，员工反馈应优先标记品牌关联、事实错误、策略泛化
  和正文质量，而不是只评价是否生成成功。
- 自动发布、复杂 CMS、精细团队协作、商业计费和大规模知识图谱不在 M1。

# GEO / AI品牌可见度监测与信源诊断平台 PRD

版本：V1.0
产品方向：国内主流AI平台品牌可见度监测 + 引用源内容诊断 + GEO档案复盘系统
目标使用方：GEO工程师、SEO/内容营销团队、B2B品牌市场团队、数字营销代理商
开发方式：分版本迭代，先验证数据底座，再扩展商业增强功能

---

## 1. 产品定位

### 1.1 产品一句话

本产品用于监测品牌在国内主流AI问答/AI搜索平台中的可见度表现，分析AI引用了哪些来源、来源中哪些内容影响了答案，并沉淀可复盘的GEO优化档案。

### 1.2 核心价值

产品不是传统SEO排名查询工具，也不承诺固定“AI排名”。
产品提供的是基于多平台、多Prompt、多次采样的统计型品牌可见度监测。

核心回答四个问题：

1. AI有没有提到我的品牌？
2. AI在什么问题下推荐了竞品，而没有推荐我？
3. AI引用了哪些来源，这些来源里有什么内容？
4. 我优化官网、案例、FAQ、媒体信源后，AI可见度有没有变化？

### 1.3 产品边界

#### 产品要做

* 国内主流AI平台可见度监测
* Prompt问题集管理
* 品牌与竞品提及分析
* 推荐入围率、声量份额、引用率统计
* AI原始回答快照存档
* 引用URL提取与来源类型分析
* 引用源内容分析
* SERP / 信源层监测
* 优化动作记录
* 前后效果复盘
* 报告导出

#### 产品不做

* 不承诺“AI固定排名”
* 不承诺“保证AI推荐”
* 不做账号池、代理池、验证码绕过
* 不做未授权的C端平台批量自动化抓取
* 不把API结果伪装成C端真实用户结果
* MVP阶段不做全行业知识图谱
* MVP阶段不做自动发稿、自动外链、公关投放
* MVP阶段不做医疗、金融强合规行业模板

---

## 2. 核心设计原则

### 2.1 数据源分层

所有监测结果必须标记数据来源，不能混算为一个不透明总分。

数据源类型：

1. 官方API联网搜索结果
2. 官方API非联网模型认知结果
3. 官方搜索API / SERP数据
4. 人工审计结果
5. 客户上传结果
6. 系统模拟数据，仅限开发测试

### 2.2 平台结果不等于真实用户端

每个平台都要保存以下字段：

* 平台名称
* 数据入口
* 模型名称
* 模型版本
* 是否联网
* 是否C端人工审计
* 查询时间
* 查询地区
* 语言
* Prompt原文
* 原始回答
* 引用URL
* 采集状态

### 2.3 统计优先于单次排名

同一Prompt需要重复采样。
产品展示提及率、入围率、引用率、声量份额、波动率，不以单次回答顺序作为唯一结论。

### 2.4 原始证据优先

任何统计指标都必须能追溯到：

* 原始Prompt
* 原始AI回答
* 引用URL
* 引用源快照
* 抽取结果
* 抽取时间
* 优化动作记录

---

## 3. 用户角色

### 3.1 超级管理员

负责系统配置、平台Adapter配置、用户管理、用量管理。

### 3.2 组织管理员

通常是企业市场负责人或代理商项目负责人。

权限：

* 创建组织项目
* 添加品牌和竞品
* 管理Prompt库
* 配置监测计划
* 查看所有报告
* 管理成员权限

### 3.3 项目成员

通常是SEO、GEO、内容运营人员。

权限：

* 查看项目数据
* 编辑Prompt
* 发起监测
* 记录优化动作
* 查看引用源分析
* 导出报告

### 3.4 只读成员

通常是老板、客户或外部顾问。

权限：

* 查看仪表盘
* 查看报告
* 查看原始快照
* 不可修改配置

---

## 4. 版本路线

产品分三个版本完成。

---

# V0：技术验证版

目标：验证数据底座是否可用，不做完整商业化。

周期建议：2-4周
适用对象：内部团队
核心目标：跑通多平台API监测、原始存档、基础抽取、引用URL保存。

## V0.1 功能范围

### 4.1 项目管理

支持创建一个监测项目。

字段：

* 项目名称
* 主品牌名称
* 品牌别名
* 官网URL
* 竞品列表
* 行业
* 目标地区
* 默认语言

### 4.2 Prompt管理

支持手动录入Prompt。

字段：

* Prompt标题
* Prompt正文
* Prompt分组
* 意图类型
* 重要程度
* 是否启用

意图类型：

* 品类认知
* 解决方案研究
* 产品比较
* 供应商推荐
* 品牌验证
* 价格成本
* 实施交付
* 风险合规
* 售后替代

### 4.3 平台Adapter

V0需要完成统一Adapter接口。

必须支持：

* 千问 / 阿里百炼联网搜索
* Kimi联网搜索
* 文心 / 千帆联网搜索
* DeepSeek模型认知
* Mock测试Adapter

可选验证：

* 豆包 / 火山方舟
* 腾讯混元
* 腾讯联网搜索API

每个Adapter必须返回统一结构：

```json
{
  "platform": "qwen",
  "entry_type": "official_api_web_search",
  "model": "string",
  "model_version": "string|null",
  "web_search_enabled": true,
  "prompt": "string",
  "answer_text": "string",
  "citations": [
    {
      "title": "string",
      "url": "string",
      "snippet": "string|null",
      "source_name": "string|null"
    }
  ],
  "raw_response": {},
  "status": "success|failed|partial",
  "error_code": "string|null",
  "error_message": "string|null",
  "latency_ms": 0,
  "token_usage": {},
  "cost_estimate": 0
}
```

### 4.4 监测任务

支持手动发起一次监测。

输入：

* 项目ID
* Prompt列表
* 平台列表
* 每个Prompt重复次数，默认3次

输出：

* 任务状态
* 成功数量
* 失败数量
* 平均耗时
* 预估成本

### 4.5 原始回答存档

每次观测保存：

* 项目ID
* Prompt ID
* 平台
* 数据入口
* 模型
* 是否联网
* 查询时间
* 原始Prompt
* 原始回答
* 原始响应JSON
* 引用URL
* 失败原因
* 内容hash

### 4.6 基础品牌/竞品抽取

V0先做规则抽取，不必上复杂模型。

抽取内容：

* 是否提到主品牌
* 是否提到竞品
* 主品牌首次出现位置
* 竞品出现次数
* 引用URL数量
* 是否引用主品牌官网
* 是否引用竞品官网

### 4.7 V0基础仪表盘

页面展示：

* 总Prompt数量
* 总观测次数
* 平台成功率
* 主品牌提及率
* 竞品提及率
* 官网引用率
* 最近10条原始回答

### 4.8 V0验收标准

必须满足：

1. 能创建项目、品牌、竞品、Prompt。
2. 能调用至少3个真实官方API Adapter。
3. 能对10个Prompt × 3个平台 × 每个重复3次完成监测。
4. 每条结果都能保存原始回答和引用URL。
5. 能展示基础提及率、竞品提及率、官网引用率。
6. 所有数据都带有来源标签。
7. 不使用账号池、代理池、C端自动化抓取。

---

# V1：可售MVP版

目标：形成可给种子客户使用的SaaS MVP。

周期建议：6-8周
适用对象：3-5家种子客户
核心目标：项目化、周期监测、引用源分析、报告导出、优化动作复盘。

---

## 5. V1功能范围

## 5.1 账号与组织

支持：

* 用户注册 / 登录
* 组织创建
* 组织成员管理
* 项目列表
* 简单角色权限

角色：

* owner
* admin
* member
* viewer

## 5.2 多项目管理

一个组织可以创建多个项目。

项目字段：

* 项目名称
* 主品牌
* 品牌别名
* 官网域名
* 竞品列表
* 行业
* 地区
* 语言
* 项目状态
* 创建时间

## 5.3 向导式项目创建

流程：

1. 输入品牌名称
2. 输入官网
3. 输入行业
4. 输入产品/服务描述
5. 输入竞品，可选
6. 选择监测平台
7. 生成初始Prompt建议
8. 用户确认Prompt
9. 创建第一次监测任务

## 5.4 Prompt问题库

### 5.4.1 Prompt字段

* Prompt正文
* 分组
* 意图类型
* 商业价值等级
* 目标客户阶段
* 地区
* 语言
* 是否品牌词
* 是否核心Prompt
* 是否启用

### 5.4.2 Prompt生成

输入：

* 品牌名
* 行业
* 产品描述
* 种子关键词
* 竞品名称
* 目标客户

输出：

* 20-100个候选Prompt

生成逻辑：

* LLM语义扩展
* 行业模板扩展
* 竞品对比问题扩展
* 采购意图问题扩展
* 品牌验证问题扩展

生成后必须让用户确认，不允许自动全部启用。

### 5.4.3 Prompt去重

至少支持文本相似度去重。

规则：

* 完全重复删除
* 高相似问题合并为问题簇
* 保留用户手动取消合并能力

## 5.5 平台支持

### 5.5.1 V1正式API监测源

优先支持：

* 千问 / 阿里百炼
* 文心 / 百度千帆
* Kimi
* 豆包 / 火山方舟
* DeepSeek模型认知

### 5.5.2 V1人工审计源

支持手动录入或上传：

* 腾讯元宝
* 豆包C端
* 文心一言C端
* Kimi App
* DeepSeek网页端
* 其他平台

人工审计数据必须标记为：

```text
manual_audit
```

不得和官方API数据混为同一口径。

### 5.5.2.1 V1文心助手网页端监测源

在浏览器插件 MVP 已验证可行的基础上，V1 增加“文心助手网页端监测模块”作为单平台完整链路试点。

该数据源用于采集文心助手 C 端页面中真实展示的回答、参考资料、引用 URL、检索候选源和证据文件。它不是官方 API 结果，必须单独标记为：

```text
browser_audit
```

平台入口建议命名：

```text
wenxin_web_audit
```

必须遵守：

* 使用管理员人工授权的浏览器 Profile；
* 不保存账号密码；
* 不自动登录；
* 不破解验证码；
* 不使用账号池、代理池、多账号并发；
* 默认文心网页端并发为1；
* 登录失效时标记为 login_required；
* 真实引用源 reference_sources 与检索候选源 retrieval_candidates 必须分表保存；
* URL解析率低于95%不得标记为完整成功；
* 所有运行必须保存截图、HTML、原始JSON、网络日志和采集日志。

详细工程规格见：

```text
geo-platform/docs/GEO_WENXIN_MONITORING_MODULE_SPEC.md
```

### 5.5.3 V1搜索信源数据源

支持接入：

* 百度搜索API或商业SERP API
* 腾讯联网搜索API
* 其他合规SERP数据供应商

用于信源层分析，不等同AI回答层结果。

---

## 5.6 周期监测

用户可以配置监测计划。

字段：

* 监测频率：手动 / 每周 / 每月
* 平台列表
* Prompt范围
* 重复采样次数
* 是否保存原始回答
* 是否抓取引用源快照
* 是否生成报告

默认建议：

* 每周一次
* 每个Prompt每平台重复3次
* 核心Prompt优先

---

## 5.7 AI答案分析

### 5.7.1 核心指标

系统必须计算：

1. 品牌提及率
2. 推荐入围率
3. Top推荐率
4. 竞品声量份额
5. 官网引用率
6. 第三方引用率
7. 信息准确率
8. 结果波动率
9. 平台成功率
10. 平台代表性等级

### 5.7.2 指标定义

#### 品牌提及率

```text
包含主品牌或品牌别名的有效回答数 / 有效回答总数
```

#### 推荐入围率

```text
主品牌作为推荐对象、候选供应商、解决方案或工具被正向列入的回答数 / 有效回答总数
```

#### Top推荐率

```text
主品牌出现在明确推荐列表前N位的回答数 / 有效回答总数
```

默认N=3。

#### 竞品声量份额

```text
主品牌提及次数 / 主品牌与全部竞品提及次数总和
```

#### 官网引用率

```text
引用主品牌官网域名的回答数 / 有引用的有效回答总数
```

#### 第三方引用率

```text
引用独立第三方来源支持主品牌的回答数 / 有引用的有效回答总数
```

#### 结果波动率

同一Prompt在同一平台多次采样中，品牌集合、竞品集合、推荐顺序的差异程度。

V1可先简化为：

```text
1 - 多次回答中品牌提及结果一致的比例
```

---

## 5.8 引用源分析

引用源分析分为“来源分析”和“内容分析”。

### 5.8.1 来源分析

每个引用URL需要识别：

* 域名
* URL
* 标题
* 摘要
* 页面类型
* 来源类型
* 所属关系
* 支持对象
* 首次出现时间
* 最近出现时间
* 被引用次数
* 关联Prompt数量
* 关联平台数量

### 5.8.2 页面类型枚举

* 官网首页
* 产品页
* 案例页
* 价格页
* 帮助文档
* 技术文档
* FAQ页
* 博客文章
* 新闻稿
* 行业媒体
* 第三方测评
* 榜单页
* 百科页
* 问答社区
* 论坛帖子
* 政府/协会页面
* 学术/白皮书
* 其他

### 5.8.3 来源类型枚举

* owned：自有资产
* competitor_owned：竞品资产
* third_party：第三方资产
* media：媒体
* community：社区
* search_result：搜索结果
* unknown：未知

### 5.8.4 支持对象

* 支持主品牌
* 支持竞品
* 中立比较
* 负面提及
* 无明确品牌支持

---

## 5.9 引用内容分析

V1必须做轻量内容分析。

对每个引用URL，系统抓取或保存：

* 页面标题
* 页面描述
* 可抽取正文
* 关键段落
* 品牌实体
* 产品特性词
* 场景词
* 证据类型
* 叙事标签
* 内容hash
* 抓取时间
* 页面截图，可选

### 5.9.1 产品特性词

从页面中抽取与产品能力相关的词，例如：

* 低成本
* 易部署
* 企业级
* 私有化
* 数据安全
* API
* 自动化
* 行业模板
* 多平台
* 可追踪
* 可复盘

具体词库由项目行业动态生成。

### 5.9.2 场景词

例如：

* 中小企业
* 制造业
* SaaS
* 出海
* 本地生活
* 教育培训
* 企业服务
* 采购选型
* 品牌监测
* 内容营销

### 5.9.3 证据类型

* 客户案例
* 数据指标
* 价格信息
* 第三方评测
* 认证资质
* 行业报告
* 产品参数
* 对比表
* 用户评价
* 媒体报道
* 官方说明

### 5.9.4 叙事标签

* 性价比高
* 适合中小企业
* 行业标杆
* 技术领先
* 易上手
* 生态完善
* 本土化强
* 安全合规
* 适合出海
* 服务稳定
* 价格透明
* 客户案例丰富

---

## 5.10 信源层监测

信源层用于回答：

```text
AI为什么可能推荐竞品，而不是推荐我？
```

### 5.10.1 监测内容

针对每个核心Prompt，同步查询搜索结果或联网搜索API。

保存：

* 搜索关键词 / Prompt
* 搜索结果标题
* 搜索结果摘要
* URL
* 排名位置
* 域名
* 是否出现主品牌
* 是否出现竞品
* 页面类型
* 来源类型
* 抓取时间

### 5.10.2 信源健康指标

* SERP品牌覆盖率
* SERP竞品覆盖率
* 第三方证据覆盖率
* 自有内容覆盖率
* 案例页覆盖率
* 测评/榜单覆盖率
* 搜索摘要可引用度
* 竞品信源优势主题

### 5.10.3 搜索摘要可引用度

V1可用LLM打分，范围0-100。

评分维度：

* 摘要是否包含品牌名
* 是否清晰表达产品能力
* 是否包含场景词
* 是否包含证据
* 是否适合被AI直接引用

---

## 5.11 内容生产建议

内容生产模块用于把“引用源诊断”和“信源缺口”转化为可执行的内容 Brief 和内容草稿，帮助内容团队知道应该补什么页面、补什么证据、覆盖哪些Prompt和场景。

V1阶段只做辅助生产和审核流，不做自动发布，不做自动外链，不绕过客户内容审核。

### 5.11.1 输入来源

系统可基于以下数据生成内容建议：

* 高价值Prompt下主品牌未被提及或未被推荐的回答
* 竞品被频繁引用的来源页面
* 第三方榜单、测评、案例、FAQ等高频引用页面
* 主品牌官网和自有内容的信源缺口
* 搜索摘要可引用度低的页面
* 优化动作后的前后变化

### 5.11.2 内容机会识别

系统需要识别：

* 缺失页面类型，例如案例页、FAQ页、对比页、价格说明页、行业解决方案页
* 缺失场景词，例如制造业、中小企业、出海、私有化部署
* 缺失证据类型，例如客户案例、数据指标、认证资质、第三方评测
* 缺失叙事标签，例如安全合规、部署快、成本低、服务稳定
* 竞品优势内容主题
* 可优先优化的现有URL

### 5.11.3 内容Brief生成

每条内容建议至少包含：

* 内容标题
* 内容类型
* 目标URL或建议新建URL
* 目标Prompt
* 目标关键词 / 场景词
* 需要覆盖的产品特性
* 需要补充的证据
* 建议结构大纲
* 建议FAQ
* 参考引用源
* 预期影响指标
* 优先级
* 风险提示

### 5.11.4 内容草稿生成

V1可支持生成可编辑草稿。

草稿类型：

* 官网产品页段落
* 行业解决方案页
* 客户案例页
* FAQ
* 竞品对比页
* 博客文章
* 白皮书大纲
* 媒体稿Brief

草稿必须标记为AI辅助生成，默认进入“待审核”状态，不允许自动发布。

### 5.11.5 内容审核与落地

内容建议状态：

* suggested：系统建议
* drafted：已生成草稿
* reviewing：审核中
* approved：已批准
* implemented：已落地
* rejected：已拒绝

当内容被落地后，可自动或手动创建一条优化动作记录，并关联后续效果复盘。

---

## 5.12 GEO档案库

所有数据都进入档案库。

档案类型：

1. AI回答快照
2. 引用源快照
3. 搜索结果快照
4. 引用内容版本
5. 优化动作记录
6. 监测报告
7. 人工审计记录
8. 内容建议与内容草稿

### 5.12.1 AI回答快照

字段：

* snapshot_id
* project_id
* prompt_id
* platform
* entry_type
* model
* model_version
* web_search_enabled
* query_time
* answer_text
* citations_json
* raw_response_json
* extracted_mentions_json
* content_hash

### 5.12.2 引用源快照

字段：

* source_snapshot_id
* url
* domain
* title
* meta_description
* extracted_text
* key_passages_json
* page_type
* source_type
* support_target
* content_hash
* fetched_at

### 5.12.3 优化动作记录

用户可手动记录优化动作。

字段：

* action_id
* project_id
* action_type
* action_title
* action_description
* related_url
* target_prompt_ids
* expected_effect
* action_date
* owner
* status

动作类型：

* 新增官网页面
* 修改页面标题
* 增加FAQ
* 增加案例页
* 发布博客
* 发布白皮书
* 发布媒体稿
* 获得外链
* 修正品牌信息
* 增加结构化数据
* 更新产品文档
* 其他

---

## 5.13 效果复盘

用户可以选择一个优化动作，查看动作前后的变化。

默认观察窗口：

* 动作前30天
* 动作后30天

V1展示：

* 品牌提及率变化
* 推荐入围率变化
* 官网引用率变化
* 第三方引用率变化
* 竞品声量变化
* 相关引用源变化
* 相关Prompt变化

注意：

V1不直接声称因果，只展示“相关变化”。

页面提示：

```text
以下为优化动作前后的监测变化，结果可能受模型版本、搜索源、竞品动作、平台策略变化影响。请结合原始快照和引用源变化进行判断。
```

---

## 5.14 报告导出

支持导出：

* PDF报告
* Markdown报告
* CSV原始数据
* 引用源列表
* Prompt表现表

V1报告结构：

1. 项目概览
2. 数据来源说明
3. 本周期监测范围
4. 品牌可见度总览
5. 平台表现对比
6. 竞品声量对比
7. 核心Prompt胜败场景
8. 引用源分析
9. 引用内容分析
10. 信源缺口
11. 内容生产建议
12. 优化动作建议
13. 原始证据附录

---

## 5.15 V1页面清单

### 页面1：首页 / 项目列表

展示：

* 项目名称
* 主品牌
* 监测平台数
* Prompt数
* 最近监测时间
* 品牌提及率
* 竞品声量份额
* 状态

### 页面2：项目创建向导

步骤：

1. 品牌信息
2. 竞品信息
3. 平台选择
4. Prompt生成
5. 监测设置
6. 确认创建

### 页面3：项目仪表盘

展示：

* 品牌提及率趋势
* 推荐入围率趋势
* 竞品声量份额
* 官网引用率
* 第三方引用率
* 平台成功率
* 最近变化摘要

### 页面4：Prompt库

功能：

* 新增Prompt
* 批量导入CSV
* 分组
* 意图分类
* 启用/停用
* 查看单Prompt历史表现

### 页面5：平台监测配置

展示：

* 已启用平台
* 数据入口
* 模型
* 是否联网
* 代表性等级
* 最近成功率
* 成本估算

### 页面6：监测任务列表

展示：

* 任务ID
* 项目
* 平台
* Prompt数量
* 观测次数
* 成功率
* 状态
* 开始时间
* 完成时间

### 页面7：原始回答快照

展示：

* Prompt
* 平台
* 模型
* 原始回答
* 引用URL
* 品牌抽取结果
* 竞品抽取结果
* 原始JSON

### 页面8：引用源分析

展示：

* URL
* 域名
* 页面类型
* 来源类型
* 支持对象
* 被引用次数
* 关联Prompt
* 关键段落
* 内容标签

### 页面9：信源诊断

展示：

* SERP品牌覆盖率
* SERP竞品覆盖率
* 第三方信源缺口
* 页面类型分布
* 竞品优势来源
* 建议补充内容类型

### 页面10：优化动作

功能：

* 记录动作
* 关联Prompt
* 关联URL
* 查看前后变化
* 生成复盘报告

### 页面11：内容生产

功能：

* 查看内容机会列表
* 生成内容Brief
* 生成可编辑内容草稿
* 关联目标Prompt和引用源
* 标记审核状态
* 转为优化动作

### 页面12：报告中心

功能：

* 生成报告
* 下载PDF
* 下载Markdown
* 下载CSV
* 查看历史报告

### 页面13：系统设置

功能：

* API Key配置
* 平台Adapter启用/停用
* 调用额度设置
* 任务并发设置
* 数据保留周期

---

# V2：商业增强版

目标：提升付费价值，支持代理商和企业长期使用。

周期建议：8-12周
核心目标：预警、深度归因、人工审计工作流、团队协作、用量计费。

---

## 6. V2功能范围

## 6.1 竞品动态预警

支持配置预警规则。

规则类型：

* 某竞品声量份额上升超过X%
* 主品牌提及率下降超过X%
* 官网引用率下降超过X%
* 新竞品首次出现
* 某平台连续失败
* 某引用源消失
* 某高价值Prompt下主品牌掉出推荐列表

通知方式：

* 站内通知
* 邮件
* 企业微信/飞书Webhook，可选

## 6.2 新对手发现

从AI答案和搜索结果中抽取未登记品牌。

触发条件：

* 同一未知品牌在多个Prompt中出现
* 同一未知品牌在多个平台中出现
* 未知品牌进入推荐列表Top N
* 未知品牌被第三方来源频繁引用

## 6.3 深度原因分析

针对竞品领先Prompt，自动生成诊断。

输出：

* 竞品被推荐原因
* 竞品引用源列表
* 竞品引用内容共性
* 我方缺失内容类型
* 我方缺失场景
* 我方缺失证据
* 建议优先级

诊断示例：

```text
在“适合中小制造企业的ERP系统”问题下，竞品A被推荐率高于主品牌。
主要原因：
1. 竞品A有更多中小制造业案例页被引用。
2. 竞品A在第三方榜单中出现频率更高。
3. 搜索摘要中频繁出现“部署快”“适合中小企业”等叙事标签。
4. 主品牌官网多为功能介绍，缺少场景化客户案例。
建议优先补充3篇中小制造业场景案例，并优化产品页摘要。
```

## 6.4 人工审计工作流

用于C端平台校准。

功能：

* 创建人工审计任务
* 分配审计人员
* 固定Prompt清单
* 上传截图
* 粘贴原始回答
* 填写引用URL
* 系统自动解析
* 与API结果对比
* 生成代表性等级

代表性等级：

* A：API与用户端高度一致
* B：趋势一致，具体顺序有差异
* C：只能参考，不可作为主报告
* D：不建议用于正式报告

## 6.5 优化实验

在V1“优化动作记录”基础上增强。

支持：

* 创建实验
* 设置干预组Prompt
* 设置观察组Prompt
* 记录动作时间
* 设置观察窗口
* 输出实验报告

实验报告包括：

* 干预组变化
* 观察组变化
* 同期竞品变化
* 平台变化
* 结果置信说明

注意：

产品不得声称强因果，只能输出“相关性证据”。

## 6.6 团队协作

支持：

* 任务分配
* 评论
* 标记待处理
* 标记已优化
* 给内容团队派发建议
* 导出任务清单

## 6.7 代理商模式

适合SEO/GEO服务商。

功能：

* 多客户空间
* 白标报告
* 客户只读链接
* 项目用量统计
* 客户维度成本统计
* 报告模板配置

## 6.8 用量与套餐

用量维度：

* 项目数
* Prompt数
* 平台数
* 重复采样次数
* 监测频率
* 引用源抓取次数
* 报告导出次数
* 人工审计任务数

不允许出现“无限Prompt、无限项目、无限平台”的套餐。

建议套餐：

### 免费诊断版

* 1个项目
* 10个Prompt
* 2个平台
* 单次监测
* 无周期任务
* 无报告导出或水印报告

### 试点版

* 1个项目
* 50个Prompt
* 3个平台
* 每周监测
* 6周周期
* 1份完整报告
* 适合5000元试点

### 专业版

* 3个项目
* 300个Prompt额度
* 5个平台
* 周监测
* 完整报告
* 优化动作复盘

### 代理商版

* 多项目
* 多客户
* 阶梯用量
* 白标报告
* 团队协作

---

## 7. 数据库设计建议

使用PostgreSQL。

### 7.1 核心表

#### users

* id
* email
* password_hash
* name
* created_at
* updated_at

#### organizations

* id
* name
* plan_type
* created_at
* updated_at

#### organization_members

* id
* organization_id
* user_id
* role
* created_at

#### projects

* id
* organization_id
* name
* brand_name
* brand_aliases_json
* website_url
* industry
* region
* language
* status
* created_at
* updated_at

#### competitors

* id
* project_id
* name
* aliases_json
* website_url
* created_at

#### prompts

* id
* project_id
* prompt_text
* prompt_group
* intent_type
* business_value
* customer_stage
* region
* language
* is_brand_prompt
* is_core
* enabled
* created_at
* updated_at

#### platform_adapters

* id
* platform_key
* platform_name
* entry_type
* enabled
* config_json
* representation_grade
* created_at
* updated_at

#### monitor_runs

* id
* project_id
* run_type
* status
* platform_keys_json
* prompt_count
* repeat_count
* started_at
* finished_at
* success_count
* failure_count
* cost_estimate
* error_summary_json

#### observations

* id
* run_id
* project_id
* prompt_id
* platform_key
* entry_type
* model
* model_version
* web_search_enabled
* sample_index
* status
* answer_text
* raw_response_json
* latency_ms
* cost_estimate
* queried_at
* content_hash

#### answer_citations

* id
* observation_id
* url
* title
* snippet
* source_name
* domain
* position
* created_at

#### extracted_mentions

* id
* observation_id
* brand_mentioned
* brand_recommended
* brand_first_position
* competitors_json
* cited_official_domain
* cited_competitor_domains_json
* sentiment
* extraction_json
* created_at

#### source_pages

* id
* url
* domain
* canonical_url
* first_seen_at
* last_seen_at

#### source_page_snapshots

* id
* source_page_id
* title
* meta_description
* extracted_text
* key_passages_json
* page_type
* source_type
* support_target
* content_tags_json
* content_hash
* fetched_at

#### serp_observations

* id
* project_id
* prompt_id
* provider
* query_text
* result_position
* url
* title
* snippet
* domain
* brand_mentioned
* competitors_mentioned_json
* fetched_at

#### optimization_actions

* id
* project_id
* action_type
* title
* description
* related_url
* target_prompt_ids_json
* expected_effect
* action_date
* owner_user_id
* status
* created_at

#### content_recommendations

* id
* project_id
* source_type
* opportunity_type
* title
* content_type
* target_url
* target_prompt_ids_json
* related_source_page_ids_json
* target_keywords_json
* feature_terms_json
* scenario_terms_json
* evidence_requirements_json
* suggested_outline_json
* suggested_faq_json
* priority
* expected_effect
* risk_notes
* status
* created_at
* updated_at

#### content_drafts

* id
* project_id
* recommendation_id
* draft_type
* title
* outline_json
* body_markdown
* ai_generation_meta_json
* reviewer_user_id
* status
* created_at
* updated_at

#### reports

* id
* project_id
* report_type
* period_start
* period_end
* report_json
* markdown_content
* pdf_url
* created_at

#### manual_audits

* id
* project_id
* platform_name
* prompt_id
* auditor_user_id
* answer_text
* screenshot_url
* citations_json
* audit_time
* created_at

#### alerts

* id
* project_id
* rule_type
* threshold_json
* enabled
* last_triggered_at
* created_at

---

## 8. 后端接口建议

后端使用FastAPI。

### 8.1 项目

```text
POST /api/projects
GET /api/projects
GET /api/projects/{project_id}
PUT /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

### 8.2 竞品

```text
POST /api/projects/{project_id}/competitors
GET /api/projects/{project_id}/competitors
PUT /api/competitors/{competitor_id}
DELETE /api/competitors/{competitor_id}
```

### 8.3 Prompt

```text
POST /api/projects/{project_id}/prompts
POST /api/projects/{project_id}/prompts/import
POST /api/projects/{project_id}/prompts/generate
GET /api/projects/{project_id}/prompts
PUT /api/prompts/{prompt_id}
DELETE /api/prompts/{prompt_id}
```

### 8.4 监测任务

```text
POST /api/projects/{project_id}/monitor-runs
GET /api/projects/{project_id}/monitor-runs
GET /api/monitor-runs/{run_id}
POST /api/monitor-runs/{run_id}/cancel
```

### 8.5 观测结果

```text
GET /api/projects/{project_id}/observations
GET /api/observations/{observation_id}
GET /api/projects/{project_id}/metrics/overview
GET /api/projects/{project_id}/metrics/platforms
GET /api/projects/{project_id}/metrics/competitors
GET /api/projects/{project_id}/metrics/prompts
```

### 8.6 引用源

```text
GET /api/projects/{project_id}/citations
GET /api/source-pages/{source_page_id}
POST /api/source-pages/fetch
GET /api/projects/{project_id}/source-diagnostics
```

### 8.7 优化动作

```text
POST /api/projects/{project_id}/optimization-actions
GET /api/projects/{project_id}/optimization-actions
GET /api/optimization-actions/{action_id}
PUT /api/optimization-actions/{action_id}
GET /api/optimization-actions/{action_id}/impact
```

### 8.8 内容生产

```text
POST /api/projects/{project_id}/content-recommendations/generate
GET /api/projects/{project_id}/content-recommendations
GET /api/content-recommendations/{recommendation_id}
PUT /api/content-recommendations/{recommendation_id}
POST /api/content-recommendations/{recommendation_id}/drafts
GET /api/content-drafts/{draft_id}
PUT /api/content-drafts/{draft_id}
POST /api/content-recommendations/{recommendation_id}/convert-to-action
```

### 8.9 报告

```text
POST /api/projects/{project_id}/reports
GET /api/projects/{project_id}/reports
GET /api/reports/{report_id}
GET /api/reports/{report_id}/download
```

### 8.10 人工审计

```text
POST /api/projects/{project_id}/manual-audits
GET /api/projects/{project_id}/manual-audits
GET /api/projects/{project_id}/representation
```

---

## 9. 技术架构建议

### 9.1 前端

建议：

* React
* Vite
* TypeScript
* Ant Design
* ECharts / Recharts
* TanStack Query

### 9.2 后端

建议：

* Python
* FastAPI
* SQLAlchemy
* Alembic
* PostgreSQL
* Redis
* Celery / RQ
* Pydantic

### 9.3 存储

* PostgreSQL：结构化数据
* S3兼容对象存储：截图、PDF、原始快照文件
* Redis：任务队列和缓存

### 9.4 LLM调用

统一封装：

* Provider Client
* Adapter Interface
* Retry Policy
* Rate Limit
* Cost Tracking
* Raw Response Storage

### 9.5 Adapter接口

所有平台Adapter必须实现：

```python
class BaseAIAdapter:
    platform_key: str
    entry_type: str

    async def run_query(
        self,
        prompt: str,
        model: str | None = None,
        web_search_enabled: bool = True,
        metadata: dict | None = None
    ) -> AdapterResult:
        pass
```

统一结果：

```python
class AdapterResult(BaseModel):
    platform: str
    entry_type: str
    model: str | None
    model_version: str | None
    web_search_enabled: bool
    answer_text: str | None
    citations: list[Citation]
    raw_response: dict
    status: Literal["success", "failed", "partial"]
    error_code: str | None
    error_message: str | None
    latency_ms: int
    token_usage: dict | None
    cost_estimate: float | None
```

---

## 10. 合规与安全要求

### 10.1 禁止项

系统不得实现：

* 批量注册AI平台账号
* 账号池轮换
* 代理池绕过风控
* 验证码打码
* 自动化操作C端登录态产品
* 未经授权抓取登录后内容
* 隐藏数据来源

### 10.2 必须项

系统必须做到：

* 所有结果保留数据来源标签
* API Key加密存储
* 原始数据可追溯
* 客户数据隔离
* 日志脱敏
* 支持删除项目数据
* 支持配置数据保留周期

---

## 11. 关键验收指标

### V0验收

* 至少3个官方API Adapter可用
* 10个Prompt × 3个平台 × 3次重复采样跑通
* 原始回答和引用URL完整入库
* 基础提及率计算正确
* 所有结果带数据源标签

### V1验收

* 支持组织、项目、Prompt、竞品、周期监测
* 支持至少4个国内主流平台数据入口
* 支持引用源来源分析
* 支持引用内容快照
* 支持优化动作记录
* 支持报告导出
* 可用于3家种子客户试点

### V2验收

* 支持竞品动态预警
* 支持人工审计工作流
* 支持优化实验
* 支持代理商多客户模式
* 支持用量统计和套餐限制
* 支持白标报告

---

## 12. Codex开发执行顺序

### Step 1：初始化项目

创建目录：

```text
geo-platform/
├── backend/
├── frontend/
├── docs/
├── scripts/
├── docker-compose.yml
└── README.md
```

### Step 2：后端基础

完成：

* FastAPI项目
* PostgreSQL连接
* SQLAlchemy模型
* Alembic迁移
* 用户/组织/项目/Prompt/竞品表
* 基础CRUD接口

### Step 3：Adapter系统

完成：

* BaseAIAdapter
* MockAdapter
* QwenAdapter
* KimiAdapter
* WenxinAdapter
* DeepSeekAdapter
* AdapterResult统一结构
* 原始响应存储

### Step 4：监测任务系统

完成：

* monitor_runs表
* observations表
* 后台任务队列
* 重复采样
* 失败重试
* 成本记录
* 状态查询

### Step 4.1：文心助手网页端监测模块

完成：

* wenxin_web_audit 数据源入口
* 浏览器 Profile 登录态管理
* Playwright 文心采集器
* 当前问题与回答绑定
* 回答完成判断
* 参考资料面板展开与懒加载
* 真实引用源 reference_sources 入库
* 检索候选源 retrieval_candidates 入库
* 品牌提及与推荐强度分析
* 证据文件保存
* 运行状态机
* 失败重试
* 前端运行列表与运行详情

详细实现以 `geo-platform/docs/GEO_WENXIN_MONITORING_MODULE_SPEC.md` 为准。

### Step 5：抽取与指标

完成：

* 品牌提及规则抽取
* 竞品提及规则抽取
* 引用URL解析
* 官网引用率
* 竞品声量份额
* 项目概览接口

### Step 6：前端V0页面

完成：

* 项目列表
* 项目创建
* Prompt管理
* 发起监测
* 监测任务列表
* 原始回答详情
* 基础仪表盘

### Step 7：V1引用源系统

完成：

* citation表
* source_pages表
* source_page_snapshots表
* URL抓取
* 页面类型分类
* 来源类型分类
* 内容标签抽取
* 引用源分析页

### Step 8：V1报告系统

完成：

* report生成
* Markdown导出
* PDF导出
* CSV导出
* 报告中心页面

### Step 9：V1内容生产系统

完成：

* content_recommendations表
* content_drafts表
* 基于引用源和信源缺口生成内容机会
* 内容Brief生成
* 可编辑草稿生成
* 内容生产页面
* 内容建议转优化动作

### Step 10：V1优化动作

完成：

* optimization_actions表
* 动作记录页面
* 动作前后指标对比
* 复盘报告

### Step 11：V2增强

完成：

* 预警规则
* 人工审计
* 实验对比
* 内容协作与发布状态追踪
* 代理商模式
* 用量统计

---

## 13. 给Codex的首轮开发Prompt

请基于本PRD开发一个“AI品牌可见度监测与信源诊断平台”的V0版本。

技术栈要求：

* 后端：Python + FastAPI + SQLAlchemy + Alembic + PostgreSQL
* 前端：React + Vite + TypeScript + Ant Design
* 任务队列：Redis + Celery或RQ
* 图表：ECharts或Recharts
* 项目需要支持Docker Compose本地启动

第一阶段只做V0，不要实现V1/V2。

V0必须完成：

1. 用户、组织、项目、竞品、Prompt基础数据模型。
2. 创建项目，录入品牌、官网、竞品、Prompt。
3. 实现统一AI平台Adapter接口。
4. 实现MockAdapter，并预留Qwen/Kimi/Wenxin/DeepSeek Adapter文件。
5. 实现监测任务：选择Prompt、选择平台、设置重复次数，后台执行。
6. 保存每次观测的原始Prompt、原始回答、引用URL、原始响应JSON、平台、模型、是否联网、查询时间。
7. 实现基础抽取：主品牌是否出现、竞品是否出现、是否引用官网。
8. 实现基础指标：品牌提及率、竞品提及率、官网引用率、平台成功率。
9. 前端实现项目列表、项目详情、Prompt管理、发起监测、任务列表、原始回答详情、基础仪表盘。
10. 不要实现账号池、代理池、C端网页自动化抓取。
11. 所有观测结果必须保存数据来源标签 entry_type。
12. 代码结构要清晰，Adapter可插拔，后续能扩展到V1引用源分析。

开发完成后，请输出：

* 项目目录结构
* 后端启动方式
* 前端启动方式
* 数据库迁移方式
* Docker Compose启动方式
* 已实现功能清单
* 未实现但已预留的接口
* 下一步V1开发建议

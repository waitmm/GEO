# GEO 工程：文心助手完整监测模块 Coding 规格

> 用途：直接交给 Codex 开发  
> 模块定位：GEO 平台内的核心监测模块，而非独立实验采集器  
> 目标：一次性完成“任务配置 → 自动采集 → 数据入库 → GEO 分析 → 前端展示 → 重试复盘”的完整主链路  
> 开发原则：先把完整链路跑通，再针对文心页面细节和稳定性做迭代微调  
> 推荐技术栈：FastAPI + SQLAlchemy 2.x + PostgreSQL + Redis + Celery/RQ + Playwright + React/Next.js 或现有前端技术栈

---

# 1. 模块目标

在现有 GEO 工程中新增“AI 平台监测”大模块，首个平台支持文心助手。

用户可在后台完成：

```text
选择项目
→ 配置品牌
→ 添加监测问题
→ 选择文心助手
→ 创建监测任务
→ 系统自动执行
→ 获得回答、品牌表现、引用来源和证据
→ 查看单次结果及多次趋势
```

系统必须完整记录：

1. 用户原始问题；
2. 文心实际检索改写词；
3. 文心完整回答；
4. 目标品牌是否被提及；
5. 品牌提及次数；
6. 品牌首次出现位置；
7. 品牌推荐强度；
8. 回答中真实展示的参考资料；
9. 每条参考资料的标题、URL、域名和顺序；
10. 检索候选源；
11. 引用解析方法和置信度；
12. 页面截图、HTML、网络响应和日志；
13. 运行状态和失败阶段；
14. 同一问题多次运行的稳定性数据。

---

# 2. 当前可行性结论

文心引用源 Tampermonkey MVP 已完成验证。

成功样本：

```text
问题：谁是最好的二维码工具
页面参考资料：29
采集标题：29
解析标题+URL：29
标题完全匹配：26
模糊标题匹配：1
同节点序号绑定：2
最终URL：29
未解析：0
异常：0
```

已验证能力：

- 当前问题与回答绑定；
- 参考资料数量识别；
- 重复标题保留；
- 参考标题提取；
- 同一引用节点真实 URL 解析；
- linkUrl/linkTitle 编码数据解码；
- 结构化结果输出。

因此本次开发不再做“技术能否实现”的验证，而是直接工程化。

---

# 3. 完整业务链路

```text
GEO 项目
  ↓
品牌配置
  ↓
监测问题库
  ↓
创建监测任务
  ↓
任务调度队列
  ↓
文心 Playwright Worker
  ↓
获取回答 + 引用 + 候选检索源
  ↓
保存原始证据
  ↓
写入监测运行表
  ↓
品牌提及分析
  ↓
引用源相关性与质量分析
  ↓
生成单次监测结果
  ↓
聚合多次运行趋势
  ↓
前端结果页展示
```

---

# 4. 模块边界

## 4.1 本次必须开发

- 项目品牌配置；
- 监测问题管理；
- 文心平台任务配置；
- 单次立即执行；
- 批量执行问题；
- Worker 队列；
- Playwright 文心采集器；
- 登录态管理；
- 回答采集；
- 引用标题和 URL 采集；
- 候选检索源采集；
- 结果数据库；
- 品牌提及分析；
- 引用域名聚合；
- 单次结果详情；
- 问题运行历史；
- 基础重试；
- 证据文件；
- 错误日志；
- 运行状态展示。

## 4.2 本次预留接口但可暂不深化

- 定时任务；
- 多地区；
- 多账号池；
- 多平台；
- 代理池；
- 自动验证码处理；
- 情感模型精细分析；
- LLM 高级内容评估；
- 商业报告自动生成。

---

# 5. 推荐总目录

需优先适配现有项目结构。以下为逻辑目录，Codex 不得为套用目录而重构无关代码。

```text
backend/
├── app/
│   ├── modules/
│   │   └── monitoring/
│   │       ├── api/
│   │       │   ├── projects.py
│   │       │   ├── questions.py
│   │       │   ├── tasks.py
│   │       │   └── runs.py
│   │       │
│   │       ├── collectors/
│   │       │   ├── base.py
│   │       │   ├── registry.py
│   │       │   └── wenxin/
│   │       │       ├── collector.py
│   │       │       ├── browser.py
│   │       │       ├── selectors.py
│   │       │       ├── completion_detector.py
│   │       │       ├── answer_locator.py
│   │       │       ├── reference_locator.py
│   │       │       ├── reference_parser.py
│   │       │       ├── network_capture.py
│   │       │       ├── url_normalizer.py
│   │       │       └── exceptions.py
│   │       │
│   │       ├── models/
│   │       │   ├── monitoring_project.py
│   │       │   ├── project_brand.py
│   │       │   ├── monitoring_question.py
│   │       │   ├── monitoring_task.py
│   │       │   ├── monitoring_run.py
│   │       │   ├── reference_source.py
│   │       │   ├── retrieval_candidate.py
│   │       │   ├── brand_mention.py
│   │       │   └── run_artifact.py
│   │       │
│   │       ├── schemas/
│   │       │   ├── project.py
│   │       │   ├── question.py
│   │       │   ├── task.py
│   │       │   ├── run.py
│   │       │   └── reference.py
│   │       │
│   │       ├── services/
│   │       │   ├── project_service.py
│   │       │   ├── question_service.py
│   │       │   ├── task_service.py
│   │       │   ├── run_service.py
│   │       │   ├── artifact_service.py
│   │       │   ├── brand_analysis_service.py
│   │       │   ├── reference_analysis_service.py
│   │       │   └── aggregation_service.py
│   │       │
│   │       ├── workers/
│   │       │   ├── monitoring_worker.py
│   │       │   └── task_executor.py
│   │       │
│   │       └── enums.py
│   │
│   └── main.py
│
├── scripts/
│   ├── create_wenxin_profile.py
│   ├── check_wenxin_session.py
│   └── run_wenxin_once.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
└── artifacts/
```

前端：

```text
frontend/
├── src/
│   ├── pages/
│   │   └── monitoring/
│   │       ├── index.tsx
│   │       ├── questions.tsx
│   │       ├── tasks.tsx
│   │       ├── runs.tsx
│   │       └── runs/[id].tsx
│   │
│   ├── components/
│   │   └── monitoring/
│   │       ├── ProjectSelector.tsx
│   │       ├── BrandConfigForm.tsx
│   │       ├── QuestionTable.tsx
│   │       ├── TaskCreateForm.tsx
│   │       ├── RunStatusBadge.tsx
│   │       ├── BrandMentionCard.tsx
│   │       ├── ReferenceTable.tsx
│   │       ├── CandidateTable.tsx
│   │       ├── EvidencePanel.tsx
│   │       └── RunTrendChart.tsx
```

---

# 6. 数据模型

## 6.1 monitoring_projects

```text
id
name
description
status
created_at
updated_at
```

## 6.2 project_brands

```text
id
project_id
brand_name
brand_aliases JSON
official_domains JSON
competitor_names JSON
created_at
updated_at
```

示例：

```json
{
  "brand_name": "八木屋二维码",
  "brand_aliases": ["八木屋", "bamuwu"],
  "official_domains": ["bamuwu.com"],
  "competitor_names": ["草料二维码", "码上游", "互联二维码"]
}
```

## 6.3 monitoring_questions

```text
id
project_id
question
question_group
intent_type
priority
enabled
created_at
updated_at
```

## 6.4 monitoring_tasks

```text
id
project_id
platform
question_id
run_count
schedule_type
status
created_by
created_at
updated_at
```

`platform` 当前只允许：

```text
wenxin
```

状态：

```text
pending
queued
running
completed
partial_completed
failed
cancelled
```

## 6.5 monitoring_runs

```text
id
task_id
project_id
question_id
platform
run_sequence

status
stage

original_query
page_query
retrieval_query

started_at
finished_at
duration_ms

answer_text
answer_html
answer_char_count

expected_reference_count
detected_reference_count
resolved_reference_count
unresolved_reference_count
reference_complete

brand_mentioned
brand_mention_count
brand_first_position
brand_recommendation_level

error_type
error_message
retry_count

created_at
updated_at
```

## 6.6 reference_sources

```text
id
run_id

reference_index
display_title
matched_title

url
canonical_url
domain
platform_name

resolution_method
match_confidence
evidence_path

relevance_label
quality_label
is_official_domain
is_competitor_domain

created_at
```

## 6.7 retrieval_candidates

```text
id
run_id

retrieval_query
rank
title
url
canonical_url
domain
snippet
evidence_path

created_at
```

## 6.8 brand_mentions

```text
id
run_id
brand_name
alias_matched
mention_count
first_char_position
first_paragraph_index
recommendation_level
context_snippets JSON
created_at
```

## 6.9 run_artifacts

```text
id
run_id
artifact_type
storage_path
mime_type
size_bytes
created_at
```

`artifact_type`：

```text
page_screenshot
reference_screenshot
page_html
answer_html
reference_html
network_log
raw_result
collector_log
```

---

# 7. 数据关系

```text
monitoring_project
├── project_brands
├── monitoring_questions
└── monitoring_tasks
    └── monitoring_runs
        ├── reference_sources
        ├── retrieval_candidates
        ├── brand_mentions
        └── run_artifacts
```

---

# 8. 后端 API

## 8.1 项目

```http
POST   /api/monitoring/projects
GET    /api/monitoring/projects
GET    /api/monitoring/projects/{id}
PUT    /api/monitoring/projects/{id}
```

## 8.2 品牌

```http
PUT /api/monitoring/projects/{id}/brand
GET /api/monitoring/projects/{id}/brand
```

## 8.3 问题

```http
POST   /api/monitoring/projects/{id}/questions
POST   /api/monitoring/projects/{id}/questions/batch
GET    /api/monitoring/projects/{id}/questions
PUT    /api/monitoring/questions/{id}
DELETE /api/monitoring/questions/{id}
```

批量导入：

```json
{
  "questions": [
    "谁是最好的二维码工具",
    "二维码除了草料还有哪个",
    "企业二维码平台推荐"
  ]
}
```

## 8.4 创建任务

```http
POST /api/monitoring/tasks
```

请求：

```json
{
  "project_id": "uuid",
  "platform": "wenxin",
  "question_ids": ["uuid-1", "uuid-2"],
  "run_count": 3,
  "execute_now": true
}
```

响应：

```json
{
  "task_ids": ["uuid"],
  "queued_run_count": 6
}
```

## 8.5 任务列表

```http
GET /api/monitoring/tasks
```

筛选：

```text
project_id
platform
status
date_from
date_to
```

## 8.6 运行列表

```http
GET /api/monitoring/runs
```

筛选：

```text
project_id
question_id
platform
status
brand_mentioned
date_from
date_to
```

## 8.7 运行详情

```http
GET /api/monitoring/runs/{run_id}
```

返回：

- 回答；
- 品牌分析；
- 引用源；
- 检索候选；
- 指标；
- 证据；
- 错误。

## 8.8 重试

```http
POST /api/monitoring/runs/{run_id}/retry
```

---

# 9. 任务执行与队列

推荐 Redis + Celery 或项目现有队列。

创建任务时：

```text
一个 question
× run_count
= 多个 monitoring_run
```

例如：

```text
3个问题 × 每题3次 = 9个 run
```

队列载荷：

```json
{
  "run_id": "uuid",
  "platform": "wenxin"
}
```

Worker：

```python
@worker.task
def execute_monitoring_run(run_id: str):
    asyncio.run(task_executor.execute(run_id))
```

---

# 10. Worker 状态机

```text
queued
→ launching_browser
→ checking_login
→ opening_platform
→ submitting_query
→ waiting_answer
→ locating_answer
→ opening_references
→ loading_references
→ parsing_references
→ capturing_evidence
→ analyzing_brand
→ saving_result
→ success
```

异常分支：

```text
login_required
captcha_required
answer_timeout
reference_not_found
reference_incomplete
parse_failed
browser_crashed
unknown_error
```

每次状态变化写入 `monitoring_runs.stage`。

---

# 11. 浏览器会话

## 11.1 持久化 Profile

```python
context = await playwright.chromium.launch_persistent_context(
    user_data_dir=settings.WENXIN_PROFILE_DIR,
    headless=settings.WENXIN_HEADLESS,
    viewport={"width": 1440, "height": 1000},
    locale="zh-CN",
    timezone_id="Asia/Shanghai",
)
```

## 11.2 登录态

提供：

```bash
python scripts/create_wenxin_profile.py
```

首次由管理员人工登录。

系统不得：

- 保存账号密码；
- 自动破解短信；
- 自动绕过验证码。

检测未登录时：

```text
status = failed
error_type = login_required
```

后台页面显示“文心账号登录态失效”。

---

# 12. 文心采集器接口

```python
class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, run: MonitoringRun) -> CollectorResult:
        ...

    @abstractmethod
    async def health_check(self) -> CollectorHealth:
        ...


class WenxinCollector(BaseCollector):
    async def collect(self, run: MonitoringRun) -> CollectorResult:
        ...
```

注册：

```python
COLLECTOR_REGISTRY = {
    "wenxin": WenxinCollector,
}
```

---

# 13. 文心采集完整流程

```python
async def collect(self, run):
    page = await self.browser.new_page()

    await self.network_capture.attach(page, run.id)

    await self.open_home(page)
    await self.ensure_logged_in(page)
    await self.start_new_conversation(page)

    await self.submit_query(page, run.original_query)

    completion = await self.wait_for_answer_complete(
        page,
        run.original_query,
    )

    answer_context = await self.answer_locator.locate(
        page,
        run.original_query,
    )

    answer = await self.extract_answer(answer_context)

    reference_context = await self.reference_locator.locate(
        page,
        answer_context,
    )

    await self.reference_locator.open(reference_context)
    await self.reference_locator.exhaust_lazy_loading(
        reference_context,
    )

    references = await self.reference_parser.extract_all(
        reference_context,
    )

    candidates = self.network_capture.extract_candidates()

    artifacts = await self.artifact_service.capture(
        page=page,
        answer_context=answer_context,
        reference_context=reference_context,
    )

    return CollectorResult(
        answer=answer,
        references=references,
        retrieval_candidates=candidates,
        artifacts=artifacts,
    )
```

---

# 14. 自动提问

输入框候选：

```text
textarea
[contenteditable="true"][role="textbox"]
[contenteditable="true"]
```

选择：

- 可见；
- 位于主内容区；
- 可输入；
- 最后一个可见输入框优先。

提交：

1. 点击输入框；
2. 填入完整问题；
3. 按 Enter；
4. 若未发送，则找发送按钮；
5. 验证页面出现原问题。

---

# 15. 回答完成判断

不得使用固定 20 秒等待。

每秒读取当前回答：

```text
文本长度
文本哈希
停止按钮
参考入口
```

完成条件：

```text
连续3次回答文本不变
AND
停止生成按钮消失
AND/OR
参考资料入口出现
```

最大等待：

```text
180秒
```

超时也要保存当前页面证据。

---

# 16. 当前问题与回答绑定

防止抓到历史回答。

流程：

1. 定位与原始问题文本一致的用户消息节点；
2. 找其后最近的回答区域；
3. 找回答附近的“共参考 N 篇资料”；
4. 计算共同祖先；
5. 计算几何距离；
6. 选最高分组合。

打分：

```text
参考入口位于回答上方：+100
横向重叠：+60
共享对话祖先：+160 - depth*15
距离过远：扣分
问题节点位于回答前：必须
```

---

# 17. 参考入口

文本规则：

```regex
共参考\s*(\d+)\s*篇资料
```

获取：

```python
expected_reference_count
trigger_locator
bounding_box
```

---

# 18. 参考面板与懒加载

点击入口后寻找：

```text
[role="dialog"]
[aria-modal="true"]
[class*="popover"]
[class*="drawer"]
[class*="reference"]
[class*="source"]
```

面板打分：

```text
可见
文本长度
含参考资料关键词
可点击元素数量
靠近参考入口
```

滚动：

```python
for _ in range(30):
    count = await count_items()

    if count >= expected_count:
        break

    scroll_container.scrollTop = scroll_container.scrollHeight
    await wait(400ms)

    if count连续3轮不变:
        break
```

若：

```text
detected_count < expected_count
```

运行结果标为：

```text
partial_success
```

---

# 19. 引用标题提取

候选节点：

```text
a
button
[role="link"]
[data-url]
[data-href]
[data-link]
div
span
p
```

过滤：

- 不可见；
- 文本过短；
- 文本超过300字；
- 展开、收起、复制、关闭；
- “共参考N篇资料”；
- 父子节点完全重复。

禁止标题去重。

结果：

```python
ReferenceDomItem(
    reference_index=1,
    display_title="...",
    locator=locator,
)
```

---

# 20. 真实 URL 解析优先级

```text
P1 当前引用节点直接 href/data-url
P2 当前引用节点或父节点 linkUrl/linkTitle
P3 React/Vue 内部 props
P4 window.open 点击兜底
P5 retrieval candidate 标题匹配
P6 unresolved
```

V1 首版必须完成：

```text
P1 + P2 + P4 + P5
```

---

# 21. linkUrl/linkTitle 解码

支持：

```text
标准 JSON
& quot;
&#34;
%22
%3A
%2C
\u0022
\u0026
URL与linkTitle粘连
logInfo尾部
标题百分号编码
```

核心函数：

```python
normalize_serialized_text()
parse_standard_link_pair()
parse_malformed_link_pair()
clean_resolved_url()
clean_resolved_title()
```

同一引用节点向上最多检查 6 层：

```text
href
data-url
data-href
data-link
data-source-url
data-target-url
outerHTML
```

---

# 22. 引用绑定规则

## 完全一致

```text
resolution_method:
serialized-same-reference-exact-title

confidence:
1.0
```

## 模糊一致

标题相似度 >= 0.72：

```text
serialized-same-reference-fuzzy-title
```

## 同节点绑定

同一引用 DOM 节点内找到有效 URL，但内部标题不同：

```text
serialized-same-reference-index
confidence = 0.9
```

不是跨列表按顺序猜测。

---

# 23. 点击兜底

逐条处理未解析引用：

```python
async with page.expect_popup(timeout=3000):
    await item.click()
```

捕获：

```text
popup.url
redirect chain
```

然后关闭。

若无 popup，同时监听：

```text
window.open
context.on("page")
request
navigation
```

每条引用最大兜底时间：

```text
3秒
```

不能因一条失败阻塞全部任务。

---

# 24. 检索候选源

监听：

```text
/csaitab/searchresult
/aichat/api/
/conversation
/answer
```

从响应递归提取：

```text
url
href
link
targetUrl
landUrl
tcUrl
titleUrl
jumpUrl
```

只写入：

```text
retrieval_candidates
```

禁止直接混入真实引用表。

---

# 25. 静态资源过滤

排除：

```text
t7.baidu.com
t8.baidu.com
t9.baidu.com
ss0.baidu.com
ss1.baidu.com
gips*.baidu.com
*.bdstatic.com
```

排除扩展名：

```text
png jpg jpeg gif webp svg ico
css js mjs map
woff woff2 ttf
mp4 webm mp3
```

---

# 26. 品牌分析

输入：

```text
answer_text
brand_name
brand_aliases
competitor_names
official_domains
references
```

输出：

```text
brand_mentioned
brand_mention_count
first_char_position
first_paragraph_index
recommendation_level
context_snippets
competitor_mentions
official_domain_cited
```

## 26.1 提及判断

品牌名和别名统一匹配。

例如：

```text
八木屋二维码
八木屋
bamuwu
```

## 26.2 推荐强度

初版规则：

```text
0 = 未提及
1 = 仅提及
2 = 作为候选推荐
3 = 明确正向推荐
4 = 首选/最佳推荐
```

关键词规则：

```text
推荐
适合
首选
最佳
值得选择
排名第一
```

初版允许规则判断，保留后续 LLM 分析接口。

## 26.3 竞争对手

记录：

```json
[
  {
    "brand": "草料二维码",
    "mention_count": 5,
    "first_position": 120
  }
]
```

---

# 27. 引用源分析

每条引用增加：

```text
is_official_domain
is_competitor_domain
relevance_label
quality_label
```

## 27.1 初版自动规则

`relevance_label`：

```text
relevant
weakly_relevant
irrelevant
unreviewed
```

根据：

- 标题与问题关键词相似度；
- 标题与回答主题相似度；
- 域名类型；
- 是否明显下载站、垃圾页。

`quality_label`：

```text
official
media
ugc
app_store
download_site
unknown
suspicious
```

第一个版本规则即可，后续再接 LLM。

---

# 28. 聚合指标

按问题多次运行聚合：

```text
运行次数
成功次数
成功率
品牌提及率
平均提及次数
平均首次出现位置
推荐率
官方域名引用率
平均引用数量
引用URL解析率
来源域名稳定度
答案文本相似度
引用来源重复率
```

## 28.1 来源稳定度

```text
某域名出现次数 / 成功运行次数
```

## 28.2 品牌提及率

```text
品牌被提及运行数 / 成功运行数
```

---

# 29. 前端页面

## 29.1 监测总览

展示：

- 项目；
- 品牌；
- 问题数量；
- 运行次数；
- 成功率；
- 品牌提及率；
- 引用解析率；
- 最近异常。

## 29.2 问题库

表格：

```text
问题
分组
优先级
启用状态
最近运行
品牌提及率
运行次数
操作
```

操作：

```text
立即监测
编辑
停用
查看历史
```

## 29.3 创建任务

字段：

```text
项目
平台：文心助手
问题：多选
每题运行次数
立即执行
```

## 29.4 任务列表

```text
任务
平台
问题数
计划运行数
已完成
成功
失败
状态
创建时间
```

## 29.5 运行列表

```text
问题
平台
状态
品牌是否出现
引用数量
解析数量
开始时间
耗时
```

## 29.6 运行详情

顶部指标：

```text
运行状态
品牌是否提及
提及次数
推荐强度
参考数量
URL解析率
运行耗时
```

内容区域：

### 回答

完整回答正文，品牌关键词高亮。

### 品牌表现

- 命中别名；
- 首次出现位置；
- 推荐上下文；
- 竞争对手出现情况。

### 真实引用源

表格：

```text
序号
标题
域名
URL
来源类型
解析方式
置信度
相关性
质量
```

### 检索候选源

单独 Tab，不得与真实引用混合。

### 证据

- 页面截图；
- 参考资料截图；
- 页面 HTML；
- 原始 JSON；
- 网络日志；
- Collector 日志。

### 错误

显示：

```text
失败阶段
错误类型
错误信息
重试次数
```

---

# 30. 证据目录

```text
artifacts/
└── monitoring/
    └── <run_id>/
        ├── result.json
        ├── page.png
        ├── reference-panel.png
        ├── page.html
        ├── answer.html
        ├── reference-panel.html
        ├── network.jsonl
        └── collector.log
```

数据库只存路径，不存大型正文文件。

---

# 31. 重试策略

自动重试最多：

```text
2次
```

可重试：

```text
browser_crashed
answer_timeout
reference_panel_not_opened
network_error
temporary_parse_failure
```

不自动重试：

```text
login_required
captcha_required
configuration_error
```

退避：

```text
第1次：30秒
第2次：120秒
```

每次重试必须：

- 新建 run attempt 或记录 attempt；
- 保留上一次证据；
- 不覆盖失败现场。

---

# 32. 并发限制

MVP 默认：

```text
文心并发 = 1
```

原因：

- 登录态；
- 页面风控；
- Profile 锁；
- 稳定优先。

后续再扩展多 profile。

---

# 33. 配置项

`.env.example`：

```env
MONITORING_ARTIFACT_DIR=./artifacts/monitoring

REDIS_URL=redis://localhost:6379/0

WENXIN_PROFILE_DIR=./runtime/wenxin-profile
WENXIN_HEADLESS=false
WENXIN_TIMEOUT_SECONDS=180
WENXIN_MAX_CONCURRENCY=1
WENXIN_MAX_RETRIES=2

REFERENCE_RESOLUTION_MIN_RATE=0.95
REFERENCE_TITLE_FUZZY_THRESHOLD=0.72
```

---

# 34. 结果状态

## success

```text
answer_text 非空
detected_reference_count == expected_reference_count
resolved / detected >= 95%
无致命错误
```

## partial_success

```text
回答成功
但引用数量不完整
或URL解析率低于95%
```

## failed

```text
无法获取回答
无法确定本轮回答
登录失效
验证码
浏览器崩溃
```

---

# 35. 单元测试

必须覆盖：

- HTML 实体解码；
- 百分号解码；
- `\u0022`；
- 标准 linkUrl/linkTitle；
- 粘连 URL；
- `logInfo` 尾部截断；
- 重复标题；
- 同节点序号绑定；
- 标题相似度；
- URL canonical；
- 静态资源过滤；
- 品牌别名匹配；
- 竞争对手匹配；
- 推荐强度规则；
- 引用完整性状态。

---

# 36. 集成测试

## 36.1 Profile 登录测试

```bash
RUN_WENXIN_INTEGRATION=1 pytest tests/integration/test_wenxin_session.py
```

## 36.2 真实单次运行

问题：

```text
谁是最好的二维码工具
```

验收：

```text
回答非空
参考数 > 0
标题数 == 页面参考数
URL解析率 >= 95%
证据文件完整
数据成功入库
前端可查看
```

## 36.3 完整链路

```text
API创建任务
→ 队列执行
→ Worker采集
→ 入库
→ 品牌分析
→ 前端详情返回
```

---

# 37. 完整开发顺序

用户要求直接完成完整链路，因此 Codex 可以在一个开发周期内完成，但仍需按模块提交。

## Phase 1：数据与接口骨架

- 数据表；
- migrations；
- schemas；
- 项目、品牌、问题、任务、运行 API；
- 基础前端页面。

## Phase 2：Worker 与任务状态

- 队列；
- Worker；
- 状态机；
- 重试；
- ArtifactService。

## Phase 3：文心 Playwright Collector

- Profile；
- 登录检测；
- 自动提问；
- 回答完成；
- 回答定位；
- 参考资料展开；
- 懒加载；
- 标题；
- URL；
- 网络响应。

## Phase 4：分析服务

- 品牌提及；
- 推荐强度；
- 竞争对手；
- 引用域名；
- 相关性和质量基础规则。

## Phase 5：结果页面

- 总览；
- 问题库；
- 任务；
- 运行；
- 运行详情；
- 引用表；
- 候选源；
- 证据。

## Phase 6：测试和完整验收

- 单元测试；
- 集成测试；
- 真实样本；
- 失败重试；
- 文档。

---

# 38. Codex 开发执行要求

Codex 开始开发前必须先完成：

```text
1. 审计现有 GEO 项目目录；
2. 找出现有 ORM、API、队列、前端组件规范；
3. 输出“本规格 → 现有项目文件”的映射表；
4. 不重构无关模块；
5. 不另起一个孤立 demo；
6. 所有代码直接落入现有 GEO 工程。
```

必须生成：

```text
docs/MONITORING_MODULE_IMPLEMENTATION_MAP.md
docs/MONITORING_MODULE_STATUS.md
docs/MONITORING_MODULE_TEST_REPORT.md
```

---

# 39. Codex 主提示词

将本文件保存为：

```text
docs/GEO_WENXIN_MONITORING_MODULE_SPEC.md
```

然后给 Codex：

```text
请将 docs/GEO_WENXIN_MONITORING_MODULE_SPEC.md 作为最高优先级开发规格，
在现有 GEO 工程中直接实现完整的“文心助手监测模块”主链路。

本次不是开发独立采集器，也不是只做技术验证，而是完成一个可在 GEO 产品中使用的大模块：

项目与品牌配置
→ 问题库
→ 创建任务
→ Worker队列
→ Playwright自动采集
→ 回答与真实引用源解析
→ 检索候选源分离存储
→ 品牌提及分析
→ 引用源分析
→ 数据入库
→ 前端任务与结果页面
→ 证据留存
→ 重试与错误展示

执行要求：

1. 先审计当前项目，输出实施映射表后再编码。
2. 复用现有技术栈、ORM、API规范、队列和前端组件。
3. 不创建脱离现有系统的独立Demo。
4. 不得将retrieval_candidate与reference_source混表。
5. 不得按标题去重引用，reference_index是引用主身份。
6. URL优先从同一引用节点及父节点的linkUrl/linkTitle中解析。
7. 实现P1直接DOM、P2序列化数据、P4点击捕获、P5候选匹配兜底。
8. 所有运行必须保存截图、HTML、原始JSON、网络日志和采集日志。
9. 所有状态和错误必须写入monitoring_runs。
10. 文心默认并发为1，使用持久化浏览器Profile。
11. 不实现验证码破解、自动登录、代理池和多账号并发。
12. 完整实现后运行单元测试、数据库测试、API测试和真实集成测试。
13. 使用“谁是最好的二维码工具”作为首个真实验收问题。
14. URL解析率低于95%不得标记为完整成功。
15. 完成后输出：
    - 改动文件清单
    - 数据库迁移说明
    - 启动方式
    - Profile登录方式
    - 测试结果
    - 已知限制
    - 下一步微调点
16. 开发过程中不要反复询问小问题，优先依据规格和现有代码做合理实现。
17. 页面选择器如与实际页面不一致，保留截图和HTML证据，并将选择器集中放在selectors.py中，方便后续微调。
18. 不要停在半成品；至少完成从前端创建任务到前端查看运行结果的完整可运行链路。
```

---

# 40. 验收清单

## 后端

- [ ] 项目可配置品牌；
- [ ] 可批量添加问题；
- [ ] 可创建文心监测任务；
- [ ] 自动创建 run；
- [ ] Worker 可消费 run；
- [ ] Playwright 可复用登录态；
- [ ] 自动提问；
- [ ] 自动等待回答；
- [ ] 自动解析参考资料；
- [ ] URL解析率 >= 95%；
- [ ] 候选源单独保存；
- [ ] 品牌提及分析完成；
- [ ] 运行数据入库；
- [ ] 证据文件保存；
- [ ] 支持失败重试；
- [ ] 可查询运行详情。

## 前端

- [ ] 项目/品牌配置；
- [ ] 问题库；
- [ ] 创建任务；
- [ ] 任务列表；
- [ ] 运行列表；
- [ ] 运行状态；
- [ ] 回答详情；
- [ ] 品牌表现；
- [ ] 真实引用源表；
- [ ] 候选源 Tab；
- [ ] 证据下载/查看；
- [ ] 错误阶段展示；
- [ ] 手动重试。

## 稳定性

- [ ] 连续10次至少8次完整成功；
- [ ] 失败不会卡死队列；
- [ ] 浏览器进程正确关闭；
- [ ] Profile 不被并发锁死；
- [ ] 失败证据不会被覆盖；
- [ ] 下一次任务可继续运行。

---

# 41. 当前版本定位

完成本规格后，GEO 工程将具备：

```text
文心助手监测模块 V1
```

它不是最终商用成熟版，但已经是产品内可使用的完整闭环：

```text
可创建
可执行
可采集
可入库
可分析
可展示
可复盘
可重试
```

后续微调主要集中在：

- 文心页面选择器；
- 回答完成判断；
- 懒加载稳定性；
- 点击URL兜底；
- 品牌推荐强度；
- 引用相关性与质量模型；
- 定时运行；
- 多账号；
- 多平台。

这些不影响先完成完整主链路。

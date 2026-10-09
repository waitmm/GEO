# 网站与稿件 SEO/GEO 检查规范

2026-10-09。关联 T18/T25、PRD-OPS、PRD-EXE；这是本版检查口径，不是收录或引用保证。沿用22号页面规范及17号验收矩阵，不新增产品主链。

## 适用边界

当前 release 是私有控制台。`/`及其查询参数视图（Monitor/Optimize/Validate/品牌资料/设置）、`/api/*`、答案、正文快照和未公开稿件均不作为公开可索引页面。静态JS/CSS不得内嵌客户数据。实际API数据受项目鉴权保护；robots、noindex不是权限控制。

本轮没有独立公开官网、公开帮助中心或CMS。因此公开页 sitemap/canonical/富结果部署为 N/A；不得把后台列入 sitemap。将来若增加公开页面，逐路由明确索引策略，不能全站复制后台 noindex，也不能去掉私有页鉴权。

## 技术与内容要求

| 对象 | 必须检查 | 证据与判定 |
| --- | --- | --- |
| 私有控制台 | 中文语言标记、准确标题、noindex；登录前不加载客户业务结果 | 初始HTML、响应头、未授权API拒绝测试 |
| 私有API | 项目归属、会话过期/撤销、no-store、错误不暴露凭证 | 正反权限测试；不以robots替代鉴权 |
| 未存在路径 | 真实404，不能返回成功的空应用壳 | release路由测试；开发服务器不代替发布服务 |
| 页面体验 | 首屏/主要操作可用，加载/空/失败/零值区分；1440/1024/390视口、键盘路径 | 浏览器trace、截图和耗时；不声称具备线上Core Web Vitals数据 |
| 导出稿件 | 标题主题明确、具体回答需求、主体/数字/条件保留、来源可追溯 | 对实际正文检查；无依据表述改写或移除；不能只查引用字段存在 |
| 正文与内部说明 | 内部hash、QA待办、模型提示和未核实占位不混入稿件 | 复制/导出逐文本验收 |
| 结构化数据 | 仅用于实际适用公开内容，须与可见内容一致 | 当前无自动评分/FAQ/HowTo标记；无事实不得伪造 |
| 品牌关联 | 来源声称不等于目标品牌事实；第三方示例不得转写成目标能力 | 复用用途资格及错误主体、数字、条件回归 |

## GEO 的可验证范围

内容应清楚回答问题、保留出处与适用范围；这些是本项目内容质量规则，不是某平台的隐藏排名公式。不能要求固定关键词密度、引用个数、品牌重复次数，不能承诺被引用或推荐。`answer_anchor=UNPROVEN`、`generation_influence=UNAVAILABLE` 不因文本对应而提升。

Google公开说明AI搜索功能沿用搜索基础要求，没有额外特殊Schema或AI文本文件要求；满足要求也不保证抓取、索引或展示。这一说明只适用于其所述Google功能，不外推为文心或其他平台机制。[Google AI features](https://developers.google.com/search/docs/appearance/ai-features)

noindex需要爬虫能够读取才会生效；本控制台禁止抓取且有鉴权，因此不宣称搜索引擎已读取noindex或已删除历史索引。[Google noindex](https://developers.google.com/search/docs/crawling-indexing/block-indexing)

页面无障碍按适用WCAG2.2 AA条目检查，包括键盘、焦点、标签、错误反馈与文本对比度。自动扫描和几个视口通过不等于完整合规认证。[W3C WCAG2.2](https://www.w3.org/TR/WCAG22/)

## 执行记录

当前记录见 [SEO/GEO检查报告](SEO_GEO_REPORT.md)。未运行项写NOT_RUN，外部平台效果写NOT_OBSERVED，不拿工程fixture冒充真实收录/引用。

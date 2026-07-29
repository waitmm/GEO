# 文心助手网页端监测模块实施映射

本文档将 `docs/GEO_WENXIN_MONITORING_MODULE_SPEC.md` 映射到当前 `geo-platform` 工程，作为后续编码的落地边界。

## 当前工程现状

当前工程是 V0 技术验证版：

- 后端：FastAPI + SQLAlchemy，同步执行监测任务。
- 数据库：默认 SQLite，暂未接入 Alembic。
- 队列：尚未接入 Redis / Celery / RQ。
- 前端：React + Vite + TypeScript + Ant Design，单 `App.tsx` 内按左侧页签切换。
- 已有数据链路：项目、竞品、Prompt、监测任务、观测结果、引用 URL、品牌/竞品规则抽取、基础指标。
- 已有平台入口：`mock`、`wenxin` API Adapter、若干 placeholder Adapter。

## 规格到现有文件映射

| 规格模块 | 当前已有文件 | 建议落点 | 处理方式 |
| --- | --- | --- | --- |
| 项目配置 | `backend/app/models/db.py` 的 `Project` | 复用 `projects` | 不新建孤立项目表，先复用 V0 项目 |
| 品牌配置 | `Project.brand_name`、`brand_aliases_json`、`website_url`、`Competitor` | 复用并补充 official domain 解析 | V1 可增加独立 brand 配置接口 |
| 问题库 | `Prompt` | 复用 `prompts` | 规格中的 `monitoring_questions` 映射到 Prompt |
| 任务 | `MonitorRun` | 新增 `browser_monitor_tasks` 或扩展现有任务 | 为避免破坏 V0，同步保留旧表，新模块单独建表更稳 |
| 单次运行 | `Observation` | 新增 `browser_monitor_runs` | 文心网页端运行字段远多于 Observation，不建议硬塞 |
| 真实引用源 | `AnswerCitation` | 新增 `reference_sources` | 必须与检索候选源分表 |
| 检索候选源 | 无 | 新增 `retrieval_candidates` | 禁止混入真实引用源表 |
| 品牌提及 | `ExtractedMention` | 新增 `brand_mentions`，并复用规则函数 | 文心网页端需要次数、段落、推荐强度 |
| 证据文件 | 无 | 新增 `run_artifacts` + `backend/artifacts/monitoring` | 数据库存路径，不存大文件 |
| Playwright Collector | 无 | `backend/app/modules/monitoring/collectors/wenxin/` | 作为新模块接入 |
| Worker 队列 | 无 | `backend/app/modules/monitoring/workers/` | MVP 可先实现同步 executor，再接 RQ |
| 前端总览 | `frontend/src/App.tsx` | 先在现有左侧导航新增页面 | 后续再拆到 `src/pages/monitoring/` |
| 运行详情 | 无 | 新增前端详情视图 | 包含回答、品牌表现、真实引用、候选源、证据、错误 |

## 后端建议新增文件

```text
backend/app/modules/monitoring/
├── __init__.py
├── enums.py
├── models.py
├── schemas.py
├── api.py
├── services.py
├── analysis.py
├── artifacts.py
├── workers.py
└── collectors/
    ├── __init__.py
    ├── base.py
    ├── registry.py
    └── wenxin/
        ├── __init__.py
        ├── collector.py
        ├── selectors.py
        ├── reference_parser.py
        ├── url_normalizer.py
        └── exceptions.py
```

## 前端建议新增能力

先不重构路由，在现有 `App.tsx` 左侧导航增加：

- 文心监测
- 运行列表
- 运行详情

待模块稳定后，再拆成：

```text
frontend/src/pages/monitoring/
frontend/src/components/monitoring/
```

## 数据源分层

当前 `wenxin` Adapter 是百度千帆 API 入口，应标记为：

```text
wenxin_api
entry_type = official_api_non_web_model
```

本规格中的文心助手网页端采集应标记为：

```text
wenxin_web_audit
entry_type = browser_audit
```

两者不得混算为同一口径。

## 最小开发顺序

1. 将规格附件归档到 `docs/GEO_WENXIN_MONITORING_MODULE_SPEC.md`。
2. 在主 PRD 增加“文心助手网页端监测模块”引用。
3. 新增 monitoring 模块数据模型与 API 骨架。
4. 新增 artifact 目录和配置项。
5. 实现同步版 task executor，先不用队列。
6. 接入 Playwright Collector 骨架和 Profile 脚本。
7. 实现品牌分析、引用源/候选源分表入库。
8. 前端增加文心监测运行列表和详情页。
9. 再引入 Redis + RQ/Celery，将同步 executor 替换为 Worker。

## 本轮暂不做

- 多账号池。
- 代理池。
- 自动登录。
- 验证码处理。
- 多平台网页端采集。
- 定时任务。
- 自动内容发布。


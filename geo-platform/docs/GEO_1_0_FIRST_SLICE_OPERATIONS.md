# GEO 1.0 首批来源与证据主链操作说明

Status: `ENGINEERING_READY / REAL_INPUT_PENDING`
Date: 2026-09-20

## 1. 当前交付范围

正式 release 路径只包含：

```text
Project / Prompt
-> Analysis / immutable Context
-> Citation Manifest
   |-> Source Preparation -> Source Completion Manifest
   `-> Answer ResultVersion -> exact Review
-> Evidence exact-input Gate -> immutable Evidence ResultVersion
```

不包含 Strategy、Execution、Publication、Retest，也不注册 legacy
optimization workflow。

## 2. 初始化与启动

首次环境先安装并构建安全 SQLite DBAPI：

```bash
cd geo-platform/backend
./.venv/bin/pip install -r requirements.release-build.txt
./.venv/bin/python scripts/bootstrap_release_sqlite.py
```

显式迁移独立 release 数据库：

```bash
cd /Users/bmwqr/Desktop/python/GEO
./scripts/release-migrate.sh
```

构建 release 前端并启动一个 API + 一个 worker：

```bash
cd geo-platform/frontend
npm run build:release

cd /Users/bmwqr/Desktop/python/GEO
./scripts/release-dev.sh
```

默认地址：`http://127.0.0.1:8020`。启动不会执行 migration，也不会
`create_all()`；未迁移、错 revision、额外表或 SQLite 版本不安全都会拒绝启动。

## 3. 正式用户操作顺序

1. 在 release 页面创建/选择 Project 与 Prompt；
2. 用户显式启动 Analysis；此操作可能触发浏览器采样，必须已有对应授权；
3. Raw Result / Context 冻结后，点击创建来源准备；系统同时冻结 Citation Manifest；
4. 对每个来源补录标题和正文，提交后内容 Gate 校验验证页、登录墙、错误页和正文长度；
5. 合格正文生成不可变 Snapshot、正文 SHA-256、artifact 文件和 passages；
6. 无法取得的来源只能由用户明确填写原因与影响后 `WAIVED_WITH_LIMITATION`；
7. 所有来源处置完成后冻结 Source Completion Manifest；全部 WAIVED 时状态为
   `NO_USABLE_SOURCE`，不能进入 Evidence；
8. Citation Manifest 冻结后，Answer Semantic 可与第 4-7 步独立推进；完成后
   用户审核精确 ResultVersion；它不需要等待正文完成，但 Evidence 需要两侧都完成；
9. 用户显式启动 Evidence；API 先校验同一 Analysis/Context 下的 Citation、
   Completion、Answer Result 与 Review，成功后仅入队；
10. release worker 对完全相同的版本绑定再次校验并消费，发布不可变 Evidence 结果。

## 4. 关键 API

- `POST /api/v2/single-prompt/analyses`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/source-preparation`
- `POST /api/v2/single-prompt/source-preparations/{preparation_id}/manual-content`
- `POST /api/v2/single-prompt/source-preparations/{preparation_id}/waivers`
- `POST /api/v2/single-prompt/source-preparations/{preparation_id}/completion-manifests`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/answer-diagnoses`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/diagnoses/{diagnosis_id}/results/{result_version}/reviews`
- `POST /api/v2/single-prompt/analyses/{analysis_id}/diagnoses/{diagnosis_id}/evidence-continuations`

所有 GET 只读。POST 返回 `QUEUED` 不表示计算完成；页面轮询后端状态，不能由
前端推断 ready/current。

## 5. 状态边界

- `READY` 正文只表示可定位、可校验、可复现，不代表正文主张真实；
- `WAIVED_WITH_LIMITATION` 只表示人工完成处置，不提供证据结论；
- `PENDING` 存在时 Completion 不可冻结；
- Answer 未审核、Review 错版、Manifest 错版、跨 Context 或全部来源 WAIVED，
  Evidence 均被后端阻断；
- Evidence 结果为零只有在实际评估完成且合法返回零关系时成立；未执行、失败、
  未召回或无正文不能写成零结果。

## 6. 当前真实验收缺口

2026-09-20 已完成新空库迁移、正式 API/worker 启动和隔离测试链。尚未获授权执行
新的浏览器采样、来源抓取或外部模型调用，也没有用户提供要补录到 release 库的
真实正文。因此当前没有可报告的真实 Snapshot ID、Completion Manifest、Answer
Review 或 Evidence Result。下一次真实验收必须先固定 release Analysis/Context，
再明确列出采样、来源获取和模型调用各自范围及预算。

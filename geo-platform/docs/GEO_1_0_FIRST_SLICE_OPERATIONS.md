# GEO 1.0 首批来源与证据主链操作说明

Status: `REAL_INPUT_PARTIAL / BLOCKED_BY_MANUAL_SOURCE_COMPLETION_AND_ANSWER_REVIEW`
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

## 6. 2026-09-20 首轮真实验收

固定 Project `1`（爱短链）/ Prompt `1`（抖音跳转链接）已通过正式 release
入口建立真实链路：

- Analysis `a2d0c0ee-b62e-4f39-9fe9-1bc14efdea33`，Task `1`；
- Context `ctx-96357192-0f2d-45db-b70c-0b58c2987dcd`；
- Raw Result `raw-v1:c0918158fcea889c`，完整 SHA-256
  `c0918158fcea889ccff970e15f56bb1a98b3220daec8c9b57aff1f9d612bbfc3`；
- Citation Manifest `citation-manifest-fe0a0f19-2579-45ec-a5f3-f4b2eca2695d`，
  38 个唯一来源 / 87 条引用记录；
- Source Preparation `source-prep-626e2e6e-4cda-41a2-81b7-cc08a393198e`；
- 真实人工正文补录生成 Snapshot
  `source-snapshot-1a51fa9d-9c0a-4cea-85f2-db72a67db8d0`，正文/artifact
  SHA-256 `d163a7fe5f3a5140339a62df58da64032922ab020c4a05695667e030f7d99822`，
  passages SHA-256 `717fd262e71459d7f8257bb2e39db9c8912e29082f31e8e2eb2f0ab1d8fb470f`，
  20 passages；
- Answer Diagnosis `aac746f4-6b9b-4cda-b981-3487b5ef2f9b`，Result
  `diag-v1:69cb9884452deead`，3/3 回答通过准入并合法返回零事件；DeepSeek
  外部请求 3 次、缓存命中 0、总 token 8,922。

来源获取审计在每个唯一 URL 最多 2 次、串行、不递归的边界内完成：除已正式
READY 的 1 条外，形成 10 份待人工检查的正文候选、17 条内容复核项、8 条人工
补录项，另 2 条已达尝试上限。候选文件不属于正式 Snapshot，验证码页、JS 壳及
403/412/521 响应均未进入 READY。

当前真实守恒为 `READY=1 / PENDING=37`，Completion Manifest 未生成；Answer
Review 也尚未由用户完成。正式 API 已分别验证：来源范围未完成时冻结 Completion
返回 409，缺精确 Answer Review 时 Evidence continuation 返回 409。没有 Evidence
Task、SourceClaim/Alignment 调用、WAIVE、Truth 或 Review 自动写入。服务重启后
Analysis、Snapshot、artifact hash、Diagnosis 和 `review=null` 均保持一致。

精确页面入口：

```text
http://127.0.0.1:8020/?v2_analysis=a2d0c0ee-b62e-4f39-9fe9-1bc14efdea33&v2_project=1&v2_prompt=1&v2_diagnosis=aac746f4-6b9b-4cda-b981-3487b5ef2f9b&v2_diagnosis_result=diag-v1%3A69cb9884452deead
```

下一步仅是用户在该页面完成精确 Answer Review，并逐条补录或明确 WAIVE 剩余
37 个来源。两侧均完成后才可冻结 Completion Manifest 并执行已授权 Evidence；
当前正确状态是 Gate 真实阻断，不是 Evidence 正向消费完成。

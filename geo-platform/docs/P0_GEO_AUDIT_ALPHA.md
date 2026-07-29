# GEO Audit Alpha（P0）

## 产品口径

当前版本是“可信的 AI 可见度、竞品表现和引用来源审计系统”，回答：

1. AI 是否提到目标品牌；
2. AI 是否推荐目标品牌或竞品；
3. AI 实际引用哪些来源；
4. 重复观测是否稳定，证据质量如何。

Dashboard 中的 `出现 x / n` 是单一采集环境的 Validation Sample，不代表总体曝光概率。

## 数据层级

```text
Project
└── Topic
    └── Prompt Cluster
        └── Prompt

Monitoring Batch
└── Sample Run
    ├── Answer
    ├── Brand / competitor observation
    ├── Reference sources
    ├── Collection environment
    └── Evidence
```

## 两种采集模式

- `single_continuous`：复用一个正式 Chrome 和同一文心对话连续采集。用于稳定产品观测，降低安全验证风险。
- `single_independent`：复用一个正式 Chrome，但每个 Sample 点击“开启新对话”。用于 Collector Qualification；只表示对话上下文独立。

两者都是同一客户端、浏览器、网络环境，不能解释为真实用户总体分布。

## 引用质量四层

每个 Run 独立记录：

- `ui_declared_count`
- `dom_reference_count`
- `parsed_reference_count`
- `resolved_url_count`

Data Quality 独立展示成功、Blocked、Collector Failed、引用完整 Run 和 URL 解析率。

## 每个 Run 的证据

```text
artifacts/monitoring/<run_id>/
├── page.png
├── page.html
├── reference-panel.html
├── network.jsonl
├── result.json
└── collector.log
```

`network.jsonl` 仅保存请求元数据，敏感 token、session、conversation 参数会被移除。

## 启动

后端：

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

前端：

```powershell
cd frontend
npm.cmd run dev
```

Worker：

```powershell
cd backend
python scripts\worker_monitoring_loop.py --interval 10 --batch-size 1
```

浏览器打开 `http://127.0.0.1:5173`。

## 八木屋 10 × 3 Dogfood

先确定项目 ID，然后执行：

```powershell
cd backend
python scripts\seed_bamuwu_audit.py --project-id 1 --sample-count 3 --queue --collection-mode single_continuous
```

这会复用已有的 Topic/Cluster/Prompt，并新建：

- Topic：二维码平台选择
- Cluster：综合工具推荐、企业选型
- 10 个 Prompt
- 一个 Monitoring Batch
- 30 个排队 Sample Run

随后启动 Worker。若要做对话上下文独立的 Collector Qualification，把模式改为 `single_independent`。

## Collector Qualification 验收

- Answer Fidelity：页面回答与数据库回答一致；
- Turn Binding：Qn → An → References n，串题为 0；
- Reference Fidelity：四层数量分别记录；
- Evidence：核心证据齐全；
- Blocked：与 Collector Failed 分离。

资格验收判断 Collector 是否忠实采集，不判断文心答案是否一致。

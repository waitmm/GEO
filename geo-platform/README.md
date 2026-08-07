# GEO Platform

> Current product direction: a trustworthy AI visibility, competitor presence,
> and citation-source audit Alpha. See
> [`docs/P0_GEO_AUDIT_ALPHA.md`](docs/P0_GEO_AUDIT_ALPHA.md).

V0 implementation for an AI brand visibility monitoring and source diagnostics platform.

## Current usable status

The project is now usable as an Alpha for Wenxin browser-audit monitoring.

You can start using it for:

- Creating projects, brands, competitors, and prompt questions
- Running Wenxin web-audit collection for small batches
- Importing browser-plugin JSON evidence into the same `wenxin_web_audit` data model
- Viewing answer text, page HTML, screenshots, collector logs, brand mentions, and reference titles
- Running the P0 optimization loop: issue discovery, action recording, fixed retest comparison, and human conclusion

Current limitation:

- Wenxin page automation is ready for single-question and small-batch collection.
- Reference title extraction is available, but real reference URL resolution still needs more tuning against Wenxin page HTML/panel behavior.
- Keep concurrency at `1` for now.

## Current scope

- Project, brand, competitor, and prompt management
- Unified AI adapter interface
- Mock adapter with normalized `AdapterResult`
- Manual monitor runs with repeat sampling
- Raw answer, citation, and extraction storage
- Basic metrics overview
- React V0 dashboard

## Local dev stack

From the repository root:

```bash
./scripts/dev.sh
```

Default URLs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://localhost:5173`

Optional environment overrides:

```bash
BACKEND_RELOAD=1 BACKEND_PORT=8000 FRONTEND_HOST=localhost FRONTEND_PORT=5173 ./scripts/dev.sh
```

The script uses `geo-platform/backend/.venv/bin/python` when it exists, and loads
`nvm` automatically when `npm` is not already on `PATH`.

## Local backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app
```

The default database is SQLite at `backend/geo_v0.db`.

### Wenxin / Qianfan adapter

Create `backend/.env` from `backend/.env.example` and fill:

```env
WENXIN_API_KEY=your_baidu_api_key
WENXIN_SECRET_KEY=your_baidu_secret_key
WENXIN_MODEL=ernie-4.0-turbo-8k
```

Then choose `百度文心 / 千帆` in the monitoring page. If credentials are missing, the platform remains visible but is marked as needing configuration.

### Wenxin web audit module

The browser-audit source is separate from the API adapter:

```text
platform=wenxin
source_type=browser_audit
adapter=wenxin_web_audit
```

Install Playwright and Chromium before real browser collection:

```bash
cd backend
pip install -r requirements.txt
playwright install chromium
python scripts/create_wenxin_profile.py
python scripts/check_wenxin_session.py
```

The admin must log in manually in the persistent browser profile. The system does not store passwords, bypass captcha, use proxy pools, or run multiple Wenxin profiles concurrently.

For a one-question smoke run:

```bash
cd backend
python scripts/run_wenxin_once.py
```

For queued runs created from the frontend:

```bash
cd backend
python scripts/worker_monitoring_once.py --limit 1
```

For continuous small-batch collection:

```bash
cd backend
python scripts/worker_monitoring_loop.py --interval 10 --batch-size 1
```

For daily Prompt monitoring, queue due schedules once:

```bash
cd backend
python scripts/queue_daily_schedules.py --project-id 3
```

Queue and execute due daily schedules immediately:

```bash
cd backend
python scripts/queue_daily_schedules.py --project-id 3 --execute-now
```

When starting the local dev stack, daily scheduling and the monitoring worker
can be enabled explicitly:

```bash
DAILY_SCHEDULER=1 DAILY_SCHEDULER_PROJECT_ID=3 MONITORING_WORKER=1 ./scripts/dev.sh
```

If you want the daily scheduler itself to execute queued browser tasks, use:

```bash
DAILY_SCHEDULER=1 DAILY_SCHEDULER_PROJECT_ID=3 DAILY_SCHEDULER_EXECUTE_NOW=1 ./scripts/dev.sh
```

The default browser collection timeout is controlled by
`WENXIN_BROWSER_TIMEOUT_SECONDS` and is now 300 seconds.

Plugin-exported JSON can also be imported through the frontend "文心网页审计" page, or by command line:

```bash
cd backend
python scripts/import_wenxin_plugin_result.py "C:\Users\mingy\Downloads\test-001-1784564289782.json" --project-id 1
```

## Local frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Next development steps

1. Deepen citation-source analysis inside the optimization loop.
2. Add repeatable retest task creation from experiments.
3. Add Alembic migrations.
4. Replace placeholder adapters with Qwen, Kimi, Wenxin, and DeepSeek API clients.
5. Move monitor execution to Redis plus Celery or RQ.

# 03 Architecture

Status: ACTIVE

## Backend

- `app/main.py`: FastAPI app, CORS, startup DB init, router registration.
- `app/core/database.py`: SQLAlchemy engine/session and SQLite additive column
  sync.
- `app/models/db.py`: central SQLAlchemy models.
- `app/api/v0.py`: base project/prompt/batch/legacy monitor APIs.
- `app/modules/monitoring`: Wenxin browser-audit task/run execution, evidence,
  import, and run detail APIs.
- `app/modules/analytics`: validation dashboard and Prompt daily reports.
- `app/modules/optimization`: P0 optimization issue/action/experiment/evidence
  loop.

## Frontend

- `frontend/src/App.tsx`: current single-page application shell.
- `frontend/src/api/client.ts`: API client mapping.
- `frontend/src/types.ts`: frontend wire/domain types.

## Data Flow

```text
Prompt configuration
  -> Browser audit task
  -> BrowserMonitorRun
  -> ReferenceSource + RetrievalCandidate + RunArtifact
  -> Analytics dashboard / Prompt daily report
  -> OptimizationIssue
  -> OptimizationAction
  -> OptimizationExperiment
  -> Evidence chain and conclusion
```

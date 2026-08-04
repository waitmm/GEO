from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project, Prompt, PromptDailyReport
from app.modules.analytics.schemas import PromptDailyReportRead, ValidationDashboard
from app.modules.analytics.service import build_prompt_daily_report, build_validation_dashboard, prompt_daily_report_to_read


router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/projects/{project_id}/validation-dashboard", response_model=ValidationDashboard)
def get_validation_dashboard(
    project_id: int,
    citation_limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ValidationDashboard:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return build_validation_dashboard(db, project, citation_limit)


@router.get("/projects/{project_id}/prompt-daily-reports", response_model=list[PromptDailyReportRead])
def list_prompt_daily_reports(
    project_id: int,
    prompt_id: int | None = Query(default=None),
    report_date: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[PromptDailyReportRead]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    query = db.query(PromptDailyReport).filter(PromptDailyReport.project_id == project_id)
    if prompt_id is not None:
        query = query.filter(PromptDailyReport.prompt_id == prompt_id)
    if report_date:
        query = query.filter(PromptDailyReport.report_date == report_date)
    reports = query.order_by(PromptDailyReport.report_date.desc(), PromptDailyReport.id.desc()).limit(limit).all()
    return [prompt_daily_report_to_read(report) for report in reports]


@router.post("/projects/{project_id}/prompt-daily-reports/generate", response_model=PromptDailyReportRead)
def generate_prompt_daily_report(
    project_id: int,
    prompt_id: int = Query(...),
    report_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PromptDailyReportRead:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    report = build_prompt_daily_report(db, project, prompt, report_date)
    return prompt_daily_report_to_read(report)

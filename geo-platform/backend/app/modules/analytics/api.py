from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Project
from app.modules.analytics.schemas import ValidationDashboard
from app.modules.analytics.service import build_validation_dashboard


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


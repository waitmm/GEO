"""Minimal catalog API registered by the GEO 1.0 first-slice release app."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.adapters.registry import list_platforms
from app.core.release_database import get_release_db
from app.models import Competitor, Organization, Project, Prompt, PromptCluster, Topic
from app.schemas.v0 import (
    CompetitorRead,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    PromptClusterCreate,
    PromptClusterRead,
    PromptCreate,
    PromptRead,
    PromptUpdate,
    TopicCreate,
    TopicRead,
)
from app.services.serialization import dumps, loads


router = APIRouter(prefix="/api", tags=["release-catalog"])
get_db = get_release_db


def _default_org(db: Session) -> Organization:
    row = db.query(Organization).order_by(Organization.id).first()
    if row:
        return row
    row = Organization(name="Default Organization", plan_type="release-1.0")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _project_read(project: Project, competitors: Optional[list[Competitor]] = None) -> ProjectRead:
    rows = competitors if competitors is not None else db_competitors(project)
    return ProjectRead(
        id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        brand_name=project.brand_name,
        brand_aliases=loads(project.brand_aliases_json, []),
        website_url=project.website_url,
        industry=project.industry,
        region=project.region,
        language=project.language,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
        competitors=[
            CompetitorRead(
                id=row.id,
                project_id=row.project_id,
                name=row.name,
                aliases=loads(row.aliases_json, []),
                website_url=row.website_url,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


def db_competitors(project: Project) -> list[Competitor]:
    # Only used when SQLAlchemy has already loaded the explicit relationship.
    return list(project.competitors)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(request: Request, db: Session = Depends(get_db)) -> list[ProjectRead]:
    user = request.state.principal
    query = db.query(Project)
    if not user.get('admin'):
        query = query.filter(Project.id.in_(user.get('project_ids', [])))
    projects = query.order_by(Project.id.desc()).all()
    return [
        _project_read(row, db.query(Competitor).filter_by(project_id=row.id).order_by(Competitor.id).all())
        for row in projects
    ]


@router.post("/projects", response_model=ProjectRead)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectRead:
    organization_id = payload.organization_id or _default_org(db).id
    if not db.get(Organization, organization_id):
        raise HTTPException(status_code=422, detail="Organization 不存在")
    project = Project(
        organization_id=organization_id,
        name=payload.name,
        brand_name=payload.brand_name,
        brand_aliases_json=dumps(payload.brand_aliases),
        website_url=payload.website_url,
        industry=payload.industry,
        region=payload.region,
        language=payload.language,
    )
    db.add(project)
    db.flush()
    for item in payload.competitors:
        db.add(Competitor(
            project_id=project.id,
            name=item.name,
            aliases_json=dumps(item.aliases),
            website_url=item.website_url,
        ))
    db.commit()
    db.refresh(project)
    return _project_read(project, db.query(Competitor).filter_by(project_id=project.id).all())


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)) -> ProjectRead:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project 不存在")
    values = payload.model_dump(exclude_unset=True)
    aliases = values.pop("brand_aliases", None)
    competitors = values.pop("competitors", None)
    if aliases is not None:
        project.brand_aliases_json = dumps(aliases)
    if competitors is not None:
        validated = []
        for item in competitors:
            name = str(item.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=422, detail="竞品名称不能为空")
            validated.append(item)
        db.query(Competitor).filter_by(project_id=project_id).delete()
        for item in validated:
            db.add(Competitor(
                project_id=project_id,
                name=str(item["name"]).strip(),
                aliases_json=dumps(item.get("aliases") or []),
                website_url=str(item.get("website_url") or ""),
            ))
    for key, value in values.items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return _project_read(project, db.query(Competitor).filter_by(project_id=project.id).all())


@router.get("/projects/{project_id}/prompts", response_model=list[PromptRead])
def list_prompts(project_id: int, db: Session = Depends(get_db)) -> list[Prompt]:
    return db.query(Prompt).filter_by(project_id=project_id).order_by(Prompt.id.desc()).all()


@router.post("/projects/{project_id}/prompts", response_model=PromptRead)
def create_prompt(project_id: int, payload: PromptCreate, db: Session = Depends(get_db)) -> Prompt:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project 不存在")
    if not payload.prompt_text.strip() or len(payload.prompt_text) > 10000:
        raise HTTPException(422, "问题原文须为1到10000字符")
    if db.query(Prompt).filter_by(project_id=project_id, prompt_text=payload.prompt_text.strip()).first():
        raise HTTPException(409, "该项目已有相同问题，请继续使用已有问题")
    if payload.daily_tracking_enabled:
        raise HTTPException(422, "请通过正式采样计划入口明确时区与授权次数")
    if payload.topic_id is not None:
        topic = db.get(Topic, payload.topic_id)
        if not topic or topic.project_id != project_id:
            raise HTTPException(status_code=422, detail="Topic 不属于当前 Project")
    if payload.cluster_id is not None:
        cluster = db.get(PromptCluster, payload.cluster_id)
        if not cluster or cluster.project_id != project_id:
            raise HTTPException(status_code=422, detail="Prompt Cluster 不属于当前 Project")
    prompt = Prompt(project_id=project_id, **payload.model_dump())
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.patch("/projects/{project_id}/prompts/{prompt_id}", response_model=PromptRead)
def update_prompt(project_id: int, prompt_id: int, payload: PromptUpdate, db: Session = Depends(get_db)) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    values = payload.model_dump(exclude_unset=True)
    if values.get("daily_tracking_enabled"):
        raise HTTPException(422, "请通过正式采样计划入口明确时区与授权次数")
    if "prompt_text" in values:
        value = str(values["prompt_text"] or "").strip()
        if not value or len(value) > 10000:
            raise HTTPException(422, "问题原文须为1到10000字符")
        if db.query(Prompt).filter(Prompt.project_id == project_id, Prompt.prompt_text == value, Prompt.id != prompt_id).first():
            raise HTTPException(409, "该项目已有相同问题")
        values["prompt_text"] = value
    if values.get("topic_id") is not None:
        topic = db.get(Topic, values["topic_id"])
        if not topic or topic.project_id != project_id:
            raise HTTPException(status_code=422, detail="Topic 不属于当前 Project")
    if values.get("cluster_id") is not None:
        cluster = db.get(PromptCluster, values["cluster_id"])
        if not cluster or cluster.project_id != project_id:
            raise HTTPException(status_code=422, detail="Prompt Cluster 不属于当前 Project")
    for key, value in values.items():
        setattr(prompt, key, value)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.get("/projects/{project_id}/topics", response_model=list[TopicRead])
def list_topics(project_id: int, db: Session = Depends(get_db)) -> list[Topic]:
    return db.query(Topic).filter_by(project_id=project_id).order_by(Topic.sort_order, Topic.id).all()


@router.post("/projects/{project_id}/topics", response_model=TopicRead)
def create_topic(project_id: int, payload: TopicCreate, db: Session = Depends(get_db)) -> Topic:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project 不存在")
    row = Topic(project_id=project_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/projects/{project_id}/prompt-clusters", response_model=list[PromptClusterRead])
def list_prompt_clusters(project_id: int, db: Session = Depends(get_db)) -> list[PromptCluster]:
    return db.query(PromptCluster).filter_by(project_id=project_id).order_by(PromptCluster.sort_order, PromptCluster.id).all()


@router.post("/projects/{project_id}/prompt-clusters", response_model=PromptClusterRead)
def create_prompt_cluster(project_id: int, payload: PromptClusterCreate, db: Session = Depends(get_db)) -> PromptCluster:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project 不存在")
    row = PromptCluster(project_id=project_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/platforms")
def platforms() -> list[dict[str, str]]:
    return list_platforms()

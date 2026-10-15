"""Minimal catalog API registered by the GEO 1.0 first-slice release app."""

from __future__ import annotations

import hashlib
import json
from typing import Optional
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.registry import list_platforms
from app.core.release_database import get_release_db
from app.models import (
    Base, Competitor, Organization, Project, ProjectConfigurationVersion, Prompt, PromptCluster,
    PromptVersion, Topic,
)
from app.release_schema import RELEASE_TABLE_ALLOWLIST
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


class PromptBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict] = Field(min_length=1, max_length=20)


class BatchPromptItem(PromptCreate):
    model_config = ConfigDict(extra="forbid")


def _text(value: object, label: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise HTTPException(422, f"{label}不能为 null")
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise HTTPException(422, f"{label}须为{'1' if required else '0'}到{limit}字符")
    return value


def _website(value: object) -> str:
    value = _text(value, "官网地址", 2048)
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        parsed.port  # Reject malformed ports even though configuration does not fetch this URL.
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    if not valid or any(char.isspace() for char in value):
        raise HTTPException(422, "官网地址须为不含账号密码的完整 HTTP/HTTPS 地址")
    return value


def _aliases(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 50:
        raise HTTPException(422, "别名须为最多50项的列表")
    return list(dict.fromkeys(_text(item, "别名", 200, required=True) for item in value))


def _project_values(values: dict) -> dict:
    values = dict(values)
    for key, label, limit in [("name", "项目名称", 200), ("brand_name", "品牌名称", 200),
            ("industry", "行业", 200), ("region", "地区", 100), ("language", "语言", 100), ("status", "状态", 50)]:
        if key in values:
            values[key] = _text(values[key], label, limit, required=key in {"name", "brand_name", "region", "language", "status"})
    if "website_url" in values:
        values["website_url"] = _website(values["website_url"])
    if "brand_aliases" in values:
        values["brand_aliases"] = _aliases(values["brand_aliases"])
    if "competitors" in values:
        if not isinstance(values["competitors"], list) or len(values["competitors"]) > 50:
            raise HTTPException(422, "竞品须为最多50项的列表")
        values["competitors"] = [{"name": _text(item.get("name"), "竞品名称", 200, required=True),
            "aliases": _aliases(item.get("aliases", [])), "website_url": _website(item.get("website_url", ""))}
            for item in values["competitors"]]
    return values


def _prompt_values(values: dict) -> dict:
    values = dict(values)
    for key, value in values.items():
        if value is None and key not in {"topic_id", "cluster_id"}:
            raise HTTPException(422, f"问题字段 {key} 不能为 null")
    for key, label, limit in [("prompt_text", "问题原文", 10000), ("title", "问题标题", 200),
            ("prompt_group", "问题组", 160), ("intent_type", "问题意图", 100)]:
        if key in values:
            values[key] = _text(values[key], label, limit, required=key in {"prompt_text", "intent_type"})
    return values


def _prompt_snapshot(prompt: Prompt) -> dict:
    return {
        "project_id": prompt.project_id,
        "prompt_id": prompt.id,
        "prompt_text": prompt.prompt_text,
        "title": prompt.title,
        "intent_type": prompt.intent_type,
        "prompt_group": prompt.prompt_group,
        "enabled": prompt.enabled,
        "topic_id": prompt.topic_id,
        "cluster_id": prompt.cluster_id,
        "importance": prompt.importance,
        "sample_count": prompt.sample_count,
        "daily_tracking_enabled": prompt.daily_tracking_enabled,
        "daily_schedule_time": prompt.daily_schedule_time,
        "daily_sample_count": prompt.daily_sample_count,
    }


def _record_prompt_version(db: Session, prompt: Prompt) -> PromptVersion:
    snapshot = _prompt_snapshot(prompt)
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    latest = db.query(PromptVersion).filter_by(prompt_id=prompt.id).order_by(
        PromptVersion.version_number.desc()).first()
    if latest and latest.snapshot_hash == snapshot_hash:
        return latest
    row = PromptVersion(
        prompt_version_id=f"prompt-version-{uuid4()}",
        project_id=prompt.project_id,
        prompt_id=prompt.id,
        version_number=(latest.version_number + 1) if latest else 1,
        snapshot_json=serialized,
        snapshot_hash=snapshot_hash,
    )
    db.add(row)
    db.flush()
    return row


def _prompt_version_read(row: PromptVersion, latest_number: int) -> dict:
    return {
        "prompt_version_id": row.prompt_version_id,
        "version_number": row.version_number,
        "status": "EFFECTIVE" if row.version_number == latest_number else "SUPERSEDED",
        "snapshot": loads(row.snapshot_json, {}),
        "snapshot_hash": row.snapshot_hash,
        "created_at": row.created_at,
    }


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


def _project_configuration_snapshot(project: Project, competitors: list[Competitor]) -> dict:
    return {
        "project_id": project.id,
        "name": project.name,
        "brand_name": project.brand_name,
        "brand_aliases": loads(project.brand_aliases_json, []),
        "website_url": project.website_url,
        "industry": project.industry,
        "region": project.region,
        "language": project.language,
        "status": project.status,
        "competitors": [
            {"name": row.name, "aliases": loads(row.aliases_json, []), "website_url": row.website_url}
            for row in sorted(competitors, key=lambda item: item.id or 0)
        ],
    }


def _record_project_configuration(db: Session, project: Project) -> ProjectConfigurationVersion:
    competitors = db.query(Competitor).filter_by(project_id=project.id).order_by(Competitor.id).all()
    snapshot = _project_configuration_snapshot(project, competitors)
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    latest = db.query(ProjectConfigurationVersion).filter_by(project_id=project.id).order_by(
        ProjectConfigurationVersion.version_number.desc()).first()
    if latest and latest.snapshot_hash == snapshot_hash:
        return latest
    row = ProjectConfigurationVersion(
        configuration_version_id=f"project-config-{uuid4()}",
        project_id=project.id,
        version_number=(latest.version_number + 1) if latest else 1,
        snapshot_json=serialized,
        snapshot_hash=snapshot_hash,
    )
    db.add(row)
    db.flush()
    return row


def _configuration_version_read(row: ProjectConfigurationVersion, latest_number: int) -> dict:
    return {
        "configuration_version_id": row.configuration_version_id,
        "project_id": row.project_id,
        "version_number": row.version_number,
        "status": "EFFECTIVE" if row.version_number == latest_number else "SUPERSEDED",
        "snapshot": loads(row.snapshot_json, {}),
        "snapshot_hash": row.snapshot_hash,
        "created_at": row.created_at,
    }


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
    values = _project_values(payload.model_dump())
    organization_id = values.pop("organization_id") or _default_org(db).id
    if not db.get(Organization, organization_id):
        raise HTTPException(status_code=422, detail="Organization 不存在")
    aliases = values.pop("brand_aliases")
    competitors = values.pop("competitors")
    project = Project(organization_id=organization_id, brand_aliases_json=dumps(aliases), **values)
    db.add(project)
    db.flush()
    for item in competitors:
        db.add(Competitor(
            project_id=project.id,
            name=item["name"],
            aliases_json=dumps(item["aliases"]),
            website_url=item["website_url"],
        ))
    db.flush()
    _record_project_configuration(db, project)
    db.commit()
    db.refresh(project)
    return _project_read(project, db.query(Competitor).filter_by(project_id=project.id).all())


@router.post("/projects/configuration-preview")
def preview_project_configuration(payload: ProjectCreate) -> dict:
    values = _project_values(payload.model_dump())
    return {
        "values": values,
        "configured_official_host": urlsplit(values["website_url"]).hostname or None,
        "alias_duplicates_removed": len(payload.brand_aliases) - len(values["brand_aliases"]),
        "domain_status": "CONFIGURED_NOT_VERIFIED" if values["website_url"] else "UNKNOWN",
    }


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)) -> ProjectRead:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project 不存在")
    values = _project_values(payload.model_dump(exclude_unset=True))
    # Upgraded databases may contain projects created before the version ledger.
    # Freeze their current configuration before applying the first later edit.
    _record_project_configuration(db, project)
    aliases = values.pop("brand_aliases", None)
    competitors = values.pop("competitors", None)
    if aliases is not None:
        project.brand_aliases_json = dumps(aliases)
    if competitors is not None:
        db.query(Competitor).filter_by(project_id=project_id).delete()
        for item in competitors:
            db.add(Competitor(
                project_id=project_id,
                name=str(item["name"]).strip(),
                aliases_json=dumps(item.get("aliases") or []),
                website_url=str(item.get("website_url") or ""),
            ))
    for key, value in values.items():
        setattr(project, key, value)
    db.flush()
    _record_project_configuration(db, project)
    db.commit()
    db.refresh(project)
    return _project_read(project, db.query(Competitor).filter_by(project_id=project.id).all())


@router.get("/projects/{project_id}/configuration-versions")
def list_project_configuration_versions(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project 不存在")
    rows = db.query(ProjectConfigurationVersion).filter_by(project_id=project_id).order_by(
        ProjectConfigurationVersion.version_number.desc()).all()
    latest_number = rows[0].version_number if rows else 0
    return [_configuration_version_read(row, latest_number) for row in rows]


@router.get("/projects/{project_id}/configuration-versions/{configuration_version_id}")
def get_project_configuration_version(
    project_id: int, configuration_version_id: str, db: Session = Depends(get_db),
) -> dict:
    row = db.query(ProjectConfigurationVersion).filter_by(
        project_id=project_id, configuration_version_id=configuration_version_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="项目配置版本不存在")
    latest_number = db.query(ProjectConfigurationVersion.version_number).filter_by(project_id=project_id).order_by(
        ProjectConfigurationVersion.version_number.desc()).limit(1).scalar() or 0
    return _configuration_version_read(row, latest_number)


@router.get("/projects/{project_id}/prompts", response_model=list[PromptRead])
def list_prompts(project_id: int, db: Session = Depends(get_db)) -> list[Prompt]:
    return db.query(Prompt).filter_by(project_id=project_id).order_by(Prompt.id.desc()).all()


@router.get("/projects/{project_id}/prompts/{prompt_id}/versions")
def list_prompt_versions(project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> list[dict]:
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    rows = db.query(PromptVersion).filter_by(project_id=project_id, prompt_id=prompt_id).order_by(
        PromptVersion.version_number.desc()).all()
    latest_number = rows[0].version_number if rows else 0
    return [_prompt_version_read(row, latest_number) for row in rows]


@router.get("/projects/{project_id}/prompts/{prompt_id}/versions/{prompt_version_id}")
def get_prompt_version(
    project_id: int, prompt_id: int, prompt_version_id: str, db: Session = Depends(get_db),
) -> dict:
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    row = db.query(PromptVersion).filter_by(
        project_id=project_id, prompt_id=prompt_id, prompt_version_id=prompt_version_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Prompt 版本不存在")
    latest_number = db.query(PromptVersion.version_number).filter_by(prompt_id=prompt_id).order_by(
        PromptVersion.version_number.desc()).limit(1).scalar() or 0
    return _prompt_version_read(row, latest_number)


@router.post("/projects/{project_id}/prompts", response_model=PromptRead)
def create_prompt(project_id: int, payload: PromptCreate, db: Session = Depends(get_db)) -> Prompt:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project 不存在")
    values = _prompt_values(payload.model_dump())
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
    if db.query(Prompt).filter_by(project_id=project_id, prompt_text=values["prompt_text"]).first():
        raise HTTPException(409, "该项目已有相同问题，请继续使用已有问题")
    prompt = Prompt(project_id=project_id, **values)
    db.add(prompt)
    db.flush()
    _record_prompt_version(db, prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.post("/projects/{project_id}/prompts/batch")
def create_prompt_batch(project_id: int, payload: PromptBatchCreate, db: Session = Depends(get_db)) -> dict:
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project 不存在")
    results = []
    for index, raw in enumerate(payload.items):
        try:
            item = BatchPromptItem.model_validate(raw)
            prompt = create_prompt(project_id, item, db)
            results.append({"index": index, "status": "CREATED", "prompt_id": prompt.id, "detail": "已创建"})
        except ValidationError as error:
            fields = {"prompt_text": "问题原文", "importance": "优先级", "sample_count": "采样次数",
                "intent_type": "意图", "topic_id": "主题", "cluster_id": "问题组"}
            labels = list(dict.fromkeys(fields.get(str(issue["loc"][0]), "问题配置") for issue in error.errors()))
            results.append({"index": index, "status": "REJECTED", "prompt_id": None,
                "detail": "、".join(labels) + "格式不正确，请检查必填项、范围和字段"})
        except HTTPException as error:
            if error.status_code == 409:
                existing = db.query(Prompt).filter_by(project_id=project_id, prompt_text=item.prompt_text.strip()).first()
                if existing:
                    results.append({"index": index, "status": "EXISTING", "prompt_id": existing.id,
                        "detail": "已有相同问题，保留原配置"})
                    continue
            results.append({"index": index, "status": "REJECTED", "prompt_id": None, "detail": str(error.detail)})
    return {"project_id": project_id, "items": results}


@router.patch("/projects/{project_id}/prompts/{prompt_id}", response_model=PromptRead)
def update_prompt(project_id: int, prompt_id: int, payload: PromptUpdate, db: Session = Depends(get_db)) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    values = _prompt_values(payload.model_dump(exclude_unset=True))
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
    changed = {key: value for key, value in values.items() if getattr(prompt, key) != value}
    if not changed:
        return prompt
    if not db.query(PromptVersion.id).filter_by(prompt_id=prompt_id).first():
        _record_prompt_version(db, prompt)
    for key, value in changed.items():
        setattr(prompt, key, value)
    _record_prompt_version(db, prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.delete("/projects/{project_id}/prompts/{prompt_id}")
def delete_unused_prompt(project_id: int, prompt_id: int, db: Session = Depends(get_db)) -> dict:
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(404, "问题不存在")
    # Guard in the DELETE itself: a history/plan created concurrently must not be cascaded away.
    references = [table for table in Base.metadata.sorted_tables
                  if table.name in RELEASE_TABLE_ALLOWLIST and table.name != "prompt_versions"
                  and "prompt_id" in table.c]
    statement = delete(Prompt).where(Prompt.id == prompt_id, Prompt.project_id == project_id,
        *(~exists(select(1).select_from(table).where(table.c.prompt_id == prompt_id)) for table in references))
    try:
        affected = db.execute(statement.execution_options(synchronize_session=False)).rowcount
        if affected != 1:
            db.rollback()
            raise HTTPException(409, "此问题已有采样、计划或分析记录，不能删除；可停用并保留历史")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "此问题已被其他记录使用，不能删除；请刷新后停用") from None
    return {"deleted": True, "prompt_id": prompt_id}


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

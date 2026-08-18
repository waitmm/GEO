from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.adapters.registry import list_platforms
from app.core.database import get_db
from app.models import (
    AnswerCitation, BrowserMonitorRun, Competitor, ExtractedMention, MonitorRun, MonitoringBatch,
    Observation, Organization, Project, Prompt, PromptCluster, Topic,
)
from app.schemas.v0 import (
    CitationRead,
    CompetitorRead,
    MentionRead,
    MetricsOverview,
    MonitorRunCreate,
    MonitorRunRead,
    ObservationRead,
    OrganizationCreate,
    OrganizationRead,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    PromptCreate,
    PromptRead,
    PromptUpdate,
    PromptClusterCreate,
    PromptClusterRead,
    PromptClusterUpdate,
    MonitoringBatchCreate,
    MonitoringBatchRead,
    MonitoringBatchUpdate,
    TopicCreate,
    TopicRead,
    TopicUpdate,
)
from app.services.monitoring import run_monitoring_job
from app.services.serialization import dumps, loads


router = APIRouter(prefix="/api", tags=["v0"])


def ensure_default_org(db: Session) -> Organization:
    org = db.query(Organization).order_by(Organization.id.asc()).first()
    if org:
        return org
    org = Organization(name="Default Organization", plan_type="v0")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def project_to_read(project: Project, competitors: Optional[list[Competitor]] = None) -> ProjectRead:
    competitors = competitors if competitors is not None else project.competitors
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
                id=item.id,
                project_id=item.project_id,
                name=item.name,
                aliases=loads(item.aliases_json, []),
                website_url=item.website_url,
                created_at=item.created_at,
            )
            for item in competitors
        ],
    )


def run_to_read(run: MonitorRun) -> MonitorRunRead:
    return MonitorRunRead(
        id=run.id,
        project_id=run.project_id,
        run_type=run.run_type,
        status=run.status,
        platform_keys=loads(run.platform_keys_json, []),
        prompt_count=run.prompt_count,
        repeat_count=run.repeat_count,
        started_at=run.started_at,
        finished_at=run.finished_at,
        success_count=run.success_count,
        failure_count=run.failure_count,
        cost_estimate=run.cost_estimate,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/organizations", response_model=OrganizationRead)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)) -> Organization:
    org = Organization(name=payload.name, plan_type=payload.plan_type)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    ensure_default_org(db)
    return db.query(Organization).order_by(Organization.id.desc()).all()


@router.post("/projects", response_model=ProjectRead)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectRead:
    org_id = payload.organization_id or ensure_default_org(db).id
    project = Project(
        organization_id=org_id,
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
        db.add(
            Competitor(
                project_id=project.id,
                name=item.name,
                aliases_json=dumps(item.aliases),
                website_url=item.website_url,
            )
        )
    db.commit()
    db.refresh(project)
    competitors = db.query(Competitor).filter(Competitor.project_id == project.id).all()
    return project_to_read(project, competitors)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectRead]:
    projects = db.query(Project).order_by(Project.id.desc()).all()
    return [project_to_read(project, db.query(Competitor).filter(Competitor.project_id == project.id).all()) for project in projects]


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectRead:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    competitors = db.query(Competitor).filter(Competitor.project_id == project.id).all()
    return project_to_read(project, competitors)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)) -> ProjectRead:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    data = payload.model_dump(exclude_unset=True)
    competitors_payload = data.pop("competitors", None)
    brand_aliases = data.pop("brand_aliases", None)
    if brand_aliases is not None:
        project.brand_aliases_json = dumps(brand_aliases)
    for key, value in data.items():
        setattr(project, key, value)
    if competitors_payload is not None:
        # 安全护栏：删除前先完整校验 payload，任何一项非法立即 fail-closed，
        # 绝不先删后验（此前事故：测试请求带 1 个竞品覆盖了全部 3 个）。
        validated: list[dict] = []
        for item in competitors_payload:
            name = str(item.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="竞品名称不能为空")
            validated.append({
                "name": name,
                "aliases": [str(a) for a in (item.get("aliases") or []) if str(a).strip()],
                "website_url": str(item.get("website_url") or "").strip(),
            })
        db.query(Competitor).filter(Competitor.project_id == project_id).delete()
        for item in validated:
            db.add(Competitor(project_id=project_id, name=item["name"], aliases_json=dumps(item["aliases"]), website_url=item["website_url"]))
    db.commit()
    db.refresh(project)
    competitors = db.query(Competitor).filter(Competitor.project_id == project.id).all()
    return project_to_read(project, competitors)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/topics", response_model=TopicRead)
def create_topic(project_id: int, payload: TopicCreate, db: Session = Depends(get_db)) -> Topic:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    topic = Topic(project_id=project_id, **payload.model_dump())
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


@router.get("/projects/{project_id}/topics", response_model=list[TopicRead])
def list_topics(project_id: int, db: Session = Depends(get_db)) -> list[Topic]:
    return db.query(Topic).filter(Topic.project_id == project_id).order_by(Topic.sort_order, Topic.id).all()


@router.patch("/topics/{topic_id}", response_model=TopicRead)
def update_topic(topic_id: int, payload: TopicUpdate, db: Session = Depends(get_db)) -> Topic:
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(topic, key, value)
    db.commit()
    db.refresh(topic)
    return topic


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    db.query(Prompt).filter(Prompt.topic_id == topic_id).update({Prompt.topic_id: None})
    db.query(PromptCluster).filter(PromptCluster.topic_id == topic_id).update({PromptCluster.topic_id: None})
    db.delete(topic)
    db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/prompt-clusters", response_model=PromptClusterRead)
def create_prompt_cluster(project_id: int, payload: PromptClusterCreate, db: Session = Depends(get_db)) -> PromptCluster:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.topic_id is not None:
        topic = db.get(Topic, payload.topic_id)
        if not topic or topic.project_id != project_id:
            raise HTTPException(status_code=400, detail="Topic does not belong to project")
    cluster = PromptCluster(project_id=project_id, **payload.model_dump())
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return cluster


@router.get("/projects/{project_id}/prompt-clusters", response_model=list[PromptClusterRead])
def list_prompt_clusters(project_id: int, db: Session = Depends(get_db)) -> list[PromptCluster]:
    return db.query(PromptCluster).filter(PromptCluster.project_id == project_id).order_by(PromptCluster.sort_order, PromptCluster.id).all()


@router.patch("/prompt-clusters/{cluster_id}", response_model=PromptClusterRead)
def update_prompt_cluster(cluster_id: int, payload: PromptClusterUpdate, db: Session = Depends(get_db)) -> PromptCluster:
    cluster = db.get(PromptCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Prompt cluster not found")
    values = payload.model_dump(exclude_unset=True)
    if values.get("topic_id") is not None:
        topic = db.get(Topic, values["topic_id"])
        if not topic or topic.project_id != cluster.project_id:
            raise HTTPException(status_code=400, detail="Topic does not belong to project")
    for key, value in values.items():
        setattr(cluster, key, value)
    db.commit()
    db.refresh(cluster)
    return cluster


@router.delete("/prompt-clusters/{cluster_id}")
def delete_prompt_cluster(cluster_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    cluster = db.get(PromptCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Prompt cluster not found")
    db.query(Prompt).filter(Prompt.cluster_id == cluster_id).update({Prompt.cluster_id: None})
    db.delete(cluster)
    db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/monitoring-batches", response_model=MonitoringBatchRead)
def create_monitoring_batch(project_id: int, payload: MonitoringBatchCreate, db: Session = Depends(get_db)) -> MonitoringBatch:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    batch = MonitoringBatch(project_id=project_id, **payload.model_dump())
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/projects/{project_id}/monitoring-batches", response_model=list[MonitoringBatchRead])
def list_monitoring_batches(project_id: int, db: Session = Depends(get_db)) -> list[MonitoringBatch]:
    return db.query(MonitoringBatch).filter(MonitoringBatch.project_id == project_id).order_by(MonitoringBatch.id.desc()).all()


@router.patch("/monitoring-batches/{batch_id}", response_model=MonitoringBatchRead)
def update_monitoring_batch(batch_id: int, payload: MonitoringBatchUpdate, db: Session = Depends(get_db)) -> MonitoringBatch:
    batch = db.get(MonitoringBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Monitoring batch not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(batch, key, value)
    db.commit()
    db.refresh(batch)
    return batch


@router.delete("/monitoring-batches/{batch_id}")
def delete_monitoring_batch(batch_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    batch = db.get(MonitoringBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Monitoring batch not found")
    db.delete(batch)
    db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/prompts", response_model=PromptRead)
def create_prompt(project_id: int, payload: PromptCreate, db: Session = Depends(get_db)) -> Prompt:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.topic_id is not None:
        topic = db.get(Topic, payload.topic_id)
        if not topic or topic.project_id != project_id:
            raise HTTPException(status_code=400, detail="Topic does not belong to project")
    if payload.cluster_id is not None:
        cluster = db.get(PromptCluster, payload.cluster_id)
        if not cluster or cluster.project_id != project_id:
            raise HTTPException(status_code=400, detail="Prompt cluster does not belong to project")
    prompt = Prompt(project_id=project_id, **payload.model_dump())
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.get("/projects/{project_id}/prompts", response_model=list[PromptRead])
def list_prompts(project_id: int, db: Session = Depends(get_db)) -> list[Prompt]:
    return db.query(Prompt).filter(Prompt.project_id == project_id).order_by(Prompt.id.desc()).all()


@router.patch("/projects/{project_id}/prompts/{prompt_id}", response_model=PromptRead)
def update_prompt(project_id: int, prompt_id: int, payload: PromptUpdate, db: Session = Depends(get_db)) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt not found")
    values = payload.model_dump(exclude_unset=True)
    if "topic_id" in values and values["topic_id"] is not None:
        topic = db.get(Topic, values["topic_id"])
        if not topic or topic.project_id != project_id:
            raise HTTPException(status_code=400, detail="Topic does not belong to project")
    if "cluster_id" in values and values["cluster_id"] is not None:
        cluster = db.get(PromptCluster, values["cluster_id"])
        if not cluster or cluster.project_id != project_id:
            raise HTTPException(status_code=400, detail="Prompt cluster does not belong to project")
    for key, value in values.items():
        setattr(prompt, key, value)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.delete("/projects/{project_id}/prompts/{prompt_id}")
def delete_prompt(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    prompt = db.get(Prompt, prompt_id)
    if not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Prompt not found")
    # Check dependencies
    run_count = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.prompt_id == prompt_id).count()
    obs_count = db.query(Observation).filter(Observation.prompt_id == prompt_id).count()
    if run_count > 0 or obs_count > 0:
        raise HTTPException(status_code=400, detail=f"无法删除：该 Prompt 有 {run_count} 个采集 Run 和 {obs_count} 个观测记录，请先删除关联数据")
    db.delete(prompt)
    db.commit()
    return {"deleted": True, "id": prompt_id}


@router.post("/projects/{project_id}/prompts/batch-delete")
def batch_delete_prompts(project_id: int, payload: dict, db: Session = Depends(get_db)):
    prompt_ids = payload.get("ids", [])
    if not prompt_ids:
        raise HTTPException(status_code=400, detail="请提供要删除的 Prompt ID 列表")
    # Preflight: check ALL prompts before deleting any
    blocked = []
    for pid in prompt_ids:
        prompt = db.get(Prompt, pid)
        if not prompt or prompt.project_id != project_id:
            blocked.append(f"#{pid}: 不存在或不属于该项目")
            continue
        runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.prompt_id == pid).count()
        obs = db.query(Observation).filter(Observation.prompt_id == pid).count()
        if runs > 0 or obs > 0:
            blocked.append(f"#{pid}: 有 {runs} 个采集 Run / {obs} 个观测记录")
    if blocked:
        raise HTTPException(
            status_code=400,
            detail=f"批量删除失败，以下 Prompt 无法删除：{'；'.join(blocked)}。请先清理关联数据后再试。",
        )
    # All clear — delete all
    for pid in prompt_ids:
        db.delete(db.get(Prompt, pid))
    db.commit()
    return {"deleted": len(prompt_ids)}


@router.get("/platforms")
def platforms() -> list[dict[str, str]]:
    return list_platforms()


@router.post("/projects/{project_id}/monitor-runs", response_model=MonitorRunRead)
def create_monitor_run(project_id: int, payload: MonitorRunCreate, db: Session = Depends(get_db)) -> MonitorRunRead:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    prompts = db.query(Prompt).filter(Prompt.project_id == project_id, Prompt.id.in_(payload.prompt_ids)).all()
    if not prompts:
        raise HTTPException(status_code=400, detail="No prompts selected")
    run = run_monitoring_job(db, project, prompts, payload.platform_keys, payload.repeat_count)
    return run_to_read(run)


@router.get("/projects/{project_id}/monitor-runs", response_model=list[MonitorRunRead])
def list_monitor_runs(project_id: int, db: Session = Depends(get_db)) -> list[MonitorRunRead]:
    runs = db.query(MonitorRun).filter(MonitorRun.project_id == project_id).order_by(MonitorRun.id.desc()).all()
    return [run_to_read(run) for run in runs]


@router.get("/projects/{project_id}/observations", response_model=list[ObservationRead])
def list_observations(project_id: int, db: Session = Depends(get_db)) -> list[ObservationRead]:
    observations = db.query(Observation).filter(Observation.project_id == project_id).order_by(Observation.id.desc()).limit(100).all()
    return [observation_to_read(db, observation) for observation in observations]


@router.get("/observations/{observation_id}", response_model=ObservationRead)
def get_observation(observation_id: int, db: Session = Depends(get_db)) -> ObservationRead:
    observation = db.get(Observation, observation_id)
    if not observation:
        raise HTTPException(status_code=404, detail="Observation not found")
    return observation_to_read(db, observation)


@router.get("/projects/{project_id}/metrics/overview", response_model=MetricsOverview)
def metrics_overview(project_id: int, db: Session = Depends(get_db)) -> MetricsOverview:
    prompt_count = db.query(Prompt).filter(Prompt.project_id == project_id).count()
    observations = db.query(Observation).filter(Observation.project_id == project_id).all()
    observation_count = len(observations)
    if observation_count == 0:
        return MetricsOverview(
            prompt_count=prompt_count,
            observation_count=0,
            platform_success_rate=0,
            brand_mention_rate=0,
            competitor_mention_rate=0,
            official_citation_rate=0,
        )
    observation_ids = [item.id for item in observations]
    mentions = db.query(ExtractedMention).filter(ExtractedMention.observation_id.in_(observation_ids)).all()
    success_count = sum(1 for item in observations if item.status == "success")
    brand_mentions = sum(1 for item in mentions if item.brand_mentioned)
    competitor_mentions = sum(1 for item in mentions if loads(item.competitors_json, []))
    official_citations = sum(1 for item in mentions if item.cited_official_domain)
    return MetricsOverview(
        prompt_count=prompt_count,
        observation_count=observation_count,
        platform_success_rate=success_count / observation_count,
        brand_mention_rate=brand_mentions / observation_count,
        competitor_mention_rate=competitor_mentions / observation_count,
        official_citation_rate=official_citations / observation_count,
    )


def observation_to_read(db: Session, observation: Observation) -> ObservationRead:
    citations = db.query(AnswerCitation).filter(AnswerCitation.observation_id == observation.id).order_by(AnswerCitation.position.asc()).all()
    mention = db.query(ExtractedMention).filter(ExtractedMention.observation_id == observation.id).first()
    mention_read = None
    if mention:
        mention_read = MentionRead(
            brand_mentioned=mention.brand_mentioned,
            brand_recommended=mention.brand_recommended,
            brand_first_position=mention.brand_first_position,
            competitors=loads(mention.competitors_json, []),
            cited_official_domain=mention.cited_official_domain,
            cited_competitor_domains=loads(mention.cited_competitor_domains_json, []),
            sentiment=mention.sentiment,
        )
    return ObservationRead(
        id=observation.id,
        run_id=observation.run_id,
        project_id=observation.project_id,
        prompt_id=observation.prompt_id,
        platform_key=observation.platform_key,
        entry_type=observation.entry_type,
        model=observation.model,
        model_version=observation.model_version,
        web_search_enabled=observation.web_search_enabled,
        sample_index=observation.sample_index,
        status=observation.status,
        answer_text=observation.answer_text,
        latency_ms=observation.latency_ms,
        cost_estimate=observation.cost_estimate,
        queried_at=observation.queried_at,
        content_hash=observation.content_hash,
        citations=[CitationRead.model_validate(item) for item in citations],
        mention=mention_read,
    )

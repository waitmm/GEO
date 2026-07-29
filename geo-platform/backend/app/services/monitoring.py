import asyncio
import hashlib
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.adapters.registry import get_adapter
from app.models import AnswerCitation, Competitor, ExtractedMention, MonitorRun, Observation, Project, Prompt
from app.services.extraction import extract_mentions
from app.services.serialization import dumps


def domain_from_url(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower().removeprefix("www.")


def run_monitoring_job(
    db: Session,
    project: Project,
    prompts: list[Prompt],
    platform_keys: list[str],
    repeat_count: int,
) -> MonitorRun:
    monitor_run = MonitorRun(
        project_id=project.id,
        run_type="manual",
        status="running",
        platform_keys_json=dumps(platform_keys),
        prompt_count=len(prompts),
        repeat_count=repeat_count,
        started_at=datetime.utcnow(),
    )
    db.add(monitor_run)
    db.commit()
    db.refresh(monitor_run)

    success_count = 0
    failure_count = 0
    competitors = db.query(Competitor).filter(Competitor.project_id == project.id).all()

    for prompt in prompts:
        for platform_key in platform_keys:
            adapter = get_adapter(platform_key)
            for sample_index in range(1, repeat_count + 1):
                try:
                    result = asyncio.run(
                        adapter.run_query(
                            prompt.prompt_text,
                            metadata={
                                "brand_name": project.brand_name,
                                "website_url": project.website_url,
                                "competitors": [competitor.name for competitor in competitors],
                            },
                        )
                    )
                    answer_text = result.answer_text or ""
                    content_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
                    observation = Observation(
                        run_id=monitor_run.id,
                        project_id=project.id,
                        prompt_id=prompt.id,
                        platform_key=result.platform,
                        entry_type=result.entry_type,
                        model=result.model or "",
                        model_version=result.model_version or "",
                        web_search_enabled=result.web_search_enabled,
                        sample_index=sample_index,
                        status=result.status,
                        answer_text=answer_text,
                        raw_response_json=dumps(result.raw_response),
                        latency_ms=result.latency_ms,
                        cost_estimate=result.cost_estimate or 0,
                        queried_at=datetime.utcnow(),
                        content_hash=content_hash,
                    )
                    db.add(observation)
                    db.flush()

                    citation_urls = []
                    for index, citation in enumerate(result.citations, start=1):
                        citation_urls.append(citation.url)
                        db.add(
                            AnswerCitation(
                                observation_id=observation.id,
                                url=citation.url,
                                title=citation.title,
                                snippet=citation.snippet or "",
                                source_name=citation.source_name or "",
                                domain=domain_from_url(citation.url),
                                position=index,
                            )
                        )

                    extracted = extract_mentions(answer_text, citation_urls, project, competitors)
                    db.add(
                        ExtractedMention(
                            observation_id=observation.id,
                            brand_mentioned=extracted["brand_mentioned"],
                            brand_recommended=extracted["brand_recommended"],
                            brand_first_position=extracted["brand_first_position"],
                            competitors_json=dumps(extracted["competitors"]),
                            cited_official_domain=extracted["cited_official_domain"],
                            cited_competitor_domains_json=dumps(extracted["cited_competitor_domains"]),
                            sentiment=extracted["sentiment"],
                            extraction_json=dumps(extracted),
                        )
                    )
                    success_count += 1 if result.status == "success" else 0
                    failure_count += 1 if result.status != "success" else 0
                    db.commit()
                except Exception as exc:
                    failure_count += 1
                    db.rollback()
                    monitor_run.error_summary_json = dumps({"last_error": str(exc)})
                    db.commit()

    monitor_run.status = "completed" if failure_count == 0 else "partial"
    monitor_run.finished_at = datetime.utcnow()
    monitor_run.success_count = success_count
    monitor_run.failure_count = failure_count
    db.commit()
    db.refresh(monitor_run)
    return monitor_run

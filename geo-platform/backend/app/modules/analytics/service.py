from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import BrowserMonitorRun, Competitor, Project, Prompt, ReferenceSource
from app.modules.analytics.schemas import (
    CitationDomainRow,
    CitationUrlRow,
    DataQuality,
    PresenceRow,
    PromptSummary,
    RecommendationPresence,
    ReferenceQuality,
    ValidationDashboard,
)
from app.services.serialization import loads


VALID_STATUSES = {"success", "partial_success"}
TERMINAL_STATUSES = VALID_STATUSES | {"failed", "blocked", "collector_failed"}
BLOCKED_ERROR_TYPES = {
    "blocked",
    "captcha_required",
    "login_required",
    "security_verification",
    "access_denied",
    "rate_limited",
}


@dataclass(frozen=True)
class _Entity:
    entity_type: str
    name: str
    aliases: tuple[str, ...]


def build_validation_dashboard(db: Session, project: Project, limit: int = 10) -> ValidationDashboard:
    prompts = db.query(Prompt).filter(Prompt.project_id == project.id).all()
    runs = (
        db.query(BrowserMonitorRun)
        .filter(BrowserMonitorRun.project_id == project.id)
        .order_by(BrowserMonitorRun.id.asc())
        .all()
    )
    valid_runs = [run for run in runs if run.status in VALID_STATUSES]
    valid_run_ids = [run.id for run in valid_runs]
    references = (
        db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(valid_run_ids)).all()
        if valid_run_ids
        else []
    )

    brand = _Entity(
        entity_type="brand",
        name=project.brand_name,
        aliases=_aliases(project.brand_name, getattr(project, "brand_aliases_json", "[]")),
    )
    competitors = [
        _Entity("competitor", item.name, _aliases(item.name, item.aliases_json))
        for item in db.query(Competitor).filter(Competitor.project_id == project.id).all()
    ]

    return ValidationDashboard(
        project_id=project.id,
        prompts=_prompt_summary(prompts, runs, valid_runs),
        brand_presence=_presence(brand, valid_runs),
        competitor_presence=[_presence(entity, valid_runs) for entity in competitors],
        recommendation_presence=_recommendations(brand, valid_runs),
        top_citation_domains=_top_domains(references, runs, limit),
        top_citation_urls=_top_urls(references, runs, limit),
        data_quality=_data_quality(runs),
    )


def _prompt_summary(
    prompts: list[Prompt], runs: list[BrowserMonitorRun], valid_runs: list[BrowserMonitorRun]
) -> PromptSummary:
    prompt_ids_with_runs = {run.prompt_id for run in runs}
    clusters = {
        (getattr(prompt, "prompt_group", "") or "Ungrouped").strip()
        for prompt in prompts
    }
    configured_samples = sum(max(1, int(getattr(prompt, "sample_count", 1) or 1)) for prompt in prompts)
    return PromptSummary(
        total_prompts=len(prompts),
        total_clusters=len(clusters) if prompts else 0,
        prompts_with_runs=len(prompt_ids_with_runs),
        configured_samples=configured_samples,
        collected_samples=len(runs),
        valid_samples=len(valid_runs),
    )


def _aliases(name: str, raw_aliases: str) -> tuple[str, ...]:
    values = [name, *loads(raw_aliases, [])]
    return tuple(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))


def _mentions(text: str, aliases: Iterable[str]) -> bool:
    folded = (text or "").casefold()
    return any(alias.casefold() in folded for alias in aliases)


def _presence(entity: _Entity, runs: list[BrowserMonitorRun]) -> PresenceRow:
    observed = sum(_mentions(run.answer_text, entity.aliases) for run in runs)
    sample_count = len(runs)
    return PresenceRow(
        entity_type=entity.entity_type,
        name=entity.name,
        observed_runs=observed,
        sample_runs=sample_count,
        observed_share=round(observed / sample_count, 4) if sample_count else 0,
    )


def _recommendations(brand: _Entity, runs: list[BrowserMonitorRun]) -> RecommendationPresence:
    explicit = general = absent = 0
    for run in runs:
        if not _mentions(run.answer_text, brand.aliases):
            absent += 1
        elif int(getattr(run, "brand_recommendation_level", 0) or 0) >= 2:
            explicit += 1
        else:
            general += 1
    return RecommendationPresence(
        explicit_recommendation=explicit,
        general_mention=general,
        not_observed=absent,
        sample_runs=len(runs),
    )


def _run_prompt_map(runs: list[BrowserMonitorRun]) -> dict[int, int]:
    return {run.id: run.prompt_id for run in runs}


def _top_domains(
    references: list[ReferenceSource], runs: list[BrowserMonitorRun], limit: int
) -> list[CitationDomainRow]:
    prompt_by_run = _run_prompt_map(runs)
    buckets: dict[str, dict[str, object]] = defaultdict(
        lambda: {"occurrences": 0, "runs": set(), "prompts": set()}
    )
    for reference in references:
        domain = (reference.domain or "").strip().lower()
        if not domain:
            continue
        bucket = buckets[domain]
        bucket["occurrences"] += 1
        bucket["runs"].add(reference.run_id)
        bucket["prompts"].add(prompt_by_run.get(reference.run_id))
    ordered = sorted(buckets.items(), key=lambda item: (-int(item[1]["occurrences"]), item[0]))
    return [
        CitationDomainRow(
            domain=domain,
            occurrences=int(bucket["occurrences"]),
            run_count=len(bucket["runs"]),
            prompt_count=len(bucket["prompts"] - {None}),
        )
        for domain, bucket in ordered[:limit]
    ]


def _top_urls(
    references: list[ReferenceSource], runs: list[BrowserMonitorRun], limit: int
) -> list[CitationUrlRow]:
    prompt_by_run = _run_prompt_map(runs)
    buckets: dict[str, dict[str, object]] = {}
    for reference in references:
        url = (reference.canonical_url or reference.url or "").strip()
        if not url:
            continue
        bucket = buckets.setdefault(
            url,
            {
                "title": reference.display_title or reference.matched_title or "",
                "domain": reference.domain or "",
                "occurrences": 0,
                "runs": set(),
                "prompts": set(),
            },
        )
        bucket["occurrences"] += 1
        bucket["runs"].add(reference.run_id)
        bucket["prompts"].add(prompt_by_run.get(reference.run_id))
    ordered = sorted(buckets.items(), key=lambda item: (-int(item[1]["occurrences"]), item[0]))
    return [
        CitationUrlRow(
            url=url,
            title=str(bucket["title"]),
            domain=str(bucket["domain"]),
            occurrences=int(bucket["occurrences"]),
            run_count=len(bucket["runs"]),
            prompt_count=len(bucket["prompts"] - {None}),
        )
        for url, bucket in ordered[:limit]
    ]


def _data_quality(runs: list[BrowserMonitorRun]) -> DataQuality:
    success = blocked = collector_failed = pending = 0
    valid_runs: list[BrowserMonitorRun] = []
    for run in runs:
        if run.status in VALID_STATUSES:
            success += 1
            valid_runs.append(run)
        elif run.status == "blocked" or (run.error_type or "").lower() in BLOCKED_ERROR_TYPES:
            blocked += 1
        elif run.status in {"failed", "collector_failed"}:
            collector_failed += 1
        else:
            pending += 1

    ui_count = sum(int(getattr(run, "ui_declared_reference_count", None) or run.expected_reference_count or 0) for run in valid_runs)
    dom_count = sum(int(getattr(run, "dom_reference_count", None) or run.detected_reference_count or 0) for run in valid_runs)
    parsed_count = sum(int(getattr(run, "parsed_reference_count", None) or run.detected_reference_count or 0) for run in valid_runs)
    resolved_count = sum(resolved_count_for_run(run) for run in valid_runs)
    assessed = sum(max(ui_count_for_run(run), dom_count_for_run(run), parsed_count_for_run(run)) > 0 for run in valid_runs)
    complete = sum(_reference_complete(run) for run in valid_runs if max(ui_count_for_run(run), dom_count_for_run(run), parsed_count_for_run(run)) > 0)
    return DataQuality(
        total_runs=len(runs),
        success=success,
        blocked=blocked,
        collector_failed=collector_failed,
        pending=pending,
        references=ReferenceQuality(
            ui_declared_count=ui_count,
            dom_reference_count=dom_count,
            parsed_reference_count=parsed_count,
            resolved_url_count=resolved_count,
            complete_runs=complete,
            assessed_runs=assessed,
            url_resolution_rate=round(resolved_count / parsed_count, 4) if parsed_count else 0,
        ),
    )


def ui_count_for_run(run: BrowserMonitorRun) -> int:
    return int(
        getattr(run, "ui_declared_count", None)
        or getattr(run, "ui_declared_reference_count", None)
        or run.expected_reference_count
        or 0
    )


def dom_count_for_run(run: BrowserMonitorRun) -> int:
    return int(getattr(run, "dom_reference_count", None) or run.detected_reference_count or 0)


def parsed_count_for_run(run: BrowserMonitorRun) -> int:
    return int(getattr(run, "parsed_reference_count", None) or run.detected_reference_count or 0)


def resolved_count_for_run(run: BrowserMonitorRun) -> int:
    return int(
        getattr(run, "resolved_url_count", None)
        or run.resolved_reference_count
        or 0
    )


def _reference_complete(run: BrowserMonitorRun) -> bool:
    ui_count = ui_count_for_run(run)
    dom_count = dom_count_for_run(run)
    parsed_count = parsed_count_for_run(run)
    resolved_count = resolved_count_for_run(run)
    return bool(
        getattr(run, "reference_complete", False)
        or (ui_count == dom_count == parsed_count == resolved_count and ui_count > 0)
    )

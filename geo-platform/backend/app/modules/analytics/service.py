from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import BrowserMonitorRun, Competitor, Project, Prompt, PromptDailyReport, ReferenceSource, RetrievalCandidate
from app.modules.analytics.schemas import (
    CitationDomainRow,
    CitationUrlRow,
    DataQuality,
    PresenceRow,
    PromptDailyReportRead,
    PromptSummary,
    RecommendationPresence,
    ReferenceQuality,
    ValidationDashboard,
)
from app.services.serialization import dumps, loads


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


def build_prompt_daily_report(
    db: Session,
    project: Project,
    prompt: Prompt,
    report_date: str | None = None,
) -> PromptDailyReport:
    target_date = _parse_report_date(report_date)
    start_at = datetime.combine(target_date, time.min)
    end_at = start_at + timedelta(days=1)
    runs = (
        db.query(BrowserMonitorRun)
        .filter(
            BrowserMonitorRun.project_id == project.id,
            BrowserMonitorRun.prompt_id == prompt.id,
            BrowserMonitorRun.created_at >= start_at,
            BrowserMonitorRun.created_at < end_at,
        )
        .order_by(BrowserMonitorRun.id.asc())
        .all()
    )
    valid_runs = [run for run in runs if run.status in VALID_STATUSES]
    run_ids = [run.id for run in valid_runs]
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all() if run_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all() if run_ids else []

    brand_aliases = _aliases(project.brand_name, getattr(project, "brand_aliases_json", "[]"))
    brand_mentions = sum(_mentions(run.answer_text, brand_aliases) for run in valid_runs)
    reference_total = sum(parsed_count_for_run(run) for run in valid_runs)
    top_reference_domains = _rank_domains([item.domain for item in references], limit=8)
    top_retrieval_domains = _rank_domains([item.domain for item in retrievals], limit=8)
    report_date_key = target_date.isoformat()
    recommendations = _daily_recommendations(
        project=project,
        prompt=prompt,
        sample_count=len(valid_runs),
        brand_mentions=brand_mentions,
        avg_reference_count=round(reference_total / len(valid_runs), 2) if valid_runs else 0,
        top_reference_domains=top_reference_domains,
        top_retrieval_domains=top_retrieval_domains,
    )
    summary = _daily_summary(
        project=project,
        prompt=prompt,
        report_date=report_date_key,
        sample_count=len(valid_runs),
        brand_mentions=brand_mentions,
        avg_reference_count=round(reference_total / len(valid_runs), 2) if valid_runs else 0,
    )

    report = (
        db.query(PromptDailyReport)
        .filter(
            PromptDailyReport.project_id == project.id,
            PromptDailyReport.prompt_id == prompt.id,
            PromptDailyReport.report_date == report_date_key,
        )
        .first()
    )
    if report is None:
        report = PromptDailyReport(project_id=project.id, prompt_id=prompt.id, report_date=report_date_key)
        db.add(report)
    report.run_ids_json = dumps(run_ids)
    report.sample_count = len(valid_runs)
    report.success_count = sum(run.status == "success" for run in valid_runs)
    report.brand_mention_count = brand_mentions
    report.brand_mention_rate = round(brand_mentions / len(valid_runs), 4) if valid_runs else 0
    report.avg_reference_count = round(reference_total / len(valid_runs), 2) if valid_runs else 0
    report.top_reference_domains_json = dumps(top_reference_domains)
    report.top_retrieval_domains_json = dumps(top_retrieval_domains)
    report.summary = summary
    report.recommendations_json = dumps(recommendations)
    db.commit()
    db.refresh(report)
    return report


def prompt_daily_report_to_read(report: PromptDailyReport) -> PromptDailyReportRead:
    return PromptDailyReportRead(
        id=report.id,
        project_id=report.project_id,
        prompt_id=report.prompt_id,
        report_date=report.report_date,
        run_ids=loads(report.run_ids_json, []),
        sample_count=report.sample_count,
        success_count=report.success_count,
        brand_mention_count=report.brand_mention_count,
        brand_mention_rate=report.brand_mention_rate,
        avg_reference_count=report.avg_reference_count,
        top_reference_domains=loads(report.top_reference_domains_json, []),
        top_retrieval_domains=loads(report.top_retrieval_domains_json, []),
        summary=report.summary,
        recommendations=loads(report.recommendations_json, []),
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _parse_report_date(value: str | None) -> date:
    if not value:
        return datetime.utcnow().date()
    return date.fromisoformat(value)


def _rank_domains(domains: Iterable[str], limit: int) -> list[dict[str, object]]:
    counter = Counter(domain.strip().lower() for domain in domains if domain and domain.strip())
    return [{"domain": domain, "count": count} for domain, count in counter.most_common(limit)]


def _daily_summary(
    project: Project,
    prompt: Prompt,
    report_date: str,
    sample_count: int,
    brand_mentions: int,
    avg_reference_count: float,
) -> str:
    if sample_count == 0:
        return f"{report_date} 尚无可用于分析的成功样本，Prompt「{prompt.prompt_text[:60]}」需要先完成采集。"
    rate = round(brand_mentions / sample_count * 100, 1)
    return (
        f"{report_date} 对 Prompt「{prompt.prompt_text[:60]}」完成 {sample_count} 个有效样本；"
        f"品牌「{project.brand_name}」出现 {brand_mentions} 次，出现率 {rate}%；"
        f"平均引用资料 {avg_reference_count} 条。"
    )


def _daily_recommendations(
    project: Project,
    prompt: Prompt,
    sample_count: int,
    brand_mentions: int,
    avg_reference_count: float,
    top_reference_domains: list[dict],
    top_retrieval_domains: list[dict],
) -> list[str]:
    if sample_count == 0:
        return ["先完成当天采集，再生成报告；没有样本时不建议给出品牌优化结论。"]
    recommendations: list[str] = []
    if brand_mentions == 0:
        recommendations.append(
            f"品牌「{project.brand_name}」未进入该 Prompt 的答案，需要建设直接回答该问题的内容页，并在标题、H1、首段明确覆盖 Prompt 的核心问法。"
        )
    elif brand_mentions < sample_count:
        recommendations.append(
            "品牌只在部分样本出现，建议补强更稳定的品牌实体信号：官网内容、品牌别名、典型使用场景和第三方可引用资料需要保持一致。"
        )
    else:
        recommendations.append("品牌已在当天全部有效样本出现，下一步重点从“被提及”提升到“被明确推荐”。")
    if top_reference_domains:
        domain = top_reference_domains[0]["domain"]
        recommendations.append(f"优先研究高频引用域名 {domain} 的内容结构，补齐同类问题的定义、步骤、避坑、案例和更新时间信号。")
    if top_retrieval_domains:
        domain = top_retrieval_domains[0]["domain"]
        recommendations.append(f"检索候选里高频出现 {domain}，说明模型检索阶段会先接触这类来源；可围绕该来源覆盖的关键词布局对标内容。")
    if avg_reference_count < 3:
        recommendations.append("当天平均引用资料偏少，建议增加可被引用的长文、教程、FAQ 或权威说明页，提高检索阶段可选资料密度。")
    return recommendations
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
        getattr(prompt, "cluster_id", None) or (getattr(prompt, "prompt_group", "") or "Ungrouped").strip()
        for prompt in prompts
    }
    return PromptSummary(
        total_prompts=len(prompts),
        total_clusters=len(clusters) if prompts else 0,
        prompts_with_runs=len(prompt_ids_with_runs),
        configured_samples=len(runs),
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

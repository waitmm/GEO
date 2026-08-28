from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import html as html_lib
import ipaddress
import json
import re
import subprocess
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import urllib.request

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    AnswerDecisionBinding,
    AnswerSemanticFact,
    BrowserMonitorRun,
    Competitor,
    DecisionEvidenceAdoption,
    MonitoringBatch,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationHypothesis,
    OptimizationIssue,
    OptimizationIssueRun,
    OptimizationStrategyCandidate,
    PageSnapshot,
    Project,
    Prompt,
    AnswerUnit,
    EvidenceAlignment,
    RecommendationClaim,
    RecommendationEvent,
    RecommendationIntelligenceSnapshot,
    ReferenceSource,
    ReleaseAuditRecord,
    RetrievalCandidate,
    SourceClaim,
    SourceDocument,
    SourceMetadataCache,
    SourceQuality,
    TargetBrandCapabilityTruth,
    WorkflowConfirmation,
)
from app.core.config import get_settings
from app.modules.monitoring.enums import BROWSER_AUDIT_ENTRY_TYPE, WENXIN_PLATFORM, WENXIN_WEB_ADAPTER
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import create_browser_task, update_task_status_from_runs
from app.modules.optimization.evidence_lineage import eligible_evidence_alignments_for_v1
from app.modules.optimization.passage_retrieval import ANSWER_BINDING_REASON_SOURCE, FORMAL_V1_1_INPUT_VERSION
from app.modules.optimization.source_qualification import derive_content_status
from app.services.serialization import dumps, loads


VALID_RUN_STATUSES = {"success", "partial_success"}
ACTION_STATUS_MAP = {
    "draft": "PLANNED",
    "released": "RELEASE_CONFIRMED",
}
RELEASABLE_ACTION_STATUSES = {"PLANNED", "READY_FOR_MANUAL_RELEASE", "draft", "released"}
CONCLUSION_MAP = {
    "positive": "EFFECTIVE",
    "neutral": "NO_MEASURABLE_EFFECT",
    "negative": "NEGATIVE_EFFECT",
    "inconclusive": "INSUFFICIENT_EVIDENCE",
}
CONCLUSION_TYPES = {
    "EFFECTIVE",
    "PARTIALLY_EFFECTIVE",
    "MIXED_RESULT",
    "NO_MEASURABLE_EFFECT",
    "NEGATIVE_EFFECT",
    "INSUFFICIENT_EVIDENCE",
}
COMPARABILITY_STATUSES = {
    "COMPARABLE",
    "POTENTIALLY_CONFOUNDED",
    "MATERIALLY_CONFOUNDED",
    "INSUFFICIENT_CONTEXT",
}
KNOWN_ENVIRONMENT_AUDIT_KEYS = [
    "model_version_known_changed",
    "citation_landscape_changed",
    "competitor_source_changed",
    "brand_market_changed",
    "other_known_changes",
]
ISSUE_TYPES = {
    "brand_absent",
    "brand_not_recommended",
    "target_page_not_retrieved",
    "retrieved_not_cited",
    "official_source_absent",
    "citation_unstable",
}
SOURCE_METADATA_FETCH_LIMIT = 8
SOURCE_METADATA_TIMEOUT_SECONDS = 4
EVIDENCE_SCHEMA_VERSION = "b1.v4"
METRIC_SPEC_VERSION = "metric.v3"
COLLECTOR_VERSION = "wenxin_web_audit"
RETRIEVAL_PARSER_VERSION = "retrieval_parser.v3_no_top20_cap"
CONTENT_CLASSIFIER_VERSION = "content_classifier.v1"
TIME_EXTRACTOR_VERSION = "time_extractor.v1"
RUN_ELIGIBILITY_VERSION = "run_eligibility.v1"
EVIDENCE_VALIDATOR_VERSION = "evidence_validator.v1"
EVIDENCE_ACTION_VERSION = "evidence_action.v1"
SOURCE_RELATION_VERSION = "relation.v1"
STRATEGY_VERSION = "strategy.v2"
VERTICAL_SLICE_VERSION = "citation_decision_vertical_slice.v1"
UNAVAILABLE_RETRIEVAL_METRIC_STATUSES = {"not_applicable", "insufficient_retrieval_candidates", "unknown"}

# Canonical intervention types (single source of truth — project spec §7)
# OFFICIAL_PAGE_UPDATE  = modify existing official page (e.g. /card)
# OFFICIAL_NEW_PAGE     = create new informational page on owned site
# EXTERNAL_PLATFORM_ARTICLE = publish article on external platform
# EXTERNAL_PLATFORM_QA      = publish Q&A content on external platform
# VIDEO_CONTENT         = produce video content
# THIRD_PARTY_REVIEW    = secure third-party review/comparison coverage
# THIRD_PARTY_COMPARISON = secure third-party comparison/list inclusion
# CONTENT_REFRESH       = refresh stale content
# NO_ACTION             = no intervention warranted
# UNRESOLVED            = proposal-stage only; must be resolved during review
INTERVENTION_TYPE = {
    "UNRESOLVED",
    "OFFICIAL_PAGE_UPDATE",
    "OFFICIAL_NEW_PAGE",
    "EXTERNAL_PLATFORM_ARTICLE",
    "EXTERNAL_PLATFORM_QA",
    "VIDEO_CONTENT",
    "THIRD_PARTY_REVIEW",
    "THIRD_PARTY_COMPARISON",
    "CONTENT_REFRESH",
    "NO_ACTION",
}

SOURCE_RELATION = {
    "MATCHED",
    "CITATION_ONLY",
    "CANDIDATE_ONLY",
    "UNKNOWN",
}

DECISION_STATUS = {
    "OPTIONS_AVAILABLE",
    "NEEDS_MORE_EVIDENCE",
    "NO_VIABLE_OPTIONS",
}

DECISION_CAPABILITY = {
    "CONTENT_DIRECTION_ONLY",
    "PLATFORM_AND_CONTENT_DIRECTION",
    "FULL_EXECUTION_READY",
}

STRATEGY_LIFECYCLE = {
    "ACTIVE",
    "SUPERSEDED",
    "OBSOLETE",
}

# ---------------------------------------------------------------------------
# Effective Payload — single executable truth for all strategy execution paths
# ---------------------------------------------------------------------------
EFFECTIVE_PAYLOAD_VERSION = "effective_payload.v1"


def deterministic_merge(base: dict, delta: dict) -> dict:
    """Deterministic merge for effective_payload.v1.

    Rules:
    - Scalar: delta overrides base
    - Dict: recursive merge
    - List: delta replaces base entirely (no append, no dedup, no concat)
    - None: explicit clear
    - Missing key: inherit from base
    """
    result = dict(base)
    for key, val in delta.items():
        if key not in result:
            result[key] = val
        elif isinstance(val, dict) and isinstance(result[key], dict):
            result[key] = deterministic_merge(result[key], val)
        elif isinstance(val, list) and isinstance(result[key], list):
            result[key] = list(val)
        elif val is None:
            result[key] = None
        else:
            result[key] = val
    return result


def get_effective_strategy_payload(candidate) -> dict:
    """Return the single executable truth for this strategy candidate.

    All execution paths (Action, Experiment, Hypothesis, Release Gate, metric
    mapping) MUST use this function. Legacy identity columns and unstructured
    payloads are NEVER authoritative.

    Fail-closed: only VALIDATED effective payloads can be executed.
    BACKFILLED_UNVERIFIED, LEGACY_INVALID, PENDING, VALIDATION_FAILED
    are all rejected — backfill is not automatic re-certification.
    """
    if not candidate:
        return {}
    if candidate.effective_validation_status != "VALIDATED":
        raise HTTPException(
            status_code=400,
            detail=f"Strategy Candidate #{candidate.id} effective payload is not validated (status={candidate.effective_validation_status}). Cannot execute. Backfilled candidates must be re-validated before execution.",
        )
    effective = loads(candidate.effective_payload_json, {})
    if not effective:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy Candidate #{candidate.id} has no effective_payload. Cannot execute.",
        )
    unresolved_fields = _unresolved_strategy_execution_fields(effective)
    if unresolved_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Strategy Candidate #{candidate.id} effective payload still has unresolved execution fields "
                f"({', '.join(unresolved_fields)}). Please resolve channel, asset and intervention during review."
            ),
        )
    return effective


def _unresolved_strategy_execution_fields(payload: dict) -> list[str]:
    if payload.get("intervention_type") == "NO_ACTION":
        return []
    fields: list[str] = []
    for key in ("intervention_type", "target_platform", "target_object", "target_asset", "target_content_type"):
        if payload.get(key) == "UNRESOLVED":
            fields.append(key)
    return fields


INTERVENTION_METRIC_MAP = {
    "UNRESOLVED": "manual_review",
    "OFFICIAL_PAGE_UPDATE": "target_page_retrieval_rate",
    "OFFICIAL_NEW_PAGE": "target_page_retrieval_rate",
    "EXTERNAL_PLATFORM_ARTICLE": "brand_mention_rate",
    "EXTERNAL_PLATFORM_QA": "brand_mention_rate",
    "VIDEO_CONTENT": "brand_mention_rate",
    "THIRD_PARTY_REVIEW": "brand_mention_rate",
    "THIRD_PARTY_COMPARISON": "brand_mention_rate",
    "CONTENT_REFRESH": "official_reference_rate",
    "NO_ACTION": "brand_mention_rate",
}

# Domain → platform mapping for inferred platform semantics
# raw_platform stays as parser-reported value; inferred_platform uses this table
DOMAIN_PLATFORM_MAP = {
    "bilibili.com": "BILIBILI",
    "douyin.com": "DOUYIN",
    "zhihu.com": "ZHIHU",
    "zhuanlan.zhihu.com": "ZHIHU",
    "xiaohongshu.com": "XIAOHONGSHU",
    "baidu.com": "BAIJIAHAO",
    "mbd.baidu.com": "BAIJIAHAO",
    "jingyan.baidu.com": "BAIJIAHAO",
    "haokan.baidu.com": "BAIJIAHAO",
    "quanmin.baidu.com": "BAIJIAHAO",
    "word.baidu.com": "BAIJIAHAO",
    "weixin.qq.com": "WECHAT",
    "mp.weixin.qq.com": "WECHAT",
    "sohu.com": "SOHU",
    "news.sohu.com": "SOHU",
    "sina.com.cn": "SINA",
    "qq.com": "TENCENT",
    "csdn.net": "CSDN",
    "jianshu.com": "JIANSHU",
    "juejin.cn": "JUEJIN",
    "douban.com": "DOUBAN",
    "zhongce.com": "THIRD_PARTY",
}
HYPOTHESIS_VALIDATOR_VERSION = "hypothesis_validator.v1"


def host_from_url(url: str) -> str:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def issue_to_read(issue: OptimizationIssue) -> dict:
    observed_facts = loads(issue.observed_facts_json, {})
    return {
        "id": issue.id,
        "project_id": issue.project_id,
        "prompt_id": issue.prompt_id,
        "prompt_text": str(observed_facts.get("prompt_text", "") or ""),
        "cluster_id": issue.cluster_id,
        "issue_type": issue.issue_type,
        "status": issue.status,
        "severity": issue.severity,
        "confidence_level": issue.confidence_level,
        "observation_start": issue.observation_start,
        "observation_end": issue.observation_end,
        "analyzable_sample_count": issue.analyzable_sample_count,
        "observed_facts": observed_facts,
        "possible_causes": loads(issue.possible_causes_json, []),
        "diagnosis_summary": issue.diagnosis_summary,
        "rejected_reason": issue.rejected_reason,
        "run_ids": [],
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
        "confirmed_at": issue.confirmed_at,
        "resolved_at": issue.resolved_at,
    }


def action_to_read(action: OptimizationAction) -> dict:
    return {
        "id": action.id,
        "issue_id": action.issue_id,
        "action_type": action.action_type,
        "target_type": action.target_type,
        "target_url": action.target_url,
        "status": _normalize_action_status(action.status),
        "priority": action.priority,
        "owner": action.owner,
        "action_summary": action.action_summary,
        "action_detail": action.action_detail,
        "content_feature_changes": _normalize_feature_changes(loads(action.content_feature_changes_json, [])),
        "planned_at": action.planned_at,
        "released_at": action.released_at,
        "release_note": action.release_note,
        "release_evidence": loads(action.release_evidence_json, {}),
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def experiment_to_read(experiment: OptimizationExperiment) -> dict:
    return {
        "id": experiment.id,
        "action_id": experiment.action_id,
        "status": experiment.status,
        "hypothesis": experiment.hypothesis,
        "hypothesis_type": experiment.hypothesis_type,
        "mechanism": experiment.mechanism,
        "intervention_family": experiment.intervention_family,
        "intervention_variables": loads(experiment.intervention_variables_json, {}),
        "allowed_changes": loads(experiment.allowed_changes_json, []),
        "forbidden_changes": loads(experiment.forbidden_changes_json, []),
        "target_prompt_scope": loads(experiment.target_prompt_scope_json, []),
        "control_prompt_scope": loads(experiment.control_prompt_scope_json, []),
        "sentinel_prompt_scope": loads(experiment.sentinel_prompt_scope_json, []),
        "environment_scope": loads(experiment.environment_scope_json, {}),
        "sample_plan": loads(experiment.sample_plan_json, {}),
        "primary_metric": experiment.primary_metric,
        "secondary_metrics": loads(experiment.secondary_metrics_json, []),
        "baseline_numerator": experiment.baseline_numerator,
        "baseline_denominator": experiment.baseline_denominator,
        "baseline_metric_value": experiment.baseline_metric_value,
        "success_threshold": experiment.success_threshold,
        "sample_size_target": experiment.sample_size_target,
        "target_prompt_ids": loads(experiment.target_prompt_ids_json, []),
        "target_brand_id": experiment.target_brand_id,
        "target_asset_ids": loads(experiment.target_asset_ids_json, []),
        "recollection_strategy": loads(experiment.recollection_strategy_json, {}),
        "baseline_start": experiment.baseline_start,
        "baseline_end": experiment.baseline_end,
        "baseline_run_ids": loads(experiment.baseline_run_ids_json, []),
        "baseline_metrics": loads(experiment.baseline_metrics_json, {}),
        "release_blocked": bool(experiment.release_blocked),
        "release_blocked_reason": experiment.release_blocked_reason,
        "released_at": experiment.released_at,
        "first_recrawled_at": experiment.first_recrawled_at,
        "validation_not_before": experiment.validation_not_before,
        "validation_start": experiment.validation_start,
        "validation_end": experiment.validation_end,
        "validation_run_ids": loads(experiment.validation_run_ids_json, []),
        "result_metrics": loads(experiment.result_metrics_json, {}),
        "comparison": loads(experiment.comparison_json, {}),
        "per_prompt_results": loads(experiment.per_prompt_results_json, []),
        "per_environment_results": loads(experiment.per_environment_results_json, []),
        "confounders": loads(experiment.confounders_json, []),
        "known_environment_audit": loads(experiment.known_environment_audit_json, {}),
        "comparability_status": experiment.comparability_status,
        "comparability_note": experiment.comparability_note,
        "controlled_intervention": loads(experiment.controlled_intervention_json, {}),
        "conclusion": _normalize_conclusion(experiment.conclusion) if experiment.conclusion else "",
        "conclusion_reason": experiment.conclusion_reason,
        "post_run_ids": loads(experiment.post_run_ids_json, []),
        "outcome_summary": loads(experiment.outcome_summary_json, {}),
        "created_at": experiment.created_at,
        "updated_at": experiment.updated_at,
        "completed_at": experiment.completed_at,
    }


def page_snapshot_to_read(snapshot: PageSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "experiment_id": snapshot.experiment_id,
        "target_url": snapshot.target_url,
        "url": snapshot.url,
        "http_status": snapshot.http_status,
        "final_url": snapshot.final_url,
        "canonical_url": snapshot.canonical_url,
        "captured_at": snapshot.captured_at,
        "raw_html": snapshot.raw_html,
        "html_hash": snapshot.html_hash,
        "title": snapshot.title,
        "meta_description": snapshot.meta_description,
        "h1": snapshot.h1,
        "main_text": snapshot.main_text,
        "main_text_hash": snapshot.main_text_hash,
        "section_headings": loads(snapshot.section_headings_json, []),
        "structured_data": loads(snapshot.structured_data_json, []),
        "internal_links": loads(snapshot.internal_links_json, []),
        "robots_directives": loads(snapshot.robots_directives_json, {}),
        "snapshot_type": snapshot.snapshot_type,
        "capture_status": snapshot.capture_status,
        "capture_error": snapshot.capture_error,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


def hypothesis_to_read(hypothesis: OptimizationHypothesis) -> dict:
    return {
        "id": hypothesis.id,
        "project_id": hypothesis.project_id,
        "issue_id": hypothesis.issue_id,
        "experiment_id": hypothesis.experiment_id,
        "evidence_package_id": hypothesis.evidence_package_id,
        "status": hypothesis.status,
        "observed_problem": hypothesis.observed_problem,
        "hypothesized_cause": hypothesis.hypothesized_cause,
        "core_mechanism": hypothesis.core_mechanism,
        "target_metric": hypothesis.target_metric,
        "baseline_value": hypothesis.baseline_value,
        "expected_direction": hypothesis.expected_direction,
        "entry_observed_condition": hypothesis.entry_observed_condition,
        "sustained_improvement_condition": hypothesis.sustained_improvement_condition,
        "invalidating_result": hypothesis.invalidating_result,
        "changed_features": loads(hypothesis.changed_features_json, []),
        "controlled_variables": loads(hypothesis.controlled_variables_json, []),
        "accepted_by": hypothesis.accepted_by,
        "accepted_at": hypothesis.accepted_at,
        "review_note": hypothesis.review_note,
        "created_at": hypothesis.created_at,
        "updated_at": hypothesis.updated_at,
    }


def release_audit_to_read(record: ReleaseAuditRecord) -> dict:
    return {
        "id": record.id,
        "experiment_id": record.experiment_id,
        "hypothesis_id": record.hypothesis_id,
        "pre_release_snapshot_id": record.pre_release_snapshot_id,
        "post_release_snapshot_id": record.post_release_snapshot_id,
        "planned_feature_changes": loads(record.planned_feature_changes_json, []),
        "deployed_feature_changes": loads(record.deployed_feature_changes_json, []),
        "undeployed_feature_changes": loads(record.undeployed_feature_changes_json, []),
        "release_note": record.release_note,
        "confirmed_by": record.confirmed_by,
        "confirmed_at": record.confirmed_at,
        "online_verification_status": record.online_verification_status,
        "correction_of_id": record.correction_of_id,
        "correction_reason": record.correction_reason,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def strategy_candidate_to_read(candidate: OptimizationStrategyCandidate) -> dict:
    return {
        "id": candidate.id,
        "project_id": candidate.project_id,
        "experiment_id": candidate.experiment_id,
        "evidence_package_id": candidate.evidence_package_id,
        "target_url": candidate.target_url,
        "provider": candidate.provider,
        "model": candidate.model,
        "prompt_version": candidate.prompt_version,
        "prompt_text": candidate.prompt_text,
        "generated_at": candidate.generated_at,
        "generation_status": candidate.generation_status,
        "original_llm_payload": loads(candidate.original_llm_payload_json, {}),
        "structured_payload": loads(candidate.structured_payload_json, {}),
        "human_edited_payload": loads(candidate.human_edited_payload_json, {}),
        "effective_payload": loads(candidate.effective_payload_json, {}),
        "effective_payload_version": candidate.effective_payload_version,
        "effective_validation_status": candidate.effective_validation_status,
        "effective_validated_at": candidate.effective_validated_at,
        "evidence_validation_status": candidate.evidence_validation_status,
        "evidence_validation_errors": loads(candidate.evidence_validation_errors_json, []),
        "evidence_validation_warnings": loads(candidate.evidence_validation_warnings_json, []),
        "evidence_validated_at": candidate.evidence_validated_at,
        "evidence_validator_version": candidate.evidence_validator_version,
        "hypothesis_validation_status": candidate.hypothesis_validation_status,
        "hypothesis_validation_errors": loads(candidate.hypothesis_validation_errors_json, []),
        "hypothesis_validation_warnings": loads(candidate.hypothesis_validation_warnings_json, []),
        "hypothesis_validated_at": candidate.hypothesis_validated_at,
        "hypothesis_validator_version": candidate.hypothesis_validator_version,
        "review_status": candidate.review_status,
        "reviewed_by": candidate.reviewed_by,
        "reviewed_at": candidate.reviewed_at,
        "review_note": candidate.review_note,
        "converted_hypothesis_id": candidate.converted_hypothesis_id,
        "experiment_plan": loads(candidate.experiment_plan_json, {}),
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
    }


def list_issue_reads(db: Session, project_id: int) -> list[dict]:
    issues = (
        db.query(OptimizationIssue)
        .filter(OptimizationIssue.project_id == project_id)
        .order_by(OptimizationIssue.updated_at.desc(), OptimizationIssue.id.desc())
        .all()
    )
    run_ids_by_issue = _run_ids_by_issue(db, [issue.id for issue in issues])
    prompt_ids = [issue.prompt_id for issue in issues if issue.prompt_id]
    prompts = {
        prompt.id: prompt.prompt_text
        for prompt in db.query(Prompt).filter(Prompt.project_id == project_id, Prompt.id.in_(prompt_ids)).all()
    } if prompt_ids else {}
    result = []
    for issue in issues:
        row = issue_to_read(issue)
        if not row["prompt_text"] and issue.prompt_id:
            row["prompt_text"] = prompts.get(issue.prompt_id, "")
        row["run_ids"] = run_ids_by_issue.get(issue.id, [])
        result.append(row)
    return result


def create_issue(db: Session, payload) -> OptimizationIssue:
    if payload.issue_type not in ISSUE_TYPES:
        raise HTTPException(status_code=400, detail="未知问题类型")
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    runs = _runs_by_ids(db, payload.run_ids, payload.project_id)
    issue = OptimizationIssue(
        project_id=payload.project_id,
        prompt_id=payload.prompt_id,
        cluster_id=payload.cluster_id,
        issue_type=payload.issue_type,
        severity=payload.severity,
        confidence_level=payload.confidence_level,
        observation_start=min((run.created_at for run in runs), default=None),
        observation_end=max((run.created_at for run in runs), default=None),
        analyzable_sample_count=len([run for run in runs if run.status in VALID_RUN_STATUSES]),
        observed_facts_json=dumps(payload.observed_facts),
        possible_causes_json=dumps(payload.possible_causes),
        diagnosis_summary=payload.diagnosis_summary,
    )
    db.add(issue)
    db.flush()
    for run in runs:
        db.add(OptimizationIssueRun(issue_id=issue.id, run_id=run.id, evidence_role="supporting"))
    db.commit()
    db.refresh(issue)
    return issue


def generate_candidate_issues(db: Session, project_id: int, limit: int = 8) -> list[OptimizationIssue]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    prompts = {prompt.id: prompt for prompt in db.query(Prompt).filter(Prompt.project_id == project_id).all()}
    runs = (
        db.query(BrowserMonitorRun)
        .filter(BrowserMonitorRun.project_id == project_id, BrowserMonitorRun.status.in_(VALID_RUN_STATUSES))
        .order_by(BrowserMonitorRun.id.desc())
        .limit(240)
        .all()
    )
    grouped: dict[int, list[BrowserMonitorRun]] = defaultdict(list)
    for run in runs:
        grouped[run.prompt_id].append(run)

    created: list[OptimizationIssue] = []
    brand_domain = host_from_url(project.website_url) if project.website_url else ""
    for prompt_id, prompt_runs in grouped.items():
        if len(created) >= limit:
            break
        existing = (
            db.query(OptimizationIssue)
            .filter(
                OptimizationIssue.project_id == project_id,
                OptimizationIssue.prompt_id == prompt_id,
                OptimizationIssue.status.in_(["candidate", "confirmed", "in_action", "validating"]),
            )
            .first()
        )
        if existing:
            continue
        sample_count = len(prompt_runs)
        brand_mentions = sum(1 for run in prompt_runs if run.brand_mentioned)
        recommendations = sum(1 for run in prompt_runs if int(run.brand_recommendation_level or 0) >= 2)
        complete_refs = sum(1 for run in prompt_runs if run.reference_complete)
        run_ids = [run.id for run in prompt_runs[:8]]
        refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
        retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all()
        official_refs = _official_count(refs, brand_domain)
        official_retrievals = _official_count(retrievals, brand_domain)

        issue_type = ""
        causes: list[str] = []
        if brand_mentions == 0:
            issue_type = "brand_absent"
            causes = ["答案中缺少稳定品牌实体信号", "当前可引用资料可能没有直接覆盖该 Prompt 问法"]
        elif recommendations < sample_count:
            issue_type = "brand_not_recommended"
            causes = ["品牌只被提及，缺少可被模型转述的推荐理由", "对比维度、适用场景或案例证据不足"]
        elif official_retrievals and official_refs == 0:
            issue_type = "retrieved_not_cited"
            causes = ["官网已进入检索候选但未成为引用资料", "页面标题、结构化信息或内容可信度可能弱于第三方来源"]
        elif brand_domain and official_refs == 0:
            issue_type = "official_source_absent"
            causes = ["引用主要来自第三方站点，官网权威页信号不足"]
        elif complete_refs < sample_count:
            issue_type = "citation_unstable"
            causes = ["引用资料解析或展示不稳定，需要先排除采集质量因素再判断业务问题"]
        if not issue_type:
            continue

        prompt = prompts.get(prompt_id)
        facts = {
            "prompt_text": prompt.prompt_text if prompt else "",
            "sample_count": sample_count,
            "brand_mention_count": brand_mentions,
            "brand_recommendation_count": recommendations,
            "official_reference_count": official_refs,
            "official_retrieval_candidate_count": official_retrievals,
            "reference_complete_count": complete_refs,
            "top_reference_domains": Counter((ref.domain or "").lower() for ref in refs if ref.domain).most_common(5),
            "top_retrieval_domains": Counter((item.domain or "").lower() for item in retrievals if item.domain).most_common(5),
        }
        issue = OptimizationIssue(
            project_id=project_id,
            prompt_id=prompt_id,
            cluster_id=getattr(prompt, "cluster_id", None) if prompt else None,
            issue_type=issue_type,
            severity=_severity(issue_type, sample_count, brand_mentions, recommendations, official_refs),
            confidence_level="high" if sample_count >= 3 else "medium",
            observation_start=min(run.created_at for run in prompt_runs),
            observation_end=max(run.created_at for run in prompt_runs),
            analyzable_sample_count=sample_count,
            observed_facts_json=dumps(facts),
            possible_causes_json=dumps(causes),
            diagnosis_summary=_diagnosis(project, prompt, issue_type, facts),
        )
        db.add(issue)
        db.flush()
        for run_id in run_ids:
            db.add(OptimizationIssueRun(issue_id=issue.id, run_id=run_id, evidence_role="supporting"))
        created.append(issue)
    db.commit()
    for issue in created:
        db.refresh(issue)
    return created


def confirm_issue(db: Session, issue_id: int) -> OptimizationIssue:
    issue = _get_issue(db, issue_id)
    if issue.status not in {"candidate"}:
        raise HTTPException(status_code=400, detail="只有 candidate 问题可以确认")
    issue.status = "confirmed"
    issue.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(issue)
    return issue


def reject_issue(db: Session, issue_id: int, reason: str) -> OptimizationIssue:
    issue = _get_issue(db, issue_id)
    if issue.status in {"resolved", "closed"}:
        raise HTTPException(status_code=400, detail="已结束问题不能驳回")
    issue.status = "rejected"
    issue.rejected_reason = reason
    db.commit()
    db.refresh(issue)
    return issue


def create_action(db: Session, issue_id: int, payload) -> OptimizationAction:
    issue = _get_issue(db, issue_id)
    if issue.status not in {"confirmed", "in_action"}:
        raise HTTPException(status_code=400, detail="问题需先确认后才能创建优化动作")
    action = OptimizationAction(issue_id=issue.id, **_action_payload(payload))
    issue.status = "in_action"
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def update_action(db: Session, action_id: int, payload) -> OptimizationAction:
    action = _get_action(db, action_id)
    data = payload.model_dump(exclude_unset=True)
    if "content_feature_changes" in data:
        action.content_feature_changes_json = dumps(_normalize_feature_changes(data.pop("content_feature_changes")))
    for key, value in data.items():
        setattr(action, key, value)
    db.commit()
    db.refresh(action)
    return action


def release_action(db: Session, action_id: int, payload) -> OptimizationAction:
    action = _get_action(db, action_id)
    normalized_status = _normalize_action_status(action.status)
    if normalized_status in {"CANCELLED"}:
        raise HTTPException(status_code=400, detail="已取消动作不能发布")
    action.release_note = payload.release_note
    action.release_evidence_json = dumps(payload.release_evidence)
    if not payload.release_confirmed:
        action.status = "READY_FOR_MANUAL_RELEASE"
        for experiment in db.query(OptimizationExperiment).filter(OptimizationExperiment.action_id == action.id).all():
            if experiment.status in {"draft", "baseline_locked"}:
                if experiment.release_blocked:
                    raise HTTPException(status_code=400, detail=f"实验发布确认被阻塞：{experiment.release_blocked_reason or 'UNKNOWN'}")
                experiment.status = "READY_FOR_MANUAL_RELEASE"
        db.commit()
        db.refresh(action)
        return action

    raise HTTPException(status_code=400, detail="发布确认必须通过实验发布审计接口，并提供发布后成功快照。")


def capture_page_snapshot(db: Session, project_id: int, payload) -> PageSnapshot:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    experiment = db.get(OptimizationExperiment, payload.experiment_id) if payload.experiment_id else None
    if payload.experiment_id and not experiment:
        raise HTTPException(status_code=404, detail="实验不存在")
    snapshot_type = str(payload.snapshot_type or "PRE_RELEASE").strip().upper()
    if snapshot_type not in {"PRE_RELEASE", "POST_RELEASE"}:
        raise HTTPException(status_code=400, detail="snapshot_type 仅支持 PRE_RELEASE/POST_RELEASE")
    snapshot = _capture_page_snapshot(project_id, payload.url, snapshot_type, experiment.id if experiment else None)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def list_page_snapshots(db: Session, project_id: int, experiment_id: int | None = None) -> list[dict]:
    query = db.query(PageSnapshot).filter(PageSnapshot.project_id == project_id)
    if experiment_id is not None:
        query = query.filter(PageSnapshot.experiment_id == experiment_id)
    rows = query.order_by(PageSnapshot.captured_at.desc(), PageSnapshot.id.desc()).limit(80).all()
    return [page_snapshot_to_read(row) for row in rows]


def create_hypothesis(db: Session, experiment_id: int, payload) -> OptimizationHypothesis:
    experiment = _get_experiment(db, experiment_id)
    action = _get_action(db, experiment.action_id)
    issue = _get_issue(db, action.issue_id)
    package = db.get(OptimizationEvidencePackage, payload.evidence_package_id)
    if not package:
        raise HTTPException(status_code=404, detail="证据事实包不存在")
    if package.project_id != issue.project_id:
        raise HTTPException(status_code=400, detail="证据事实包和实验项目不一致")
    if payload.issue_id and payload.issue_id != issue.id:
        raise HTTPException(status_code=400, detail="Hypothesis 关联的问题与实验不一致")

    # P0-3: Historical hypothesis evidence_package_id is immutable.
    # An experiment's hypothesis, once created, must never be rebound to a different package.
    any_existing = (
        db.query(OptimizationHypothesis)
        .filter(
            OptimizationHypothesis.experiment_id == experiment.id,
            OptimizationHypothesis.status == "ACCEPTED",
        )
        .first()
    )
    if any_existing and any_existing.evidence_package_id != package.id:
        raise HTTPException(
            status_code=400,
            detail=f"HYPOTHESIS_EVIDENCE_IMMUTABLE: Experiment #{experiment.id} already has an ACCEPTED Hypothesis bound to Package #{any_existing.evidence_package_id}. Cannot rebind to Package #{package.id}. Historical evidence provenance must be preserved.",
        )

    existing = (
        db.query(OptimizationHypothesis)
        .filter(
            OptimizationHypothesis.experiment_id == experiment.id,
            OptimizationHypothesis.evidence_package_id == package.id,
            OptimizationHypothesis.status == "ACCEPTED",
        )
        .first()
    )
    if existing:
        return existing
    hypothesis = OptimizationHypothesis(
        project_id=issue.project_id,
        issue_id=issue.id,
        experiment_id=experiment.id,
        evidence_package_id=package.id,
        status="ACCEPTED",
        observed_problem=payload.observed_problem,
        hypothesized_cause=payload.hypothesized_cause,
        core_mechanism=payload.core_mechanism,
        target_metric=payload.target_metric,
        baseline_value=payload.baseline_value,
        expected_direction=payload.expected_direction,
        entry_observed_condition=payload.entry_observed_condition,
        sustained_improvement_condition=payload.sustained_improvement_condition,
        invalidating_result=payload.invalidating_result,
        changed_features_json=dumps(payload.changed_features),
        controlled_variables_json=dumps(payload.controlled_variables),
        accepted_by=payload.accepted_by,
        accepted_at=datetime.utcnow(),
        review_note=payload.review_note,
    )
    db.add(hypothesis)
    db.commit()
    db.refresh(hypothesis)
    return hypothesis


def list_hypotheses(db: Session, experiment_id: int) -> list[dict]:
    _get_experiment(db, experiment_id)
    rows = (
        db.query(OptimizationHypothesis)
        .filter(OptimizationHypothesis.experiment_id == experiment_id)
        .order_by(OptimizationHypothesis.created_at.desc(), OptimizationHypothesis.id.desc())
        .all()
    )
    return [hypothesis_to_read(row) for row in rows]


def list_strategy_candidates(db: Session, project_id: int, experiment_id: int | None = None, evidence_package_id: int | None = None) -> list[dict]:
    query = db.query(OptimizationStrategyCandidate).filter(OptimizationStrategyCandidate.project_id == project_id)
    if experiment_id is not None:
        query = query.filter(OptimizationStrategyCandidate.experiment_id == experiment_id)
    if evidence_package_id is not None:
        query = query.filter(OptimizationStrategyCandidate.evidence_package_id == evidence_package_id)
    rows = query.order_by(OptimizationStrategyCandidate.created_at.desc(), OptimizationStrategyCandidate.id.desc()).limit(80).all()
    return [strategy_candidate_to_read(row) for row in rows]


def generate_strategy_candidates(db: Session, project_id: int, payload) -> list[dict]:
    """Legacy endpoint compatibility shim.

    The old local strategy path embedded owned-site assumptions. Keep the route
    alive for clients, but route all generation through the neutral V2 provider.
    """
    return generate_strategy_candidates_v2(db, project_id, payload)


def review_strategy_candidate(db: Session, candidate_id: int, payload) -> dict:
    candidate = db.get(OptimizationStrategyCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="策略候选不存在")
    status = str(payload.review_status or "").strip().upper()
    if status not in {"PENDING_REVIEW", "ACCEPTED", "ACCEPTED_WITH_EDITS", "REJECTED", "DEFERRED"}:
        raise HTTPException(status_code=400, detail="未知人工审核状态")
    if status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"}:
        _ensure_product_truth_gate_allows_strategy_execution(candidate)
    if status == "ACCEPTED":
        if candidate.evidence_validation_status != "VALIDATED" or candidate.hypothesis_validation_status != "VALIDATED":
            raise HTTPException(status_code=400, detail="Validator 未通过，不能接受策略候选")
    candidate.review_status = status
    candidate.reviewed_by = payload.reviewed_by
    candidate.reviewed_at = datetime.utcnow()
    candidate.review_note = payload.review_note
    if status == "ACCEPTED_WITH_EDITS":
        edited = payload.human_edited_payload or {}
        # Deterministic merge: structured + human delta → effective payload
        original = loads(candidate.structured_payload_json, {})
        effective = deterministic_merge(original, edited)
        # Re-validate effective payload through Evidence + Hypothesis validators
        if candidate.evidence_package_id:
            package = db.get(OptimizationEvidencePackage, candidate.evidence_package_id)
            if package:
                evidence_result = validate_strategy_evidence(package, None, effective)
                hypothesis_result = validate_strategy_hypothesis(effective, evidence_result)
                if evidence_result["status"] != "VALIDATED" or hypothesis_result["status"] != "VALIDATED":
                    raise HTTPException(
                        status_code=400,
                        detail=f"人工编辑后的策略未通过重新验证。Evidence: {evidence_result['status']} ({'; '.join(evidence_result['errors'][:3])}). Hypothesis: {hypothesis_result['status']} ({'; '.join(hypothesis_result['errors'][:3])}). 请修正编辑内容后重试。",
                    )
                candidate.evidence_validation_status = evidence_result["status"]
                candidate.evidence_validation_errors_json = dumps(evidence_result["errors"])
                candidate.evidence_validation_warnings_json = dumps(evidence_result["warnings"])
                candidate.hypothesis_validation_status = hypothesis_result["status"]
                candidate.hypothesis_validation_errors_json = dumps(hypothesis_result["errors"])
                candidate.hypothesis_validation_warnings_json = dumps(hypothesis_result["warnings"])
                _set_effective_payload_review_status(candidate, effective)
            else:
                candidate.effective_validation_status = "BACKFILLED_UNVERIFIED"
        # Save the effective payload as single executable truth
        candidate.effective_payload_json = dumps(effective)
        candidate.effective_payload_version = EFFECTIVE_PAYLOAD_VERSION
        candidate.human_edited_payload_json = dumps(edited)
    elif status == "ACCEPTED":
        # No human edits — effective = structured
        effective = loads(candidate.structured_payload_json, {})
        candidate.effective_payload_json = dumps(effective)
        candidate.effective_payload_version = EFFECTIVE_PAYLOAD_VERSION
        _set_effective_payload_review_status(candidate, effective)
    db.commit()
    db.refresh(candidate)
    return strategy_candidate_to_read(candidate)


def _set_effective_payload_review_status(candidate: OptimizationStrategyCandidate, effective: dict) -> None:
    if candidate.evidence_validation_status != "VALIDATED" or candidate.hypothesis_validation_status != "VALIDATED":
        candidate.effective_validation_status = "VALIDATION_FAILED"
        candidate.effective_validated_at = None
        return
    if _unresolved_strategy_execution_fields(effective):
        candidate.effective_validation_status = "PENDING_HUMAN_CHANNEL_REVIEW"
        candidate.effective_validated_at = None
        return
    candidate.effective_validation_status = "VALIDATED"
    candidate.effective_validated_at = datetime.utcnow()


def _ensure_product_truth_gate_allows_strategy_execution(candidate: OptimizationStrategyCandidate) -> None:
    payload = loads(candidate.structured_payload_json, {})
    gate = payload.get("product_truth_gate") if isinstance(payload, dict) else None
    if not isinstance(gate, dict):
        return
    if gate.get("status") != "READY_FOR_STRATEGY_REVIEW":
        raise HTTPException(
            status_code=400,
            detail="Product Truth 未确认，不能接受或执行该策略候选。请先人工确认目标品牌能力后重新生成候选。",
        )


def strategy_to_experiment_plan(db: Session, candidate_id: int) -> dict:
    candidate = db.get(OptimizationStrategyCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="策略候选不存在")
    if candidate.review_status not in {"ACCEPTED", "ACCEPTED_WITH_EDITS"}:
        raise HTTPException(status_code=400, detail="只有人工接受后的策略候选才能转换实验计划")
    package = db.get(OptimizationEvidencePackage, candidate.evidence_package_id)
    effective = get_effective_strategy_payload(candidate)
    experiment = db.get(OptimizationExperiment, candidate.experiment_id) if candidate.experiment_id else None

    # NO_ACTION: evidence does not support any intervention — do not create Action/Experiment
    if effective.get("intervention_type") == "NO_ACTION":
        known_environment_audit = _normalize_known_environment_audit({})
        comparability_status, comparability_note = _resolve_comparability(None, None, known_environment_audit, [])
        no_action_plan = {
            "readiness_status": "NO_ACTION",
            "reason": "当前证据不支持执行干预，建议继续观察或补充证据。",
            "known_environment_audit": known_environment_audit,
            "comparability_status": comparability_status,
            "comparability_note": comparability_note,
            "controlled_intervention": _strategy_controlled_intervention_payload(effective, package),
        }
        candidate.experiment_plan_json = dumps(no_action_plan)
        db.commit()
        return {
            "strategy_candidate_id": candidate.id,
            "readiness_status": "NO_ACTION",
            "readiness_errors": [],
            "readiness_warnings": [],
            "experiment_id": None,
            "action_id": None,
            "hypothesis_id": None,
            "plan_payload": no_action_plan,
        }

    # Auto-create Action + Experiment if strategy accepted but has no experiment
    if not experiment and candidate.review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"}:
        target_url = effective.get("target_url") or ""
        intervention_type = effective.get("intervention_type") or ""
        primary_metric = INTERVENTION_METRIC_MAP.get(intervention_type, "brand_mention_rate")
        known_environment_audit = _normalize_known_environment_audit({})
        comparability_status, comparability_note = _resolve_comparability(None, None, known_environment_audit, [])
        controlled_intervention = _strategy_controlled_intervention_payload(effective, package)

        # Create Issue if needed
        existing_issue = (
            db.query(OptimizationIssue)
            .filter(
                OptimizationIssue.project_id == candidate.project_id,
                OptimizationIssue.prompt_id == package.prompt_id,
                OptimizationIssue.status.in_(["confirmed", "in_action"]),
            )
            .first()
        )
        if not existing_issue:
            existing_issue = OptimizationIssue(
                project_id=candidate.project_id,
                prompt_id=package.prompt_id,
                issue_type="brand_absent",
                status="confirmed",
                severity=4,
                confidence_level="medium",
                analyzable_sample_count=len(loads(package.source_run_ids_json, [])),
                observed_facts_json=dumps({"prompt_text": "Strategy-driven intervention"}),
                diagnosis_summary=f"Strategy Candidate #{candidate.id} driven intervention: {intervention_type}",
                confirmed_at=datetime.utcnow(),
            )
            db.add(existing_issue)
            db.flush()

        # Map intervention_type → action_type + target_type (from effective payload)
        _action_map = {
            "OFFICIAL_PAGE_UPDATE": ("content_update", "owned_content"),
            "OFFICIAL_NEW_PAGE": ("content_create", "owned_content"),
            "OWNED_CONTENT_EXTENSION": ("content_create", "owned_content"),
            "EXTERNAL_PLATFORM_ARTICLE": ("article_publish", "external_platform"),
            "EXTERNAL_PLATFORM_QA": ("qa_publish", "external_platform"),
            "EXTERNAL_PLATFORM_CONTENT": ("content_publish", "external_platform"),
            "VIDEO_CONTENT": ("video_publish", "external_platform"),
            "THIRD_PARTY_REVIEW": ("review_outreach", "third_party"),
            "THIRD_PARTY_COMPARISON": ("comparison_outreach", "third_party"),
            "CONTENT_REFRESH": ("content_update", "owned_content"),
            "NO_ACTION": ("monitor_only", "none"),
        }
        mapped = _action_map.get(intervention_type, ("content_create", "owned_content"))
        action = OptimizationAction(
            issue_id=existing_issue.id,
            action_type=mapped[0],
            target_type=mapped[1],
            target_url=target_url if mapped[1] == "owned_content" else "",
            status="PLANNED",
            priority=3,
            action_summary=f"Strategy Candidate #{candidate.id}: {intervention_type} → {mapped[0]}",
            action_detail=effective.get("recommended_action", "") if isinstance(effective.get("recommended_action"), str) else "",
        )
        db.add(action)
        db.flush()

        # Create Experiment
        experiment = OptimizationExperiment(
            action_id=action.id,
            hypothesis=effective.get("hypothesized_cause", "")[:500],
            hypothesis_type="strategy_candidate",
            mechanism=effective.get("core_mechanism", "")[:500],
            intervention_family=intervention_type,
            intervention_variables_json=dumps({
                "strategy_candidate_id": candidate.id,
                "evidence_package_id": package.id if package else None,
                "target_url": target_url,
            }),
            allowed_changes_json=dumps(controlled_intervention["allowed_changes"]),
            forbidden_changes_json=dumps(controlled_intervention["forbidden_changes"]),
            target_prompt_scope_json=dumps([package.prompt_id] if package.prompt_id else []),
            control_prompt_scope_json=dumps([]),
            sentinel_prompt_scope_json=dumps([]),
            primary_metric=primary_metric,
            secondary_metrics_json=dumps(["brand_mention_rate", "brand_recommendation_rate"]),
            known_environment_audit_json=dumps(known_environment_audit),
            comparability_status=comparability_status,
            comparability_note=comparability_note,
            controlled_intervention_json=dumps(controlled_intervention),
            status="draft",
            release_blocked=True,
            release_blocked_reason="WAITING_FOR_BASELINE_LOCK",
        )
        db.add(experiment)
        db.flush()

        candidate.experiment_id = experiment.id
        db.flush()

    readiness = _experiment_readiness_for_strategy(db, candidate, effective, package, experiment)
    hypothesis_id = candidate.converted_hypothesis_id
    if readiness["readiness_status"] == "READY" and experiment and not hypothesis_id:
        hypothesis = create_hypothesis(
            db,
            experiment.id,
            type(
                "Payload",
                (),
                {
                    "evidence_package_id": package.id,
                    "issue_id": None,
                    "observed_problem": effective.get("observed_problem", ""),
                    "hypothesized_cause": effective.get("hypothesized_cause", ""),
                    "core_mechanism": effective.get("core_mechanism", ""),
                    "target_metric": effective.get("target_metric", "official_reference_rate"),
                    "baseline_value": str(effective.get("baseline_value", "")),
                    "expected_direction": effective.get("expected_direction", "increase"),
                    "entry_observed_condition": (effective.get("validation_plan") or {}).get("entry_observed_condition", ""),
                    "sustained_improvement_condition": (effective.get("validation_plan") or {}).get("sustained_improvement_condition", ""),
                    "invalidating_result": effective.get("invalidating_result", ""),
                    "changed_features": [item.get("feature", "") for item in effective.get("changed_features", []) if isinstance(item, dict)],
                    "controlled_variables": effective.get("controlled_variables", []),
                    "accepted_by": candidate.reviewed_by or "human",
                    "review_note": candidate.review_note,
                },
            )(),
        )
        candidate.converted_hypothesis_id = hypothesis.id
        hypothesis_id = hypothesis.id
    if experiment and readiness["readiness_status"] != "READY":
        experiment.release_blocked = True
        experiment.release_blocked_reason = "WAITING_FOR_RECOLLECTED_RETRIEVAL_BASELINE"
    candidate.experiment_plan_json = dumps({**readiness, "payload": effective})
    db.commit()
    return {
        "strategy_candidate_id": candidate.id,
        "readiness_status": readiness["readiness_status"],
        "readiness_errors": readiness["readiness_errors"],
        "readiness_warnings": readiness["readiness_warnings"],
        "experiment_id": experiment.id if experiment else None,
        "action_id": experiment.action_id if experiment else None,
        "hypothesis_id": hypothesis_id,
        "plan_payload": {**readiness, "payload": effective},
    }


STEP8_CHANNELS = {
    "OFFICIAL_SITE",
    "PRODUCT_DOCS",
    "ZHIHU",
    "BAIJIAHAO",
    "THIRD_PARTY_MEDIA",
    "OTHER",
}
STEP8_ASSET_OPERATIONS = {"UPDATE_EXISTING", "CREATE_NEW"}
STRATEGY_CORE_FIELD_PATHS = {
    "target_decision_change",
    "priority_capabilities",
    "strategic_hypothesis",
    "intervention_mechanism",
    "mechanism",
    "core_mechanism",
    "primary_intervention_path",
    "planned_channels",
    "channel_roles",
    "asset_direction",
    "execution_sequence",
    "required_signals",
    "required_signal",
    "non_goals",
    "attribution_intent",
}
EXECUTION_MECHANISM_REVIEW_FIELDS = {
    "execution.channel",
    "execution.asset_operation",
    "execution.selected_asset_type",
    "execution.target_content_type",
    "execution.target_object",
    "execution.content_structure",
}
DECISION_STABILITY_VERSION = "decision_stability.phase5.v1"
DECISION_STABILITY_EVENT_STATUSES = {"MACHINE_GROUNDED", "MACHINE_CANDIDATE", "HUMAN_CONFIRMED"}
DECISION_STABILITY_DECISION_ACTS = {"RECOMMEND", "INCLUDE_AS_OPTION", "COMPARE"}
DECISION_STABILITY_REASON_ROLES = {"DIRECT_REASON", "SUPPORTING_REASON"}
DECISION_STABILITY_REASON_SEMANTIC_TYPES = {
    "FEATURE",
    "BENEFIT",
    "PRICE",
    "USE_CASE",
    "RESULT_EFFECT",
    "COMPARATIVE_ADVANTAGE",
}
DECISION_STABILITY_REASON_EXCLUDE_PHRASES = (
    "打开官网",
    "进入工具",
    "完成注册",
    "粘贴",
    "输入框",
    "点击生成",
    "生成按钮",
    "操作步骤",
    "使用注意事项",
    "需要我",
    "帮你挑选",
    "是将",
)


def confirm_strategy_execution_plan(db: Session, candidate_id: int, payload) -> dict:
    """Step 8: confirm channel/asset execution plan and create a draft experiment.

    Step 7 confirmation and Step 8 execution planning are intentionally
    separate: ACCEPTED + PENDING_HUMAN_CHANNEL_REVIEW means the strategy is
    confirmed, but its executable channel/asset fields still need this human
    review before Action/Experiment materialization.
    """
    candidate = db.get(OptimizationStrategyCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="策略候选不存在")
    package = db.get(OptimizationEvidencePackage, candidate.evidence_package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Evidence Package 不存在")
    project = db.get(Project, candidate.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project 不存在")
    prompt = db.get(Prompt, package.prompt_id) if package.prompt_id else None
    _ensure_strategy_candidate_can_enter_step8(candidate)
    current_effective = loads(candidate.effective_payload_json, {})
    _ensure_step8_does_not_change_strategy_core(current_effective, payload)

    if candidate.experiment_id:
        experiment = db.get(OptimizationExperiment, candidate.experiment_id)
        if experiment:
            return {
                "strategy_candidate_id": candidate.id,
                "readiness_status": "DRAFT_ALREADY_EXISTS",
                "readiness_errors": [],
                "readiness_warnings": ["该策略候选已创建实验草案，本次未重复创建。"],
                "experiment_id": experiment.id,
                "action_id": experiment.action_id,
                "hypothesis_id": candidate.converted_hypothesis_id,
                "plan_payload": loads(candidate.experiment_plan_json, {}),
            }

    channel = _normalize_step8_channel(_payload_value(payload, "channel", ""))
    asset_operation = _normalize_step8_asset_operation(_payload_value(payload, "asset_operation", ""))
    baseline_run_ids = _normalize_int_list(_payload_value(payload, "baseline_run_ids", []))
    if not baseline_run_ids:
        raise HTTPException(status_code=400, detail="Step 8 必须显式传入固定 baseline_run_ids，不能按 prompt_id 动态读取最新采集。")
    package_run_ids = set(loads(package.source_run_ids_json, []))
    if any(run_id not in package_run_ids for run_id in baseline_run_ids):
        raise HTTPException(status_code=400, detail="baseline_run_ids 必须来自当前 Evidence Package 的固定 Run 集。")

    selected_asset_ref = _resolve_selected_asset_ref(db, project, payload, channel, asset_operation)
    execution_parameters = _step8_execution_parameters(payload, selected_asset_ref, channel, asset_operation)
    execution_delta = _execution_delta_for_step8(current_effective, execution_parameters, payload)
    compatibility = _mechanism_compatibility_for_step8(current_effective, execution_parameters)
    if compatibility["status"] == "STRATEGY_RECONFIRM_REQUIRED":
        raise HTTPException(
            status_code=400,
            detail={
                "status": "RETURN_TO_STEP_7",
                "message": "当前执行方案已改变 Strategy Core 的机制边界，需要返回第 7 步重新确认 Strategy。",
                "mechanism_compatibility": compatibility,
                "execution_delta": execution_delta,
            },
        )
    effective = deterministic_merge(current_effective, {
        "strategy_phase": "PHASE_4_EXECUTION_PLAN_CONFIRMED",
        "target_platform": channel,
        "asset_operation": asset_operation,
        "selected_asset_ref": selected_asset_ref,
        "target_asset": _selected_asset_identity(selected_asset_ref),
        "target_url": selected_asset_ref.get("canonical_url") or selected_asset_ref.get("url") or "",
        "target_content_type": _payload_value(payload, "target_content_type", "") or selected_asset_ref.get("asset_type") or "ARTICLE",
        "target_object": _payload_value(payload, "target_object", "") or selected_asset_ref.get("asset_type") or "CONTENT_ASSET",
        "intervention_type": _intervention_type_for_step8(channel, asset_operation, {"effective_payload": current_effective}),
        "execution_parameters": execution_parameters,
        "execution_delta": execution_delta,
        "mechanism_compatibility": compatibility,
        "step8_confirmation": {
            "confirmed_by": _payload_value(payload, "confirmed_by", "human"),
            "confirmed_at": datetime.utcnow().isoformat(),
            "confirmation_note": _payload_value(payload, "confirmation_note", ""),
        },
    })

    candidate.effective_payload_json = dumps(effective)
    candidate.effective_payload_version = EFFECTIVE_PAYLOAD_VERSION
    candidate.intervention_type = effective.get("intervention_type")
    candidate.target_platform = channel
    candidate.target_asset = effective.get("target_asset")
    candidate.target_content_type = effective.get("target_content_type")
    _set_effective_payload_review_status(candidate, effective)
    if candidate.effective_validation_status != "VALIDATED":
        raise HTTPException(status_code=400, detail="Step 8 执行方案仍有未解决字段，不能创建实验草案。")

    strategy_snapshot = _strategy_snapshot_for_experiment(candidate, package)
    runs = _runs_by_ids(db, baseline_run_ids, candidate.project_id)
    if len(runs) != len(baseline_run_ids):
        raise HTTPException(status_code=400, detail="部分 baseline_run_ids 不存在或不属于当前项目。")
    baseline_metrics = baseline_metrics_for_fixed_runs(db, project, runs, effective, selected_asset_ref)
    issue = _get_or_create_step8_issue(db, candidate, package, prompt, strategy_snapshot, baseline_run_ids)
    action = _create_step8_action(db, issue, effective, selected_asset_ref, strategy_snapshot)
    experiment = _create_step8_experiment(
        db,
        candidate,
        package,
        prompt,
        action,
        effective,
        strategy_snapshot,
        selected_asset_ref,
        baseline_run_ids,
        baseline_metrics,
    )

    candidate.experiment_id = experiment.id
    plan_payload = {
        "readiness_status": "DRAFT_CREATED",
        "phase": "PHASE_4_EXECUTION_PLAN",
        "strategy_candidate_id": candidate.id,
        "evidence_package_id": package.id,
        "channel": channel,
        "asset_operation": asset_operation,
        "selected_asset_ref": selected_asset_ref,
        "strategy_snapshot": strategy_snapshot,
        "execution_parameters": execution_parameters,
        "execution_delta": execution_delta,
        "mechanism_compatibility": compatibility,
        "baseline_run_ids": baseline_run_ids,
        "baseline_metrics": baseline_metrics,
        "action_snapshot": _action_snapshot(action),
        "experiment_id": experiment.id,
        "action_id": action.id,
        "release_gate": "这里只创建实验草案；真实发布仍需 Release Audit 人工确认。",
    }
    candidate.experiment_plan_json = dumps(plan_payload)
    db.commit()
    db.refresh(candidate)
    db.refresh(action)
    db.refresh(experiment)
    return {
        "strategy_candidate_id": candidate.id,
        "readiness_status": "DRAFT_CREATED",
        "readiness_errors": [],
        "readiness_warnings": [],
        "experiment_id": experiment.id,
        "action_id": action.id,
        "hypothesis_id": candidate.converted_hypothesis_id,
        "plan_payload": plan_payload,
    }


def _ensure_strategy_candidate_can_enter_step8(candidate: OptimizationStrategyCandidate) -> None:
    if candidate.review_status not in {"ACCEPTED", "ACCEPTED_WITH_EDITS"}:
        raise HTTPException(status_code=400, detail="Strategy 尚未人工确认，不能进入 Step 8。")
    if candidate.effective_validation_status not in {"PENDING_HUMAN_CHANNEL_REVIEW", "VALIDATED"}:
        raise HTTPException(status_code=400, detail="当前 Strategy 状态不能进入 Step 8。")


def _ensure_step8_does_not_change_strategy_core(strategy: dict, payload) -> None:
    attempts: list[dict] = []
    updates = _payload_value(payload, "strategy_core_updates", {}) or {}
    if isinstance(updates, dict):
        for key, value in updates.items():
            if key in STRATEGY_CORE_FIELD_PATHS:
                attempts.append(_strategy_core_change_attempt(strategy, key, value))
    for key in STRATEGY_CORE_FIELD_PATHS:
        value = _payload_value(payload, key, None)
        if value is not None:
            attempts.append(_strategy_core_change_attempt(strategy, key, value))
    attempts = [item for item in attempts if item["changed"]]
    if attempts:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "RETURN_TO_STEP_7",
                "message": "Step 8 不能直接修改 Strategy Core。请返回第 7 步重新编辑并确认策略。",
                "blocked_changes": attempts,
            },
        )


def _strategy_core_change_attempt(strategy: dict, key: str, new_value) -> dict:
    canonical_key = {
        "required_signal": "required_signals",
        "mechanism": "intervention_mechanism",
        "core_mechanism": "intervention_mechanism",
    }.get(key, key)
    original_value = strategy.get(canonical_key)
    if canonical_key == "intervention_mechanism" and original_value is None:
        original_value = strategy.get("mechanism") or strategy.get("core_mechanism")
    return {
        "field_path": canonical_key,
        "original_value": original_value,
        "new_value": new_value,
        "impact_level": "STRATEGY_CORE_CHANGE",
        "changed": _json_stable(original_value) != _json_stable(new_value),
    }


def _step8_execution_parameters(payload, selected_asset_ref: dict, channel: str, asset_operation: str) -> dict:
    return {
        "selected_channel": channel,
        "channel_instance": _payload_value(payload, "channel_instance", "") or channel,
        "asset_operation": asset_operation,
        "selected_asset_ref": selected_asset_ref,
        "selected_asset": _selected_asset_identity(selected_asset_ref),
        "selected_asset_type": _payload_value(payload, "selected_asset_type", "") or selected_asset_ref.get("asset_type") or "ARTICLE",
        "target_content_type": _payload_value(payload, "target_content_type", "") or selected_asset_ref.get("asset_type") or "ARTICLE",
        "target_object": _payload_value(payload, "target_object", "") or selected_asset_ref.get("asset_type") or "CONTENT_ASSET",
        "concrete_url": selected_asset_ref.get("canonical_url") or selected_asset_ref.get("url") or "",
        "account": _payload_value(payload, "account", ""),
        "location": _payload_value(payload, "location", ""),
        "title": _payload_value(payload, "title", "") or selected_asset_ref.get("title", ""),
        "section": _payload_value(payload, "section", ""),
        "content_structure": _payload_value(payload, "content_structure", []) or [],
    }


def _execution_delta_for_step8(strategy: dict, execution: dict, payload) -> list[dict]:
    changed_by = _payload_value(payload, "confirmed_by", "human")
    changed_at = datetime.utcnow().isoformat()
    reason = _payload_value(payload, "execution_reason", "") or _payload_value(payload, "confirmation_note", "") or "Step 8 人工配置执行参数"
    planned = _planned_execution_defaults(strategy)
    rows = []
    comparisons = [
        ("execution.channel", planned.get("channel"), execution.get("selected_channel")),
        ("execution.asset_operation", planned.get("asset_operation"), execution.get("asset_operation")),
        ("execution.selected_asset", planned.get("selected_asset"), execution.get("selected_asset")),
        ("execution.selected_asset_type", planned.get("selected_asset_type"), execution.get("selected_asset_type")),
        ("execution.target_content_type", planned.get("target_content_type"), execution.get("target_content_type")),
        ("execution.target_object", planned.get("target_object"), execution.get("target_object")),
        ("execution.concrete_url", planned.get("concrete_url"), execution.get("concrete_url")),
        ("execution.account", planned.get("account"), execution.get("account")),
        ("execution.location", planned.get("location"), execution.get("location")),
        ("execution.title", planned.get("title"), execution.get("title")),
        ("execution.section", planned.get("section"), execution.get("section")),
        ("execution.content_structure", planned.get("content_structure"), execution.get("content_structure")),
    ]
    for field_path, original, new_value in comparisons:
        if _json_stable(original) == _json_stable(new_value):
            continue
        rows.append({
            "field_path": field_path,
            "original_value": original,
            "new_value": new_value,
            "reason": reason,
            "changed_by": changed_by,
            "changed_at": changed_at,
            "impact_level": _execution_delta_impact_level(field_path),
        })
    return rows


def _execution_delta_impact_level(field_path: str) -> str:
    if field_path in STRATEGY_CORE_FIELD_PATHS:
        return "STRATEGY_CORE_CHANGE"
    if field_path in EXECUTION_MECHANISM_REVIEW_FIELDS:
        return "MECHANISM_REVIEW_REQUIRED"
    return "EXECUTION_ONLY"


def _planned_execution_defaults(strategy: dict) -> dict:
    primary_channel = _primary_planned_channel(strategy)
    asset_direction = strategy.get("asset_direction") or {}
    if not isinstance(asset_direction, dict):
        asset_direction = {}
    return {
        "channel": primary_channel.get("channel"),
        "asset_operation": asset_direction.get("asset_operation"),
        "selected_asset": None,
        "selected_asset_type": asset_direction.get("asset_type") or "ARTICLE",
        "target_content_type": asset_direction.get("asset_type") or "ARTICLE",
        "target_object": asset_direction.get("target_object") or "CONTENT_ASSET",
        "concrete_url": None,
        "account": "",
        "location": "",
        "title": "",
        "section": "",
        "content_structure": [],
    }


def _mechanism_compatibility_for_step8(strategy: dict, execution: dict) -> dict:
    selected_channel = execution.get("selected_channel") or ""
    planned_channels = strategy.get("planned_channels") or []
    exact = next((item for item in planned_channels if isinstance(item, dict) and item.get("channel") == selected_channel), None)
    selected_family = _channel_family(selected_channel)
    family_match = next((
        item for item in planned_channels
        if isinstance(item, dict) and _channel_family(item.get("channel") or "") == selected_family
    ), None)
    checked = {
        "intervention_mechanism": strategy.get("intervention_mechanism") or strategy.get("mechanism") or strategy.get("core_mechanism"),
        "channel_role": exact.get("channel_role") if isinstance(exact, dict) else (family_match.get("channel_role") if isinstance(family_match, dict) else ""),
        "required_signals": strategy.get("required_signals", []),
        "attribution_intent": strategy.get("attribution_intent", {}),
    }
    if exact:
        return {
            "status": "EXECUTION_COMPATIBLE",
            "selected_channel": selected_channel,
            "planned_channel_match": True,
            "checked_against": checked,
            "reasons": ["执行渠道属于已确认 Strategy 的 planned_channels。"],
        }
    if family_match:
        return {
            "status": "REVIEW_REQUIRED",
            "selected_channel": selected_channel,
            "planned_channel_match": False,
            "checked_against": checked,
            "reasons": [
                "执行渠道不在已确认 planned_channels 中，但与其中一个计划渠道属于相近机制族。",
                "需要人工确认新渠道仍能履行原 channel_role 和 required_signals。",
            ],
        }
    return {
        "status": "STRATEGY_RECONFIRM_REQUIRED",
        "selected_channel": selected_channel,
        "planned_channel_match": False,
        "checked_against": checked,
        "reasons": ["执行渠道不在已确认 Strategy 中，也没有相近机制角色；需要返回第 7 步重新确认。"],
    }


def _primary_planned_channel(strategy: dict) -> dict:
    channels = [item for item in strategy.get("planned_channels") or [] if isinstance(item, dict)]
    primary = next((item for item in channels if item.get("intervention_priority") == "PRIMARY"), None)
    return primary or (channels[0] if channels else {})


def _channel_family(channel: str) -> str:
    if channel in {"OFFICIAL_SITE", "PRODUCT_DOCS"}:
        return "FIRST_PARTY"
    if channel in {"ZHIHU", "BAIJIAHAO", "THIRD_PARTY_MEDIA"}:
        return "THIRD_PARTY"
    return channel or "UNKNOWN"


def _json_stable(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _normalize_step8_channel(value: str) -> str:
    channel = str(value or "").strip().upper()
    if channel not in STEP8_CHANNELS:
        raise HTTPException(status_code=400, detail=f"未知执行渠道: {value}")
    return channel


def _normalize_step8_asset_operation(value: str) -> str:
    operation = str(value or "").strip().upper()
    if operation not in STEP8_ASSET_OPERATIONS:
        raise HTTPException(status_code=400, detail=f"未知资产操作: {value}")
    return operation


def _resolve_selected_asset_ref(db: Session, project: Project, payload, channel: str, asset_operation: str) -> dict:
    asset_type = str(_payload_value(payload, "selected_asset_type", "") or _payload_value(payload, "target_content_type", "") or "ARTICLE").strip().upper()
    if asset_operation == "UPDATE_EXISTING":
        snapshot_id = _payload_value(payload, "selected_asset_id", None)
        if not snapshot_id:
            raise HTTPException(status_code=400, detail="更新已有资产必须绑定真实 PageSnapshot ID，不能用自由文本 URL 冒充已有资产。")
        snapshot = db.get(PageSnapshot, int(snapshot_id))
        if not snapshot or snapshot.project_id != project.id:
            raise HTTPException(status_code=404, detail="选定资产快照不存在或不属于当前项目")
        canonical_url = snapshot.canonical_url or snapshot.final_url or snapshot.url or snapshot.target_url
        return {
            "asset_ref_type": "PAGE_SNAPSHOT",
            "asset_id": snapshot.id,
            "snapshot_id": snapshot.id,
            "canonical_url": canonical_url,
            "url": snapshot.url or snapshot.target_url or canonical_url,
            "asset_type": asset_type,
            "snapshot_type": snapshot.snapshot_type,
            "capture_status": snapshot.capture_status,
            "title": snapshot.title or snapshot.h1 or "",
            "channel": channel,
            "asset_operation": asset_operation,
        }
    proposal = _payload_value(payload, "new_asset_proposal", {}) or {}
    if not isinstance(proposal, dict) or not proposal:
        raise HTTPException(status_code=400, detail="新建资产必须提供 NEW_ASSET proposal。")
    return {
        "asset_ref_type": "NEW_ASSET",
        "asset_id": None,
        "canonical_url": proposal.get("canonical_url") or proposal.get("url") or "",
        "url": proposal.get("url") or proposal.get("canonical_url") or "",
        "asset_type": asset_type,
        "title": proposal.get("title") or "",
        "proposal": proposal,
        "channel": channel,
        "asset_operation": asset_operation,
    }


def _selected_asset_identity(selected_asset_ref: dict) -> str:
    if selected_asset_ref.get("asset_ref_type") == "PAGE_SNAPSHOT":
        return f"PAGE_SNAPSHOT:{selected_asset_ref.get('asset_id')}"
    return "NEW_ASSET"


def _intervention_type_for_step8(channel: str, asset_operation: str, strategy_snapshot: dict) -> str:
    if asset_operation == "UPDATE_EXISTING":
        return "OFFICIAL_PAGE_UPDATE" if channel in {"OFFICIAL_SITE", "PRODUCT_DOCS"} else "CONTENT_REFRESH"
    if channel in {"OFFICIAL_SITE", "PRODUCT_DOCS"}:
        return "OFFICIAL_NEW_PAGE"
    if channel == "ZHIHU":
        return "EXTERNAL_PLATFORM_QA"
    if channel in {"BAIJIAHAO", "THIRD_PARTY_MEDIA", "OTHER"}:
        return "EXTERNAL_PLATFORM_ARTICLE"
    return strategy_snapshot.get("effective_payload", {}).get("intervention_type") or "UNRESOLVED"


def _strategy_snapshot_for_experiment(candidate: OptimizationStrategyCandidate, package: OptimizationEvidencePackage) -> dict:
    return {
        "snapshot_version": "strategy_snapshot.phase4.v1",
        "strategy_candidate_id": candidate.id,
        "review_status": candidate.review_status,
        "reviewed_by": candidate.reviewed_by,
        "reviewed_at": candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
        "effective_payload_version": candidate.effective_payload_version,
        "effective_validation_status": candidate.effective_validation_status,
        "effective_payload": loads(candidate.effective_payload_json, {}),
        "structured_payload": loads(candidate.structured_payload_json, {}),
        "human_edited_payload": loads(candidate.human_edited_payload_json, {}),
        "evidence_package_id": package.id,
        "prompt_id": package.prompt_id,
        "frozen_at": datetime.utcnow().isoformat(),
    }


def baseline_metrics_for_fixed_runs(
    db: Session,
    project: Project,
    runs: list[BrowserMonitorRun],
    strategy_payload: dict,
    selected_asset_ref: dict,
) -> dict:
    run_ids = [run.id for run in runs]
    if not run_ids:
        raise HTTPException(status_code=400, detail="Baseline Metrics Calculator 必须接收固定 run_ids。")
    answer_run_ids = [run.id for run in runs if run.status in VALID_RUN_STATUSES]
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(answer_run_ids)).all() if answer_run_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(answer_run_ids)).all() if answer_run_ids else []
    events = db.query(RecommendationEvent).filter(RecommendationEvent.run_id.in_(answer_run_ids)).all() if answer_run_ids else []
    aliases = [project.brand_name, *loads(project.brand_aliases_json, [])]
    candidate_speech_acts = {"INCLUDE_AS_OPTION", "COMPARE", "RECOMMEND"}
    candidate_run_ids = {
        event.run_id for event in events
        if _event_matches_brand(event, aliases) and (event.speech_act or "").upper() in candidate_speech_acts
    }
    recommendation_run_ids = {
        event.run_id for event in events
        if _event_matches_brand(event, aliases) and (event.speech_act or "").upper() == "RECOMMEND"
    }
    capability_labels = _target_capability_labels_from_strategy(strategy_payload)
    target_reason_run_ids = _target_brand_reason_adoption_run_ids(db, events, aliases, capability_labels)
    brand_retrieval_run_ids = {
        item.run_id for item in retrievals if _source_matches_project_brand(project, item.url, item.canonical_url, item.domain, item.title)
    }
    brand_citation_run_ids = {
        ref.run_id for ref in refs if _source_matches_project_brand(project, ref.url, ref.canonical_url, ref.domain, ref.display_title or ref.matched_title)
    }
    asset_retrieval_run_ids = {
        item.run_id for item in retrievals if _source_matches_selected_asset_ref(selected_asset_ref, item.url, item.canonical_url, item.domain, item.title)
    }
    asset_citation_run_ids = {
        ref.run_id for ref in refs if _source_matches_selected_asset_ref(selected_asset_ref, ref.url, ref.canonical_url, ref.domain, ref.display_title or ref.matched_title)
    }
    denominator = len(answer_run_ids)
    brand_mention_row = _baseline_metric_row("brand_mention", [run.id for run in runs if run.id in answer_run_ids and run.brand_mentioned], denominator)
    brand_candidate_row = _baseline_metric_row("brand_candidate", sorted(candidate_run_ids), denominator)
    brand_recommendation_row = _baseline_metric_row("brand_recommendation", sorted(recommendation_run_ids), denominator)
    target_reason_row = _baseline_metric_row("target_reason_adoption", sorted(target_reason_run_ids), denominator)
    brand_retrieval_row = _baseline_metric_row("brand_retrieval_presence", sorted(brand_retrieval_run_ids), denominator, level="brand_level")
    brand_citation_row = _baseline_metric_row("brand_citation_presence", sorted(brand_citation_run_ids), denominator, level="brand_level")
    asset_retrieval_row = _baseline_metric_row("selected_asset_retrieval_presence", sorted(asset_retrieval_run_ids), denominator, level="selected_asset_level")
    asset_citation_row = _baseline_metric_row("selected_asset_citation_presence", sorted(asset_citation_run_ids), denominator, level="selected_asset_level")
    return {
        "calculator_version": "baseline_metrics.phase4.v1",
        "fixed_run_ids": run_ids,
        "eligible_run_ids": answer_run_ids,
        "calculation_status": "ok" if denominator else "no_valid_runs",
        "target_capabilities": capability_labels,
        "metrics": {
            "brand_mention": brand_mention_row,
            "brand_mention_rate": {**brand_mention_row, "metric_name": "brand_mention_rate"},
            "brand_candidate": brand_candidate_row,
            "brand_candidate_rate": {**brand_candidate_row, "metric_name": "brand_candidate_rate"},
            "brand_recommendation": brand_recommendation_row,
            "brand_recommendation_rate": {**brand_recommendation_row, "metric_name": "brand_recommendation_rate"},
            "target_reason_adoption": target_reason_row,
            "target_reason_adoption_rate": {**target_reason_row, "metric_name": "target_reason_adoption_rate"},
            "brand_retrieval_presence": brand_retrieval_row,
            "brand_citation_presence": brand_citation_row,
            "selected_asset_retrieval_presence": asset_retrieval_row,
            "selected_asset_citation_presence": asset_citation_row,
        },
        "boundary_note": "Baseline 只由显式固定 run_ids 计算，属于 Experiment；不会按 prompt_id 动态读取最新 Runs。",
    }


def _baseline_metric_row(name: str, source_run_ids: list[int], denominator: int, level: str = "brand_level") -> dict:
    numerator = len(set(source_run_ids))
    return {
        "metric_name": name,
        "level": level,
        "numerator": numerator,
        "denominator": denominator,
        "value": _rate(numerator, denominator),
        "source_run_ids": sorted(set(source_run_ids)),
        "calculation_status": "ok" if denominator else "no_valid_runs",
    }


def _target_capability_labels_from_strategy(strategy_payload: dict) -> list[str]:
    labels: list[str] = []
    for item in strategy_payload.get("target_capabilities") or []:
        if isinstance(item, dict) and item.get("capability_label"):
            labels.append(str(item["capability_label"]))
    if strategy_payload.get("target_capability_or_reason"):
        labels.extend(str(strategy_payload["target_capability_or_reason"]).split("/"))
    return [label.strip() for label in labels if label and label.strip()]


def _target_brand_reason_adoption_run_ids(
    db: Session,
    events: list[RecommendationEvent],
    aliases: list[str],
    capability_labels: list[str],
) -> set[int]:
    label_keys = [_compact_key(label) for label in capability_labels if _compact_key(label)]
    if not label_keys:
        return set()
    brand_events = [event for event in events if _event_matches_brand(event, aliases)]
    event_ids = [event.id for event in brand_events]
    units_by_event: dict[int, list[AnswerUnit]] = defaultdict(list)
    if event_ids:
        bindings = db.query(AnswerDecisionBinding).filter(AnswerDecisionBinding.recommendation_event_id.in_(event_ids)).all()
        unit_ids = [binding.answer_unit_id for binding in bindings]
        units = db.query(AnswerUnit).filter(AnswerUnit.id.in_(unit_ids)).all() if unit_ids else []
        unit_by_id = {unit.id: unit for unit in units}
        for binding in bindings:
            unit = unit_by_id.get(binding.answer_unit_id)
            if unit:
                units_by_event[binding.recommendation_event_id].append(unit)
    matched_run_ids: set[int] = set()
    for event in brand_events:
        texts = [event.answer_span or ""]
        texts.extend(str(item.get("normalized_reason") or item.get("text") or item) for item in loads(event.reasons_json, []))
        texts.extend(unit.unit_text_normalized or unit.unit_text_original or "" for unit in units_by_event.get(event.id, []))
        haystack = _compact_key(" ".join(texts))
        if any(label_key and label_key in haystack for label_key in label_keys):
            matched_run_ids.add(event.run_id)
    return matched_run_ids


def _source_matches_project_brand(project: Project, url: str, canonical_url: str, domain: str, title: str) -> bool:
    brand_domain = (host_from_url(project.website_url) if project.website_url else "").lower().removeprefix("www.")
    source_domain = (domain or host_from_url(url or canonical_url or "") or "").lower().removeprefix("www.")
    if brand_domain and source_domain == brand_domain:
        return True
    text = _compact_key(" ".join([url or "", canonical_url or "", title or ""]))
    return any(_compact_key(alias) and _compact_key(alias) in text for alias in [project.brand_name, *loads(project.brand_aliases_json, [])])


def _source_matches_selected_asset_ref(selected_asset_ref: dict, url: str, canonical_url: str, domain: str, title: str) -> bool:
    if selected_asset_ref.get("asset_ref_type") != "PAGE_SNAPSHOT":
        return False
    targets = {
        _normalize_source_url(selected_asset_ref.get("canonical_url") or ""),
        _normalize_source_url(selected_asset_ref.get("url") or ""),
    }
    candidate_urls = {_normalize_source_url(url or ""), _normalize_source_url(canonical_url or "")}
    if any(target and target in candidate_urls for target in targets):
        return True
    asset_domain = host_from_url(selected_asset_ref.get("canonical_url") or selected_asset_ref.get("url") or "").lower().removeprefix("www.")
    source_domain = (domain or host_from_url(url or canonical_url or "") or "").lower().removeprefix("www.")
    if asset_domain and source_domain == asset_domain:
        text = _compact_key(" ".join([url or "", canonical_url or "", title or ""]))
        title_key = _compact_key(selected_asset_ref.get("title") or "")
        return bool(title_key and title_key in text)
    return False


def _get_or_create_step8_issue(
    db: Session,
    candidate: OptimizationStrategyCandidate,
    package: OptimizationEvidencePackage,
    prompt: Prompt | None,
    strategy_snapshot: dict,
    baseline_run_ids: list[int],
) -> OptimizationIssue:
    issue = OptimizationIssue(
        project_id=candidate.project_id,
        prompt_id=package.prompt_id,
        issue_type="citation_strategy_execution_plan",
        status="in_action",
        severity=3,
        confidence_level="medium",
        analyzable_sample_count=len(baseline_run_ids),
        observed_facts_json=dumps({
            "strategy_candidate_id": candidate.id,
            "evidence_package_id": package.id,
            "prompt_text": prompt.prompt_text if prompt else "",
            "gap_item_ids": (strategy_snapshot.get("effective_payload") or {}).get("gap_item_ids", []),
        }),
        possible_causes_json=dumps([(strategy_snapshot.get("effective_payload") or {}).get("hypothesized_cause", "")]),
        diagnosis_summary=f"StrategyCandidate #{candidate.id} 已确认，进入 Step 8 实验方案草案。",
        confirmed_at=datetime.utcnow(),
    )
    db.add(issue)
    db.flush()
    for run_id in baseline_run_ids:
        db.add(OptimizationIssueRun(issue_id=issue.id, run_id=run_id, evidence_role="baseline"))
    db.flush()
    return issue


def _create_step8_action(
    db: Session,
    issue: OptimizationIssue,
    effective: dict,
    selected_asset_ref: dict,
    strategy_snapshot: dict,
) -> OptimizationAction:
    action_type = "content_update" if selected_asset_ref.get("asset_operation") == "UPDATE_EXISTING" else "content_create"
    if (effective.get("proposed_direction") or "").upper() == "PRODUCT":
        action_type = "product_review"
    target_type = "owned_content" if selected_asset_ref.get("channel") in {"OFFICIAL_SITE", "PRODUCT_DOCS"} else "external_platform"
    action = OptimizationAction(
        issue_id=issue.id,
        action_type=action_type,
        target_type=target_type,
        target_url=selected_asset_ref.get("canonical_url") or selected_asset_ref.get("url") or "",
        status="PLANNED",
        priority=2 if effective.get("priority") == "PRIORITY_HIGH" else 3,
        owner="human",
        action_summary=effective.get("recommended_action") or "已确认策略执行方案",
        action_detail=effective.get("mechanism") or effective.get("core_mechanism") or "",
        content_feature_changes_json=dumps(_normalize_feature_changes(effective.get("changed_features", []))),
        planned_at=datetime.utcnow(),
        release_evidence_json=dumps({
            "strategy_candidate_id": strategy_snapshot.get("strategy_candidate_id"),
            "selected_asset_ref": selected_asset_ref,
            "step": "PHASE_4_EXECUTION_PLAN_DRAFT",
        }),
    )
    db.add(action)
    db.flush()
    return action


def _create_step8_experiment(
    db: Session,
    candidate: OptimizationStrategyCandidate,
    package: OptimizationEvidencePackage,
    prompt: Prompt | None,
    action: OptimizationAction,
    effective: dict,
    strategy_snapshot: dict,
    selected_asset_ref: dict,
    baseline_run_ids: list[int],
    baseline_metrics: dict,
) -> OptimizationExperiment:
    primary_metric = effective.get("target_metric") or effective.get("validation_metric") or "brand_recommendation_rate"
    metric = (baseline_metrics.get("metrics") or {}).get(primary_metric) or {}
    attribution_intent = effective.get("attribution_intent") if isinstance(effective.get("attribution_intent"), dict) else {}
    intervention_variables = {
        "strategy_candidate_id": candidate.id,
        "strategy_snapshot": json.loads(json.dumps(strategy_snapshot, ensure_ascii=False)),
        "selected_asset_ref": json.loads(json.dumps(selected_asset_ref, ensure_ascii=False)),
        "gap_diagnosis_refs": {
            "gap_item_ids": effective.get("gap_item_ids", []),
            "benchmark_evidence_ids": effective.get("benchmark_evidence_ids", []),
            "product_truth_refs": effective.get("product_truth_refs", {}),
            "relevant_asset_refs": effective.get("relevant_asset_refs", []),
        },
        "action_snapshot": _action_snapshot(action),
        "target_decision_change": effective.get("target_decision_change"),
        "primary_capability": attribution_intent.get("primary_capability"),
        "secondary_capabilities": attribution_intent.get("secondary_capabilities", []),
        "attribution_scope": attribution_intent.get("attribution_scope"),
        "tested_strategy_path": attribution_intent.get("tested_strategy_path"),
        "validation_hypothesis": attribution_intent.get("validation_hypothesis"),
        "intervention_mechanism": effective.get("intervention_mechanism") or effective.get("mechanism") or effective.get("core_mechanism"),
        "required_signals": effective.get("required_signals", []),
        "execution_delta": effective.get("execution_delta", []),
        "mechanism_compatibility": effective.get("mechanism_compatibility", {}),
    }
    experiment = OptimizationExperiment(
        action_id=action.id,
        status="draft",
        hypothesis=(effective.get("hypothesized_cause") or effective.get("observed_problem") or "")[:500],
        hypothesis_type="strategy_execution_plan",
        mechanism=(effective.get("mechanism") or effective.get("core_mechanism") or "")[:500],
        intervention_family=effective.get("intervention_type") or "",
        intervention_variables_json=dumps(intervention_variables),
        allowed_changes_json=dumps(_normalize_feature_changes(effective.get("changed_features", []))),
        forbidden_changes_json=dumps(["未完成人工 Release Audit 前不得标记已发布", "不得自动发布外部平台内容"]),
        target_prompt_scope_json=dumps([prompt.id] if prompt else []),
        control_prompt_scope_json=dumps([]),
        sentinel_prompt_scope_json=dumps([]),
        environment_scope_json=dumps({"platform": "wenxin", "source_type": "browser_audit"}),
        sample_plan_json=dumps({"baseline_run_ids": baseline_run_ids, "validation_samples": 3, "collection_mode": "single_independent"}),
        primary_metric=primary_metric,
        secondary_metrics_json=dumps(["brand_candidate", "brand_recommendation", "target_reason_adoption", "selected_asset_retrieval_presence", "selected_asset_citation_presence"]),
        baseline_numerator=metric.get("numerator"),
        baseline_denominator=metric.get("denominator"),
        baseline_metric_value=metric.get("value"),
        target_prompt_ids_json=dumps([prompt.id] if prompt else []),
        target_asset_ids_json=dumps([selected_asset_ref.get("asset_id")] if selected_asset_ref.get("asset_id") else []),
        baseline_run_ids_json=dumps(baseline_run_ids),
        baseline_metrics_json=dumps(baseline_metrics),
        release_blocked=True,
        release_blocked_reason="WAITING_FOR_RELEASE_AUDIT",
        controlled_intervention_json=dumps({
            "strategy_snapshot": strategy_snapshot,
            "selected_asset_ref": selected_asset_ref,
            "action_snapshot": _action_snapshot(action),
            "baseline_run_ids": baseline_run_ids,
            "baseline_metrics": baseline_metrics,
            "execution_delta": effective.get("execution_delta", []),
            "mechanism_compatibility": effective.get("mechanism_compatibility", {}),
            "attribution_intent": attribution_intent,
        }),
        channel=selected_asset_ref.get("channel", ""),
        experiment_mode="PER_CHANNEL",
        primary_benchmark_source_id=_primary_benchmark_source_id_from_strategy(effective),
        benchmark_source_ids_json=dumps(_benchmark_source_ids_from_strategy(effective)),
        target_reason_ids_json=dumps(effective.get("benchmark_evidence_ids", [])),
        target_gap_ids_json=dumps(effective.get("gap_item_ids", [])),
        hypothesis_text=(effective.get("mechanism") or effective.get("core_mechanism") or ""),
        brief_json=dumps({
            "strategy_candidate_id": candidate.id,
            "selected_asset_ref": selected_asset_ref,
            "strategy_snapshot": strategy_snapshot,
            "baseline_metrics": baseline_metrics,
            "attribution_intent": attribution_intent,
            "execution_delta": effective.get("execution_delta", []),
            "mechanism_compatibility": effective.get("mechanism_compatibility", {}),
        }),
        target_asset_type=selected_asset_ref.get("asset_type", "TBD"),
        target_asset_url=selected_asset_ref.get("canonical_url") or selected_asset_ref.get("url") or "",
    )
    db.add(experiment)
    db.flush()
    return experiment


def _primary_benchmark_source_id_from_strategy(effective: dict) -> int | None:
    source_ids = _benchmark_source_ids_from_strategy(effective)
    return source_ids[0] if source_ids else None


def _benchmark_source_ids_from_strategy(effective: dict) -> list[int]:
    ids = []
    for item in effective.get("target_capabilities") or []:
        benchmark = item.get("benchmark_source") if isinstance(item, dict) else None
        if isinstance(benchmark, dict) and benchmark.get("source_document_id"):
            ids.append(int(benchmark["source_document_id"]))
    for item in effective.get("relevant_asset_refs") or []:
        if isinstance(item, dict) and item.get("source_document_id"):
            ids.append(int(item["source_document_id"]))
    summary = effective.get("evidence_summary") or {}
    benchmark = summary.get("benchmark_source") if isinstance(summary, dict) else None
    if isinstance(benchmark, dict) and benchmark.get("source_document_id"):
        ids.append(int(benchmark["source_document_id"]))
    return sorted(set(ids))


def _action_snapshot(action: OptimizationAction) -> dict:
    return {
        "action_id": action.id,
        "action_type": action.action_type,
        "target_type": action.target_type,
        "target_url": action.target_url,
        "status": action.status,
        "priority": action.priority,
        "action_summary": action.action_summary,
        "action_detail": action.action_detail,
        "content_feature_changes": loads(action.content_feature_changes_json, []),
        "snapshot_at": datetime.utcnow().isoformat(),
    }


def _payload_value(payload, key: str, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _normalize_int_list(value) -> list[int]:
    result: list[int] = []
    for item in value or []:
        if item is None:
            continue
        number = int(item)
        if number not in result:
            result.append(number)
    return result


class LLMStrategyProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self.provider = settings.strategy_llm_provider
        self.model = settings.strategy_llm_model
        self.prompt_version = settings.strategy_llm_prompt_version
        if not self.provider or not self.model:
            raise HTTPException(status_code=400, detail="B2 Strategy Provider 未配置，已失败关闭")

    def generate(
        self,
        project: Project,
        package: OptimizationEvidencePackage,
        snapshot: PageSnapshot | None,
        target_url: str,
        max_hypotheses: int,
    ) -> dict:
        evidence = loads(package.package_payload_json, {})
        prompt_text = _strategy_prompt_text(evidence, snapshot, target_url, max_hypotheses)
        hypothesis = _local_strategy_hypothesis(project, evidence, snapshot, target_url)
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "prompt_text": prompt_text,
            "generated_at": datetime.utcnow(),
            "hypotheses": [hypothesis][:max_hypotheses],
        }


def _strategy_prompt_text(evidence: dict, snapshot: PageSnapshot | None, target_url: str, max_hypotheses: int) -> str:
    prompt = evidence.get("prompt") or {}
    return (
        f"Prompt version {get_settings().strategy_llm_prompt_version}. "
        f"Generate 1-{max_hypotheses} grounded optimization hypotheses from Evidence Package. "
        f"Prompt: {prompt.get('display_label') or prompt.get('prompt_text')}. "
        f"Target URL: {target_url}. "
        f"Snapshot title: {snapshot.title if snapshot else 'NO_PRE_RELEASE_SNAPSHOT'}."
    )


def _local_strategy_hypothesis(project: Project, evidence: dict, snapshot: PageSnapshot | None, target_url: str) -> dict:
    prompt = evidence.get("prompt") or {}
    prompt_text = (prompt.get("prompt_text") or prompt.get("display_label") or "当前问题").strip() or "当前问题"
    prompt_title = prompt_text.rstrip("？?！!。；;：:") or "当前问题"
    run_ids = evidence.get("citation_eligible_run_ids") or evidence.get("answer_eligible_run_ids") or evidence.get("source_run_ids") or []
    citation_ids = []
    platforms = []
    for row in evidence.get("platform_gap_matrix", []):
        if row.get("citation_run_count", 0) > 0:
            platforms.append(row.get("platform_label") or row.get("platform"))
            citation_ids.extend(row.get("citation_ids", [])[:5])
    title = snapshot.title if snapshot else ""
    h1 = snapshot.h1 if snapshot else ""
    retrieval_status = evidence.get("retrieval_metrics_status", "unknown")
    metric_rows = {row.get("metric_name"): row for row in evidence.get("metrics", [])}
    retrieval_metric = metric_rows.get("target_page_retrieval_rate") or {}
    official_metric = metric_rows.get("official_reference_rate") or {}
    if retrieval_metric.get("calculation_status") == "ok":
        target_metric = "target_page_retrieval_rate"
        baseline_value = f"{retrieval_metric.get('numerator', 0)}/{retrieval_metric.get('denominator', 0)}"
        observed_problem = (
            f"「{prompt_text}」的合格新基线中，{project.brand_name} 目标页 {target_url} "
            f"进入检索候选为 {baseline_value}。"
        )
        validation_goal = "目标页进入合格检索候选率出现可复核提升。"
    else:
        target_metric = "official_reference_rate"
        baseline_value = f"{official_metric.get('numerator', 0)}/{official_metric.get('denominator', 0)}" if official_metric else ""
        observed_problem = (
            f"「{prompt_text}」的历史样本中，{project.brand_name} 目标页没有形成可验证的官方引用表现；"
            "旧检索候选分母不足，不能使用完整候选漏斗判断。"
        )
        validation_goal = "官方域名引用率出现可复核提升，并继续观察目标页是否进入合格检索候选。"
    evidence_summary = (
        f"当前 Evidence Package 显示回答和引用数据可用；主要引用平台包括 {', '.join(platforms[:4]) or '未知'}。"
        f"目标页 {target_url} 的发布前 Title/H1 为「{title} / {h1}」。"
        f"检索候选指标状态为 {retrieval_status}。"
    )
    return {
        "observed_problem": observed_problem,
        "hypothesized_cause": f"目标页可能更像产品或功能落地页，而不是完整承接「{prompt_text}」搜索意图的解释型内容，因此在 AI 组织答案时缺少可直接引用的定义、边界、步骤和失败排查信息。",
        "core_mechanism": f"强化目标页面对「{prompt_text}」意图的直接承接，使页面具备可被答案引用的完整信息块。",
        "target_object": "UNRESOLVED",
        "target_url": target_url,
        "target_platform": "UNRESOLVED",
        "target_intent": prompt_text,
        "recommended_intervention": f"先保持渠道和资产未决；围绕「{prompt_text}」整理需要补齐的定义、适用场景、实现路径、步骤、失败原因和 FAQ，并在人工审核后再决定官网、外部平台或暂不行动。",
        "changed_features": [
            {"feature": "TITLE_H1_INTENT_ALIGNMENT", "before": title or "", "after": f"标题和 H1 明确承接「{prompt_text}」意图", "description": f"让页面主题直接回应「{prompt_text}」对应的问题承接", "location": "Title/H1"},
            {"feature": "DIRECT_ANSWER_BLOCK", "before": False, "after": True, "description": f"新增直接回答「{prompt_text}」核心问题、适用边界和完成路径", "location": "正文顶部"},
            {"feature": "TROUBLESHOOTING_FAQ", "before": False, "after": True, "description": "补充常见失败、受限条件和异常排查", "location": "页面主体/FAQ"},
        ],
        "controlled_variables": ["target_url", "product_capabilities", "collection_prompt", "wenxin_entry", "account_profile", "external_platform_content"],
        "recommended_title": f"{prompt_title}：使用场景、操作步骤与常见问题",
        "recommended_outline": ["直接回答", "适用场景", "限制条件", "操作步骤", "常见失败原因", "FAQ", f"使用{project.brand_name}完成配置"],
        "required_sections": ["定义与边界", "适用场景", "限制条件", "操作步骤", "失败排查", "FAQ"],
        "evidence_run_ids": run_ids,
        "evidence_candidate_ids": [],
        "evidence_citation_ids": sorted(set(citation_ids))[:20],
        "evidence_summary": evidence_summary,
        "target_metric": target_metric,
        "baseline_value": baseline_value,
        "expected_direction": "increase",
        "priority": "HIGH",
        "evidence_support_level": "SOURCE_LEVEL_ONLY",
        "controllability": "HIGH",
        "effort": "MEDIUM",
        "validation_plan": {
            "entry_observed_condition": "人工发布后等待冷却期，再用同 Prompt/模型/环境/账号独立会话复采。",
            "sustained_improvement_condition": validation_goal,
            "minimum_sample_count": 12,
        },
        "invalidating_result": "复采后官方域名仍无引用，且目标页仍未进入合格检索候选；或页面改动未真实发布。",
        "needs": ["NEEDS_PLATFORM_RULE_VERIFICATION"],
    }


def validate_strategy_evidence(package: OptimizationEvidencePackage, snapshot: PageSnapshot | None, payload: dict) -> dict:
    evidence = loads(package.package_payload_json, {})
    errors: list[str] = []
    warnings: list[str] = []
    source_run_ids = set(loads(package.source_run_ids_json, []))
    all_urls = set(_evidence_urls(evidence))
    all_urls.update(_normalize_source_url(url) for url in loads(package.target_page_urls_json, []) if url)
    if snapshot:
        all_urls.add(_normalize_source_url(snapshot.url))
        all_urls.add(_normalize_source_url(snapshot.final_url))
        all_urls.add(_normalize_source_url(snapshot.canonical_url))
    for run_id in payload.get("evidence_run_ids", []):
        if int(run_id) not in source_run_ids:
            errors.append(f"虚构或越界 Run ID: {run_id}")
    target_url = _normalize_source_url(payload.get("target_url", ""))
    if target_url and target_url not in all_urls:
        errors.append(f"URL 不在 Evidence Package 或目标页快照中: {payload.get('target_url')}")
    metric_rows = {row.get("metric_name"): row for row in evidence.get("metrics", [])}
    target_metric = payload.get("target_metric")
    metric = metric_rows.get(target_metric)
    if not metric:
        errors.append(f"target_metric 不存在于 Evidence Package: {target_metric}")
    elif metric.get("calculation_status") in {"not_applicable", "insufficient_retrieval_candidates"} and target_metric in {"target_page_retrieval_rate", "target_page_conversion_rate"}:
        errors.append(f"不可使用当前不可用的检索指标: {target_metric}")
    if evidence.get("retrieval_metrics_status") == "insufficient_retrieval_candidates":
        forbidden_metrics = {"target_page_retrieval_rate", "target_page_conversion_rate", "candidate_to_citation_rate", "platform_candidate_conversion_rate"}
        if target_metric in forbidden_metrics:
            errors.append("检索候选不足时不能使用完整候选漏斗指标")
        text = json.dumps(payload, ensure_ascii=False)
        if "更容易被引用" in text or "候选到引用转化" in text:
            warnings.append("检索候选不足，不能把候选漏斗解释为完整平台优势。")
    if "%" in str(payload.get("baseline_value", "")) and "not_applicable" in json.dumps(metric_rows, ensure_ascii=False):
        errors.append("不得将 not_applicable 或 insufficient_retrieval_candidates 写成 0%。")
    return {
        "status": "VALIDATED" if not errors else "VALIDATION_FAILED",
        "errors": errors,
        "warnings": warnings,
        "validated_at": datetime.utcnow(),
    }


def validate_strategy_hypothesis(payload: dict, evidence_result: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = list(evidence_result.get("warnings", []))

    # V2 payloads use different field names; normalize for validation
    is_v2 = payload.get("intervention_type") is not None
    required_v1 = ["observed_problem", "hypothesized_cause", "core_mechanism", "target_object", "target_url", "recommended_intervention", "target_metric", "validation_plan", "invalidating_result"]
    required_v2 = ["observed_problem", "hypothesized_cause", "core_mechanism", "intervention_type", "target_platform", "target_metric", "validation_plan", "invalidating_result"]

    if is_v2:
        for key in required_v2:
            if not payload.get(key):
                errors.append(f"缺少字段: {key}")
        # V2 may have nullable target_url for external platform or unresolved platform
        if not payload.get("target_url") and payload.get("intervention_type") not in {"EXTERNAL_PLATFORM_ARTICLE", "EXTERNAL_PLATFORM_QA", "VIDEO_CONTENT", "THIRD_PARTY_REVIEW", "THIRD_PARTY_COMPARISON", "NO_ACTION"}:
            # Also allow when target_platform is UNRESOLVED (content direction only)
            if payload.get("target_platform") != "UNRESOLVED":
                errors.append("非外部平台或 UNRESOLVED 干预类型必须指定 target_url")
    else:
        for key in required_v1:
            if not payload.get(key):
                errors.append(f"缺少字段: {key}")

    cause = str(payload.get("hypothesized_cause", ""))
    if cause and not any(word in cause for word in ["可能", "推测", "假设", "或许", "implies", "suggests", "may", "might", "could"]):
        errors.append("hypothesized_cause 必须保持推断语气")

    intervention = str(payload.get("recommended_intervention") or payload.get("recommended_action", ""))
    if re.fullmatch(r".{0,20}(优化SEO|提升曝光|完善内容).{0,20}", intervention):
        errors.append("建议过于通用，缺少可执行机制")

    if not payload.get("changed_features") and not payload.get("recommended_outline"):
        errors.append("changed_features 或 recommended_outline 不能为空")
    if not payload.get("controlled_variables") and not payload.get("required_sections"):
        warnings.append("最好指定 controlled_variables 或 required_sections")

    # V2: validate intervention_type is in known enum
    if is_v2 and payload.get("intervention_type") not in INTERVENTION_TYPE:
        errors.append(f"未知 intervention_type: {payload.get('intervention_type')}")

    return {
        "status": "VALIDATED" if not errors else "VALIDATION_FAILED",
        "errors": errors,
        "warnings": warnings,
        "validated_at": datetime.utcnow(),
    }


def _experiment_readiness_for_strategy(
    db: Session,
    candidate: OptimizationStrategyCandidate,
    payload: dict,
    package: OptimizationEvidencePackage,
    experiment: OptimizationExperiment | None,
) -> dict:
    evidence = loads(package.package_payload_json, {})
    errors = []
    warnings = []
    snapshots = db.query(PageSnapshot).filter(PageSnapshot.project_id == candidate.project_id, PageSnapshot.snapshot_type == "PRE_RELEASE", PageSnapshot.capture_status == "success").all()
    if not candidate.target_url:
        errors.append("目标页面未人工确认")
    if not snapshots:
        errors.append("缺少成功的 PRE_RELEASE 快照")
    if candidate.review_status not in {"ACCEPTED", "ACCEPTED_WITH_EDITS"}:
        errors.append("Hypothesis 尚未人工审核接受")
    metric_rows = {row.get("metric_name"): row for row in evidence.get("metrics", [])}
    target_metric = payload.get("target_metric")
    metric = metric_rows.get(target_metric)
    if not metric or metric.get("calculation_status") not in {"ok"}:
        errors.append(f"目标指标当前不可用于实验计划: {target_metric}")
    if evidence.get("retrieval_metrics_status") == "insufficient_retrieval_candidates":
        errors.append("WAITING_FOR_RECOLLECTED_RETRIEVAL_BASELINE")
    if experiment and experiment.released_at:
        errors.append("发布前 released_at 必须为空")
    known_environment_audit = _normalize_known_environment_audit(
        loads(experiment.known_environment_audit_json, {}) if experiment else {}
    )
    comparability_status, comparability_note = _resolve_comparability(
        experiment.comparability_status if experiment else None,
        experiment.comparability_note if experiment else None,
        known_environment_audit,
        loads(experiment.confounders_json, []) if experiment else [],
    )
    controlled_intervention = (
        loads(experiment.controlled_intervention_json, {})
        if experiment and experiment.controlled_intervention_json
        else _strategy_controlled_intervention_payload(payload, package)
    )
    return {
        "readiness_status": "READY" if not errors else "BLOCKED",
        "readiness_errors": errors,
        "readiness_warnings": warnings,
        "evidence_package_id": package.id,
        "target_url": candidate.target_url,
        "target_metric": target_metric,
        "baseline": metric,
        "known_environment_audit": known_environment_audit,
        "comparability_status": comparability_status,
        "comparability_note": comparability_note,
        "controlled_intervention": controlled_intervention,
    }


def _latest_success_snapshot(db: Session, project_id: int, target_url: str, snapshot_type: str, experiment_id: int | None) -> PageSnapshot | None:
    query = db.query(PageSnapshot).filter(
        PageSnapshot.project_id == project_id,
        PageSnapshot.snapshot_type == snapshot_type,
        PageSnapshot.capture_status == "success",
    )
    if experiment_id is not None:
        query = query.filter(PageSnapshot.experiment_id == experiment_id)
    rows = query.order_by(PageSnapshot.captured_at.desc(), PageSnapshot.id.desc()).all()
    normalized_target = _normalize_source_url(target_url)
    for row in rows:
        if not normalized_target or _normalize_source_url(row.url) == normalized_target or _normalize_source_url(row.canonical_url) == normalized_target:
            return row
    return rows[0] if rows else None


def _normalize_known_environment_audit(value: dict | None) -> dict:
    raw = value or {}
    audit = {
        "model_version_known_changed": bool(raw.get("model_version_known_changed", False)),
        "citation_landscape_changed": bool(raw.get("citation_landscape_changed", False)),
        "competitor_source_changed": bool(raw.get("competitor_source_changed", False)),
        "brand_market_changed": bool(raw.get("brand_market_changed", False)),
        "other_known_changes": bool(raw.get("other_known_changes", False)),
        "other_known_changes_note": str(raw.get("other_known_changes_note", "") or ""),
        "audit_note": str(raw.get("audit_note", "") or ""),
    }
    audit["boundary_note"] = "只能记录当前观察窗口内已知变化；不得声称黑盒 AI 环境完全不变。"
    return audit


def _resolve_comparability(
    requested_status: str | None,
    requested_note: str | None,
    known_environment_audit: dict,
    confounders: list[str],
) -> tuple[str, str]:
    if requested_status in COMPARABILITY_STATUSES and requested_status != "COMPARABLE":
        status = requested_status
    elif known_environment_audit.get("model_version_known_changed") or known_environment_audit.get("brand_market_changed"):
        status = "MATERIALLY_CONFOUNDED"
    elif any(known_environment_audit.get(key) for key in KNOWN_ENVIRONMENT_AUDIT_KEYS) or confounders:
        status = "POTENTIALLY_CONFOUNDED"
    elif requested_status == "COMPARABLE":
        status = "COMPARABLE"
    else:
        status = "INSUFFICIENT_CONTEXT"

    if requested_note:
        return status, requested_note
    notes = {
        "COMPARABLE": "当前观察窗口内未发现显著已知混杂因素；这不是严格因果证明，也不代表黑盒环境完全不变。",
        "POTENTIALLY_CONFOUNDED": "存在已知或人工记录的潜在混杂因素，结论只能作为方向性观察。",
        "MATERIALLY_CONFOUNDED": "存在可能实质影响复采结果的已知变化，不能把差异直接归因于本次改动。",
        "INSUFFICIENT_CONTEXT": "尚未完成复采环境审计，无法判断前后结果是否可比。",
    }
    return status, notes[status]


def _controlled_intervention_payload(payload) -> dict:
    return {
        "intervention_family": payload.intervention_family,
        "mechanism": payload.mechanism,
        "primary_metric": payload.primary_metric,
        "allowed_changes": payload.allowed_changes,
        "forbidden_changes": payload.forbidden_changes,
        "target_prompt_scope": payload.target_prompt_scope,
        "control_prompt_scope": payload.control_prompt_scope,
        "sentinel_prompt_scope": payload.sentinel_prompt_scope,
        "boundary_note": "一次实验只验证一个主要机制假设；允许多个页面改动，但必须同属同一干预家族。",
    }


def _strategy_controlled_intervention_payload(payload: dict, package: OptimizationEvidencePackage | None) -> dict:
    changed_features = payload.get("changed_features") or []
    allowed_changes = [
        str(item.get("feature") or item.get("description") or item)
        for item in changed_features
        if item
    ]
    forbidden_changes = [
        str(item)
        for item in (payload.get("controlled_variables") or [])
        if item
    ]
    prompt_scope = [package.prompt_id] if package and package.prompt_id else []
    return {
        "intervention_family": str(payload.get("intervention_type") or payload.get("recommended_intervention") or "strategy_candidate"),
        "mechanism": str(payload.get("core_mechanism") or payload.get("hypothesized_cause") or ""),
        "primary_metric": str(payload.get("target_metric") or "official_reference_rate"),
        "allowed_changes": allowed_changes,
        "forbidden_changes": forbidden_changes or [
            "collection_prompt",
            "target_url",
            "product_capabilities",
            "external_platform_content",
        ],
        "target_prompt_scope": prompt_scope,
        "control_prompt_scope": [],
        "sentinel_prompt_scope": [],
        "boundary_note": "一次实验只验证一个主要机制假设；允许多个内容块改动，但不得同时混入 Prompt、产品能力、目标 URL 或外部投放变化。",
    }


def _evidence_urls(evidence: dict) -> list[str]:
    urls: list[str] = []
    for key in ["representative_sources", "source_level_evidence"]:
        for row in evidence.get(key, []) or []:
            url = row.get("url") if isinstance(row, dict) else ""
            if url:
                urls.append(_normalize_source_url(url))
    for key in ["platform_gap_matrix", "content_type_distribution"]:
        for row in evidence.get(key, []) or []:
            if not isinstance(row, dict):
                continue
            for list_key in ["representative_candidate_urls", "representative_cited_urls", "representative_urls"]:
                for item in row.get(list_key, []) or []:
                    url = item.get("url") if isinstance(item, dict) else ""
                    if url:
                        urls.append(_normalize_source_url(url))
    return [url for url in urls if url]


def confirm_experiment_release(db: Session, experiment_id: int, payload) -> OptimizationExperiment:
    experiment = _get_experiment(db, experiment_id)
    action = _get_action(db, experiment.action_id)
    if experiment.release_blocked:
        raise HTTPException(status_code=400, detail=f"实验发布确认被阻塞：{experiment.release_blocked_reason or 'UNKNOWN'}")
    accepted_strategy = (
        db.query(OptimizationStrategyCandidate)
        .filter(
            OptimizationStrategyCandidate.experiment_id == experiment.id,
            OptimizationStrategyCandidate.review_status.in_(["ACCEPTED", "ACCEPTED_WITH_EDITS"]),
            OptimizationStrategyCandidate.generation_status == "GENERATED",
        )
        .first()
    )
    if not accepted_strategy:
        raise HTTPException(status_code=400, detail="WAITING_FOR_INTERVENTION_SELECTION：发布确认前必须存在已人工接受（ACCEPTED 或 ACCEPTED_WITH_EDITS）的策略候选，且已明确干预选择。")
    hypothesis = db.get(OptimizationHypothesis, payload.hypothesis_id)
    if not hypothesis or hypothesis.experiment_id != experiment.id or hypothesis.status != "ACCEPTED":
        raise HTTPException(status_code=400, detail="发布确认前必须关联已人工接受的 Hypothesis")
    pre_snapshot = db.get(PageSnapshot, payload.pre_release_snapshot_id)
    post_snapshot = db.get(PageSnapshot, payload.post_release_snapshot_id)
    _validate_release_snapshot(pre_snapshot, experiment.id, "PRE_RELEASE")
    _validate_release_snapshot(post_snapshot, experiment.id, "POST_RELEASE")
    if _normalize_source_url(action.target_url) != _normalize_source_url(post_snapshot.url):
        raise HTTPException(status_code=400, detail="发布后快照 URL 与 Action 目标 URL 不一致")
    if _robots_block_indexing(loads(post_snapshot.robots_directives_json, {})):
        raise HTTPException(status_code=400, detail="发布后页面 robots/index 指令异常，不能确认发布")
    if post_snapshot.canonical_url and _normalize_source_url(action.target_url) != _normalize_source_url(post_snapshot.canonical_url):
        raise HTTPException(status_code=400, detail="发布后页面 canonical 指向异常，不能确认发布")
    now = datetime.utcnow()
    record = ReleaseAuditRecord(
        experiment_id=experiment.id,
        hypothesis_id=hypothesis.id,
        pre_release_snapshot_id=pre_snapshot.id,
        post_release_snapshot_id=post_snapshot.id,
        planned_feature_changes_json=dumps(_normalize_feature_changes(payload.planned_feature_changes)),
        deployed_feature_changes_json=dumps(_normalize_feature_changes(payload.deployed_feature_changes)),
        undeployed_feature_changes_json=dumps(_normalize_feature_changes(payload.undeployed_feature_changes)),
        release_note=payload.release_note,
        confirmed_by=payload.confirmed_by,
        confirmed_at=now,
        online_verification_status=payload.online_verification_status,
    )
    db.add(record)
    action.status = "RELEASE_CONFIRMED"
    action.released_at = now
    action.release_note = payload.release_note
    action.release_evidence_json = dumps({"release_audit_record_id": None})
    experiment.status = "cooling"
    experiment.released_at = now
    experiment.validation_not_before = now + timedelta(hours=payload.validation_wait_hours)
    db.flush()
    action.release_evidence_json = dumps({"release_audit_record_id": record.id, "post_release_snapshot_id": post_snapshot.id})
    db.commit()
    db.refresh(experiment)
    return experiment


def create_experiment(db: Session, action_id: int, payload) -> OptimizationExperiment:
    action = _get_action(db, action_id)
    issue = _get_issue(db, action.issue_id)
    target_scope = payload.target_prompt_scope or ([issue.prompt_id] if issue.prompt_id else [])
    secondary_metrics = payload.secondary_metrics
    for metric in ["target_page_retrieval_rate", "target_page_conversion_rate"]:
        if metric != payload.primary_metric and metric not in secondary_metrics:
            secondary_metrics = [*secondary_metrics, metric]
    known_environment_audit = _normalize_known_environment_audit(payload.known_environment_audit)
    comparability_status, comparability_note = _resolve_comparability(
        payload.comparability_status,
        payload.comparability_note,
        known_environment_audit,
        [],
    )
    experiment = OptimizationExperiment(
        action_id=action.id,
        hypothesis=payload.hypothesis,
        hypothesis_type=payload.hypothesis_type,
        mechanism=payload.mechanism,
        intervention_family=payload.intervention_family,
        intervention_variables_json=dumps(payload.intervention_variables),
        allowed_changes_json=dumps(payload.allowed_changes),
        forbidden_changes_json=dumps(payload.forbidden_changes),
        target_prompt_scope_json=dumps(target_scope),
        control_prompt_scope_json=dumps(payload.control_prompt_scope),
        sentinel_prompt_scope_json=dumps(payload.sentinel_prompt_scope),
        environment_scope_json=dumps(payload.environment_scope),
        sample_plan_json=dumps(payload.sample_plan),
        primary_metric=payload.primary_metric,
        secondary_metrics_json=dumps(secondary_metrics),
        baseline_numerator=payload.baseline_numerator,
        baseline_denominator=payload.baseline_denominator,
        baseline_metric_value=payload.baseline_metric_value,
        success_threshold=payload.success_threshold,
        sample_size_target=payload.sample_size_target,
        target_prompt_ids_json=dumps(payload.target_prompt_ids),
        target_brand_id=payload.target_brand_id,
        target_asset_ids_json=dumps(payload.target_asset_ids),
        recollection_strategy_json=dumps(payload.recollection_strategy),
        known_environment_audit_json=dumps(known_environment_audit),
        comparability_status=comparability_status,
        comparability_note=comparability_note,
        controlled_intervention_json=dumps(payload.controlled_intervention or _controlled_intervention_payload(payload)),
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return experiment


def lock_baseline(db: Session, experiment_id: int, run_ids: list[int]) -> OptimizationExperiment:
    experiment = _get_experiment(db, experiment_id)
    if experiment.released_at:
        raise HTTPException(status_code=400, detail="已确认发布后的实验不能静默替换基线")
    if experiment.status not in {"draft", "baseline_locked", "READY_FOR_MANUAL_RELEASE"}:
        raise HTTPException(status_code=400, detail="只有未发布实验可以锁定或替换基线")
    if not run_ids:
        action = _get_action(db, experiment.action_id)
        run_ids = _issue_run_ids(db, action.issue_id)
    runs = _valid_runs_for_experiment(db, experiment, run_ids)
    if not runs:
        raise HTTPException(status_code=400, detail="没有可用于基线的有效 Run")
    action = _get_action(db, experiment.action_id)
    baseline_metrics = metrics_for_runs(db, runs, action.target_url)
    if experiment.status == "draft":
        experiment.status = "baseline_locked"
    experiment.baseline_run_ids_json = dumps([run.id for run in runs])
    experiment.baseline_metrics_json = dumps(baseline_metrics)
    experiment.baseline_start = min(run.created_at for run in runs)
    experiment.baseline_end = max(run.created_at for run in runs)
    primary_metric = experiment.primary_metric or "target_page_retrieval_rate"
    metric_key = "target_page_retrieval" if primary_metric == "target_page_retrieval_rate" else "target_page_conversion"
    primary_status = (baseline_metrics.get(metric_key) or {}).get("calculation_status")
    if experiment.release_blocked_reason == "WAITING_FOR_RECOLLECTED_RETRIEVAL_BASELINE" and primary_status == "ok":
        experiment.release_blocked = False
        experiment.release_blocked_reason = ""
    db.commit()
    db.refresh(experiment)
    return experiment


def start_validation(db: Session, experiment_id: int) -> OptimizationExperiment:
    experiment = _get_experiment(db, experiment_id)
    if experiment.status not in {"cooling", "validating"}:
        raise HTTPException(status_code=400, detail="只有确认真实发布并进入 cooling 后才能进入复测")
    experiment.status = "validating"
    experiment.validation_start = experiment.validation_start or datetime.utcnow()
    db.commit()
    db.refresh(experiment)
    return experiment


def queue_retest_task(db: Session, experiment_id: int, payload) -> dict:
    experiment = _get_experiment(db, experiment_id)
    action = _get_action(db, experiment.action_id)
    issue = _get_issue(db, action.issue_id)
    project = db.get(Project, issue.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if experiment.status not in {"cooling", "validating"}:
        raise HTTPException(status_code=400, detail="只有确认真实发布并进入 cooling/validating 后才能创建复测任务")

    prompt_ids = loads(experiment.target_prompt_scope_json, []) or ([issue.prompt_id] if issue.prompt_id else [])
    prompt_ids = [int(prompt_id) for prompt_id in prompt_ids if prompt_id]
    prompts = (
        db.query(Prompt)
        .filter(Prompt.project_id == project.id, Prompt.id.in_(prompt_ids), Prompt.enabled == True)  # noqa: E712
        .order_by(Prompt.id.asc())
        .all()
        if prompt_ids
        else []
    )
    if not prompts:
        raise HTTPException(status_code=400, detail="实验缺少可复测的目标 Prompt")

    now_key = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    batch = MonitoringBatch(
        project_id=project.id,
        name=payload.batch_name or f"优化复测 Experiment #{experiment.id} · {now_key}",
        platform=WENXIN_PLATFORM,
        collection_mode=payload.collection_mode,
        sample_count=payload.sample_count,
        status="queued" if payload.execute_now else "pending",
        notes=f"optimization_experiment_retest:{experiment.id}; action:{action.id}; issue:{issue.id}",
    )
    db.add(batch)
    db.flush()
    task = create_browser_task(
        db=db,
        project=project,
        prompts=prompts,
        run_count=payload.sample_count,
        execute_now=payload.execute_now,
        platform=WENXIN_PLATFORM,
        source_type=BROWSER_AUDIT_ENTRY_TYPE,
        adapter=WENXIN_WEB_ADAPTER,
        batch_id=batch.id,
        schedule_type="optimization_retest",
    )
    if payload.execute_now:
        executor = MonitoringTaskExecutor()
        try:
            executor.execute_queued_runs(db, task.id)
        finally:
            executor.close()
        update_task_status_from_runs(db, task)

    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.task_id == task.id).order_by(BrowserMonitorRun.id.asc()).all()
    experiment.status = "validating"
    experiment.validation_start = experiment.validation_start or datetime.utcnow()
    db.commit()
    db.refresh(experiment)
    return {
        "experiment_id": experiment.id,
        "batch_id": batch.id,
        "task_id": task.id,
        "run_ids": [run.id for run in runs],
        "queued_run_count": len(runs),
        "status": experiment.status,
    }


def attach_validation_runs(db: Session, experiment_id: int, run_ids: list[int]) -> OptimizationExperiment:
    experiment = _get_experiment(db, experiment_id)
    if experiment.status not in {"validating", "cooling"}:
        raise HTTPException(status_code=400, detail="当前状态不能挂载验证 Run")
    action = _get_action(db, experiment.action_id)
    runs = _valid_runs_for_experiment(db, experiment, run_ids)
    if not runs:
        raise HTTPException(status_code=400, detail="没有可用于验证的有效 Run")
    experiment.status = "analyzing"
    experiment.validation_run_ids_json = dumps([run.id for run in runs])
    experiment.validation_start = experiment.validation_start or min(run.created_at for run in runs)
    experiment.validation_end = max(run.created_at for run in runs)
    experiment.result_metrics_json = dumps(metrics_for_runs(db, runs, action.target_url))
    _write_comparison(db, experiment)
    db.commit()
    db.refresh(experiment)
    return experiment


def analyze_experiment(db: Session, experiment_id: int) -> OptimizationExperiment:
    experiment = _get_experiment(db, experiment_id)
    baseline_ids = loads(experiment.baseline_run_ids_json, [])
    validation_ids = loads(experiment.validation_run_ids_json, [])
    if not baseline_ids or not validation_ids:
        raise HTTPException(status_code=400, detail="分析前必须同时具备基线 Run 和验证 Run")
    action = _get_action(db, experiment.action_id)
    experiment.baseline_metrics_json = dumps(metrics_for_runs(db, _runs_by_ids(db, baseline_ids), action.target_url))
    experiment.result_metrics_json = dumps(metrics_for_runs(db, _runs_by_ids(db, validation_ids), action.target_url))
    _write_comparison(db, experiment)
    experiment.status = "analyzing"
    db.commit()
    db.refresh(experiment)
    return experiment


def confirm_conclusion(db: Session, experiment_id: int, payload) -> OptimizationExperiment:
    experiment = _get_experiment(db, experiment_id)
    if experiment.status != "analyzing":
        raise HTTPException(status_code=400, detail="只有 analyzing 状态可以确认实验结论")
    conclusion = _normalize_conclusion(payload.conclusion)
    if conclusion not in CONCLUSION_TYPES:
        raise HTTPException(status_code=400, detail="未知实验结论枚举")
    action = _get_action(db, experiment.action_id)
    issue = _get_issue(db, action.issue_id)
    experiment.status = "completed"
    experiment.conclusion = conclusion
    experiment.conclusion_reason = payload.conclusion_reason
    experiment.confounders_json = dumps(payload.confounders)
    known_environment_audit = _normalize_known_environment_audit(payload.known_environment_audit)
    comparability_status, comparability_note = _resolve_comparability(
        payload.comparability_status,
        payload.comparability_note,
        known_environment_audit,
        payload.confounders,
    )
    experiment.known_environment_audit_json = dumps(known_environment_audit)
    experiment.comparability_status = comparability_status
    experiment.comparability_note = comparability_note
    experiment.completed_at = datetime.utcnow()
    if payload.resolved:
        issue.status = "resolved"
        issue.resolved_at = experiment.completed_at
    else:
        issue.status = "validating"
    db.commit()
    db.refresh(experiment)
    return experiment


def evidence_chain(db: Session, issue_id: int) -> dict:
    issue = _get_issue(db, issue_id)
    run_ids = _issue_run_ids(db, issue_id)
    actions = db.query(OptimizationAction).filter(OptimizationAction.issue_id == issue_id).order_by(OptimizationAction.id.asc()).all()
    experiments = (
        db.query(OptimizationExperiment)
        .filter(OptimizationExperiment.action_id.in_([action.id for action in actions]))
        .order_by(OptimizationExperiment.id.asc())
        .all()
        if actions
        else []
    )
    experiment_ids = [experiment.id for experiment in experiments]
    for experiment in experiments:
        run_ids.extend(loads(experiment.baseline_run_ids_json, []))
        run_ids.extend(loads(experiment.validation_run_ids_json, []))
    unique_run_ids = list(dict.fromkeys(run_ids))
    runs = _runs_by_ids(db, unique_run_ids)
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(unique_run_ids)).all() if unique_run_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(unique_run_ids)).all() if unique_run_ids else []
    project = db.get(Project, issue.project_id)
    prompt = db.get(Prompt, issue.prompt_id) if issue.prompt_id else None
    issue_read = issue_to_read(issue)
    if prompt and not issue_read["prompt_text"]:
        issue_read["prompt_text"] = prompt.prompt_text
    issue_read["run_ids"] = _issue_run_ids(db, issue_id)
    hypotheses = (
        db.query(OptimizationHypothesis)
        .filter(OptimizationHypothesis.experiment_id.in_(experiment_ids))
        .order_by(OptimizationHypothesis.id.asc())
        .all()
        if experiment_ids
        else []
    )
    strategy_candidates = (
        db.query(OptimizationStrategyCandidate)
        .filter(OptimizationStrategyCandidate.experiment_id.in_(experiment_ids))
        .order_by(OptimizationStrategyCandidate.id.asc())
        .all()
        if experiment_ids
        else []
    )
    snapshots = (
        db.query(PageSnapshot)
        .filter(PageSnapshot.experiment_id.in_(experiment_ids))
        .order_by(PageSnapshot.captured_at.desc(), PageSnapshot.id.desc())
        .all()
        if experiment_ids
        else []
    )
    audits = (
        db.query(ReleaseAuditRecord)
        .filter(ReleaseAuditRecord.experiment_id.in_(experiment_ids))
        .order_by(ReleaseAuditRecord.confirmed_at.desc(), ReleaseAuditRecord.id.desc())
        .all()
        if experiment_ids
        else []
    )
    return {
        "issue": issue_read,
        "actions": [action_to_read(action) for action in actions],
        "experiments": [experiment_to_read(experiment) for experiment in experiments],
        "runs": [_run_evidence(run) for run in runs],
        "references": _dedupe_reference_evidence(references),
        "retrieval_candidates": _dedupe_retrieval_evidence(retrievals),
        "source_analysis": source_analysis(db, project, prompt, runs, references, retrievals) if project else [],
        "hypotheses": [hypothesis_to_read(row) for row in hypotheses],
        "strategy_candidates": [strategy_candidate_to_read(row) for row in strategy_candidates],
        "page_snapshots": [page_snapshot_to_read(row) for row in snapshots],
        "release_audits": [release_audit_to_read(row) for row in audits],
    }


def list_evidence_packages(db: Session, project_id: int, prompt_id: int | None = None) -> list[dict]:
    query = db.query(OptimizationEvidencePackage).filter(OptimizationEvidencePackage.project_id == project_id)
    if prompt_id is not None:
        query = query.filter(OptimizationEvidencePackage.prompt_id == prompt_id)
    packages = query.order_by(OptimizationEvidencePackage.created_at.desc(), OptimizationEvidencePackage.id.desc()).limit(80).all()
    return [evidence_package_to_read(db, package) for package in packages]


def get_evidence_package(db: Session, package_id: int) -> dict:
    package = db.get(OptimizationEvidencePackage, package_id)
    if not package:
        raise HTTPException(status_code=404, detail="证据事实包不存在")
    return evidence_package_to_read(db, package)


def evidence_package_to_read(db: Session, package: OptimizationEvidencePackage) -> dict:
    prompt_text = ""
    if package.prompt_id:
        prompt = db.get(Prompt, package.prompt_id)
        prompt_text = prompt.prompt_text if prompt else ""
    payload = loads(package.package_payload_json, {})
    if not prompt_text:
        prompt_text = str((payload.get("prompt") or {}).get("prompt_text") or "")
    return {
        "id": package.id,
        "project_id": package.project_id,
        "prompt_id": package.prompt_id,
        "prompt_text": prompt_text,
        "version": package.version,
        "schema_version": package.schema_version,
        "metric_spec_version": package.metric_spec_version,
        "source_run_ids": loads(package.source_run_ids_json, []),
        "target_page_urls": loads(package.target_page_urls_json, []),
        "environment_snapshot": loads(package.environment_snapshot_json, {}),
        "package_payload": payload,
        "package_hash": package.package_hash,
        "status": package.status,
        "superseded_by_id": package.superseded_by_id,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
    }


def create_evidence_package(db: Session, project_id: int, payload) -> OptimizationEvidencePackage:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    prompt = db.get(Prompt, payload.prompt_id) if payload.prompt_id else None
    if payload.prompt_id and (not prompt or prompt.project_id != project_id):
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    runs = _evidence_package_runs(db, project_id, payload.prompt_id, payload.run_ids, payload.window_start, payload.window_end)
    valid_runs = [run for run in runs if run.status in VALID_RUN_STATUSES]
    if not valid_runs:
        raise HTTPException(status_code=400, detail="没有可用于证据事实包的有效 Run")
    run_ids = [run.id for run in valid_runs]
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all()
    target_urls = _clean_target_urls(payload.target_page_urls)
    if not target_urls:
        target_urls = _target_urls_from_existing_experiment(db, project_id, prompt.id if prompt else None, run_ids)
    environment_snapshot = _environment_snapshot(valid_runs, prompt, payload.source_note)
    report_payload = _build_evidence_report_payload(db, project, prompt, valid_runs, references, retrievals, target_urls, environment_snapshot)
    version_manifest = _evidence_version_manifest(environment_snapshot)
    package_hash = _package_hash({
        "source_run_ids": run_ids,
        "target_page_urls": target_urls,
        "environment_snapshot": environment_snapshot,
        **version_manifest,
    })
    existing = (
        db.query(OptimizationEvidencePackage)
        .filter(
            OptimizationEvidencePackage.project_id == project_id,
            OptimizationEvidencePackage.package_hash == package_hash,
            OptimizationEvidencePackage.status == "active",
        )
        .first()
    )
    if existing:
        return existing
    latest_version = (
        db.query(OptimizationEvidencePackage)
        .filter(
            OptimizationEvidencePackage.project_id == project_id,
            OptimizationEvidencePackage.prompt_id == (prompt.id if prompt else None),
        )
        .order_by(OptimizationEvidencePackage.version.desc())
        .first()
    )
    package = OptimizationEvidencePackage(
        project_id=project_id,
        prompt_id=prompt.id if prompt else None,
        version=(latest_version.version + 1) if latest_version else 1,
        schema_version=EVIDENCE_SCHEMA_VERSION,
        metric_spec_version=METRIC_SPEC_VERSION,
        source_run_ids_json=dumps(run_ids),
        target_page_urls_json=dumps(target_urls),
        environment_snapshot_json=dumps(environment_snapshot),
        package_payload_json=dumps(report_payload),
        package_hash=package_hash,
        status="active",
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    return package


def citation_decision_vertical_slice(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None = None,
    max_actions: int = 5,
    use_answer_binding_v1_1: bool | None = None,
) -> dict:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project/Prompt 不存在")
    use_v1_1 = (
        get_settings().citation_decision_v1_1_formal_input_enabled
        if use_answer_binding_v1_1 is None
        else bool(use_answer_binding_v1_1)
    )
    package = _resolve_vertical_slice_package(db, project_id, prompt_id, evidence_package_id)
    rows = _source_analysis_for_package(db, project, prompt, package, include_answer_binding_v1_1=use_v1_1)
    recommended_actions = [
        row["recommended_action"]
        for row in rows
        if row.get("recommended_action")
    ][:max_actions]
    channel_opportunities = _dedupe_channel_opportunities(rows)
    experiment_proposals = [
        _experiment_proposal_for_action(action, channel_opportunities, package, prompt)
        for action in recommended_actions
        if action.get("route") in {"CONTENT", "EVIDENCE"}
    ]
    decision_stability = _decision_stability_for_resolved_package(db, project, prompt, package)
    return {
        "version": VERTICAL_SLICE_VERSION,
        "analysis_version": VERTICAL_SLICE_VERSION,
        "project_id": project_id,
        "prompt_id": prompt_id,
        "evidence_package_id": package.id,
        "use_answer_binding_v1_1": use_v1_1,
        "context_identity": {
            "project_id": project_id,
            "prompt_id": prompt_id,
            "evidence_package_id": package.id,
            "analysis_version": VERTICAL_SLICE_VERSION,
            "citation_decision_v1_1_formal_input": use_v1_1,
            "source_run_ids": loads(package.source_run_ids_json, []),
        },
        "status": "READY_FOR_HUMAN_CONFIRM" if recommended_actions else "NO_EXECUTABLE_RECOMMENDATION",
        "summary": _vertical_slice_summary(rows, recommended_actions, channel_opportunities),
        "recommended_actions": recommended_actions,
        "channel_opportunities": channel_opportunities,
        "experiment_proposals": experiment_proposals,
        "decision_stability": decision_stability,
        "resampling_plan": _vertical_resampling_plan(prompt, package),
        "outcome_plan": _vertical_outcome_plan(),
        "source_analysis": rows,
    }


def decision_stability_for_package(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None = None,
) -> dict:
    """Phase 5: read-only post-hoc description of multi-Run decision variance.

    This calculator must not feed Benchmark, Gap, Strategy, Action, Experiment,
    or Baseline gates. It only reports how stable the already-observed
    run-level recommendation decisions are for the fixed Evidence Package.
    """
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt or prompt.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project/Prompt 不存在")
    package = _resolve_vertical_slice_package(db, project_id, prompt_id, evidence_package_id)
    return _decision_stability_for_resolved_package(db, project, prompt, package)


def _decision_stability_for_resolved_package(
    db: Session,
    project: Project,
    prompt: Prompt,
    package: OptimizationEvidencePackage,
) -> dict:
    run_ids = loads(package.source_run_ids_json, [])
    runs = _runs_by_ids(db, run_ids, project.id)
    valid_runs = [run for run in runs if run.status in VALID_RUN_STATUSES]
    valid_run_ids = [run.id for run in valid_runs]
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt.id,
        RecommendationEvent.run_id.in_(valid_run_ids),
        RecommendationEvent.review_status.in_(DECISION_STABILITY_EVENT_STATUSES),
    ).all() if valid_run_ids else []
    return _decision_stability_from_runs(db, project, prompt, package, valid_runs, events)


def _decision_stability_from_runs(
    db: Session,
    project: Project,
    prompt: Prompt,
    package: OptimizationEvidencePackage,
    valid_runs: list[BrowserMonitorRun],
    events: list[RecommendationEvent],
) -> dict:
    valid_run_ids = [run.id for run in valid_runs]
    valid_run_set = set(valid_run_ids)
    denominator = len(valid_run_ids)
    decision_events = [
        event for event in events
        if (event.speech_act or "").upper() in DECISION_STABILITY_DECISION_ACTS
    ]
    brand_decision_run_ids = sorted({
        event.run_id for event in decision_events if event.run_id in valid_run_set
    })
    recommendation_events = [
        event for event in events
        if (event.speech_act or "").upper() == "RECOMMEND" and event.run_id in valid_run_set
    ]
    recommendation_run_ids = sorted({event.run_id for event in recommendation_events})
    recommendation_entities = _decision_stability_recommendation_entities(recommendation_events, denominator)
    no_recommendation_run_ids = sorted(valid_run_set - set(recommendation_run_ids))
    dominant = _dominant_recommendation_outcome(recommendation_entities, no_recommendation_run_ids, denominator)
    score = int(round((dominant["run_count"] / denominator) * 100)) if denominator else 0
    level = _decision_stability_level(score, denominator)
    return {
        "version": DECISION_STABILITY_VERSION,
        "project_id": project.id,
        "prompt_id": prompt.id,
        "evidence_package_id": package.id,
        "metric_role": "POST_HOC_DESCRIPTIVE_ONLY",
        "valid_run_ids": valid_run_ids,
        "valid_run_count": denominator,
        "brand_decision_run_count": len(brand_decision_run_ids),
        "brand_decision_rate": _decision_stability_metric(
            "brand_decision_run_count",
            brand_decision_run_ids,
            denominator,
        ),
        "recommendation_entities": recommendation_entities,
        "dominant_recommendation_outcome": dominant,
        "recommendation_reasons": _decision_stability_reasons(
            db,
            recommendation_events,
            current_answer_binding_shadow_run_id=_current_answer_binding_shadow_run_id_for_stability(
                db,
                project,
                prompt,
                package,
                valid_run_ids,
            ),
        ),
        "decision_stability_score": score,
        "stability_level": level,
        "stability_level_label": _decision_stability_level_label(level),
        "formula": "round(dominant_recommendation_outcome.run_count / valid_run_count * 100)",
        "thresholds": {
            "HIGH_STABILITY": "score >= 80",
            "MIXED": "50 <= score < 80",
            "HIGH_VOLATILITY": "score < 50",
        },
        "boundary_note": (
            "Decision Stability 只描述多 Run 推荐结果分布；不参与 Evidence、Benchmark、Gap、"
            "Strategy、Action、Experiment 或 Baseline 的任何 Gate。"
        ),
    }


def _decision_stability_recommendation_entities(events: list[RecommendationEvent], denominator: int) -> list[dict]:
    grouped: dict[str, dict] = {}
    for event in events:
        entity = (event.entity_text or "未知对象").strip() or "未知对象"
        key = _compact_key(entity) or entity
        row = grouped.setdefault(key, {
            "entity_text": entity,
            "recommendation_run_ids": set(),
            "recommendation_event_ids": [],
        })
        row["recommendation_run_ids"].add(event.run_id)
        row["recommendation_event_ids"].append(event.id)
    result = []
    for row in grouped.values():
        run_ids = sorted(row["recommendation_run_ids"])
        result.append({
            "entity_text": row["entity_text"],
            "recommendation_run_count": len(run_ids),
            "denominator": denominator,
            "value": _rate(len(run_ids), denominator),
            "observed_run_ids": run_ids,
            "recommendation_event_ids": sorted(set(row["recommendation_event_ids"])),
        })
    return sorted(result, key=lambda item: (-item["recommendation_run_count"], item["entity_text"]))


def _dominant_recommendation_outcome(
    recommendation_entities: list[dict],
    no_recommendation_run_ids: list[int],
    denominator: int,
) -> dict:
    if not denominator:
        return {
            "outcome_type": "NO_VALID_RUNS",
            "entity_text": "",
            "run_count": 0,
            "denominator": 0,
            "value": 0,
            "observed_run_ids": [],
            "is_tie": False,
            "co_dominant_entities": [],
        }
    if recommendation_entities:
        top_entity_count = max(entity["recommendation_run_count"] for entity in recommendation_entities)
        tied_entities = [
            entity for entity in recommendation_entities
            if entity["recommendation_run_count"] == top_entity_count
        ]
        no_recommendation_count = len(no_recommendation_run_ids)
        if len(tied_entities) > 1 and top_entity_count >= no_recommendation_count:
            observed_run_ids = sorted({
                run_id
                for entity in tied_entities
                for run_id in entity.get("observed_run_ids", [])
            })
            return {
                "outcome_type": "CO_DOMINANT_RECOMMENDATION_ENTITIES",
                "entity_text": "",
                "run_count": top_entity_count,
                "denominator": denominator,
                "value": _rate(top_entity_count, denominator),
                "observed_run_ids": observed_run_ids,
                "is_tie": True,
                "co_dominant_count": len(tied_entities),
                "co_dominant_entities": [
                    {
                        "entity_text": entity.get("entity_text"),
                        "recommendation_run_count": entity.get("recommendation_run_count"),
                        "denominator": entity.get("denominator"),
                        "value": entity.get("value"),
                        "observed_run_ids": entity.get("observed_run_ids", []),
                    }
                    for entity in tied_entities
                ],
            }
    candidates: list[dict] = []
    for entity in recommendation_entities:
        candidates.append({
            "outcome_type": "RECOMMENDATION_ENTITY",
            "entity_text": entity["entity_text"],
            "run_count": entity["recommendation_run_count"],
            "denominator": denominator,
            "value": entity["value"],
            "observed_run_ids": entity["observed_run_ids"],
            "is_tie": False,
            "co_dominant_entities": [],
        })
    candidates.append({
        "outcome_type": "NO_RECOMMENDATION",
        "entity_text": "",
        "run_count": len(no_recommendation_run_ids),
        "denominator": denominator,
        "value": _rate(len(no_recommendation_run_ids), denominator),
        "observed_run_ids": no_recommendation_run_ids,
        "is_tie": False,
        "co_dominant_entities": [],
    })
    return sorted(candidates, key=lambda item: (-item["run_count"], item["outcome_type"], item.get("entity_text") or ""))[0] if candidates else {
        "outcome_type": "NO_VALID_RUNS",
        "entity_text": "",
        "run_count": 0,
        "denominator": 0,
        "value": 0,
        "observed_run_ids": [],
        "is_tie": False,
        "co_dominant_entities": [],
    }


def _current_answer_binding_shadow_run_id_for_stability(
    db: Session,
    project: Project,
    prompt: Prompt,
    package: OptimizationEvidencePackage,
    valid_run_ids: list[int],
) -> int | None:
    """Return the current formal-input AnswerDecisionBinding batch if present.

    AnswerDecisionBinding keeps historical Shadow batches for audit. Decision
    Stability is read-only, but its reason coverage should describe the current
    formal V1.1 input batch when one exists, not every historical Shadow run.
    """
    if not valid_run_ids:
        return None
    alignments = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt.id,
        EvidenceAlignment.run_id.in_(valid_run_ids),
    ).all()
    shadow_run_ids: set[int] = set()
    for alignment in alignments:
        payload = loads(alignment.machine_payload_json, {})
        if (
            payload.get("reason_source") != ANSWER_BINDING_REASON_SOURCE
            and payload.get("formal_input_version") != FORMAL_V1_1_INPUT_VERSION
        ):
            continue
        shadow_run_id = _safe_optional_int(payload.get("shadow_run_id"))
        if shadow_run_id:
            shadow_run_ids.add(shadow_run_id)
    return max(shadow_run_ids) if shadow_run_ids else None


def _safe_optional_int(value: object) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed or None


def _decision_stability_reasons(
    db: Session,
    recommendation_events: list[RecommendationEvent],
    *,
    current_answer_binding_shadow_run_id: int | None = None,
) -> list[dict]:
    if not recommendation_events:
        return []
    event_by_id = {event.id: event for event in recommendation_events}
    event_run_denominators: dict[str, set[int]] = defaultdict(set)
    event_entities_by_run: dict[int, dict[str, str]] = defaultdict(dict)
    for event in recommendation_events:
        entity = (event.entity_text or "未知对象").strip() or "未知对象"
        entity_key = _compact_key(entity) or entity
        event_run_denominators[entity_key].add(event.run_id)
        event_entities_by_run[event.run_id][entity_key] = entity

    binding_query = db.query(AnswerDecisionBinding).filter(
        AnswerDecisionBinding.recommendation_event_id.in_(list(event_by_id)),
        AnswerDecisionBinding.decision_role.in_(DECISION_STABILITY_REASON_ROLES),
        AnswerDecisionBinding.review_status != "HUMAN_REJECTED",
    )
    if current_answer_binding_shadow_run_id:
        binding_query = binding_query.filter(
            AnswerDecisionBinding.shadow_run_id == current_answer_binding_shadow_run_id,
        )
    bindings = binding_query.all()
    unit_ids = [binding.answer_unit_id for binding in bindings if binding.answer_unit_id]
    units = db.query(AnswerUnit).filter(AnswerUnit.id.in_(unit_ids)).all() if unit_ids else []
    unit_by_id = {unit.id: unit for unit in units}
    grouped: dict[tuple[str, str], dict] = {}

    for binding in bindings:
        event = event_by_id.get(binding.recommendation_event_id)
        unit = unit_by_id.get(binding.answer_unit_id)
        if not event or not unit:
            continue
        semantic_type = (unit.semantic_type or "GENERAL_FACT").upper()
        reason_text = (unit.unit_text_normalized or unit.unit_text_original or "").strip()
        if not reason_text:
            continue
        if not _decision_stability_is_reason_like_unit(unit, reason_text):
            continue
        entity = _decision_stability_reason_entity(event, unit, reason_text, event_entities_by_run)
        role = (binding.decision_role or "SUPPORTING_REASON").upper()
        key = (_compact_key(entity) or entity, _compact_key(reason_text) or reason_text)
        row = grouped.setdefault(key, {
            "entity_text": entity,
            "reason_text": reason_text,
            "decision_role": role,
            "semantic_type": semantic_type,
            "reason_source": "ANSWER_DECISION_BINDING",
            "observed_run_ids": set(),
            "answer_unit_ids": set(),
            "decision_binding_ids": set(),
        })
        if row["decision_role"] != "DIRECT_REASON" and role == "DIRECT_REASON":
            row["decision_role"] = "DIRECT_REASON"
        row["observed_run_ids"].add(binding.run_id or unit.run_id or event.run_id)
        row["answer_unit_ids"].add(unit.id)
        row["decision_binding_ids"].add(binding.id)

    bound_event_ids = {binding.recommendation_event_id for binding in bindings}
    for event in recommendation_events:
        if event.id in bound_event_ids:
            continue
        entity = (event.entity_text or "未知对象").strip() or "未知对象"
        for raw_reason in loads(event.reasons_json, []):
            reason_text = (
                raw_reason.get("normalized_reason") or raw_reason.get("text") or raw_reason.get("reason")
                if isinstance(raw_reason, dict)
                else str(raw_reason)
            )
            reason_text = str(reason_text or "").strip()
            if not reason_text:
                continue
            key = (_compact_key(entity) or entity, _compact_key(reason_text) or reason_text)
            row = grouped.setdefault(key, {
                "entity_text": entity,
                "reason_text": reason_text,
                "decision_role": "RECOMMENDATION_EVENT_REASON",
                "semantic_type": "",
                "reason_source": "RECOMMENDATION_EVENT_REASONS_JSON",
                "observed_run_ids": set(),
                "answer_unit_ids": set(),
                "decision_binding_ids": set(),
            })
            row["observed_run_ids"].add(event.run_id)

    result = []
    for (entity_key, _), row in grouped.items():
        denominator = len(event_run_denominators.get(entity_key, set()))
        run_ids = sorted(row["observed_run_ids"])
        result.append({
            "entity_text": row["entity_text"],
            "reason_text": row["reason_text"],
            "decision_role": row["decision_role"],
            "semantic_type": row.get("semantic_type", ""),
            "reason_source": row["reason_source"],
            "reason_observed_run_count": len(run_ids),
            "denominator": denominator,
            "value": _rate(len(run_ids), denominator),
            "observed_run_ids": run_ids,
            "answer_unit_ids": sorted(row["answer_unit_ids"]),
            "decision_binding_ids": sorted(row["decision_binding_ids"]),
        })
    return sorted(result, key=lambda item: (-item["reason_observed_run_count"], item["entity_text"], item["reason_text"]))


def _decision_stability_reason_entity(
    event: RecommendationEvent,
    unit: AnswerUnit,
    reason_text: str,
    event_entities_by_run: dict[int, dict[str, str]],
) -> str:
    event_entity = (event.entity_text or "未知对象").strip() or "未知对象"
    same_run_entities = event_entities_by_run.get(event.run_id, {})

    unit_hint = (unit.entity_hint or "").strip()
    unit_hint_key = _compact_key(unit_hint) if unit_hint else ""
    if unit_hint_key and unit_hint_key in same_run_entities:
        return same_run_entities[unit_hint_key]

    reason_key = _compact_key(reason_text)
    for entity_key, entity_text in same_run_entities.items():
        if entity_key and entity_key in reason_key:
            return entity_text
    return event_entity


def _decision_stability_is_reason_like_unit(unit: AnswerUnit, reason_text: str) -> bool:
    semantic_type = (unit.semantic_type or "GENERAL_FACT").upper()
    if semantic_type not in DECISION_STABILITY_REASON_SEMANTIC_TYPES:
        return False
    text_key = _compact_key(reason_text)
    return not any(_compact_key(phrase) in text_key for phrase in DECISION_STABILITY_REASON_EXCLUDE_PHRASES)


def _decision_stability_metric(name: str, run_ids: list[int], denominator: int) -> dict:
    return {
        "metric_name": name,
        "numerator": len(set(run_ids)),
        "denominator": denominator,
        "value": _rate(len(set(run_ids)), denominator),
        "observed_run_ids": sorted(set(run_ids)),
    }


def _decision_stability_level(score: int, denominator: int) -> str:
    if denominator <= 0:
        return "NO_VALID_RUNS"
    if score >= 80:
        return "HIGH_STABILITY"
    if score >= 50:
        return "MIXED"
    return "HIGH_VOLATILITY"


def _decision_stability_level_label(level: str) -> str:
    return {
        "HIGH_STABILITY": "高稳定",
        "MIXED": "混合波动",
        "HIGH_VOLATILITY": "高波动",
        "NO_VALID_RUNS": "无有效样本",
    }.get(level, level)


def confirm_citation_decision_vertical_slice(
    db: Session,
    project_id: int,
    prompt_id: int,
    payload: dict,
) -> dict:
    reviewer = str(payload.get("reviewer") or "human")
    selected_keys = set(payload.get("action_keys") or [])
    proposal = citation_decision_vertical_slice(
        db,
        project_id,
        prompt_id,
        payload.get("evidence_package_id"),
        max_actions=int(payload.get("max_actions") or 5),
        use_answer_binding_v1_1=payload.get("use_answer_binding_v1_1"),
    )
    actions = proposal["recommended_actions"]
    if selected_keys:
        actions = [action for action in actions if action.get("action_key") in selected_keys]
    actions = [action for action in actions if action.get("route") in {"CONTENT", "EVIDENCE"}]
    if not actions:
        raise HTTPException(status_code=400, detail="没有可生成策略候选的 Content/Evidence Gap。Product/Unresolved 需要先人工补充 Product Truth 或资产信息。")

    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    package = db.get(OptimizationEvidencePackage, proposal["evidence_package_id"])
    if not project or not prompt or not package:
        raise HTTPException(status_code=404, detail="Project/Prompt/Evidence Package 不存在")

    _upsert_workflow_confirmation(
        db,
        project_id,
        prompt_id,
        "strategy_candidate",
        "PENDING_REVIEW",
        payload.get("review_note") or f"已生成 {len(actions)} 个待审核策略候选。",
        reviewer,
    )

    created = []
    for action in actions:
        strategy_payload = _strategy_payload_from_vertical_action(project, prompt, package, action, payload)
        strategy = _create_vertical_strategy_candidate(db, project, package, strategy_payload, reviewer)
        created.append({
            "action_key": action["action_key"],
            "strategy_candidate": strategy_candidate_to_read(strategy),
            "experiment_plan": None,
        })
    return {
        "status": "STRATEGY_CANDIDATES_CREATED",
        "version": VERTICAL_SLICE_VERSION,
        "project_id": project_id,
        "prompt_id": prompt_id,
        "evidence_package_id": package.id,
        "intervention_plan": None,
        "created": created,
        "boundary_note": "Step 7 只生成待审核 StrategyCandidate；人工审核形成 effective_payload 后才具有正式 Strategy 语义。本阶段不创建 Action/Experiment，不进入 Step 8。",
    }


def _resolve_vertical_slice_package(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None,
) -> OptimizationEvidencePackage:
    if evidence_package_id:
        package = db.get(OptimizationEvidencePackage, int(evidence_package_id))
        if not package or package.project_id != project_id or package.prompt_id != prompt_id:
            raise HTTPException(status_code=404, detail="指定的 Evidence Package 不属于当前 Project/Prompt")
        return package
    package = (
        db.query(OptimizationEvidencePackage)
        .filter(
            OptimizationEvidencePackage.project_id == project_id,
            OptimizationEvidencePackage.prompt_id == prompt_id,
            OptimizationEvidencePackage.status == "active",
        )
        .order_by(OptimizationEvidencePackage.created_at.desc(), OptimizationEvidencePackage.id.desc())
        .first()
    )
    if not package:
        raise HTTPException(status_code=400, detail="当前 Prompt 尚无 Evidence Package，不能生成纵向闭环 Proposal")
    return package


def _source_analysis_for_package(
    db: Session,
    project: Project,
    prompt: Prompt,
    package: OptimizationEvidencePackage,
    include_answer_binding_v1_1: bool = False,
) -> list[dict]:
    run_ids = loads(package.source_run_ids_json, [])
    runs = _runs_by_ids(db, run_ids, project.id)
    valid_run_ids = [run.id for run in runs if run.status in VALID_RUN_STATUSES]
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(valid_run_ids)).all() if valid_run_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(valid_run_ids)).all() if valid_run_ids else []
    return source_analysis(
        db,
        project,
        prompt,
        runs,
        references,
        retrievals,
        valid_run_ids=valid_run_ids,
        include_answer_binding_v1_1=include_answer_binding_v1_1,
    )


def _dedupe_channel_opportunities(rows: list[dict]) -> list[dict]:
    result: dict[str, dict] = {}
    for row in rows:
        opportunity = row.get("channel_opportunity")
        if not opportunity:
            continue
        key = opportunity.get("channel") or ""
        if key and key not in result:
            result[key] = opportunity
    return sorted(
        result.values(),
        key=lambda item: (0 if item.get("priority_level") == "PRIORITY_HIGH" else 1, item.get("channel_label") or ""),
    )


def _vertical_slice_summary(rows: list[dict], actions: list[dict], channels: list[dict]) -> dict:
    primary_count = sum(1 for row in rows if row.get("benchmark_tier") == "PRIMARY_BENCHMARK")
    secondary_count = sum(1 for row in rows if row.get("benchmark_tier") == "SECONDARY_BENCHMARK")
    benchmark_count = primary_count + secondary_count
    if benchmark_count == 0:
        boundary_note = "没有核心/辅助对标来源时允许 0 个推荐动作；不会用引用显著性或历史 RELATED 强行生成策略。"
    elif not actions:
        boundary_note = "已有核心/辅助对标来源，但 Product Truth、品牌资产或缺口判断未满足执行闸门，暂不生成推荐动作。"
    else:
        boundary_note = "推荐动作来自核心/辅助对标来源、具体 Product Truth 和缺口判断；仍需人工确认后才能进入实验草案。"
    return {
        "source_count": len(rows),
        "primary_benchmark_count": primary_count,
        "secondary_benchmark_count": secondary_count,
        "priority_high_count": sum(1 for row in rows if row.get("priority_level") == "PRIORITY_HIGH"),
        "priority_medium_count": sum(1 for row in rows if row.get("priority_level") == "PRIORITY_MEDIUM"),
        "recommended_action_count": len(actions),
        "channel_opportunity_count": len(channels),
        "boundary_note": boundary_note,
    }


def _experiment_proposal_for_action(
    action: dict,
    channels: list[dict],
    package: OptimizationEvidencePackage,
    prompt: Prompt,
) -> dict:
    benchmark = action.get("benchmark_source") or {}
    channel = _preferred_channel_for_action(action, channels)
    return {
        "action_key": action["action_key"],
        "experiment_mode": "PER_CHANNEL",
        "channel": channel.get("channel") if channel else benchmark.get("platform"),
        "channel_label": channel.get("channel_label") if channel else benchmark.get("platform_label", ""),
        "target_prompt_scope": [prompt.id],
        "benchmark_source": benchmark,
        "planned_change": action.get("planned_change", ""),
        "primary_metric": _target_metric_for_vertical_action(action),
        "secondary_metrics": ["brand_mention_rate", "brand_recommendation_rate", "official_reference_rate"],
        "release_gate": "人工确认真实发布后才能进入 cooling；当前只生成实验草案。",
        "retest_gate": "复测默认排队，不自动启动浏览器采集。",
        "human_conclusion_required": True,
        "evidence_package_id": package.id,
    }


def _vertical_resampling_plan(prompt: Prompt, package: OptimizationEvidencePackage) -> dict:
    return {
        "target_prompt_scope": [prompt.id],
        "baseline_run_ids": loads(package.source_run_ids_json, []),
        "default_sample_count": 3,
        "collection_mode": "single_independent",
        "execute_now_default": False,
        "note": "固定复测只排队；人工完成发布和冷却期后再执行/挂载 validation runs。",
    }


def _vertical_outcome_plan() -> dict:
    return {
        "dimensions": [
            "candidate_before_after",
            "recommendation_before_after",
            "target_reason_before_after",
            "citation_before_after",
        ],
        "human_conclusion_enum": list(sorted(CONCLUSION_TYPES)),
        "causality_boundary": "Outcome 只记录前后观察变化；最终有效性必须人工确认，不自动声称因果。",
    }


def _upsert_workflow_confirmation(
    db: Session,
    project_id: int,
    prompt_id: int,
    step_key: str,
    decision_status: str,
    note: str,
    reviewer: str,
) -> WorkflowConfirmation:
    row = db.query(WorkflowConfirmation).filter(
        WorkflowConfirmation.project_id == project_id,
        WorkflowConfirmation.prompt_id == prompt_id,
        WorkflowConfirmation.step_key == step_key,
    ).first()
    if row is None:
        row = WorkflowConfirmation(project_id=project_id, prompt_id=prompt_id, step_key=step_key)
        db.add(row)
    row.decision_status = decision_status
    row.decision_note = note
    row.reviewer = reviewer
    row.reviewed_at = datetime.utcnow()
    db.flush()
    return row


def _get_or_create_vertical_intervention_plan(
    db: Session,
    project: Project,
    prompt: Prompt,
    actions: list[dict],
    reviewer: str,
):
    from app.models import InterventionPlan

    plan = (
        db.query(InterventionPlan)
        .filter(InterventionPlan.project_id == project.id, InterventionPlan.prompt_id == prompt.id)
        .order_by(InterventionPlan.id.desc())
        .first()
    )
    reason_ids = sorted({
        str(alignment_id)
        for action in actions
        for alignment_id in (action.get("benchmark_source") or {}).get("supporting_alignment_ids", [])
    })
    if plan is None:
        plan = InterventionPlan(project_id=project.id, prompt_id=prompt.id, created_by=reviewer)
        db.add(plan)
    plan.title = f"Prompt #{prompt.id} · Citation Optimization Decision V1"
    plan.objective = f"基于核心/辅助对标来源为「{project.brand_name}」生成可审核干预计划。"
    plan.reason_ids_json = dumps(reason_ids)
    plan.intervention_goal = "CITATION_DECISION_VERTICAL_SLICE"
    plan.status = "APPROVED"
    plan.approved_by = reviewer
    plan.approved_at = datetime.utcnow()
    db.flush()
    return plan


def _create_vertical_strategy_candidate(
    db: Session,
    project: Project,
    package: OptimizationEvidencePackage,
    payload: dict,
    reviewer: str,
) -> OptimizationStrategyCandidate:
    evidence_result = validate_strategy_evidence(package, None, payload)
    hypothesis_result = validate_strategy_hypothesis(payload, evidence_result)
    validators_ready = evidence_result["status"] == "VALIDATED" and hypothesis_result["status"] == "VALIDATED"
    candidate = OptimizationStrategyCandidate(
        project_id=project.id,
        experiment_id=None,
        evidence_package_id=package.id,
        target_url=payload.get("target_url") or "",
        provider="LOCAL_RULE",
        model="citation-optimization-decision-v1",
        prompt_version=VERTICAL_SLICE_VERSION,
        prompt_text="",
        generated_at=datetime.utcnow(),
        generation_status="GENERATED",
        intervention_type=payload.get("intervention_type"),
        target_platform=payload.get("target_platform"),
        target_asset=payload.get("target_asset"),
        target_content_type=payload.get("target_content_type"),
        expected_primary_metric=payload.get("target_metric"),
        source_package_id=package.id,
        original_llm_payload_json=dumps(payload),
        structured_payload_json=dumps(payload),
        human_edited_payload_json=dumps({}),
        effective_payload_json=dumps({}),
        effective_payload_version="",
        effective_validation_status="PENDING" if validators_ready else "VALIDATION_FAILED",
        evidence_validation_status=evidence_result["status"],
        evidence_validation_errors_json=dumps(evidence_result["errors"]),
        evidence_validation_warnings_json=dumps(evidence_result["warnings"]),
        evidence_validated_at=evidence_result["validated_at"],
        evidence_validator_version=EVIDENCE_VALIDATOR_VERSION,
        hypothesis_validation_status=hypothesis_result["status"],
        hypothesis_validation_errors_json=dumps(hypothesis_result["errors"]),
        hypothesis_validation_warnings_json=dumps(hypothesis_result["warnings"]),
        hypothesis_validated_at=hypothesis_result["validated_at"],
        hypothesis_validator_version=HYPOTHESIS_VALIDATOR_VERSION,
        review_status="PENDING_REVIEW" if validators_ready else "VALIDATION_FAILED",
        reviewed_by="",
        reviewed_at=None,
        review_note="机器生成待审核策略候选；未人工确认前不得进入 Action/Experiment。" if validators_ready else "校验失败，未进入策略审核",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def _strategy_fields_from_vertical_action(
    project: Project,
    prompt: Prompt,
    action: dict,
    gap_items: list[dict],
    evidence_run_ids: list[int],
) -> dict:
    priority_capabilities = _strategy_priority_capabilities(gap_items, action)
    planned_channels = _strategy_planned_channels(project, action, gap_items)
    channel_roles = _strategy_channel_roles(planned_channels)
    intervention_mechanism = _strategy_intervention_mechanism(project, prompt, action, priority_capabilities, evidence_run_ids)
    primary_path = _strategy_primary_intervention_path(action, planned_channels)
    asset_direction = _strategy_asset_direction(action, gap_items, planned_channels)
    execution_sequence = _strategy_execution_sequence(action, planned_channels, asset_direction)
    attribution_intent = _strategy_attribution_intent(project, prompt, action, priority_capabilities, primary_path, evidence_run_ids)
    return {
        "target_decision_change": _strategy_target_decision_change(project, prompt, priority_capabilities, evidence_run_ids),
        "strategic_hypothesis": _strategy_hypothesis(project, prompt, action, priority_capabilities, evidence_run_ids),
        "intervention_mechanism": intervention_mechanism,
        "primary_intervention_path": primary_path,
        "planned_channels": planned_channels,
        "channel_roles": channel_roles,
        "asset_direction": asset_direction,
        "execution_sequence": execution_sequence,
        "attribution_intent": attribution_intent,
        "priority_capabilities": priority_capabilities,
        "required_signals": _strategy_required_signals(project, priority_capabilities),
        "non_goals": _strategy_non_goals(action),
        "strategy_boundary_note": (
            "第 7 步确认策略核心和计划平台层；具体账号、URL、页面、标题、段落、内容结构、发布和 Baseline 都在第 8 步人工确定。"
        ),
    }


def _strategy_planned_channels(project: Project, action: dict, gap_items: list[dict]) -> list[dict]:
    route = (action.get("route") or "").upper()
    benchmark = action.get("benchmark_source") or {}
    benchmark_platform = str(benchmark.get("platform") or "").strip().lower()
    channels: list[dict] = []
    if route in {"CONTENT", "EVIDENCE"}:
        first_party_channel = "PRODUCT_DOCS" if any(_relevant_asset_is_docs(item) for item in gap_items) else "OFFICIAL_SITE"
        channels.append({
            "channel": first_party_channel,
            "channel_label": "产品文档" if first_party_channel == "PRODUCT_DOCS" else "官网",
            "intervention_priority": "PRIMARY",
            "channel_role": "承载目标品牌自己的能力事实表达和可摘录证据，先修正品牌资产而不是追随对标来源平台。",
            "selection_basis": "由 Product Truth、相关品牌资产表达缺口、检索/引用状态共同确定；不是由 Benchmark 平台直接推出。",
        })
    if route == "EVIDENCE":
        channels.append({
            "channel": "THIRD_PARTY_MEDIA",
            "channel_label": "第三方媒体",
            "intervention_priority": "SECONDARY",
            "channel_role": "在一方资产表达完成后补充可引用的外部证明、案例或场景证据。",
            "selection_basis": "当前 Gap 需要更强证明信号，但具体平台和账号仍需 Step 8 人工确认。",
        })
    if benchmark_platform in {"zhihu", "baijiahao"}:
        channel = "ZHIHU" if benchmark_platform == "zhihu" else "BAIJIAHAO"
        if not any(item.get("channel") == channel for item in channels):
            channels.append({
                "channel": channel,
                "channel_label": "知乎" if channel == "ZHIHU" else "百家号",
                "intervention_priority": "OBSERVE",
                "channel_role": "仅作为本轮对标证据来源和后续可选验证场景，不自动成为执行渠道。",
                "selection_basis": "Benchmark 来源平台只说明 AI 当前引用过该平台；是否在该平台执行属于 Step 8 人工判断。",
            })
    if not channels:
        channels.append({
            "channel": "OTHER",
            "channel_label": "待人工确认渠道",
            "intervention_priority": "PRIMARY",
            "channel_role": "当前 Strategy 只确认干预机制，执行渠道需 Step 8 人工补齐。",
            "selection_basis": "缺口类型尚不能稳定映射到一方或第三方资产。",
        })
    return channels


def _relevant_asset_is_docs(gap_item: dict) -> bool:
    asset = gap_item.get("relevant_asset_snapshot") or {}
    if not isinstance(asset, dict):
        return False
    text = " ".join(str(asset.get(key) or "") for key in ("asset_type", "title", "canonical_url", "url"))
    return any(token in text.lower() for token in ("doc", "docs", "文档", "帮助", "guide"))


def _strategy_channel_roles(planned_channels: list[dict]) -> dict:
    return {
        item.get("channel"): {
            "channel_label": item.get("channel_label"),
            "intervention_priority": item.get("intervention_priority"),
            "channel_role": item.get("channel_role"),
            "selection_basis": item.get("selection_basis"),
        }
        for item in planned_channels
        if isinstance(item, dict) and item.get("channel")
    }


def _strategy_intervention_mechanism(
    project: Project,
    prompt: Prompt,
    action: dict,
    priority_capabilities: list[dict],
    evidence_run_ids: list[int],
) -> str:
    brand = project.brand_name or "目标品牌"
    labels = [item.get("capability_label") for item in priority_capabilities if item.get("capability_label")]
    label_text = "、".join(labels[:4]) if labels else "目标能力"
    gap_label = action.get("gap_label") or _source_gap_label(str(action.get("gap_type") or ""))
    return (
        f"把「{brand}」已确认支持的「{label_text}」沉淀为可被 AI 摘录的一方品牌事实信号；"
        f"针对当前 {gap_label}，先让相关资产明确表达品牌-能力-场景关系，再用固定 Run 复测观察"
        f"目标品牌是否进入候选/推荐理由。本机制基于 {len(set(evidence_run_ids))} 个有效 Run 的能力级证据链，不复制竞品事实。"
    )


def _strategy_primary_intervention_path(action: dict, planned_channels: list[dict]) -> str:
    route = (action.get("route") or "").upper()
    primary = next((item for item in planned_channels if item.get("intervention_priority") == "PRIMARY"), planned_channels[0] if planned_channels else {})
    channel = primary.get("channel", "OTHER")
    if route == "CONTENT":
        return f"FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION:{channel}"
    if route == "EVIDENCE":
        return f"FIRST_PARTY_EVIDENCE_STRENGTHENING:{channel}"
    if route == "PRODUCT":
        return "PRODUCT_TRUTH_OR_ROADMAP_REVIEW"
    return f"MANUAL_STRATEGY_REVIEW:{channel}"


def _strategy_asset_direction(action: dict, gap_items: list[dict], planned_channels: list[dict]) -> dict:
    snapshots = [item.get("relevant_asset_snapshot") for item in gap_items if isinstance(item.get("relevant_asset_snapshot"), dict)]
    primary_channel = next((item.get("channel") for item in planned_channels if item.get("intervention_priority") == "PRIMARY"), None)
    operation = "UPDATE_EXISTING" if snapshots else "CREATE_NEW"
    first_snapshot = snapshots[0] if snapshots else {}
    return {
        "asset_operation": operation,
        "channel": primary_channel or "OTHER",
        "asset_type": (first_snapshot.get("asset_type") or "ARTICLE"),
        "target_object": "CONTENT_ASSET",
        "existing_asset_refs": snapshots,
        "new_asset_policy": "只有现有相关品牌资产不足以稳定承载该能力事实时，Step 8 才能创建 NEW_ASSET proposal。",
        "boundary": "本字段只描述资产方向；具体 URL、账号、标题、section 和内容结构属于 Step 8。",
    }


def _strategy_execution_sequence(action: dict, planned_channels: list[dict], asset_direction: dict) -> list[dict]:
    primary = next((item for item in planned_channels if item.get("intervention_priority") == "PRIMARY"), planned_channels[0] if planned_channels else {})
    rows = [
        {
            "step": 1,
            "name": "确认执行资产",
            "owner": "human",
            "description": f"在第 8 步为计划平台「{primary.get('channel_label') or primary.get('channel') or '待确认'}」选择具体资产或 NEW_ASSET proposal。",
        },
        {
            "step": 2,
            "name": "落实能力事实表达",
            "owner": "human",
            "description": "围绕优先能力补齐目标品牌自己的能力说明、适用场景和可验证证据，不复制竞品页面。",
        },
        {
            "step": 3,
            "name": "锁定 Baseline 并进入发布 Gate",
            "owner": "system+human",
            "description": "创建 Action/Experiment 草案并冻结 Strategy、Gap、Asset、Baseline 快照；真实发布仍需 Release Audit。",
        },
    ]
    if asset_direction.get("asset_operation") == "CREATE_NEW":
        rows[0]["description"] += " 当前更倾向新建资产，但具体位置仍需人工确认。"
    return rows


def _strategy_attribution_intent(
    project: Project,
    prompt: Prompt,
    action: dict,
    priority_capabilities: list[dict],
    primary_path: str,
    evidence_run_ids: list[int],
) -> dict:
    labels = [item.get("capability_label") for item in priority_capabilities if item.get("capability_label")]
    primary = labels[0] if labels else action.get("summary") or "目标能力"
    return {
        "primary_capability": primary,
        "secondary_capabilities": labels[1:],
        "attribution_scope": "CAPABILITY_BUNDLE" if len(labels) > 1 else "SINGLE_CAPABILITY",
        "tested_strategy_path": primary_path,
        "observed_run_ids": sorted(set(evidence_run_ids)),
        "validation_hypothesis": (
            f"如果第 8 步执行严格围绕「{primary}」及同组能力，不同时混改 Prompt、产品能力或外部渠道，"
            f"则后续固定复采中可把目标品牌候选/推荐理由变化归因到本策略机制的可能性更高。"
        ),
        "non_attribution_boundary": "该归因只服务实验解释，不自动宣称因果有效；最终仍需发布、复采和人工结论。",
    }


def _strategy_priority_capabilities(gap_items: list[dict], action: dict) -> list[dict]:
    if not gap_items:
        label = str(action.get("title") or action.get("summary") or "待确认能力").strip()
        return [{
            "capability_label": label,
            "priority_band": "P1",
            "priority_basis": "当前推荐动作只有一个能力方向，需在人工确认时核对其 Product Truth 和证据链。",
            "reason_run_coverage": "0/0",
            "observed_run_ids": [],
            "benchmark_tier": action.get("benchmark_source", {}).get("benchmark_tier") or "",
            "benchmark_evidence_count": 0,
            "product_truth_status": action.get("product_truth_status", "UNKNOWN"),
            "gap_type": action.get("gap_type"),
            "gap_layer": "",
        }]

    counts = [len(set(item.get("observed_run_ids") or [])) for item in gap_items]
    max_count = max(counts) if counts else 0
    result = []
    for item, count in zip(gap_items, counts):
        evidence_count = len(set(item.get("benchmark_evidence_ids") or []))
        band = "P1" if count == max_count else "P2"
        tier = item.get("benchmark_tier") or (item.get("benchmark_source") or {}).get("benchmark_tier") or ""
        truth = item.get("product_truth_status") or action.get("product_truth_status") or "UNKNOWN"
        gap_type = item.get("gap_type") or action.get("gap_type")
        result.append({
            "gap_item_id": item.get("gap_item_id"),
            "capability_label": item.get("capability_label") or "待确认能力",
            "priority_band": band,
            "priority_basis": _strategy_priority_basis(item, count, max_count, evidence_count),
            "reason_run_coverage": f"{count}/{max_count}" if max_count else f"{count}/0",
            "observed_run_ids": sorted({int(run_id) for run_id in item.get("observed_run_ids", []) if run_id}),
            "run_coverage_count": count,
            "benchmark_tier": tier,
            "decision_support_level": item.get("decision_support_level"),
            "benchmark_evidence_ids": item.get("benchmark_evidence_ids", []),
            "benchmark_evidence_count": evidence_count,
            "product_truth_ids": item.get("product_truth_ids", []),
            "product_truth_status": truth,
            "gap_type": gap_type,
            "gap_label": item.get("gap_label") or _source_gap_label(str(gap_type or "")),
            "gap_layer": item.get("gap_layer") or "",
        })
    return result


def _benchmark_tier_label(value: str) -> str:
    return {
        "PRIMARY_BENCHMARK": "核心对标",
        "SECONDARY_BENCHMARK": "辅助对标",
        "REFERENCE_ONLY": "仅引用参考",
        "NOT_EVALUABLE": "不可评估",
    }.get(value or "", value or "未判定对标")


def _strategy_priority_basis(item: dict, count: int, max_count: int, evidence_count: int) -> str:
    label = item.get("capability_label") or "该能力"
    tier = _benchmark_tier_label(item.get("benchmark_tier") or (item.get("benchmark_source") or {}).get("benchmark_tier") or "")
    gap_label = item.get("gap_label") or _source_gap_label(str(item.get("gap_type") or ""))
    parts = [
        f"「{label}」来自 {tier}",
        f"覆盖 {count} 个有效 Run",
        f"对应 {evidence_count} 条合格证据对齐",
        f"当前缺口为 {gap_label}",
    ]
    if max_count and count == max_count:
        parts.append("在本轮能力中属于最高覆盖，可与同覆盖能力并列 P1")
    else:
        parts.append("覆盖低于本轮最高能力，列为 P2 观察")
    return "；".join(parts)


def _strategy_target_decision_change(
    project: Project,
    prompt: Prompt,
    priority_capabilities: list[dict],
    evidence_run_ids: list[int],
) -> str:
    brand = project.brand_name or "目标品牌"
    prompt_text = prompt.prompt_text or prompt.title or f"Prompt #{prompt.id}"
    labels = [item.get("capability_label") for item in priority_capabilities if item.get("capability_label")]
    capability_text = "、".join(labels[:3]) if labels else "当前已确认能力"
    return (
        f"让「{brand}」在「{prompt_text}」这类 AI 回答中，围绕「{capability_text}」"
        f"建立更明确的品牌-能力-推荐理由关联；本轮观察覆盖 {len(set(evidence_run_ids))} 个有效 Run。"
    )


def _strategy_hypothesis(
    project: Project,
    prompt: Prompt,
    action: dict,
    priority_capabilities: list[dict],
    evidence_run_ids: list[int],
) -> str:
    brand = project.brand_name or "目标品牌"
    route_label = _action_route_label((action.get("route") or "").upper())
    gap_label = action.get("gap_label") or _source_gap_label(str(action.get("gap_type") or ""))
    labels = [item.get("capability_label") for item in priority_capabilities if item.get("capability_label")]
    label_text = "、".join(labels[:4]) if labels else "当前能力"
    return (
        f"AI 已在 {len(set(evidence_run_ids))} 个有效 Run 中把竞品能力作为推荐说明或辅助理由；"
        f"如果「{brand}」的 Product Truth 已支持「{label_text}」，但相关品牌资产表达不足，"
        f"则优先补齐这些能力与品牌实体的可摘录事实信号，有机会把当前 {gap_label} "
        f"转化为后续回答中的候选/推荐理由识别。建议方向为「{route_label}」，"
        f"第 7 步只确认计划平台层和策略机制，具体账号、URL、资产、标题和段落仍待第 8 步确认。"
    )


def _strategy_required_signals(project: Project, priority_capabilities: list[dict]) -> list[dict]:
    brand = project.brand_name or "目标品牌"
    signals = []
    for item in priority_capabilities:
        label = item.get("capability_label") or "待确认能力"
        signals.append({
            "capability_label": label,
            "signal": f"回答或引用资料能够明确表达「{brand} 支持 {label}」",
            "evidence_requirement": (
                "必须是目标品牌自己的真实能力表达，并能被页面正文或引用来源摘录；不能复制竞品事实作为目标品牌事实。"
            ),
            "observed_run_ids": item.get("observed_run_ids", []),
            "product_truth_status": item.get("product_truth_status", "UNKNOWN"),
        })
    return signals


def _strategy_non_goals(action: dict) -> list[str]:
    benchmark = action.get("benchmark_source") or {}
    platform_label = benchmark.get("platform_label") or benchmark.get("platform") or "对标来源平台"
    return [
        "不在第 7 步选择具体账号、具体 URL、具体页面、具体标题、具体 section 或 Draft。",
        f"不因为核心对标来源来自「{platform_label}」就默认去该平台发布。",
        "不把竞品页面里的能力描述自动当作目标品牌 Product Truth。",
        "不新增或承诺目标品牌尚未支持的产品功能。",
        "不把价格、品牌定位或其他未进入本轮证据链的变量混入本次策略。",
    ]


def _strategy_payload_from_vertical_action(
    project: Project,
    prompt: Prompt,
    package: OptimizationEvidencePackage,
    action: dict,
    confirm_payload: dict,
) -> dict:
    benchmark = action.get("benchmark_source") or {}
    channel = str(confirm_payload.get("target_platform") or "").lower()
    intervention_type = str(confirm_payload.get("intervention_type") or "UNRESOLVED")
    target_content_type = str(confirm_payload.get("target_content_type") or "UNRESOLVED")
    target_metric = _target_metric_for_vertical_action(action)
    baseline_value = _baseline_value_for_metric(package, target_metric)
    product_truth_status = action.get("product_truth_status") or "UNKNOWN"
    gate_status = "READY_FOR_STRATEGY_REVIEW" if product_truth_status == "TRUE" else "NEEDS_HUMAN_CONFIRMATION"
    gap_items = action.get("gap_items") or []
    gap_item_ids = [item.get("gap_item_id") for item in gap_items if item.get("gap_item_id")]
    capability_labels = _capability_label_for_strategy_items(gap_items)
    evidence_run_ids = sorted({
        int(run_id)
        for item in gap_items
        for run_id in item.get("observed_run_ids", [])
        if run_id
    }) or loads(package.source_run_ids_json, [])
    benchmark_evidence_ids = sorted({
        int(alignment_id)
        for item in gap_items
        for alignment_id in item.get("benchmark_evidence_ids", [])
        if alignment_id
    })
    strategy_fields = _strategy_fields_from_vertical_action(project, prompt, action, gap_items, evidence_run_ids)
    mechanism = strategy_fields.get("intervention_mechanism") or (
        "如果目标品牌已真实具备这些能力，但当前相关资产没有形成可被引用和摘录的能力表达，"
        "则补齐能力说明、适用场景和证据表达，可能提高后续 AI 回答中目标品牌进入候选/推荐理由的机会。"
    )
    return {
        "strategy_phase": "PHASE_3_STRATEGY_CANDIDATE",
        **strategy_fields,
        "prompt_id": prompt.id,
        "gap_item_ids": gap_item_ids,
        "target_capability_or_reason": capability_labels,
        "target_capabilities": [
            {
                "gap_item_id": item.get("gap_item_id"),
                "capability_label": item.get("capability_label"),
                "gap_type": item.get("gap_type"),
                "gap_layer": item.get("gap_layer"),
                "observed_run_ids": item.get("observed_run_ids", []),
                "benchmark_evidence_ids": item.get("benchmark_evidence_ids", []),
            }
            for item in gap_items
        ],
        "observed_problem": f"Prompt #{prompt.id} 的对标来源显示 {action.get('gap_label') or action.get('gap_type')}。",
        "hypothesized_cause": (
            f"可能因为当前品牌资产未充分覆盖对标来源中影响推荐选择的证据：{action.get('summary', '')}"
        ),
        "core_mechanism": mechanism,
        "mechanism": mechanism,
        "why_candidate": (
            "该候选只来自已完成的 capability-level Gap、Phase 2A eligible Benchmark Evidence、"
            "Product Truth 和冻结的 Relevant Asset Snapshot；Step 7 不重新执行 Citation/Evidence/Gap 推理。"
        ),
        "intervention_type": intervention_type,
        "target_platform": channel.upper() if channel else "UNRESOLVED",
        "target_object": confirm_payload.get("target_object") or "UNRESOLVED",
        "target_asset": confirm_payload.get("target_asset") or "UNRESOLVED",
        "target_content_type": target_content_type,
        "target_url": confirm_payload.get("target_url") or "",
        "target_metric": target_metric,
        "validation_metric": target_metric,
        "baseline_value": baseline_value,
        "proposed_direction": action.get("route"),
        "recommended_action": action.get("summary") or "",
        "recommended_action_boundary": "这不是具体发布任务；第 7 步可确认计划平台层和渠道角色，具体账号、URL、资产、标题和内容结构属于 Step 8。",
        "changed_features": _changed_features_for_vertical_action(action),
        "controlled_variables": ["collection_prompt", "wenxin_entry", "account_profile", "product_capabilities", "single_channel_scope"],
        "recommended_outline": action.get("content_requirements", []),
        "required_sections": action.get("content_requirements", []),
        "evidence_run_ids": evidence_run_ids,
        "evidence_citation_ids": [],
        "benchmark_evidence_ids": benchmark_evidence_ids,
        "evidence_summary": {
            "benchmark_source": benchmark,
            "priority_level": action.get("priority_level"),
            "gap_type": action.get("gap_type"),
            "gap_items": gap_items,
            "decision_support_level": action.get("decision_support_level"),
        },
        "product_truth_refs": {
            "status": product_truth_status,
            "ids": action.get("product_truth_ids", []),
        },
        "relevant_asset_refs": [
            item.get("relevant_asset_snapshot") for item in gap_items if item.get("relevant_asset_snapshot")
        ],
        "observed_run_ids": evidence_run_ids,
        "run_coverage_count": len(evidence_run_ids),
        "blockers": [
            "待人工确认 Strategy 机制和范围",
            "Step 8 前不得选择具体账号、URL、资产、标题、section 或创建执行任务",
            "target_platform / target_asset / target_content_type 仍为 UNRESOLVED 时不得物化 Action/Experiment",
        ],
        "expected_direction": "increase",
        "priority": action.get("priority_level", "PRIORITY_MEDIUM"),
        "validation_plan": {
            "entry_observed_condition": "人工确认发布后，按同 Prompt/模型/账号/独立会话固定复采。",
            "sustained_improvement_condition": "validation runs 中目标品牌候选、推荐理由或引用上下文出现正向变化。",
            "minimum_sample_count": 3,
        },
        "invalidating_result": "复采后候选、推荐理由和引用上下文均无改善，或发布内容未真实上线/不符合平台规则。",
        "product_truth_gate": {
            "status": gate_status,
            "matched_product_truth_ids": action.get("product_truth_ids", []),
            "matched_product_truth_status": product_truth_status,
        },
        "effective_payload_snapshot_policy": "未来 Experiment 必须绑定创建时已确认的 effective_payload 快照，不得读取候选后续修改作为历史依据。",
        "source_action_key": action.get("action_key"),
        "benchmark_channel_boundary": "Benchmark 来源平台不能自动成为 Strategy 执行平台；平台和资产选择属于 Step 8。",
        "channel_opportunity": None,
    }


def _intervention_type_for_vertical_action(action: dict, channel: str) -> str:
    if action.get("route") == "PRODUCT":
        return "UNRESOLVED"
    if channel in {"bilibili", "douyin", "xiaohongshu"}:
        return "VIDEO_CONTENT"
    if channel == "zhihu":
        return "EXTERNAL_PLATFORM_QA"
    if channel and channel not in {"web", "owned", "unknown"}:
        return "EXTERNAL_PLATFORM_ARTICLE"
    return "UNRESOLVED"


def _target_content_type_for_vertical_payload(action: dict, channel: str) -> str:
    if channel in {"bilibili", "douyin", "xiaohongshu"}:
        return "VIDEO"
    if channel == "zhihu":
        return "Q_AND_A"
    if channel and channel not in {"web", "owned", "unknown"}:
        return "ARTICLE"
    values = action.get("content_requirements", [])
    return "ARTICLE" if values else "UNRESOLVED"


def _target_metric_for_vertical_action(action: dict) -> str:
    if action.get("route") == "PRODUCT":
        return "brand_recommendation_rate"
    return "brand_mention_rate"


def _baseline_value_for_metric(package: OptimizationEvidencePackage, metric_name: str) -> str:
    payload = loads(package.package_payload_json, {})
    metric = next((row for row in payload.get("metrics", []) if row.get("metric_name") == metric_name), None)
    if not metric:
        return ""
    numerator = metric.get("numerator")
    denominator = metric.get("denominator")
    value = metric.get("value")
    if numerator is not None and denominator is not None:
        return f"{numerator}/{denominator}" if value is None else f"{numerator}/{denominator} = {value}"
    return str(value if value is not None else "")


def _changed_features_for_vertical_action(action: dict) -> list[dict]:
    route = action.get("route")
    if route == "CONTENT":
        return [
            {"feature": "DIRECT_ANSWER_BLOCK", "before": False, "after": True, "description": action.get("summary", ""), "location": "正文顶部"},
            {"feature": "SCENARIO_AND_LIMITS", "before": False, "after": True, "description": "补充适用场景、限制条件和 FAQ。", "location": "正文主体"},
        ]
    if route == "EVIDENCE":
        return [
            {"feature": "EVIDENCE_PROOF_BLOCK", "before": False, "after": True, "description": action.get("summary", ""), "location": "证据/案例区"},
            {"feature": "VERIFIABLE_CASE_OR_DATA", "before": False, "after": True, "description": "补充案例、数据、证明或具体场景。", "location": "正文主体"},
        ]
    return [
        {"feature": "PRODUCT_TRUTH_REVIEW", "before": "NOT_SUPPORTED_OR_UNKNOWN", "after": "HUMAN_REVIEWED", "description": action.get("summary", ""), "location": "Product Truth"},
    ]


def _preferred_channel_for_action(action: dict, channels: list[dict]) -> dict | None:
    platform = ((action.get("benchmark_source") or {}).get("platform") or "").lower()
    return next((channel for channel in channels if (channel.get("channel") or "").lower() == platform), None)


def _attach_vertical_plan_to_experiment(experiment: OptimizationExperiment, plan_id: int, action: dict) -> None:
    benchmark = action.get("benchmark_source") or {}
    experiment.intervention_plan_id = plan_id
    experiment.channel = (benchmark.get("platform") or "").upper()
    experiment.experiment_mode = "PER_CHANNEL"
    experiment.primary_benchmark_source_id = benchmark.get("source_document_id")
    experiment.benchmark_source_ids_json = dumps([benchmark.get("source_document_id")] if benchmark.get("source_document_id") else [])
    experiment.target_reason_ids_json = dumps(benchmark.get("supporting_alignment_ids", []))
    experiment.target_gap_ids_json = dumps([action.get("gap_type")])
    experiment.hypothesis_text = experiment.hypothesis or action.get("summary", "")
    experiment.brief_json = dumps({
        "recommended_action": action,
        "benchmark_source": benchmark,
        "content_requirements": action.get("content_requirements", []),
    })
    experiment.target_asset_type = _target_content_type_for_vertical_payload(action, (benchmark.get("platform") or "").lower())


def metrics_for_runs(db: Session, runs: list[BrowserMonitorRun], target_url: str = "") -> dict:
    valid_runs = [run for run in runs if run.status in VALID_RUN_STATUSES]
    run_ids = [run.id for run in valid_runs]
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all() if run_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all() if run_ids else []
    eligibility = _run_metric_eligibility(valid_runs, references, retrievals)
    answer_runs = [run for run in valid_runs if run.id in set(eligibility["answer_eligible_run_ids"])]
    citation_runs = [run for run in valid_runs if run.id in set(eligibility["citation_eligible_run_ids"])]
    retrieval_runs = [run for run in valid_runs if run.id in set(eligibility["retrieval_eligible_run_ids"])]
    citation_run_ids = {run.id for run in citation_runs}
    retrieval_run_ids = {run.id for run in retrieval_runs}
    eligible_references = [ref for ref in references if ref.run_id in citation_run_ids]
    eligible_retrievals = [item for item in retrievals if item.run_id in retrieval_run_ids]
    official_run_ids = {ref.run_id for ref in eligible_references if ref.is_official_domain}
    reference_count_by_run = Counter(ref.run_id for ref in eligible_references)
    valid_count = len(valid_runs)
    answer_count = len(answer_runs)
    citation_count = len(citation_runs)
    retrieval_count = len(retrieval_runs)
    target_retrieval = _target_page_retrieval(retrieval_runs, eligible_retrievals, target_url, eligibility=eligibility)
    target_conversion = _target_page_conversion(retrieval_runs, eligible_references, eligible_retrievals, target_url, eligibility=eligibility)
    return {
        "sample_count": len(runs),
        "valid_sample_count": valid_count,
        "valid_run_count": valid_count,
        "run_metric_eligibility": eligibility,
        "answer_eligible_run_count": answer_count,
        "citation_eligible_run_count": citation_count,
        "retrieval_eligible_run_count": retrieval_count,
        "brand_mention_count": sum(1 for run in answer_runs if run.brand_mentioned),
        "brand_mention_rate": _rate(sum(1 for run in answer_runs if run.brand_mentioned), answer_count),
        "brand_recommendation_count": sum(1 for run in answer_runs if int(run.brand_recommendation_level or 0) >= 2),
        "brand_recommendation_rate": _rate(sum(1 for run in answer_runs if int(run.brand_recommendation_level or 0) >= 2), answer_count),
        "official_reference_count": len(official_run_ids),
        "official_reference_rate": _rate(len(official_run_ids), citation_count),
        "avg_reference_count": round(sum(reference_count_by_run.values()) / citation_count, 4) if citation_count else 0,
        "reference_complete_count": sum(1 for run in citation_runs if run.reference_complete),
        "reference_complete_rate": _rate(sum(1 for run in citation_runs if run.reference_complete), citation_count),
        "target_page_retrieved_run_count": target_retrieval["retrieved_run_count"],
        "target_page_retrieval_rate": target_retrieval["retrieval_rate"],
        "target_page_retrieval": target_retrieval,
        "target_page_retrieved_count": target_conversion["retrieved_count"],
        "target_page_cited_count": target_conversion["cited_count"],
        "target_page_conversion_rate": target_conversion["conversion_rate"],
        "target_page_conversion": target_conversion,
    }


def _evidence_package_runs(
    db: Session,
    project_id: int,
    prompt_id: int | None,
    run_ids: list[int],
    window_start: datetime | None,
    window_end: datetime | None,
) -> list[BrowserMonitorRun]:
    query = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.project_id == project_id)
    if run_ids:
        query = query.filter(BrowserMonitorRun.id.in_(run_ids))
    if prompt_id is not None:
        query = query.filter(BrowserMonitorRun.prompt_id == prompt_id)
    if window_start is not None:
        query = query.filter(BrowserMonitorRun.created_at >= window_start)
    if window_end is not None:
        query = query.filter(BrowserMonitorRun.created_at < window_end)
    return query.order_by(BrowserMonitorRun.id.asc()).all()


def _clean_target_urls(values: list[str]) -> list[str]:
    cleaned = []
    for value in values or []:
        url = str(value or "").strip()
        if url and url not in cleaned:
            cleaned.append(url)
    return cleaned


def _minimum_retrieval_candidate_count() -> int:
    return int(get_settings().minimum_retrieval_candidate_count or 30)


def _run_metric_eligibility(
    runs: list[BrowserMonitorRun],
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate],
) -> dict:
    minimum_required = _minimum_retrieval_candidate_count()
    reference_counts = Counter(ref.run_id for ref in references)
    retrieval_counts = Counter(item.run_id for item in retrievals)
    answer_eligible: list[int] = []
    citation_eligible: list[int] = []
    retrieval_eligible: list[int] = []
    excluded = {"answer": [], "citation": [], "retrieval": []}
    rows = []
    for run in sorted(runs, key=lambda item: item.id):
        answer_ok = run.status in VALID_RUN_STATUSES and bool((run.answer_text or "").strip() or run.answer_char_count)
        citation_ok = run.status in VALID_RUN_STATUSES and bool(run.reference_complete or reference_counts.get(run.id, 0))
        retrieval_count = retrieval_counts.get(run.id, 0)
        retrieval_ok = run.status in VALID_RUN_STATUSES and retrieval_count >= minimum_required
        if answer_ok:
            answer_eligible.append(run.id)
        else:
            excluded["answer"].append({"run_id": run.id, "reason": "NO_ANALYZABLE_ANSWER"})
        if citation_ok:
            citation_eligible.append(run.id)
        else:
            excluded["citation"].append({"run_id": run.id, "reason": "NO_ANALYZABLE_CITATIONS"})
        if retrieval_ok:
            retrieval_eligible.append(run.id)
        else:
            excluded["retrieval"].append(
                {
                    "run_id": run.id,
                    "reason": "INSUFFICIENT_RETRIEVAL_CANDIDATES",
                    "retrieval_candidate_count": retrieval_count,
                    "minimum_required": minimum_required,
                }
            )
        rows.append(
            {
                "run_id": run.id,
                "answer_metrics_eligible": answer_ok,
                "citation_metrics_eligible": citation_ok,
                "retrieval_metrics_eligible": retrieval_ok,
                "reference_count": reference_counts.get(run.id, 0),
                "retrieval_candidate_count": retrieval_count,
                "minimum_retrieval_candidate_count": minimum_required,
                "retrieval_exclusion_reason": "" if retrieval_ok else "INSUFFICIENT_RETRIEVAL_CANDIDATES",
            }
        )
    return {
        "version": RUN_ELIGIBILITY_VERSION,
        "minimum_retrieval_candidate_count": minimum_required,
        "answer_eligible_run_ids": answer_eligible,
        "citation_eligible_run_ids": citation_eligible,
        "retrieval_eligible_run_ids": retrieval_eligible,
        "excluded_run_ids_by_metric": {
            "answer": [row["run_id"] for row in excluded["answer"]],
            "citation": [row["run_id"] for row in excluded["citation"]],
            "retrieval": [row["run_id"] for row in excluded["retrieval"]],
        },
        "exclusion_reasons": excluded,
        "run_rows": rows,
    }


def _target_urls_from_existing_experiment(db: Session, project_id: int, prompt_id: int | None, run_ids: list[int]) -> list[str]:
    if prompt_id is None:
        return []
    actions = (
        db.query(OptimizationAction)
        .join(OptimizationIssue, OptimizationIssue.id == OptimizationAction.issue_id)
        .filter(OptimizationIssue.project_id == project_id, OptimizationIssue.prompt_id == prompt_id)
        .order_by(OptimizationAction.id.desc())
        .all()
    )
    urls = []
    run_id_set = set(run_ids)
    for action in actions:
        experiments = db.query(OptimizationExperiment).filter(OptimizationExperiment.action_id == action.id).all()
        if not experiments:
            continue
        for experiment in experiments:
            baseline_ids = set(loads(experiment.baseline_run_ids_json, []))
            if baseline_ids and not baseline_ids.intersection(run_id_set):
                continue
            if action.target_url and action.target_url not in urls:
                urls.append(action.target_url)
    return urls


def _environment_snapshot(runs: list[BrowserMonitorRun], prompt: Prompt | None, source_note: str = "") -> dict:
    def distinct(field: str) -> list[str]:
        values = sorted({str(getattr(run, field, "") or "") for run in runs if getattr(run, field, "")})
        return values

    return {
        "prompt_id": prompt.id if prompt else None,
        "prompt_text": prompt.prompt_text if prompt else (runs[0].original_query if runs else ""),
        "run_ids": [run.id for run in runs],
        "baseline_window": {
            "start": min((run.created_at for run in runs), default=None).isoformat() if runs else "",
            "end": max((run.created_at for run in runs), default=None).isoformat() if runs else "",
        },
        "platform": distinct("platform"),
        "source_type": distinct("source_type"),
        "adapter": distinct("adapter"),
        "collection_mode": distinct("collection_mode"),
        "browser": distinct("browser"),
        "profile_identifier": distinct("profile_identifier"),
        "collector_version": distinct("collector_version"),
        "parser_version": distinct("parser_version"),
        "retrieval_parser_version": RETRIEVAL_PARSER_VERSION,
        "content_classifier_version": CONTENT_CLASSIFIER_VERSION,
        "time_extractor_version": TIME_EXTRACTOR_VERSION,
        "network_region": distinct("network_region"),
        "source_note": source_note,
    }


def _evidence_version_manifest(environment_snapshot: dict) -> dict:
    collector_versions = environment_snapshot.get("collector_version") or []
    parser_versions = environment_snapshot.get("parser_version") or []
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "metric_spec_version": METRIC_SPEC_VERSION,
        "collector_version": collector_versions or [COLLECTOR_VERSION],
        "retrieval_parser_version": environment_snapshot.get("retrieval_parser_version") or parser_versions or [RETRIEVAL_PARSER_VERSION],
        "content_classifier_version": environment_snapshot.get("content_classifier_version") or CONTENT_CLASSIFIER_VERSION,
        "time_extractor_version": environment_snapshot.get("time_extractor_version") or TIME_EXTRACTOR_VERSION,
    }


def _build_evidence_report_payload(
    db: Session,
    project: Project,
    prompt: Prompt | None,
    runs: list[BrowserMonitorRun],
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate],
    target_urls: list[str],
    environment_snapshot: dict,
) -> dict:
    primary_target_url = target_urls[0] if target_urls else ""
    metrics = metrics_for_runs(db, runs, primary_target_url)
    source_rows = source_analysis(db, project, prompt, runs, references, retrievals)
    metric_rows = _evidence_metric_rows(metrics, runs)
    platform_matrix = _platform_gap_matrix(project, references, retrievals)
    content_distribution = _content_type_distribution(references, retrievals)
    time_distribution = _time_distribution(source_rows, runs)
    structure_summary = _content_structure_summary(source_rows)
    candidate_not_cited = _candidate_not_cited_summary(references, retrievals)
    retrieval_coverage = _retrieval_coverage_summary(runs, references, retrievals)
    eligibility = metrics.get("run_metric_eligibility", {})
    retrieval_metrics_status = "ok" if eligibility.get("retrieval_eligible_run_ids") else "insufficient_retrieval_candidates"
    if retrieval_metrics_status != "ok":
        _downgrade_candidate_funnel_rows(platform_matrix, content_distribution, candidate_not_cited, eligibility)
    validation_notes = [
        "规则层负责事实计算；本报告不使用 LLM 生成结论。",
        "候选未引用只表示进入检索候选但未进入最终参考资料，不代表模型拒绝或判定质量差。",
        "第一版引用片段证据等级为 SOURCE_LEVEL_ONLY，不能解释为已定位模型实际引用原文。",
    ]
    if retrieval_coverage["coverage_status"] != "COMPLETE":
        validation_notes.insert(0, retrieval_coverage["message"])
    return {
        "report_type": "B1_EVIDENCE_FACT_REPORT",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "metric_spec_version": METRIC_SPEC_VERSION,
        "project": {"id": project.id, "name": project.name, "brand_name": project.brand_name, "website_url": project.website_url},
        "prompt": {
            "id": prompt.id if prompt else None,
            "title": prompt.title if prompt else "",
            "prompt_text": prompt.prompt_text if prompt else (runs[0].original_query if runs else ""),
            "display_label": _prompt_display_label(prompt, runs),
        },
        "target_page_urls": target_urls,
        "summary": _evidence_human_summary(project, prompt, metrics, primary_target_url),
        "metrics": metric_rows,
        "metric_snapshot": metrics,
        "run_metric_eligibility": eligibility,
        "answer_eligible_run_ids": eligibility.get("answer_eligible_run_ids", []),
        "citation_eligible_run_ids": eligibility.get("citation_eligible_run_ids", []),
        "retrieval_eligible_run_ids": eligibility.get("retrieval_eligible_run_ids", []),
        "retrieval_metrics_status": retrieval_metrics_status,
        "platform_gap_matrix": platform_matrix,
        "content_type_distribution": content_distribution,
        "retrieval_coverage_summary": retrieval_coverage,
        "candidate_not_cited": candidate_not_cited,
        "time_distribution": time_distribution,
        "content_structure_summary": structure_summary,
        "source_level_evidence": _source_level_evidence(source_rows),
        "representative_sources": _representative_sources(source_rows),
        "run_drilldown": _package_run_drilldown(runs, metrics),
        "drilldowns": _package_drilldowns(metric_rows, platform_matrix, content_distribution, time_distribution, candidate_not_cited),
        "environment_snapshot": environment_snapshot,
        "validation_notes": validation_notes,
    }


def _prompt_display_label(prompt: Prompt | None, runs: list[BrowserMonitorRun]) -> str:
    if prompt:
        return f"Prompt #{prompt.id} · {prompt.prompt_text}"
    if runs:
        return f"Prompt #{runs[0].prompt_id} · {runs[0].original_query}"
    return "未选择 Prompt"


def _evidence_human_summary(project: Project, prompt: Prompt | None, metrics: dict, target_url: str) -> str:
    prompt_label = _prompt_display_label(prompt, [])
    retrieval = metrics.get("target_page_retrieval", {})
    conversion = metrics.get("target_page_conversion", {})
    valid = retrieval.get("valid_run_count", metrics.get("valid_run_count", 0))
    retrieved = retrieval.get("retrieved_run_count", 0)
    if retrieval.get("calculation_status") == "insufficient_retrieval_candidates":
        retrieval_text = "insufficient_retrieval_candidates"
    else:
        retrieval_text = f"{retrieved}/{valid} = {round(float(retrieval.get('retrieval_rate') or 0) * 100, 1)}%" if retrieval.get("retrieval_rate") is not None else "未设置目标页，无法计算"
    if conversion.get("calculation_status") == "insufficient_retrieval_candidates":
        conversion_text = "insufficient_retrieval_candidates"
    else:
        conversion_text = "not_applicable" if conversion.get("not_applicable") else f"{conversion.get('cited_count', 0)}/{conversion.get('retrieved_count', 0)}"
    target_text = f"目标页 {target_url}" if target_url else "未设置目标页"
    return f"{prompt_label}：{target_text}；目标页检索进入率 {retrieval_text}；检索后转引用率 {conversion_text}。"


def _evidence_metric_rows(metrics: dict, runs: list[BrowserMonitorRun]) -> list[dict]:
    run_ids = [run.id for run in runs]
    retrieval = metrics.get("target_page_retrieval", {})
    conversion = metrics.get("target_page_conversion", {})
    eligibility = metrics.get("run_metric_eligibility", {})
    valid = int(metrics.get("valid_run_count", 0) or 0)
    answer_ids = eligibility.get("answer_eligible_run_ids", run_ids)
    citation_ids = eligibility.get("citation_eligible_run_ids", run_ids)
    retrieval_ids = eligibility.get("retrieval_eligible_run_ids", run_ids)
    excluded_by_metric = eligibility.get("excluded_run_ids_by_metric", {})
    reasons = eligibility.get("exclusion_reasons", {})
    return [
        {
            "metric_name": "target_page_retrieval_rate",
            "value": retrieval.get("retrieval_rate"),
            "numerator": retrieval.get("retrieved_run_count", 0),
            "denominator": retrieval.get("valid_run_count", valid),
            "calculation_status": retrieval.get("calculation_status") or ("not_applicable" if retrieval.get("not_applicable") else "ok"),
            "source_run_ids": retrieval.get("run_ids", retrieval_ids),
            "eligible_run_ids": retrieval.get("eligible_run_ids", retrieval_ids),
            "excluded_run_ids": retrieval.get("excluded_run_ids", excluded_by_metric.get("retrieval", [])),
            "exclusion_reasons": retrieval.get("exclusion_reasons", reasons.get("retrieval", [])),
            "reason": retrieval.get("reason", ""),
        },
        {
            "metric_name": "target_page_conversion_rate",
            "value": conversion.get("conversion_rate"),
            "numerator": conversion.get("cited_count", 0),
            "denominator": conversion.get("retrieved_count", 0),
            "calculation_status": conversion.get("calculation_status") or ("not_applicable" if conversion.get("not_applicable") else "ok"),
            "source_run_ids": conversion.get("retrieved_run_ids", []),
            "eligible_run_ids": conversion.get("eligible_run_ids", retrieval_ids),
            "excluded_run_ids": conversion.get("excluded_run_ids", excluded_by_metric.get("retrieval", [])),
            "exclusion_reasons": conversion.get("exclusion_reasons", reasons.get("retrieval", [])),
            "reason": conversion.get("reason", ""),
        },
        {
            "metric_name": "brand_mention_rate",
            "value": metrics.get("brand_mention_rate"),
            "numerator": metrics.get("brand_mention_count", 0),
            "denominator": len(answer_ids),
            "calculation_status": "ok" if answer_ids else "insufficient_answer_data",
            "source_run_ids": answer_ids,
            "eligible_run_ids": answer_ids,
            "excluded_run_ids": excluded_by_metric.get("answer", []),
            "exclusion_reasons": reasons.get("answer", []),
            "reason": "",
        },
        {
            "metric_name": "brand_recommendation_rate",
            "value": metrics.get("brand_recommendation_rate"),
            "numerator": metrics.get("brand_recommendation_count", 0),
            "denominator": len(answer_ids),
            "calculation_status": "ok" if answer_ids else "insufficient_answer_data",
            "source_run_ids": answer_ids,
            "eligible_run_ids": answer_ids,
            "excluded_run_ids": excluded_by_metric.get("answer", []),
            "exclusion_reasons": reasons.get("answer", []),
            "reason": "",
        },
        {
            "metric_name": "official_reference_rate",
            "value": metrics.get("official_reference_rate"),
            "numerator": metrics.get("official_reference_count", 0),
            "denominator": len(citation_ids),
            "calculation_status": "ok" if citation_ids else "insufficient_citation_data",
            "source_run_ids": citation_ids,
            "eligible_run_ids": citation_ids,
            "excluded_run_ids": excluded_by_metric.get("citation", []),
            "exclusion_reasons": reasons.get("citation", []),
            "reason": "",
        },
    ]


def _platform_gap_matrix(project: Project, references: list[ReferenceSource], retrievals: list[RetrievalCandidate]) -> list[dict]:
    rows: dict[str, dict] = defaultdict(lambda: _empty_gap_row())
    for item in retrievals:
        platform = _item_platform(project, item, item.title, item.url or item.canonical_url, item.domain)
        row = rows[platform]
        _touch_candidate_row(row, item)
    for item in references:
        title = item.display_title or item.matched_title
        platform = _item_platform(project, item, title, item.url or item.canonical_url, item.domain)
        row = rows[platform]
        _touch_citation_row(row, item, title)
        if item.is_official_domain:
            row["brand_citation_count"] += 1
        if item.is_competitor_domain:
            row["competitor_citation_count"] += 1
    for item in retrievals:
        platform = _item_platform(project, item, item.title, item.url or item.canonical_url, item.domain)
        row = rows[platform]
        ownership = _ownership(project, [], item.domain, item.url or item.canonical_url, False, False, host_from_url(project.website_url) if project.website_url else "")
        if ownership in {"official", "brand_related"}:
            row["brand_candidate_count"] += 1
        if ownership == "competitor":
            row["competitor_candidate_count"] += 1
    result = []
    for platform, row in rows.items():
        candidate_run_count = len(row["candidate_run_ids"])
        citation_run_count = len(row["citation_run_ids"])
        retrieved_not_cited_run_ids = row["candidate_run_ids"] - row["citation_run_ids"]
        result.append({
            "platform": platform,
            "platform_label": source_platform_label(platform),
            "candidate_run_count": candidate_run_count,
            "citation_run_count": citation_run_count,
            "retrieved_not_cited_run_count": len(retrieved_not_cited_run_ids),
            "platform_citation_conversion_rate": _rate(citation_run_count, candidate_run_count) if candidate_run_count else None,
            "candidate_occurrence_count": row["candidate_occurrence_count"],
            "citation_occurrence_count": row["citation_occurrence_count"],
            "occurrence_ratio": _rate(row["citation_occurrence_count"], row["candidate_occurrence_count"]) if row["candidate_occurrence_count"] else None,
            "brand_candidate_count": row["brand_candidate_count"],
            "brand_citation_count": row["brand_citation_count"],
            "competitor_candidate_count": row["competitor_candidate_count"],
            "competitor_citation_count": row["competitor_citation_count"],
            "representative_candidate_urls": _representatives(row["candidate_representatives"]),
            "representative_cited_urls": _representatives(row["citation_representatives"]),
            "representative_run_ids": sorted(row["candidate_run_ids"] | row["citation_run_ids"])[:20],
            "candidate_run_ids": sorted(row["candidate_run_ids"]),
            "citation_run_ids": sorted(row["citation_run_ids"]),
            "retrieved_not_cited_run_ids": sorted(retrieved_not_cited_run_ids),
            "candidate_ids": sorted(row["candidate_ids"]),
            "citation_ids": sorted(row["citation_ids"]),
            "interpretation": "候选到引用转化偏低或尚未表现出稳定引用优势。" if retrieved_not_cited_run_ids else "该平台在当前样本中已有最终引用表现。",
        })
    return sorted(result, key=lambda row: (-row["citation_run_count"], -row["candidate_run_count"], row["platform_label"]))


def _content_type_distribution(references: list[ReferenceSource], retrievals: list[RetrievalCandidate]) -> list[dict]:
    rows: dict[str, dict] = defaultdict(lambda: _empty_gap_row())
    for item in retrievals:
        classification = _classify_content_type(item.title, item.url or item.canonical_url, item.snippet, item.domain)
        content_type = classification["content_type"]
        row = rows[content_type]
        row["classification_examples"].append(classification)
        _touch_candidate_row(row, item)
    for item in references:
        title = item.display_title or item.matched_title
        classification = _classify_content_type(title, item.url or item.canonical_url, "", item.domain)
        row = rows[classification["content_type"]]
        row["classification_examples"].append(classification)
        _touch_citation_row(row, item, title)
    result = []
    for content_type, row in rows.items():
        candidate_run_count = len(row["candidate_run_ids"])
        citation_run_count = len(row["citation_run_ids"])
        retrieved_not_cited_run_ids = row["candidate_run_ids"] - row["citation_run_ids"]
        conversion_rate = None
        conversion_status = "not_applicable"
        conversion_note = "该内容类型没有候选 Run，不能计算候选到引用转化率。"
        if candidate_run_count and citation_run_count <= candidate_run_count:
            conversion_rate = _rate(citation_run_count, candidate_run_count)
            conversion_status = "ok"
            conversion_note = ""
        elif candidate_run_count:
            conversion_note = "该内容类型的引用 Run 数超过候选 Run 数，说明候选解析分母不完整，不能作为转化率解释。"
        result.append({
            "content_type": content_type,
            "candidate_run_count": candidate_run_count,
            "citation_run_count": citation_run_count,
            "retrieved_not_cited_run_count": len(retrieved_not_cited_run_ids),
            "citation_conversion_rate": conversion_rate,
            "calculation_status": conversion_status,
            "calculation_note": conversion_note,
            "candidate_occurrence_count": row["candidate_occurrence_count"],
            "citation_occurrence_count": row["citation_occurrence_count"],
            "representative_urls": _representatives(row["citation_representatives"] or row["candidate_representatives"]),
            "representative_run_ids": sorted(row["candidate_run_ids"] | row["citation_run_ids"])[:20],
            "candidate_run_ids": sorted(row["candidate_run_ids"]),
            "citation_run_ids": sorted(row["citation_run_ids"]),
            "retrieved_not_cited_run_ids": sorted(retrieved_not_cited_run_ids),
            "candidate_ids": sorted(row["candidate_ids"]),
            "citation_ids": sorted(row["citation_ids"]),
            "classification_method": "RULE_HEURISTIC_V1",
            "classification_examples": _classification_examples(row["classification_examples"]),
        })
    return sorted(result, key=lambda row: (-row["citation_run_count"], -row["candidate_run_count"], row["content_type"]))


def _downgrade_candidate_funnel_rows(
    platform_rows: list[dict],
    content_rows: list[dict],
    candidate_not_cited: dict,
    eligibility: dict,
) -> None:
    excluded = eligibility.get("excluded_run_ids_by_metric", {}).get("retrieval", [])
    reasons = eligibility.get("exclusion_reasons", {}).get("retrieval", [])
    for row in platform_rows:
        row["candidate_scope"] = "captured_candidates"
        row["candidate_scope_label"] = "已捕获候选"
        row["calculation_status"] = "insufficient_retrieval_candidates"
        row["platform_citation_conversion_rate"] = None
        row["retrieved_not_cited_run_count"] = None
        row["retrieved_not_cited_run_ids"] = []
        row["excluded_run_ids"] = excluded
        row["exclusion_reasons"] = reasons
        row["interpretation"] = "检索候选未达到完整性门槛，本行只展示已捕获候选和引用事实，不计算候选漏斗指标。"
    for row in content_rows:
        row["candidate_scope"] = "captured_candidates"
        row["candidate_scope_label"] = "已捕获候选"
        row["calculation_status"] = "insufficient_retrieval_candidates"
        row["citation_conversion_rate"] = None
        row["retrieved_not_cited_run_count"] = None
        row["retrieved_not_cited_run_ids"] = []
        row["excluded_run_ids"] = excluded
        row["exclusion_reasons"] = reasons
        row["calculation_note"] = "检索候选未达到完整性门槛，本行只展示已捕获候选和引用事实，不计算内容类型候选转引用率。"
    candidate_not_cited["candidate_scope"] = "captured_candidates"
    candidate_not_cited["candidate_scope_label"] = "已捕获候选"
    candidate_not_cited["calculation_status"] = "insufficient_retrieval_candidates"
    candidate_not_cited["retrieved_not_cited_run_count"] = None
    candidate_not_cited["retrieved_not_cited_occurrence_count"] = None
    candidate_not_cited["excluded_run_ids"] = excluded
    candidate_not_cited["exclusion_reasons"] = reasons
    candidate_not_cited["interpretation"] = "检索候选未达到完整性门槛，已捕获候选仍可下钻，但不计算候选未引用指标。"


def _retrieval_coverage_summary(
    runs: list[BrowserMonitorRun],
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate],
) -> dict:
    candidate_counts = Counter(item.run_id for item in retrievals)
    citation_counts = Counter(item.run_id for item in references)
    rows = []
    incomplete_run_ids = []
    suspected_limit_counts = Counter()
    for run in sorted(runs, key=lambda item: item.id):
        candidate_count = candidate_counts.get(run.id, 0)
        citation_count = citation_counts.get(run.id, 0)
        expected_reference_count = run.parsed_reference_count or run.dom_reference_count or run.ui_declared_count or citation_count
        incomplete_reason = ""
        if candidate_count < citation_count:
            incomplete_reason = "retrieval_candidates_less_than_references"
        elif expected_reference_count and candidate_count < expected_reference_count:
            incomplete_reason = "retrieval_candidates_less_than_declared_reference_count"
        if incomplete_reason:
            incomplete_run_ids.append(run.id)
        if candidate_count:
            suspected_limit_counts[candidate_count] += 1
        rows.append(
            {
                "run_id": run.id,
                "retrieval_candidate_count": candidate_count,
                "reference_count": citation_count,
                "parsed_reference_count": run.parsed_reference_count,
                "ui_declared_count": run.ui_declared_count,
                "dom_reference_count": run.dom_reference_count,
                "coverage_status": "INCOMPLETE" if incomplete_reason else "OK",
                "incomplete_reason": incomplete_reason,
            }
        )
    total_candidate_count = sum(candidate_counts.values())
    total_reference_count = sum(citation_counts.values())
    coverage_status = "COMPLETE" if not incomplete_run_ids else "INCOMPLETE"
    common_candidate_count = suspected_limit_counts.most_common(1)[0][0] if suspected_limit_counts else 0
    suspected_fixed_limit = bool(incomplete_run_ids and common_candidate_count and suspected_limit_counts[common_candidate_count] == len(runs))
    message = "检索候选覆盖完整。"
    if coverage_status == "INCOMPLETE":
        message = (
            f"检索候选覆盖不完整：{len(incomplete_run_ids)}/{len(runs)} 个 Run 的候选数少于引用资料数或页面声明引用数。"
            "候选未引用、平台候选转引用等分析只能作为已采集候选范围内的证据，不能解释为完整检索库。"
        )
    return {
        "coverage_status": coverage_status,
        "candidate_scope": "complete_candidates" if coverage_status == "COMPLETE" else "captured_candidates",
        "candidate_scope_label": "完整候选" if coverage_status == "COMPLETE" else "已捕获候选",
        "retrieval_metrics_status": "ok" if coverage_status == "COMPLETE" else "insufficient_retrieval_candidates",
        "minimum_retrieval_candidate_count": _minimum_retrieval_candidate_count(),
        "valid_run_count": len(runs),
        "incomplete_run_count": len(incomplete_run_ids),
        "incomplete_run_ids": incomplete_run_ids,
        "total_retrieval_candidate_count": total_candidate_count,
        "total_reference_count": total_reference_count,
        "common_candidate_count_per_run": common_candidate_count,
        "suspected_fixed_collection_limit": suspected_fixed_limit,
        "message": message,
        "run_rows": rows,
    }


def _candidate_not_cited_summary(references: list[ReferenceSource], retrievals: list[RetrievalCandidate]) -> dict:
    cited_keys_by_run = _cited_keys_by_run(references)
    run_ids: set[int] = set()
    candidate_ids: set[int] = set()
    representatives = []
    occurrence_count = 0
    for item in retrievals:
        key = _source_key(item.run_id, item.canonical_url or item.url, item.domain, item.title)
        if key in cited_keys_by_run.get(item.run_id, set()):
            continue
        occurrence_count += 1
        run_ids.add(item.run_id)
        candidate_ids.add(item.id)
        representatives.append(_source_representation(item.run_id, item.title, item.url or item.canonical_url, item.domain))
    return {
        "retrieved_not_cited_run_count": len(run_ids),
        "retrieved_not_cited_occurrence_count": occurrence_count,
        "candidate_ids": sorted(candidate_ids),
        "representative_urls": _representatives(representatives),
        "representative_run_ids": sorted(run_ids),
        "interpretation": "这些资料进入检索候选但未进入最终参考资料，只能说明候选到引用转化未发生，不能解释为模型拒绝或判定质量差。",
    }


def _package_drilldowns(
    metric_rows: list[dict],
    platform_rows: list[dict],
    content_rows: list[dict],
    time_rows: list[dict],
    candidate_not_cited: dict,
) -> list[dict]:
    rows: list[dict] = []
    for metric in metric_rows:
        rows.append({
            "metric_name": metric["metric_name"],
            "filter_dimension": "metric",
            "filter_value": metric["metric_name"],
            "run_ids": metric.get("source_run_ids", []),
            "candidate_ids": [],
            "citation_ids": [],
            "representative_urls": [],
        })
    for platform in platform_rows:
        rows.extend([
            {
                "metric_name": "platform_candidate_run_count",
                "filter_dimension": "platform",
                "filter_value": platform["platform"],
                "run_ids": platform.get("candidate_run_ids", []),
                "candidate_ids": platform.get("candidate_ids", []),
                "citation_ids": [],
                "representative_urls": platform.get("representative_candidate_urls", []),
            },
            {
                "metric_name": "platform_citation_run_count",
                "filter_dimension": "platform",
                "filter_value": platform["platform"],
                "run_ids": platform.get("citation_run_ids", []),
                "candidate_ids": [],
                "citation_ids": platform.get("citation_ids", []),
                "representative_urls": platform.get("representative_cited_urls", []),
            },
            {
                "metric_name": "platform_retrieved_not_cited",
                "filter_dimension": "platform",
                "filter_value": platform["platform"],
                "run_ids": platform.get("retrieved_not_cited_run_ids", []),
                "candidate_ids": platform.get("candidate_ids", []),
                "citation_ids": [],
                "representative_urls": platform.get("representative_candidate_urls", []),
            },
        ])
    for content in content_rows:
        rows.append({
            "metric_name": "content_type_distribution",
            "filter_dimension": "content_type",
            "filter_value": content["content_type"],
            "run_ids": content.get("representative_run_ids", []),
            "candidate_ids": content.get("candidate_ids", []),
            "citation_ids": content.get("citation_ids", []),
            "representative_urls": content.get("representative_urls", []),
            "classification_examples": content.get("classification_examples", []),
        })
    for time_row in time_rows:
        rows.append({
            "metric_name": "time_distribution",
            "filter_dimension": "freshness_bucket",
            "filter_value": time_row["freshness_bucket"],
            "run_ids": time_row.get("representative_run_ids", []),
            "candidate_ids": [],
            "citation_ids": [],
            "representative_urls": time_row.get("representative_urls", []),
            "source_time_examples": time_row.get("source_time_examples", []),
        })
    rows.append({
        "metric_name": "candidate_not_cited",
        "filter_dimension": "candidate_citation_relation",
        "filter_value": "retrieved_not_cited",
        "run_ids": candidate_not_cited.get("representative_run_ids", []),
        "candidate_ids": candidate_not_cited.get("candidate_ids", []),
        "citation_ids": [],
        "representative_urls": candidate_not_cited.get("representative_urls", []),
    })
    return rows


def _time_distribution(source_rows: list[dict], runs: list[BrowserMonitorRun]) -> list[dict]:
    rows: dict[str, dict] = defaultdict(lambda: {
        "candidate_run_ids": set(),
        "citation_run_ids": set(),
        "unknown_date_count": 0,
        "representative_urls": [],
        "source_time_examples": [],
    })
    collection_date = max((run.created_at for run in runs), default=datetime.utcnow())
    for source in source_rows:
        time_info = _source_time_info(source, collection_date)
        bucket = time_info["freshness_bucket"]
        row = rows[bucket]
        if time_info["time_source"] == "UNKNOWN":
            row["unknown_date_count"] += 1
        target = row["citation_run_ids"] if source.get("cited") else row["candidate_run_ids"]
        target.update(int(run_id) for run_id in source.get("run_ids", []) if run_id)
        row["representative_urls"].append(_source_representation(source.get("run_id", 0), source.get("title", ""), source.get("url", ""), source.get("domain", "")))
        row["source_time_examples"].append({
            **time_info,
            "title": source.get("title", ""),
            "url": source.get("url", ""),
            "domain": source.get("domain", ""),
            "run_ids": source.get("run_ids", []),
            "source_kind": "final_reference" if source.get("cited") else "retrieval_candidate",
        })
    result = []
    total_sources = sum(len(row["source_time_examples"]) for row in rows.values())
    for bucket, row in rows.items():
        result.append({
            "freshness_bucket": bucket,
            "candidate_run_count": len(row["candidate_run_ids"]),
            "citation_run_count": len(row["citation_run_ids"]),
            "unknown_date_count": row["unknown_date_count"],
            "unknown_ratio": _rate(row["unknown_date_count"], total_sources) if total_sources else 0,
            "representative_urls": _representatives(row["representative_urls"]),
            "representative_run_ids": sorted(row["candidate_run_ids"] | row["citation_run_ids"])[:20],
            "time_source": "UNKNOWN" if bucket == "UNKNOWN" else "SEARCH_SNIPPET",
            "time_confidence": "low" if bucket == "UNKNOWN" else "medium",
            "source_time_examples": row["source_time_examples"][:10],
        })
    return sorted(result, key=lambda row: _freshness_bucket_order(row["freshness_bucket"]))


def _content_structure_summary(source_rows: list[dict]) -> dict:
    return {
        "evidence_level": "SOURCE_LEVEL_ONLY",
        "available": False,
        "status": "UNAVAILABLE",
        "reason": "当前只保存来源级证据，尚未抓取并解析完整页面正文。",
        "message": "页面结构分析暂不可用。",
        "fields_reserved": {
            "has_direct_answer": None,
            "has_steps": None,
            "has_numbered_steps": None,
            "has_restrictions": None,
            "has_troubleshooting": None,
            "has_faq": None,
            "has_comparison": None,
            "has_case": None,
            "has_tool_entry": None,
            "has_version_or_date": None,
            "section_headings": [],
            "word_count": None,
        },
        "source_level_signal_count": len(source_rows),
    }


def _source_level_evidence(source_rows: list[dict]) -> dict:
    return {
        "default_evidence_level": "SOURCE_LEVEL_ONLY",
        "rows_with_exact_snippet": 0,
        "rows_with_source_level_only": len(source_rows),
        "note": "当前仅确认来源页面级引用或候选关系，尚未定位答案使用的精确页面段落。",
    }


def _representative_sources(source_rows: list[dict]) -> list[dict]:
    representatives = []
    for row in source_rows[:30]:
        representatives.append({
            "source_kind": "final_reference" if row.get("cited") else "retrieval_candidate",
            "title": row.get("title", ""),
            "url": row.get("url", ""),
            "domain": row.get("domain", ""),
            "platform": row.get("platform", row.get("account_platform", "web")),
            "run_ids": row.get("run_ids", []),
            "citation_prominence_level": row.get("citation_prominence_level", "LOW"),
            "citation_prominence_basis": row.get("citation_prominence_basis", []),
            "source_score": row.get("source_score", 0),
            "legacy_source_score": row.get("legacy_source_score", row.get("source_score", 0)),
            "source_score_deprecated": row.get("source_score_deprecated", True),
            "evidence_level": "SOURCE_LEVEL_ONLY",
        })
    return representatives


def _package_run_drilldown(runs: list[BrowserMonitorRun], metrics: dict) -> list[dict]:
    retrieval = metrics.get("target_page_retrieval", {})
    conversion = metrics.get("target_page_conversion", {})
    retrieved_ids = set(retrieval.get("retrieved_run_ids", []))
    cited_ids = set(conversion.get("cited_run_ids", []))
    return [
        {
            "run_id": run.id,
            "prompt_id": run.prompt_id,
            "prompt_text": run.original_query,
            "status": run.status,
            "run_sequence": run.run_sequence,
            "sample_index": run.sample_index,
            "created_at": run.created_at.isoformat() if run.created_at else "",
            "started_at": run.started_at.isoformat() if run.started_at else "",
            "finished_at": run.finished_at.isoformat() if run.finished_at else "",
            "reference_complete": run.reference_complete,
            "parsed_reference_count": run.parsed_reference_count,
            "resolved_url_count": run.resolved_url_count,
            "target_page_retrieved": run.id in retrieved_ids,
            "target_page_cited": run.id in cited_ids,
        }
        for run in runs
    ]


def _empty_gap_row() -> dict:
    return {
        "candidate_run_ids": set(),
        "citation_run_ids": set(),
        "retrieved_not_cited_run_ids": set(),
        "candidate_ids": set(),
        "citation_ids": set(),
        "candidate_occurrence_count": 0,
        "citation_occurrence_count": 0,
        "brand_candidate_count": 0,
        "brand_citation_count": 0,
        "competitor_candidate_count": 0,
        "competitor_citation_count": 0,
        "candidate_representatives": [],
        "citation_representatives": [],
        "classification_examples": [],
    }


def _touch_candidate_row(row: dict, item: RetrievalCandidate) -> None:
    row["candidate_run_ids"].add(item.run_id)
    row["candidate_ids"].add(item.id)
    row["candidate_occurrence_count"] += 1
    row["candidate_representatives"].append(_source_representation(item.run_id, item.title, item.url or item.canonical_url, item.domain))


def _touch_citation_row(row: dict, item: ReferenceSource, title: str) -> None:
    row["citation_run_ids"].add(item.run_id)
    row["citation_ids"].add(item.id)
    row["citation_occurrence_count"] += 1
    row["citation_representatives"].append(_source_representation(item.run_id, title, item.url or item.canonical_url, item.domain))


def _source_representation(run_id: int, title: str, url: str, domain: str) -> dict:
    return {"run_id": run_id, "title": title or "", "url": url or "", "domain": domain or ""}


def _representatives(items: list[dict], limit: int = 5) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for item in items:
        key = _global_source_key(item.get("url", ""), item.get("domain", ""), item.get("title", ""))
        current = grouped.setdefault(key, {**item, "run_ids": set(), "occurrence_count": 0})
        current["run_ids"].add(item.get("run_id"))
        current["occurrence_count"] += 1
    result = []
    for item in sorted(grouped.values(), key=lambda row: (-row["occurrence_count"], row.get("domain", ""), row.get("title", "")))[:limit]:
        result.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "domain": item.get("domain", ""),
            "run_ids": sorted(run_id for run_id in item["run_ids"] if run_id),
            "occurrence_count": item["occurrence_count"],
        })
    return result


def _cited_keys_by_run(references: list[ReferenceSource]) -> dict[int, set[tuple]]:
    grouped: dict[int, set[tuple]] = defaultdict(set)
    for item in references:
        title = item.display_title or item.matched_title
        grouped[item.run_id].add(_source_key(item.run_id, item.canonical_url or item.url, item.domain, title))
    return grouped


def _item_platform(project: Project, item, title: str, url: str, domain: str) -> str:
    ownership = _ownership(
        project,
        [],
        domain,
        url,
        bool(getattr(item, "is_official_domain", False)),
        bool(getattr(item, "is_competitor_domain", False)),
        host_from_url(project.website_url) if project.website_url else "",
    )
    platform, _, _ = _account_identity(project, domain, url, title, ownership)
    return platform


def _content_type_label(content_format: str) -> str:
    return {
        "guide": "操作教程",
        "faq": "问答内容",
        "documentation": "规则解释",
        "homepage_or_channel": "工具产品页",
        "comparison": "产品推荐或对比",
        "news": "新闻资讯",
        "article": "其他",
    }.get(content_format, "其他")


def _classify_content_type(title: str, url: str, snippet: str = "", domain: str = "") -> dict:
    text = f"{title or ''} {url or ''} {snippet or ''} {domain or ''}".casefold()
    rules = [
        ("VIDEO", ["bilibili.com", "douyin.com", "xiaohongshu.com", "/video/", "视频", "短视频", "b站", "哔哩"]),
        ("Q_AND_A", ["zhihu.com/question", "faq", "常见问题", "问答", "怎么", "如何"]),
        ("TUTORIAL", ["教程", "指南", "guide", "how-to", "使用说明", "步骤", "操作方法"]),
        ("RULE_EXPLANATION", ["规则", "限制", "规范", "协议", "policy", "docs", "文档", "manual"]),
        ("TROUBLESHOOTING", ["失败", "报错", "打不开", "不能", "原因", "解决", "修复", "排查"]),
        ("COMPARISON", ["对比", "比较", "排行", "排名", "推荐", "best", "top", "review"]),
        ("TOOL_PAGE", ["工具", "生成器", "平台", "官网", "/card", "/tool", "/tools", "product"]),
        ("NEWS", ["新闻", "资讯", "公告", "news", "press", "发布"]),
    ]
    matched: list[str] = []
    for content_type, tokens in rules:
        hits = [token for token in tokens if token in text]
        if hits:
            matched = hits[:8]
            confidence = 0.86 if content_type == "VIDEO" and any("." in hit for hit in hits) else 0.72
            return {
                "content_type": content_type,
                "classification_method": "RULE_HEURISTIC_V1",
                "matched_rules": matched,
                "classification_confidence": confidence,
                "title": title or "",
                "url": url or "",
                "domain": domain or host_from_url(url) if url else domain or "",
            }
    if title or url or snippet:
        return {
            "content_type": "OTHER",
            "classification_method": "RULE_HEURISTIC_V1",
            "matched_rules": [],
            "classification_confidence": 0.35,
            "title": title or "",
            "url": url or "",
            "domain": domain or host_from_url(url) if url else domain or "",
        }
    return {
        "content_type": "UNCATEGORIZED",
        "classification_method": "RULE_HEURISTIC_V1",
        "matched_rules": [],
        "classification_confidence": 0,
        "title": "",
        "url": "",
        "domain": domain or "",
    }


def _classification_examples(items: list[dict], limit: int = 8) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("content_type"), _normalize_source_url(item.get("url", "")), item.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _freshness_bucket(published_date: str, freshness: str, collection_date: datetime) -> str:
    parsed = _parse_source_date(published_date)
    if parsed:
        age_days = max(0, (collection_date.date() - parsed.date()).days)
        if age_days <= 30:
            return "LAST_30_DAYS"
        if age_days <= 90:
            return "DAYS_31_90"
        if age_days <= 180:
            return "DAYS_91_180"
        if age_days <= 365:
            return "DAYS_181_365"
        return "OVER_1_YEAR"
    return "UNKNOWN"


def _parse_source_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            if fmt == "%Y-%m":
                return datetime.strptime(f"{raw}-01", "%Y-%m-%d")
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _freshness_bucket_order(value: str) -> int:
    order = {"LAST_30_DAYS": 0, "DAYS_31_90": 1, "DAYS_91_180": 2, "DAYS_181_365": 3, "OVER_1_YEAR": 4, "UNKNOWN": 5}
    return order.get(value, 99)


def _source_time_info(source: dict, collection_date: datetime) -> dict:
    title = source.get("title", "") or ""
    published = source.get("published_date", "") or ""
    parsed = _parse_source_date(published)
    has_year = bool(_visible_years(title))
    has_version = bool(re.search(r"(?:v\d+|版本|新版|更新|最新|202\d)", title, re.I))
    if parsed:
        age_days = max(0, (collection_date.date() - parsed.date()).days)
        return {
            "published_at": published,
            "updated_at": "",
            "date_text": published,
            "time_source": "SEARCH_SNIPPET",
            "time_confidence": "medium",
            "has_year_in_title": has_year,
            "has_version_statement": has_version,
            "age_days_at_collection": age_days,
            "freshness_bucket": _freshness_bucket(published, source.get("freshness_signal", ""), collection_date),
        }
    return {
        "published_at": "",
        "updated_at": "",
        "date_text": published if published else source.get("time_signal_detail", ""),
        "time_source": "UNKNOWN",
        "time_confidence": "low",
        "has_year_in_title": has_year,
        "has_version_statement": has_version,
        "age_days_at_collection": None,
        "freshness_bucket": "UNKNOWN",
    }


def _package_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _capture_page_snapshot(project_id: int, url: str, snapshot_type: str, experiment_id: int | None) -> PageSnapshot:
    target_url = _source_fetch_url(url)
    captured_at = datetime.utcnow()
    try:
        try:
            request = urllib.request.Request(
                target_url,
                headers={
                    "User-Agent": _metadata_user_agent(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                },
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = response.read(3_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
                status = int(getattr(response, "status", 0) or response.getcode() or 0)
                final_url = response.geturl() or target_url
            raw_html = payload.decode(charset, errors="replace")
        except Exception:
            status, final_url, raw_html = _fetch_snapshot_html_with_curl(target_url)
        parsed = _parse_snapshot_html(raw_html, final_url)
        return PageSnapshot(
            project_id=project_id,
            experiment_id=experiment_id,
            target_url=target_url,
            url=target_url,
            http_status=status,
            final_url=final_url,
            canonical_url=parsed["canonical_url"],
            captured_at=captured_at,
            raw_html=raw_html,
            html_hash=_sha256(raw_html),
            title=parsed["title"],
            meta_description=parsed["meta_description"],
            h1=parsed["h1"],
            main_text=parsed["main_text"],
            main_text_hash=_sha256(parsed["main_text"]),
            section_headings_json=dumps(parsed["section_headings"]),
            structured_data_json=dumps(parsed["structured_data"]),
            internal_links_json=dumps(parsed["internal_links"]),
            robots_directives_json=dumps(parsed["robots_directives"]),
            snapshot_type=snapshot_type,
            capture_status="success" if status and status < 400 and raw_html.strip() else "failed",
            capture_error="" if status and status < 400 and raw_html.strip() else f"http_status={status}",
        )
    except Exception as exc:
        return PageSnapshot(
            project_id=project_id,
            experiment_id=experiment_id,
            target_url=target_url,
            url=target_url,
            captured_at=captured_at,
            snapshot_type=snapshot_type,
            capture_status="failed",
            capture_error=str(exc)[:1000],
        )


def _fetch_snapshot_html_with_curl(url: str) -> tuple[int, str, str]:
    marker = "__GEO_CURL_META__"
    result = subprocess.run(
        [
            "curl",
            "-L",
            "-sS",
            "--compressed",
            "--max-time",
            "20",
            "-A",
            _metadata_user_agent(),
            "-w",
            f"\\n{marker}%{{http_code}} %{{url_effective}}",
            url,
        ],
        capture_output=True,
        timeout=24,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"curl failed with code {result.returncode}")
    body = result.stdout.decode("utf-8", errors="replace")
    if marker not in body:
        return 0, url, body
    html_text, meta = body.rsplit(marker, 1)
    parts = meta.strip().split(" ", 1)
    status = int(parts[0]) if parts and parts[0].isdigit() else 0
    final_url = parts[1].strip() if len(parts) > 1 else url
    return status, final_url, html_text


def _parse_snapshot_html(page_html: str, final_url: str) -> dict:
    title = _html_title(page_html)
    meta = _snapshot_meta_tags(page_html)
    headings = _html_headings(page_html)
    main_text = _html_main_text(page_html)
    canonical = meta.get("canonical_url") or final_url
    return {
        "title": title,
        "meta_description": meta.get("description", ""),
        "h1": headings[0] if headings else "",
        "canonical_url": canonical,
        "section_headings": headings,
        "structured_data": _snapshot_jsonld(page_html),
        "internal_links": _snapshot_internal_links(page_html, final_url),
        "robots_directives": meta.get("robots_directives", {}),
        "main_text": main_text,
    }


def _snapshot_meta_tags(page_html: str) -> dict:
    description = ""
    canonical_url = ""
    robots_directives: dict[str, str] = {}
    for match in re.finditer(r"<meta\b([^>]+)>", page_html or "", re.I | re.S):
        attrs = _html_attrs(match.group(1))
        key = (attrs.get("name") or attrs.get("property") or "").strip().lower()
        content = html_lib.unescape((attrs.get("content") or "").strip())
        if key == "description" and not description:
            description = content[:1000]
        if key in {"robots", "googlebot", "baiduspider"}:
            robots_directives[key] = content
    for match in re.finditer(r"<link\b([^>]+)>", page_html or "", re.I | re.S):
        attrs = _html_attrs(match.group(1))
        if (attrs.get("rel") or "").strip().lower() == "canonical":
            canonical_url = html_lib.unescape((attrs.get("href") or "").strip())
            break
    return {"description": description, "canonical_url": canonical_url, "robots_directives": robots_directives}


def _html_headings(page_html: str) -> list[str]:
    headings: list[str] = []
    for match in re.finditer(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", page_html or "", re.I | re.S):
        text = _strip_html(match.group(1))
        if text and text not in headings:
            headings.append(text[:300])
    return headings[:80]


def _html_main_text(page_html: str) -> str:
    html = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", page_html or "", flags=re.I | re.S)
    text = _strip_html(html)
    return text[:120000]


def _strip_html(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html_lib.unescape(no_tags)).strip()


def _snapshot_jsonld(page_html: str) -> list[dict]:
    rows = []
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        page_html or "",
        re.I | re.S,
    ):
        raw = html_lib.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            rows.append(data)
        elif isinstance(data, list):
            rows.extend(item for item in data if isinstance(item, dict))
    return rows[:30]


def _snapshot_internal_links(page_html: str, final_url: str) -> list[str]:
    base_host = host_from_url(final_url)
    links: list[str] = []
    for match in re.finditer(r"<a\b([^>]+)>", page_html or "", re.I | re.S):
        href = html_lib.unescape((_html_attrs(match.group(1)).get("href") or "").strip())
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if href.startswith("/"):
            parsed = urlparse(final_url)
            href = urlunparse((parsed.scheme, parsed.netloc, href, "", "", ""))
        if host_from_url(href) == base_host and href not in links:
            links.append(href)
    return links[:200]


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _validate_release_snapshot(snapshot: PageSnapshot | None, experiment_id: int, snapshot_type: str) -> None:
    if not snapshot:
        raise HTTPException(status_code=400, detail=f"缺少 {snapshot_type} 页面快照")
    if snapshot.experiment_id != experiment_id:
        raise HTTPException(status_code=400, detail=f"{snapshot_type} 页面快照未关联当前实验")
    if snapshot.snapshot_type != snapshot_type:
        raise HTTPException(status_code=400, detail=f"页面快照类型不是 {snapshot_type}")
    if snapshot.capture_status != "success" or not snapshot.raw_html:
        raise HTTPException(status_code=400, detail=f"{snapshot_type} 页面快照抓取未成功，不能确认发布")


def _robots_block_indexing(robots: dict) -> bool:
    values = " ".join(str(value).lower() for value in (robots or {}).values())
    return "noindex" in values or "none" in values


def source_analysis(
    db: Session,
    project: Project,
    prompt: Prompt | None,
    runs: list[BrowserMonitorRun],
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate],
    valid_run_ids: list[int] | None = None,
    include_answer_binding_v1_1: bool = False,
) -> list[dict]:
    prompt_text = (prompt.prompt_text if prompt else "") or " ".join(run.original_query for run in runs[:3])
    run_by_id = {run.id: run for run in runs}
    competitors = []
    try:
        competitors = list(project.competitors)
    except Exception:
        competitors = []
    brand_domain = host_from_url(project.website_url) if project.website_url else ""
    cited_keys = {_source_key(ref.run_id, ref.canonical_url or ref.url, ref.domain, ref.display_title) for ref in references}
    sample_count = len({run.id for run in runs}) or 1
    citation_stats = _citation_stats(references, sample_count)
    retrieval_rank = {
        _source_key(item.run_id, item.canonical_url or item.url, item.domain, item.title): item.rank
        for item in retrievals
    }
    rows = []
    for ref in references:
        title = ref.display_title or ref.matched_title or ""
        url = ref.url or ref.canonical_url
        rows.append(_source_analysis_row(
            source_kind="citation",
            source_id=ref.id,
            run_id=ref.run_id,
            cited=True,
            retrieval_rank=retrieval_rank.get(_source_key(ref.run_id, url, ref.domain, title)),
            title=title,
            url=url,
            domain=ref.domain,
            snippet="",
            answer_text=run_by_id.get(ref.run_id).answer_text if run_by_id.get(ref.run_id) else "",
            citation_stats=citation_stats.get(_global_source_key(url, ref.domain, title), _empty_citation_stats(sample_count)),
            prompt_text=prompt_text,
            project=project,
            competitors=competitors,
            brand_domain=brand_domain,
            is_official=ref.is_official_domain,
            is_competitor=ref.is_competitor_domain,
        ))
    for item in retrievals:
        title = item.title
        url = item.url or item.canonical_url
        key = _source_key(item.run_id, url, item.domain, title)
        if key in cited_keys:
            continue
        rows.append(_source_analysis_row(
            source_kind="retrieval_candidate",
            source_id=item.id,
            run_id=item.run_id,
            cited=False,
            retrieval_rank=item.rank,
            title=title,
            url=url,
            domain=item.domain,
            snippet=item.snippet,
            answer_text=run_by_id.get(item.run_id).answer_text if run_by_id.get(item.run_id) else "",
            citation_stats=citation_stats.get(_global_source_key(url, item.domain, title), _empty_citation_stats(sample_count)),
            prompt_text=prompt_text,
            project=project,
            competitors=competitors,
            brand_domain=brand_domain,
            is_official=False,
            is_competitor=False,
        ))
    rows = _dedupe_source_analysis_rows(rows)
    rows = _enrich_source_rows_with_metadata(db, rows)
    rows = _attach_decision_support_benchmarks(
        db,
        project,
        prompt,
        rows,
        valid_run_ids=valid_run_ids or [run.id for run in runs],
        include_answer_binding_v1_1=include_answer_binding_v1_1,
    )
    rows = _attach_source_gap_analysis(db, project, rows, prompt=prompt, retrievals=retrievals, references=references)
    rows = _attach_capability_gap_items(rows)
    rows = _attach_priority_action_routes(rows)
    rows = _attach_channel_opportunities(rows)
    rows = _attach_recommended_actions(rows, project, prompt)
    rows = _attach_cross_source_comparison(rows)
    return sorted(rows, key=_source_analysis_sort_key)


def _source_analysis_row(
    source_kind: str,
    source_id: int,
    run_id: int,
    cited: bool,
    retrieval_rank: int | None,
    title: str,
    url: str,
    domain: str,
    snippet: str,
    answer_text: str,
    citation_stats: dict,
    prompt_text: str,
    project: Project,
    competitors: list[Competitor],
    brand_domain: str,
    is_official: bool,
    is_competitor: bool,
) -> dict:
    combined = " ".join([title or "", snippet or "", url or "", domain or ""])
    ownership = _ownership(project, competitors, domain, url, is_official, is_competitor, brand_domain)
    content_format = _content_format(title, url)
    overlap = _overlap_score(prompt_text, combined)
    brand_signal = _brand_signal(project, combined, ownership)
    freshness = _freshness_signal(combined)
    authority = _authority_signal(ownership, domain, content_format)
    account_platform, account_identity, account_identity_reason = _account_identity(project, domain, url, title, ownership)
    author_name = _author_name(title, url, domain, account_platform)
    published_date = _published_date(combined)
    answer_usage, answer_usage_reason = _answer_usage(title, domain, answer_text, cited)
    content_structure_signals = _content_structure_signals(title, url, snippet)
    time_signal_detail = _time_signal_detail(combined, freshness)
    score, score_breakdown = _source_score(
        cited=cited,
        citation_stats=citation_stats,
        ownership=ownership,
        content_format=content_format,
        overlap=overlap,
        freshness=freshness,
        authority=authority,
        account_identity=account_identity,
        answer_usage=answer_usage,
        url=url,
    )
    citation_prominence_level, citation_prominence_basis, citation_prominence_breakdown = _citation_prominence(
        cited=cited,
        citation_stats=citation_stats,
    )
    score_explanation = _score_explanation(citation_stats, answer_usage, ownership, content_format, overlap, authority)
    risk_flags = _risk_flags(cited, ownership, content_format, overlap, freshness, url)
    diagnostic_angles = [
        {"angle": "citation_prominence", "value": citation_prominence_level, "note": "仅由引用覆盖、频次、位置和跨样本稳定性计算。"},
        {"angle": "ownership", "value": ownership, "note": _ownership_note(ownership)},
        {"angle": "content_format", "value": content_format, "note": _format_note(content_format)},
        {"angle": "prompt_match", "value": overlap, "note": _overlap_note(overlap)},
        {"angle": "freshness", "value": freshness, "note": _freshness_note(freshness)},
        {"angle": "authority", "value": authority, "note": _authority_note(authority)},
        {"angle": "account_identity", "value": account_identity, "note": account_identity_reason},
        {"angle": "answer_usage", "value": answer_usage, "note": answer_usage_reason},
    ]
    return {
        "source_kind": source_kind,
        "source_id": source_id,
        "run_id": run_id,
        "run_ids": [run_id],
        "run_count": 1,
        "cited": cited,
        "retrieval_rank": retrieval_rank,
        "title": title,
        "url": url,
        "domain": domain,
        "ownership": ownership,
        "source_role": _source_role(ownership, content_format),
        "content_format": content_format,
        "prompt_overlap_score": overlap,
        "brand_signal": brand_signal,
        "freshness_signal": freshness,
        "authority_signal": authority,
        "platform": account_platform,
        "author_name": author_name,
        "published_date": published_date,
        "source_score": score,
        "legacy_source_score": score,
        "source_score_deprecated": True,
        "score_breakdown": score_breakdown,
        "score_explanation": score_explanation,
        "citation_prominence_level": citation_prominence_level,
        "citation_prominence_basis": citation_prominence_basis,
        "citation_prominence_breakdown": citation_prominence_breakdown,
        "source_document_id": None,
        "content_status": "CONTENT_PENDING",
        "content_status_label": "待补正文",
        "content_status_reason": "尚未匹配到可用于语义判断的来源正文。",
        "blocks_alignment": True,
        "decision_support_level": "NONE",
        "has_contradiction": False,
        "benchmark_relevance": "TANGENTIAL",
        "benchmark_tier": "NOT_EVALUABLE",
        "benchmark_basis": [],
        "supporting_alignment_ids": [],
        "contradicting_alignment_ids": [],
        "decision_support_basis": [],
        "suggested_capability_label": "",
        "source_gap_type": None,
        "source_gap_label": "",
        "source_gap_reason": "尚未进入 Source Gap 分析。",
        "source_gap_basis": [],
        "source_gap_precondition": "NO_ELIGIBLE_BENCHMARK",
        "gap_analysis_status": "NOT_ELIGIBLE",
        "capability_gap_layer": "",
        "capability_gap_diagnosis": {},
        "capability_gap_items": [],
        "matched_product_truth_ids": [],
        "matched_product_truth_status": "UNKNOWN",
        "capability_truth_targets": [],
        "unmatched_capability_truth_targets": [],
        "existing_asset_status": "UNKNOWN",
        "existing_asset_snapshot_id": None,
        "existing_asset_coverage": "UNKNOWN",
        "relevant_asset_snapshot": {},
        "retrieval_candidate_context": {},
        "evidence_adoption_context": {},
        "priority_level": None,
        "priority_label": "",
        "priority_reason": "该来源未进入优化优先级判断。",
        "priority_basis": [],
        "action_route": None,
        "action_route_label": "",
        "action_route_reason": "该来源未进入处理路径判断。",
        "citation_occurrence_count": citation_stats["citation_occurrence_count"],
        "cited_run_count": citation_stats["cited_run_count"],
        "answer_citation_rate": citation_stats["answer_citation_rate"],
        "avg_reference_position": citation_stats["avg_reference_position"],
        "account_platform": account_platform,
        "account_identity": account_identity,
        "account_identity_reason": account_identity_reason,
        "answer_usage": answer_usage,
        "answer_usage_reason": answer_usage_reason,
        "citation_reason": _citation_reason(cited, retrieval_rank, citation_stats, ownership, content_format, overlap, freshness, authority),
        "citation_basis": _citation_basis(
            cited=cited,
            citation_stats=citation_stats,
            account_platform=account_platform,
            account_identity=account_identity,
            ownership=ownership,
            content_format=content_format,
            content_structure_signals=content_structure_signals,
            freshness=freshness,
            authority=authority,
            overlap=overlap,
        ),
        "content_structure_signals": content_structure_signals,
        "time_signal_detail": time_signal_detail,
        "cross_source_comparison": {},
        "diagnostic_angles": diagnostic_angles,
        "risk_flags": risk_flags,
        "comparison_note": _comparison_note(cited, retrieval_rank, ownership, overlap),
    }


def _source_key(run_id: int, url: str, domain: str, title: str) -> tuple:
    normalized_url = _normalize_source_url(url)
    if normalized_url:
        return (run_id, "url", normalized_url)
    normalized_title = re.sub(r"\s+", " ", (title or "").strip().lower())
    return (run_id, "title", (domain or "").strip().lower(), normalized_title)


def _dedupe_source_analysis_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[_global_source_key(row.get("url", ""), row.get("domain", ""), row.get("title", ""))].append(row)
    return [_merge_source_rows(group_rows) for group_rows in grouped.values()]


def _merge_source_rows(rows: list[dict]) -> dict:
    sorted_rows = sorted(
        rows,
        key=_source_analysis_sort_key,
    )
    base = dict(sorted_rows[0])
    run_ids = sorted({int(row["run_id"]) for row in rows if row.get("run_id")})
    retrieval_ranks = [int(row["retrieval_rank"]) for row in rows if row.get("retrieval_rank")]
    risk_flags = sorted({flag for row in rows for flag in row.get("risk_flags", [])})
    structure_signals = []
    for row in rows:
        for signal in row.get("content_structure_signals", []):
            if signal not in structure_signals:
                structure_signals.append(signal)
    answer_usage = max((row.get("answer_usage", "unknown") for row in rows), key=_answer_usage_priority)
    usage_row = next((row for row in rows if row.get("answer_usage") == answer_usage), base)
    base.update(
        {
            "source_kind": "citation" if any(row.get("cited") for row in rows) else "retrieval_candidate",
            "cited": any(row.get("cited") for row in rows),
            "run_ids": run_ids,
            "run_count": len(run_ids),
            "retrieval_rank": min(retrieval_ranks) if retrieval_ranks else None,
            "risk_flags": risk_flags,
            "content_structure_signals": structure_signals,
            "answer_usage": answer_usage,
            "answer_usage_reason": usage_row.get("answer_usage_reason", base.get("answer_usage_reason", "")),
        }
    )
    if len(rows) > 1:
        base["comparison_note"] = f"已合并 {len(rows)} 条相同资料记录，覆盖 Run：{', '.join(str(run_id) for run_id in run_ids)}。"
    return base


def _source_analysis_sort_key(row: dict) -> tuple:
    return (
        _priority_rank(row.get("priority_level")),
        -_decision_support_rank(row.get("decision_support_level")),
        _benchmark_tier_rank(row.get("benchmark_tier")),
        -_citation_prominence_rank(row.get("citation_prominence_level")),
        0 if row.get("cited") else 1,
        -float(row.get("answer_citation_rate", 0) or 0),
        -int(row.get("citation_occurrence_count", 0) or 0),
        float(row.get("avg_reference_position") or 999),
        int(row.get("retrieval_rank") or 999),
        int(row.get("run_id") or 0),
        int(row.get("source_id") or 0),
    )


def _attach_decision_support_benchmarks(
    db: Session,
    project: Project,
    prompt: Prompt | None,
    rows: list[dict],
    valid_run_ids: list[int] | None = None,
    include_answer_binding_v1_1: bool = False,
) -> list[dict]:
    if not rows or not prompt:
        return rows
    doc_by_key = _source_document_lookup_for_rows(db, rows)
    doc_ids = {doc.id for doc in doc_by_key.values()}
    if not doc_ids:
        for row in rows:
            row.update(_empty_benchmark_payload("尚未匹配到可用于语义判断的来源正文。"))
        return rows

    quality_by_doc_id = _latest_source_quality_by_doc_id(db, doc_ids)
    support_by_doc_id = _decision_support_by_doc_id(
        db,
        project.id,
        prompt.id,
        doc_ids,
        allowed_run_ids=set(int(run_id) for run_id in (valid_run_ids or []) if run_id),
        include_answer_binding_v1_1=include_answer_binding_v1_1,
    )
    for row in rows:
        doc = _source_document_for_row(row, doc_by_key)
        if not doc:
            row.update(_empty_benchmark_payload("尚未匹配到可用于语义判断的来源正文。"))
            continue
        content_payload = derive_content_status(doc, quality_by_doc_id.get(doc.id))
        support_payload = support_by_doc_id.get(doc.id, _empty_decision_support_payload())
        tier = _benchmark_tier_for_decision(
            content_status=content_payload["content_status"],
            relevance=support_payload["benchmark_relevance"],
            decision_support=support_payload["decision_support_level"],
        )
        row.update(content_payload)
        row.update(support_payload)
        row.update({
            "source_document_id": doc.id,
            "benchmark_tier": tier,
            "benchmark_basis": _benchmark_basis(content_payload, support_payload, tier),
        })
    return rows


def _source_document_lookup_for_rows(db: Session, rows: list[dict]) -> dict[str, SourceDocument]:
    urls = {row.get("url") for row in rows if row.get("url")}
    if not urls:
        return {}
    docs = db.query(SourceDocument).filter(or_(
        SourceDocument.url.in_(urls),
        SourceDocument.original_url.in_(urls),
        SourceDocument.canonical_url.in_(urls),
    )).all()
    lookup: dict[str, SourceDocument] = {}
    for doc in docs:
        for raw in {doc.url, doc.original_url, doc.canonical_url}:
            key = _normalize_source_url(raw or "")
            if key and key not in lookup:
                lookup[key] = doc
    return lookup


def _source_document_for_row(row: dict, doc_by_key: dict[str, SourceDocument]) -> SourceDocument | None:
    return doc_by_key.get(_normalize_source_url(row.get("url") or ""))


def _latest_source_quality_by_doc_id(db: Session, doc_ids: set[int]) -> dict[int, SourceQuality]:
    qualities = (
        db.query(SourceQuality)
        .filter(SourceQuality.source_document_id.in_(doc_ids))
        .order_by(SourceQuality.source_document_id.asc(), SourceQuality.id.desc())
        .all()
    )
    result: dict[int, SourceQuality] = {}
    for quality in qualities:
        if quality.source_document_id not in result:
            result[quality.source_document_id] = quality
    return result


def _decision_support_by_doc_id(
    db: Session,
    project_id: int,
    prompt_id: int,
    doc_ids: set[int],
    allowed_run_ids: set[int] | None = None,
    include_answer_binding_v1_1: bool = False,
) -> dict[int, dict]:
    alignments = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project_id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.source_document_id.in_(doc_ids),
        EvidenceAlignment.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
    ).all()
    if not include_answer_binding_v1_1:
        alignments = [
            alignment
            for alignment in alignments
            if not _is_answer_binding_v1_1_alignment(alignment)
        ]
    alignments, eligibility_by_id = eligible_evidence_alignments_for_v1(
        db,
        alignments,
        allowed_run_ids=allowed_run_ids,
        include_answer_binding_v1_1=include_answer_binding_v1_1,
    )
    event_ids = {alignment.recommendation_event_id for alignment in alignments if alignment.recommendation_event_id}
    events = db.query(RecommendationEvent).filter(RecommendationEvent.id.in_(event_ids)).all() if event_ids else []
    event_by_id = {event.id: event for event in events}

    grouped: dict[int, list[tuple[EvidenceAlignment, RecommendationEvent | None]]] = defaultdict(list)
    for alignment in alignments:
        grouped[alignment.source_document_id].append((alignment, event_by_id.get(alignment.recommendation_event_id)))

    payload = {
        doc_id: _decision_support_from_alignments(items)
        for doc_id, items in grouped.items()
    }
    ineligible_counts: dict[int, Counter] = defaultdict(Counter)
    for alignment_id, eligibility in eligibility_by_id.items():
        if eligibility.eligible_for_v1 or not eligibility.source_document_id:
            continue
        for reason in eligibility.ineligibility_reasons:
            ineligible_counts[eligibility.source_document_id][reason] += 1
    for doc_id, counts in ineligible_counts.items():
        payload.setdefault(doc_id, _empty_decision_support_payload())
        payload[doc_id]["ineligible_alignment_counts"] = dict(sorted(counts.items()))
    return payload


def _decision_support_from_alignments(items: list[tuple[EvidenceAlignment, RecommendationEvent | None]]) -> dict:
    supports = [(alignment, event) for alignment, event in items if (alignment.relation or "").upper() == "SUPPORTS"]
    contradictions = [alignment for alignment, _ in items if (alignment.relation or "").upper() == "CONTRADICTS"]
    if not supports:
        return {
            **_empty_decision_support_payload(),
            "has_contradiction": bool(contradictions),
            "contradicting_alignment_ids": [alignment.id for alignment in contradictions],
        }

    level = "FACT_ONLY"
    relevance = "DIRECT"
    supporting_ids: list[int] = []
    support_notes: list[str] = []
    for alignment, event in supports:
        supporting_ids.append(alignment.id)
        scope = (alignment.scope_relation or "").upper()
        if scope == "PASS_MARKET":
            relevance = "PARTIAL"
        elif scope == "PASS" and relevance != "PARTIAL":
            relevance = "DIRECT"
        event_level = _decision_support_level_for_event(event)
        if _decision_support_rank(event_level) > _decision_support_rank(level):
            level = event_level
        if event:
            support_notes.append(f"{event.speech_act}:{event.entity_text}")

    return {
        "decision_support_level": level,
        "has_contradiction": bool(contradictions),
        "benchmark_relevance": relevance,
        "supporting_alignment_ids": supporting_ids,
        "contradicting_alignment_ids": [alignment.id for alignment in contradictions],
        "decision_support_basis": sorted(set(support_notes))[:8],
        "evidence_observed_run_ids": sorted({alignment.run_id for alignment, _ in supports if alignment.run_id}),
        "evidence_run_coverage_count": len({alignment.run_id for alignment, _ in supports if alignment.run_id}),
    }


def _is_answer_binding_v1_1_alignment(alignment: EvidenceAlignment) -> bool:
    payload = loads(alignment.machine_payload_json, {})
    return (
        payload.get("reason_source") == ANSWER_BINDING_REASON_SOURCE
        or payload.get("formal_input_version") == FORMAL_V1_1_INPUT_VERSION
    )


def _decision_support_level_for_event(event: RecommendationEvent | None) -> str:
    if not event:
        return "FACT_ONLY"
    speech_act = (event.speech_act or "").upper()
    strength = (event.recommendation_strength or "").upper()
    polarity = (event.polarity or "").upper()
    if speech_act == "RECOMMEND":
        return "RECOMMENDATION_REASON"
    if speech_act in {"INCLUDE_AS_OPTION", "COMPARE"} or strength in {"MODERATE", "STRONG"} or polarity == "POSITIVE":
        return "CANDIDATE_OR_EVALUATION"
    return "FACT_ONLY"


def _benchmark_tier_for_decision(content_status: str, relevance: str, decision_support: str) -> str:
    if content_status != "CONTENT_VALID":
        return "NOT_EVALUABLE"
    if relevance == "DIRECT" and decision_support in {"RECOMMENDATION_REASON", "CANDIDATE_OR_EVALUATION"}:
        return "PRIMARY_BENCHMARK"
    if (relevance == "DIRECT" and decision_support == "FACT_ONLY") or (
        relevance == "PARTIAL" and decision_support in {"RECOMMENDATION_REASON", "CANDIDATE_OR_EVALUATION"}
    ):
        return "SECONDARY_BENCHMARK"
    if relevance == "TANGENTIAL" or decision_support == "NONE":
        return "REFERENCE_ONLY"
    return "REFERENCE_ONLY"


def _benchmark_tier_rank(tier: str | None) -> int:
    return {
        "PRIMARY_BENCHMARK": 1,
        "SECONDARY_BENCHMARK": 2,
        "REFERENCE_ONLY": 3,
        "NOT_EVALUABLE": 4,
    }.get((tier or "NOT_EVALUABLE").upper(), 4)


def _decision_support_rank(level: str) -> int:
    return {
        "NONE": 0,
        "FACT_ONLY": 1,
        "CANDIDATE_OR_EVALUATION": 2,
        "RECOMMENDATION_REASON": 3,
    }.get((level or "NONE").upper(), 0)


def _empty_decision_support_payload() -> dict:
    return {
        "decision_support_level": "NONE",
        "has_contradiction": False,
        "benchmark_relevance": "TANGENTIAL",
        "supporting_alignment_ids": [],
        "contradicting_alignment_ids": [],
        "decision_support_basis": [],
        "evidence_observed_run_ids": [],
        "evidence_run_coverage_count": 0,
        "ineligible_alignment_counts": {},
    }


def _empty_benchmark_payload(reason: str) -> dict:
    content_payload = {
        "content_status": "CONTENT_PENDING",
        "content_status_label": "待补正文",
        "content_status_reason": reason,
        "blocks_alignment": True,
    }
    support_payload = _empty_decision_support_payload()
    return {
        **content_payload,
        **support_payload,
        "source_document_id": None,
        "benchmark_tier": "NOT_EVALUABLE",
        "benchmark_basis": _benchmark_basis(content_payload, support_payload, "NOT_EVALUABLE"),
    }


def _benchmark_basis(content_payload: dict, support_payload: dict, tier: str) -> list[str]:
    basis = [
        f"正文状态: {content_payload.get('content_status')}",
        f"决策支撑: {support_payload.get('decision_support_level')}",
        f"相关性: {support_payload.get('benchmark_relevance')}",
        f"对标层级: {tier}",
    ]
    if support_payload.get("has_contradiction"):
        basis.append("存在 CONTRADICTS 对齐；该信号独立于 decision_support_level。")
    if content_payload.get("content_status") != "CONTENT_VALID":
        basis.append("正文不可评估或待补，不进入对标来源。")
    return basis


def _attach_source_gap_analysis(
    db: Session,
    project: Project,
    rows: list[dict],
    prompt: Prompt | None = None,
    retrievals: list[RetrievalCandidate] | None = None,
    references: list[ReferenceSource] | None = None,
) -> list[dict]:
    if not rows:
        return rows
    support_ids = {
        int(alignment_id)
        for row in rows
        for alignment_id in row.get("supporting_alignment_ids", [])
        if alignment_id
    }
    benchmark_by_row = _benchmark_evidence_by_alignment_id(db, support_ids)
    truths = db.query(TargetBrandCapabilityTruth).filter(TargetBrandCapabilityTruth.project_id == project.id).all()
    for row in rows:
        tier = (row.get("benchmark_tier") or "").upper()
        if tier not in {"PRIMARY_BENCHMARK", "SECONDARY_BENCHMARK"}:
            row.update(_not_eligible_source_gap_payload("NO_ELIGIBLE_BENCHMARK", "该来源未进入核心/辅助对标来源，不做来源缺口判断。"))
            continue
        benchmark_items = [
            benchmark_by_row[alignment_id]
            for alignment_id in row.get("supporting_alignment_ids", [])
            if alignment_id in benchmark_by_row
        ]
        row.update(_source_gap_for_benchmark(
            benchmark_items,
            truths,
            None,
            db=db,
            project=project,
            prompt=prompt,
            retrievals=retrievals or [],
            references=references or [],
        ))
    return rows


def _benchmark_evidence_by_alignment_id(db: Session, support_ids: set[int]) -> dict[int, dict]:
    if not support_ids:
        return {}
    alignments = db.query(EvidenceAlignment).filter(EvidenceAlignment.id.in_(support_ids)).all()
    claim_ids = {alignment.source_claim_id for alignment in alignments if alignment.source_claim_id}
    event_ids = {alignment.recommendation_event_id for alignment in alignments if alignment.recommendation_event_id}
    payload_by_alignment_id = {alignment.id: loads(alignment.machine_payload_json, {}) for alignment in alignments}
    answer_unit_ids = {
        int(payload.get("answer_unit_id"))
        for payload in payload_by_alignment_id.values()
        if payload.get("answer_unit_id")
    }
    claims = db.query(SourceClaim).filter(SourceClaim.id.in_(claim_ids)).all() if claim_ids else []
    events = db.query(RecommendationEvent).filter(RecommendationEvent.id.in_(event_ids)).all() if event_ids else []
    units = db.query(AnswerUnit).filter(AnswerUnit.id.in_(answer_unit_ids)).all() if answer_unit_ids else []
    claim_by_id = {claim.id: claim for claim in claims}
    event_by_id = {event.id: event for event in events}
    unit_by_id = {unit.id: unit for unit in units}
    result: dict[int, dict] = {}
    for alignment in alignments:
        claim = claim_by_id.get(alignment.source_claim_id)
        event = event_by_id.get(alignment.recommendation_event_id)
        payload = payload_by_alignment_id.get(alignment.id, {})
        answer_unit_id = int(payload.get("answer_unit_id") or 0)
        unit = unit_by_id.get(answer_unit_id)
        result[alignment.id] = {
            "alignment_id": alignment.id,
            "source_claim_id": alignment.source_claim_id,
            "recommendation_event_id": alignment.recommendation_event_id,
            "run_id": alignment.run_id,
            "claim_text": claim.normalized_claim if claim else "",
            "source_span": claim.source_span if claim else "",
            "claim_subject": claim.subject_entity if claim else "",
            "claim_object": claim.object_text if claim else "",
            "claim_predicate": claim.predicate if claim else "",
            "event_entity": event.entity_text if event else "",
            "event_answer_span": event.answer_span if event else "",
            "event_reasons": loads(event.reasons_json, []) if event else [],
            "answer_unit_id": answer_unit_id or None,
            "answer_unit_text": (unit.unit_text_normalized or unit.unit_text_original) if unit else "",
            "decision_binding_id": payload.get("decision_binding_id"),
            "reason_source": payload.get("reason_source"),
            "formal_input_version": payload.get("formal_input_version"),
            "observed_run_ids": [alignment.run_id] if alignment.run_id else [],
            "run_coverage_count": 1 if alignment.run_id else 0,
            "run_coverage_denominator": 1,
        }
    return result


def _brand_asset_context(
    db: Session,
    project: Project,
    capability_targets: list[dict] | None = None,
    prompt: Prompt | None = None,
    benchmark_text: str = "",
) -> dict:
    snapshot, audit = _latest_brand_asset_snapshot(db, project, capability_targets or [], prompt, benchmark_text)
    if not snapshot:
        return {
            "status": "INCOMPLETE",
            "snapshot_id": None,
            "text": "",
            "reason": "尚未找到可用的品牌资产页面快照。",
            "relevance_status": "NO_SNAPSHOT",
            "audit": audit,
        }
    text = " ".join([snapshot.title or "", snapshot.h1 or "", snapshot.meta_description or "", snapshot.main_text or ""]).strip()
    if len(text) < 30:
        return {
            "status": "INCOMPLETE",
            "snapshot_id": snapshot.id,
            "url": snapshot.final_url or snapshot.url or snapshot.target_url or snapshot.canonical_url,
            "text": text,
            "reason": "品牌资产快照正文不足，不能可靠判断覆盖情况。",
            "relevance_status": audit.get("relevance_status", "UNKNOWN"),
            "audit": audit,
        }
    return {
        "status": "AVAILABLE",
        "snapshot_id": snapshot.id,
        "url": snapshot.final_url or snapshot.url or snapshot.target_url or snapshot.canonical_url,
        "title": snapshot.title or snapshot.h1 or "",
        "text": text,
        "reason": "已找到可用于判断的品牌资产快照。",
        "relevance_status": audit.get("relevance_status", "UNKNOWN"),
        "audit": audit,
    }


def _latest_brand_asset_snapshot(
    db: Session,
    project: Project,
    capability_targets: list[dict] | None = None,
    prompt: Prompt | None = None,
    benchmark_text: str = "",
) -> tuple[PageSnapshot | None, dict]:
    rows = (
        db.query(PageSnapshot)
        .filter(PageSnapshot.project_id == project.id, PageSnapshot.capture_status == "success")
        .order_by(PageSnapshot.captured_at.desc(), PageSnapshot.id.desc())
        .limit(100)
        .all()
    )
    if not rows:
        return None, {"candidate_snapshot_ids": [], "selected_snapshot_id": None, "relevance_status": "NO_SNAPSHOT"}
    scored = [
        (_brand_asset_relevance_score(project, row, capability_targets or [], prompt, benchmark_text), row)
        for row in rows
    ]
    scored.sort(key=lambda item: (-item[0]["score"], -int(item[1].id or 0)))
    best_score, best_snapshot = scored[0]
    audit = {
        "candidate_snapshot_ids": [row.id for _score, row in scored[:10]],
        "selected_snapshot_id": best_snapshot.id,
        "selected_url": best_snapshot.final_url or best_snapshot.url or best_snapshot.target_url or best_snapshot.canonical_url,
        "selected_title": best_snapshot.title or best_snapshot.h1 or "",
        "relevance_score": best_score["score"],
        "matched_terms": best_score["matched_terms"],
        "relevance_status": "RELEVANT" if best_score["matched_terms"] else "LOW_RELEVANCE",
        "selection_method": "CAPABILITY_PROMPT_RELEVANCE",
    }
    return best_snapshot, audit


def _brand_asset_relevance_score(
    project: Project,
    snapshot: PageSnapshot,
    capability_targets: list[dict],
    prompt: Prompt | None,
    benchmark_text: str,
) -> dict:
    text = " ".join([
        snapshot.target_url or "",
        snapshot.url or "",
        snapshot.final_url or "",
        snapshot.canonical_url or "",
        snapshot.title or "",
        snapshot.h1 or "",
        snapshot.meta_description or "",
        snapshot.main_text or "",
    ])
    text_key = _compact_key(text)
    terms = []
    for target in capability_targets or []:
        label = str(target.get("label") or "")
        if label:
            terms.append(label)
    terms.extend(_important_prompt_terms(prompt.prompt_text if prompt else ""))
    terms.extend(_important_prompt_terms(benchmark_text))
    matched_terms = []
    score = 0
    for term in terms:
        key = _compact_key(term)
        if not key or key in {_compact_key(project.brand_name or ""), "短链", "链接"}:
            continue
        if key in text_key:
            score += 4 if any(key == _compact_key(str(target.get("label") or "")) for target in capability_targets or []) else 1
            if term not in matched_terms:
                matched_terms.append(term)
    target = _normalize_source_url(project.website_url or "")
    if target:
        if target in {
            _normalize_source_url(snapshot.target_url or ""),
            _normalize_source_url(snapshot.url or ""),
            _normalize_source_url(snapshot.final_url or ""),
            _normalize_source_url(snapshot.canonical_url or ""),
        }:
            score += 1
    return {"score": score, "matched_terms": matched_terms[:8]}


def _important_prompt_terms(text: str) -> list[str]:
    cleaned = re.sub(r"[，。！？、；:：\s]+", " ", text or "")
    return [
        token
        for token in cleaned.split()
        if len(_compact_key(token)) >= 4
    ][:8]


def _source_gap_for_benchmark(
    benchmark_items: list[dict],
    truths: list[TargetBrandCapabilityTruth],
    asset: dict | None,
    db: Session | None = None,
    project: Project | None = None,
    prompt: Prompt | None = None,
    retrievals: list[RetrievalCandidate] | None = None,
    references: list[ReferenceSource] | None = None,
) -> dict:
    capability_targets = _benchmark_capability_targets(benchmark_items)
    suggested_capability_label = _suggested_capability_label_for_benchmark(benchmark_items)
    benchmark_text = _benchmark_evidence_text(benchmark_items)
    asset = asset or (_brand_asset_context(db, project, capability_targets, prompt, benchmark_text) if db and project else _empty_brand_asset_context())
    retrieval_context = _brand_asset_retrieval_context(project, asset, capability_targets, retrievals, benchmark_items) if retrievals is not None else _unchecked_retrieval_context()
    adoption_context = _brand_asset_evidence_adoption_context(db, project, prompt, asset, references, benchmark_items) if references is not None else _unchecked_adoption_context()
    if not benchmark_text:
        return {
            **_blocked_source_gap_payload("BENCHMARK_EVIDENCE_INSUFFICIENT", "对标来源缺少可解释的支持文本，暂不生成缺口。"),
            **_capability_gap_context(
                failure_layer="BENCHMARK_EVIDENCE",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=[],
                unmatched_targets=[],
                asset=asset,
                coverage="UNKNOWN",
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }

    if capability_targets:
        matched_truths, unmatched_targets = _match_product_truths_for_capability_targets(capability_targets, truths)
    else:
        matched_truths = _match_product_truths(benchmark_text, truths)
        unmatched_targets = []
    if unmatched_targets:
        return {
            **_source_gap_payload(
            gap_type="UNKNOWN",
            precondition="PRODUCT_TRUTH_UNKNOWN",
            reason="对标证据中的具体能力尚未匹配到同粒度目标品牌事实，不能生成推荐动作。",
            basis=[f"待确认目标品牌事实: {target}" for target in unmatched_targets[:6]],
            truths=matched_truths,
            asset=asset,
            coverage="UNKNOWN",
            ),
            **_capability_gap_context(
                failure_layer="PRODUCT_TRUTH",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=unmatched_targets,
                asset=asset,
                coverage="UNKNOWN",
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    if not matched_truths:
        return {
            **_source_gap_payload(
            gap_type="UNKNOWN",
            precondition="PRODUCT_TRUTH_UNKNOWN",
            reason="对标证据尚未匹配到人工确认的目标品牌事实。",
            basis=["没有可匹配的目标品牌能力事实，不能推导 Source Gap。"],
            truths=[],
            asset=asset,
            coverage="UNKNOWN",
            ),
            **_capability_gap_context(
                failure_layer="PRODUCT_TRUTH",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=[],
                unmatched_targets=[],
                asset=asset,
                coverage="UNKNOWN",
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    status = _combined_product_truth_status(matched_truths)
    if status == "FALSE":
        return {
            **_source_gap_payload(
            gap_type="PRODUCT_GAP",
            precondition="READY",
            reason="对标证据对应真实决策理由，但目标品牌事实显示目标品牌不支持该能力。",
            basis=["PRODUCT_GAP 是高价值产品发现，不等于无需处理。"],
            truths=matched_truths,
            asset=asset,
            coverage="NOT_APPLICABLE",
            ),
            **_capability_gap_context(
                failure_layer="PRODUCT_TRUTH",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=[],
                asset=asset,
                coverage="NOT_APPLICABLE",
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    if status == "UNKNOWN":
        return {
            **_source_gap_payload(
            gap_type="UNKNOWN",
            precondition="PRODUCT_TRUTH_UNKNOWN",
            reason="目标品牌事实尚未确认，不能判断内容、证据或产品缺口。",
            basis=["目标品牌事实未知时保守输出 UNKNOWN。"],
            truths=matched_truths,
            asset=asset,
            coverage="UNKNOWN",
            ),
            **_capability_gap_context(
                failure_layer="PRODUCT_TRUTH",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=[],
                asset=asset,
                coverage="UNKNOWN",
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    if asset.get("status") != "AVAILABLE":
        return {
            **_source_gap_payload(
            gap_type="UNKNOWN",
            precondition="BRAND_ASSET_INCOMPLETE",
            reason=asset.get("reason") or "品牌资产不完整，不能判断覆盖情况。",
            basis=["缺少可用品牌资产快照时保守输出 UNKNOWN。"],
            truths=matched_truths,
            asset=asset,
            coverage="UNKNOWN",
            ),
            **_capability_gap_context(
                failure_layer="RELEVANT_ASSET_EXPRESSION",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=[],
                asset=asset,
                coverage="UNKNOWN",
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }

    coverage = _existing_asset_coverage(asset.get("text", ""), benchmark_text, matched_truths)
    if coverage == "MISSING":
        return {
            **_source_gap_payload(
            gap_type="CONTENT_GAP",
            precondition="READY",
            reason="目标品牌事实已确认，但现有品牌资产未覆盖对标来源中的关键能力表达。",
            basis=["对标来源有重要证据，目标品牌真实支持，但现有资产未覆盖或表达不足。"],
            truths=matched_truths,
            asset=asset,
            coverage=coverage,
            ),
            **_capability_gap_context(
                failure_layer="RELEVANT_ASSET_EXPRESSION",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=[],
                asset=asset,
                coverage=coverage,
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    if coverage == "CLAIM_ONLY":
        return {
            **_source_gap_payload(
            gap_type="EVIDENCE_GAP",
            precondition="READY",
            reason="现有品牌资产已经声称该能力，但缺少对标来源具备的案例、数据、证明、场景或具体性。",
            basis=["目标品牌事实已确认且资产已有能力声明，但证据强度不足。"],
            truths=matched_truths,
            asset=asset,
            coverage=coverage,
            ),
            **_capability_gap_context(
                failure_layer="RELEVANT_ASSET_EXPRESSION",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=[],
                asset=asset,
                coverage=coverage,
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    if retrieval_context.get("status") != "NOT_CHECKED" and not retrieval_context.get("retrieved"):
        return {
            **_source_gap_payload(
                gap_type="DISCOVERABILITY_GAP",
                precondition="READY",
                reason="目标品牌已有相关资产表达，但该资产未进入当前 Prompt 的有效检索候选。",
                basis=["Discoverability 只基于当前证据包内有效 RetrievalCandidate 判断，不从任意品牌资产推断。"],
                truths=matched_truths,
                asset=asset,
                coverage=coverage,
            ),
            **_capability_gap_context(
                failure_layer="RETRIEVAL_CANDIDATE",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=[],
                asset=asset,
                coverage=coverage,
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    if adoption_context.get("status") != "NOT_CHECKED" and not adoption_context.get("adopted"):
        return {
            **_source_gap_payload(
                gap_type="EVIDENCE_GAP",
                precondition="EVIDENCE_ADOPTION_MISSING",
                reason="目标品牌相关资产已进入有效检索候选，但当前答案未形成引用或 Evidence Adoption 上下文。",
                basis=["Evidence Adoption 层只描述当前样本中的引用/采纳上下文，不证明模型内部因果。"],
                truths=matched_truths,
                asset=asset,
                coverage=coverage,
            ),
            **_capability_gap_context(
                failure_layer="EVIDENCE_ADOPTION",
                benchmark_items=benchmark_items,
                capability_targets=capability_targets,
                truths=matched_truths,
                unmatched_targets=[],
                asset=asset,
                coverage=coverage,
                retrieval_context=retrieval_context,
                adoption_context=adoption_context,
            ),
            "suggested_capability_label": suggested_capability_label,
        }
    return {
        **_source_gap_payload(
            gap_type="NO_GAP",
            precondition="READY",
            reason="Product Truth 已确认，现有品牌资产已充分覆盖关键 Evidence，且当前样本中已出现检索和引用/采纳上下文。",
            basis=["目标品牌资产已覆盖对标来源关键能力与证据表达，并通过 RetrievalCandidate 与 Evidence Adoption 检查。"],
            truths=matched_truths,
            asset=asset,
            coverage=coverage,
        ),
        **_capability_gap_context(
            failure_layer="NONE",
            benchmark_items=benchmark_items,
            capability_targets=capability_targets,
            truths=matched_truths,
            unmatched_targets=[],
            asset=asset,
            coverage=coverage,
            retrieval_context=retrieval_context,
            adoption_context=adoption_context,
        ),
        "suggested_capability_label": suggested_capability_label,
    }


def _empty_brand_asset_context() -> dict:
    return {
        "status": "INCOMPLETE",
        "snapshot_id": None,
        "url": "",
        "title": "",
        "text": "",
        "reason": "未提供可审计品牌资产快照。",
        "relevance_status": "NO_CONTEXT",
        "audit": {"candidate_snapshot_ids": [], "selected_snapshot_id": None},
    }


def _unchecked_retrieval_context() -> dict:
    return {"status": "NOT_CHECKED", "retrieved": None, "valid_retrieval_count": 0, "matched_retrievals": []}


def _unchecked_adoption_context() -> dict:
    return {"status": "NOT_CHECKED", "adopted": None, "matched_citations": [], "matched_adoptions": []}


def _capability_gap_context(
    failure_layer: str,
    benchmark_items: list[dict],
    capability_targets: list[dict],
    truths: list[TargetBrandCapabilityTruth],
    unmatched_targets: list[str],
    asset: dict,
    coverage: str,
    retrieval_context: dict,
    adoption_context: dict,
) -> dict:
    evidence_run_ids = sorted({
        int(run_id)
        for item in benchmark_items
        for run_id in item.get("observed_run_ids", [])
        if run_id
    })
    support_alignment_ids = sorted({
        int(item.get("alignment_id"))
        for item in benchmark_items
        if item.get("alignment_id")
    })
    return {
        "capability_gap_layer": failure_layer,
        "capability_truth_targets": capability_targets,
        "unmatched_capability_truth_targets": unmatched_targets,
        "relevant_asset_snapshot": {
            "status": asset.get("status", "UNKNOWN"),
            "snapshot_id": asset.get("snapshot_id"),
            "url": asset.get("url", ""),
            "title": asset.get("title", ""),
            "relevance_status": asset.get("relevance_status", "UNKNOWN"),
            "coverage": coverage,
            "reason": asset.get("reason", ""),
            "audit": asset.get("audit", {}),
        },
        "retrieval_candidate_context": retrieval_context,
        "evidence_adoption_context": adoption_context,
        "capability_gap_diagnosis": {
            "diagnosis_version": "capability_gap.phase2b.v1",
            "failure_layer": failure_layer,
            "decision_tree": [
                "PRODUCT_TRUTH",
                "RELEVANT_ASSET_EXPRESSION",
                "RETRIEVAL_CANDIDATE",
                "EVIDENCE_ADOPTION",
            ],
            "matched_product_truth_ids": [truth.id for truth in truths],
            "matched_product_truth_status": _combined_product_truth_status(truths) if truths else "UNKNOWN",
            "capability_truth_targets": capability_targets,
            "unmatched_capability_truth_targets": unmatched_targets,
            "relevant_asset_snapshot": {
                "snapshot_id": asset.get("snapshot_id"),
                "url": asset.get("url", ""),
                "title": asset.get("title", ""),
                "coverage": coverage,
                "relevance_status": asset.get("relevance_status", "UNKNOWN"),
                "audit": asset.get("audit", {}),
            },
            "retrieval_candidate_context": retrieval_context,
            "evidence_adoption_context": adoption_context,
            "eligible_evidence_lineage": {
                "supporting_alignment_ids": support_alignment_ids,
                "observed_run_ids": evidence_run_ids,
            },
        },
    }


def _brand_asset_retrieval_context(
    project: Project | None,
    asset: dict,
    capability_targets: list[dict],
    retrievals: list[RetrievalCandidate],
    benchmark_items: list[dict],
) -> dict:
    observed_run_ids = _observed_run_ids_from_benchmark_items(benchmark_items)
    valid_retrievals = [
        item
        for item in retrievals
        if _valid_retrieval_candidate(item, observed_run_ids)
    ]
    matches = [
        item
        for item in valid_retrievals
        if _source_matches_brand_asset(project, asset, capability_targets, item.url, item.canonical_url, item.domain, item.title)
    ]
    return {
        "status": "RETRIEVED" if matches else "NOT_RETRIEVED",
        "retrieved": bool(matches),
        "valid_retrieval_count": len(valid_retrievals),
        "observed_run_ids": sorted(observed_run_ids),
        "matched_retrievals": [
            {
                "id": item.id,
                "run_id": item.run_id,
                "rank": item.rank,
                "title": item.title or "",
                "url": item.url or item.canonical_url or "",
                "domain": item.domain or host_from_url(item.url or item.canonical_url or ""),
            }
            for item in matches[:10]
        ],
        "rule": "仅使用当前证据包 Run 内有 URL/域名/标题信号的有效 RetrievalCandidate。",
    }


def _brand_asset_evidence_adoption_context(
    db: Session | None,
    project: Project | None,
    prompt: Prompt | None,
    asset: dict,
    references: list[ReferenceSource] | None,
    benchmark_items: list[dict],
) -> dict:
    observed_run_ids = _observed_run_ids_from_benchmark_items(benchmark_items)
    matched_refs = [
        ref
        for ref in (references or [])
        if ref.run_id in observed_run_ids
        and _source_matches_brand_asset(project, asset, [], ref.url, ref.canonical_url, ref.domain, ref.display_title or ref.matched_title)
    ]
    matched_adoptions: list[DecisionEvidenceAdoption] = []
    if db and project and prompt and observed_run_ids:
        adoption_rows = db.query(DecisionEvidenceAdoption).filter(
            DecisionEvidenceAdoption.project_id == project.id,
            DecisionEvidenceAdoption.prompt_id == prompt.id,
            DecisionEvidenceAdoption.run_id.in_(observed_run_ids),
        ).all()
        matched_adoptions = [
            row
            for row in adoption_rows
            if row.cited and _source_matches_brand_asset(project, asset, [], row.source_url, "", row.source_domain, row.source_title)
        ]
    adopted = bool(matched_refs or matched_adoptions)
    return {
        "status": "ADOPTED_OR_CITED" if adopted else "NOT_ADOPTED",
        "adopted": adopted,
        "observed_run_ids": sorted(observed_run_ids),
        "matched_citations": [
            {
                "id": ref.id,
                "run_id": ref.run_id,
                "title": ref.display_title or ref.matched_title or "",
                "url": ref.url or ref.canonical_url or "",
                "domain": ref.domain or host_from_url(ref.url or ref.canonical_url or ""),
            }
            for ref in matched_refs[:10]
        ],
        "matched_adoptions": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "evidence_status": row.evidence_status,
                "support_role": row.support_role,
                "source_title": row.source_title or "",
                "source_url": row.source_url or "",
            }
            for row in matched_adoptions[:10]
        ],
        "boundary_note": "引用/采纳上下文不等于模型内部因果，只用于判断当前样本是否出现目标品牌资产采纳迹象。",
    }


def _observed_run_ids_from_benchmark_items(items: list[dict]) -> set[int]:
    result: set[int] = set()
    for item in items:
        for run_id in item.get("observed_run_ids") or []:
            if run_id:
                result.add(int(run_id))
        if item.get("run_id"):
            result.add(int(item["run_id"]))
    return result


def _valid_retrieval_candidate(item: RetrievalCandidate, allowed_run_ids: set[int]) -> bool:
    if allowed_run_ids and item.run_id not in allowed_run_ids:
        return False
    if not (item.url or item.canonical_url or item.domain or item.title):
        return False
    return item.rank is None or int(item.rank or 0) >= 0


def _source_matches_brand_asset(
    project: Project | None,
    asset: dict,
    capability_targets: list[dict],
    url: str,
    canonical_url: str,
    domain: str,
    title: str,
) -> bool:
    asset_url = _normalize_source_url(asset.get("url") or "")
    source_urls = {
        _normalize_source_url(url or ""),
        _normalize_source_url(canonical_url or ""),
    }
    if asset_url and asset_url in source_urls:
        return True
    asset_domain = host_from_url(asset.get("url") or "") or ""
    source_domain = (domain or host_from_url(url or canonical_url or "") or "").lower().removeprefix("www.")
    brand_domain = host_from_url(project.website_url) if project and project.website_url else ""
    domains_match = bool(source_domain and source_domain in {
        asset_domain.lower().removeprefix("www."),
        brand_domain.lower().removeprefix("www."),
    })
    if not domains_match:
        return False
    source_text = _compact_key(" ".join([url or "", canonical_url or "", title or ""]))
    brand_key = _compact_key(project.brand_name if project else "")
    if brand_key and brand_key in source_text:
        return True
    audit_terms = [
        str(term)
        for term in ((asset.get("audit") or {}).get("matched_terms") or [])
    ]
    target_terms = [str(target.get("label") or "") for target in capability_targets or []]
    return any(_compact_key(term) and _compact_key(term) in source_text for term in [*audit_terms, *target_terms])


def _benchmark_evidence_text(items: list[dict]) -> str:
    parts: list[str] = []
    for item in items:
        parts.extend([
            item.get("claim_text", ""),
            item.get("source_span", ""),
            item.get("claim_object", ""),
            item.get("claim_predicate", ""),
            item.get("event_answer_span", ""),
        ])
        parts.extend(_relevant_event_reason_texts(item))
    return " ".join(part for part in parts if part).strip()


def _benchmark_capability_targets(items: list[dict]) -> list[dict]:
    targets_by_key: dict[str, dict] = {}
    for item in items:
        candidates = [
            (item.get("answer_unit_text", ""), "ANSWER_UNIT"),
            *[(text, "RECOMMENDATION_REASON") for text in _relevant_event_reason_texts(item)],
            (item.get("claim_object", ""), "SOURCE_CLAIM_OBJECT"),
        ]
        for candidate, source in candidates:
            label = _compact_capability_label(candidate, items)
            key = _compact_key(label)
            if not key:
                continue
            run_ids = [int(run_id) for run_id in (item.get("observed_run_ids") or []) if run_id]
            if item.get("run_id"):
                run_ids.append(int(item["run_id"]))
            if key not in targets_by_key:
                targets_by_key[key] = {
                    "label": label,
                    "source": source,
                    "answer_unit_id": item.get("answer_unit_id"),
                    "alignment_id": item.get("alignment_id"),
                    "alignment_ids": [],
                    "observed_run_ids": [],
                    "run_coverage_count": 0,
                }
            target = targets_by_key[key]
            if item.get("alignment_id") and int(item["alignment_id"]) not in target["alignment_ids"]:
                target["alignment_ids"].append(int(item["alignment_id"]))
            target["observed_run_ids"] = sorted({*target["observed_run_ids"], *run_ids})
            target["run_coverage_count"] = len(target["observed_run_ids"])
            break
    return list(targets_by_key.values())[:8]


def _suggested_capability_label_for_benchmark(items: list[dict]) -> str:
    labels: list[str] = []
    for target in _benchmark_capability_targets(items):
        label = target.get("label")
        if label and label not in labels:
            labels.append(label)
    for item in items:
        relevant_reasons = _relevant_event_reason_texts(item)
        candidates = relevant_reasons or [
            item.get("claim_object", ""),
            item.get("claim_text", ""),
            item.get("source_span", ""),
        ]
        for candidate in candidates:
            label = _compact_capability_label(candidate, items)
            if label and label not in labels:
                labels.append(label)

    if labels:
        return " / ".join(labels[:3])
    return ""


def _relevant_event_reason_texts(item: dict) -> list[str]:
    item_text = _compact_key(" ".join([
        item.get("claim_text", ""),
        item.get("source_span", ""),
        item.get("claim_object", ""),
        item.get("claim_subject", ""),
    ]))
    result: list[str] = []
    for reason in item.get("event_reasons", []) or []:
        if isinstance(reason, dict):
            text = reason.get("normalized_reason") or reason.get("text") or reason.get("reason_span") or ""
        else:
            text = str(reason)
        if text and _reason_matches_source_claim(text, item_text):
            result.append(text)
    return result


def _reason_matches_source_claim(reason: str, item_text: str) -> bool:
    reason_key = _compact_key(reason)
    if not reason_key or not item_text:
        return False
    if reason_key in item_text or item_text in reason_key:
        return True
    return _capability_token_overlap(reason_key, item_text)


def _capability_token_overlap(needle: str, haystack: str) -> bool:
    tokens = [
        token
        for token in _CAPABILITY_MATCH_TOKENS
        if token in needle
    ]
    if not tokens:
        return False
    matched = sum(1 for token in tokens if token in haystack)
    if "拦截" in needle and any(token in haystack for token in ["风控", "审核", "避免"]):
        matched += 1
    if "平台" in needle and any(token in haystack for token in ["抖音", "微信", "小红书", "视频号"]):
        matched += 1
    if "规避" in needle and any(token in haystack for token in ["避免", "风控", "审核"]):
        matched += 1
    if "短链" in needle and "跳转链接" in haystack:
        matched += 1
    return matched >= 2 and matched / len(tokens) >= 0.5


_CAPABILITY_MATCH_TOKENS = [
    "抖音", "微信", "跳转", "合规", "高效", "路径", "搭建", "外链", "短链",
    "链接", "自动", "加密", "平台", "拦截", "风控", "审核", "导流", "落地页",
    "私域", "获客", "加粉", "回传", "投放", "人群", "批量", "生成", "管理",
    "案例", "数据", "证明", "转化", "监测", "统计", "二维码",
]


def _compact_capability_label(text: str, items: list[dict]) -> str:
    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text or "").strip()
    if not value:
        return ""
    for item in items:
        for entity in (item.get("event_entity"), item.get("claim_subject")):
            if entity:
                value = value.replace(str(entity), "")
    value = re.sub(r"20\d{2}\s*版?", "", value)
    value = re.sub(r"(教程|手把手|零技术入门|完整教程|操作流程|方法|方案|推荐理由|因为|案例显示|客户案例|数据证明)", "", value)
    value = re.sub(r"(已服务|服务)\s*\d+\s*(家|个|位)?客户?", "", value)
    value = re.sub(r"成功率\s*\d+[%％]", "", value)
    value = re.sub(r"\d+\s*(家|个|次|天|小时|分钟|秒|%|％)", "", value)
    value = re.sub(r"(支持|具备|提供|可以|能够|实现|适合|并有|显示|证明|自带)", "", value)
    value = re.sub(r"[：:，,。；;、（）()【】\\[\\]\"'“”]+", " ", value)
    words = [word.strip() for word in value.split() if word.strip()]
    compact = "".join(words)
    if len(compact) < 4:
        return ""
    if len(compact) > 32:
        compact = compact[:32]
    return compact


def _match_product_truths(benchmark_text: str, truths: list[TargetBrandCapabilityTruth]) -> list[TargetBrandCapabilityTruth]:
    haystack = _compact_key(benchmark_text)
    matches: list[TargetBrandCapabilityTruth] = []
    for truth in truths:
        needles = [_compact_key(truth.capability_label), _compact_key(truth.capability_key)]
        if any(needle and needle in haystack for needle in needles) or any(
            _capability_token_match(needle, haystack) for needle in needles if needle
        ):
            matches.append(truth)
    return matches


def _match_product_truths_for_capability_targets(
    targets: list[dict],
    truths: list[TargetBrandCapabilityTruth],
) -> tuple[list[TargetBrandCapabilityTruth], list[str]]:
    matches: list[TargetBrandCapabilityTruth] = []
    unmatched: list[str] = []
    seen_truth_ids: set[int] = set()
    for target in targets:
        label = str(target.get("label") or "")
        target_matches = [
            truth
            for truth in truths
            if _product_truth_matches_capability_label(label, truth)
        ]
        if not target_matches:
            unmatched.append(label)
            continue
        for truth in target_matches:
            if truth.id not in seen_truth_ids:
                seen_truth_ids.add(truth.id)
                matches.append(truth)
    return matches, unmatched


def _product_truth_matches_capability_label(label: str, truth: TargetBrandCapabilityTruth) -> bool:
    target_key = _compact_key(label)
    if not target_key:
        return False
    needles = [_compact_key(truth.capability_label), _compact_key(truth.capability_key)]
    for needle in needles:
        if not needle:
            continue
        if needle in target_key or target_key in needle:
            return True
    return False


def _capability_token_match(needle: str, haystack: str) -> bool:
    tokens = [
        token
        for token in _CAPABILITY_MATCH_TOKENS
        if token in needle
    ]
    if not tokens:
        return False
    matched = sum(1 for token in tokens if token in haystack)
    return matched >= 2 and matched / len(tokens) >= 0.5


def _combined_product_truth_status(truths: list[TargetBrandCapabilityTruth]) -> str:
    statuses = {(truth.product_truth_status or "UNKNOWN").upper() for truth in truths}
    if "NOT_SUPPORTED" in statuses:
        return "FALSE"
    if statuses and statuses <= {"SUPPORTED", "PARTIALLY_SUPPORTED"}:
        return "TRUE"
    return "UNKNOWN"


def _existing_asset_coverage(asset_text: str, benchmark_text: str, truths: list[TargetBrandCapabilityTruth]) -> str:
    asset_key = _compact_key(asset_text)
    truth_covered = any(
        needle and needle in asset_key
        for truth in truths
        for needle in (_compact_key(truth.capability_label), _compact_key(truth.capability_key))
    )
    if not truth_covered:
        return "MISSING"
    benchmark_has_proof = _has_evidence_strength_signal(benchmark_text)
    asset_has_proof = _has_evidence_strength_signal(asset_text)
    if benchmark_has_proof and not asset_has_proof:
        return "CLAIM_ONLY"
    return "SUFFICIENT"


def _has_evidence_strength_signal(text: str) -> bool:
    normalized = text or ""
    if re.search(r"\d+[%％]|\d+\s*(个|家|次|天|小时|分钟|秒|%|％)", normalized):
        return True
    return any(
        token in normalized
        for token in ["案例", "客户", "数据", "证明", "实测", "效果", "转化", "成功率", "场景", "示例", "对比", "步骤"]
    )


def _compact_key(value: str) -> str:
    cleaned = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value or "")
    return re.sub(r"[\s\W_]+", "", cleaned.lower())


def _not_eligible_source_gap_payload(precondition: str, reason: str) -> dict:
    return {
        "source_gap_type": None,
        "source_gap_label": "",
        "source_gap_reason": reason,
        "source_gap_basis": [],
        "source_gap_precondition": precondition,
        "gap_analysis_status": "NOT_ELIGIBLE",
        "capability_gap_layer": "",
        "capability_gap_diagnosis": {},
        "capability_gap_items": [],
        "matched_product_truth_ids": [],
        "matched_product_truth_status": "UNKNOWN",
        "capability_truth_targets": [],
        "unmatched_capability_truth_targets": [],
        "existing_asset_status": "UNKNOWN",
        "existing_asset_snapshot_id": None,
        "existing_asset_coverage": "UNKNOWN",
        "relevant_asset_snapshot": {},
        "retrieval_candidate_context": {},
        "evidence_adoption_context": {},
    }


def _blocked_source_gap_payload(precondition: str, reason: str) -> dict:
    return {
        "source_gap_type": "UNKNOWN",
        "source_gap_label": "无法判断",
        "source_gap_reason": reason,
        "source_gap_basis": [reason],
        "source_gap_precondition": precondition,
        "gap_analysis_status": "BLOCKED",
        "capability_gap_layer": "",
        "capability_gap_diagnosis": {},
        "capability_gap_items": [],
        "matched_product_truth_ids": [],
        "matched_product_truth_status": "UNKNOWN",
        "capability_truth_targets": [],
        "unmatched_capability_truth_targets": [],
        "existing_asset_status": "UNKNOWN",
        "existing_asset_snapshot_id": None,
        "existing_asset_coverage": "UNKNOWN",
        "relevant_asset_snapshot": {},
        "retrieval_candidate_context": {},
        "evidence_adoption_context": {},
    }


def _source_gap_payload(
    gap_type: str,
    precondition: str,
    reason: str,
    basis: list[str],
    truths: list[TargetBrandCapabilityTruth],
    asset: dict,
    coverage: str,
) -> dict:
    status = _combined_product_truth_status(truths) if truths else "UNKNOWN"
    return {
        "source_gap_type": gap_type,
        "source_gap_label": _source_gap_label(gap_type),
        "source_gap_reason": reason,
        "source_gap_basis": basis,
        "source_gap_precondition": precondition,
        "gap_analysis_status": "ANALYZED" if precondition == "READY" else "BLOCKED",
        "matched_product_truth_ids": [truth.id for truth in truths],
        "matched_product_truth_status": status,
        "existing_asset_status": asset.get("status", "UNKNOWN"),
        "existing_asset_snapshot_id": asset.get("snapshot_id"),
        "existing_asset_coverage": coverage,
    }


def _source_gap_label(gap_type: str) -> str:
    return {
        "CONTENT_GAP": "内容缺口",
        "EVIDENCE_GAP": "证据缺口",
        "PRODUCT_GAP": "产品缺口",
        "DISCOVERABILITY_GAP": "可发现性缺口",
        "NO_GAP": "暂无缺口",
        "UNKNOWN": "无法判断",
    }.get(gap_type, gap_type)


def _attach_capability_gap_items(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["capability_gap_items"] = _capability_gap_items_for_row(row)
    return rows


def _capability_gap_items_for_row(row: dict) -> list[dict]:
    gap_type = row.get("source_gap_type")
    tier = row.get("benchmark_tier")
    if not gap_type or tier not in {"PRIMARY_BENCHMARK", "SECONDARY_BENCHMARK"}:
        return []
    targets = row.get("capability_truth_targets") or []
    if not targets:
        targets = [{
            "label": row.get("suggested_capability_label") or _truth_label_for_row(row) or "未命名能力",
            "source": "SOURCE_GAP_DERIVED",
            "alignment_ids": row.get("supporting_alignment_ids", []),
            "observed_run_ids": row.get("observed_run_ids", []),
        }]
    diagnosis = row.get("capability_gap_diagnosis") or {}
    lineage = diagnosis.get("eligible_evidence_lineage") or {}
    benchmark_source = _benchmark_source_for_row(row)
    items: list[dict] = []
    for target in targets:
        label = str(target.get("label") or "").strip()
        if not label:
            continue
        alignment_ids = sorted({
            int(value)
            for value in (target.get("alignment_ids") or [target.get("alignment_id")] or [])
            if value
        })
        if not alignment_ids:
            alignment_ids = [int(value) for value in lineage.get("supporting_alignment_ids", []) if value]
        observed_run_ids = sorted({
            int(value)
            for value in (target.get("observed_run_ids") or lineage.get("observed_run_ids") or [])
            if value
        })
        raw_key = "|".join(str(part or "") for part in [
            row.get("source_document_id"),
            label,
            gap_type,
            row.get("capability_gap_layer"),
            ",".join(str(item) for item in alignment_ids),
        ])
        items.append({
            "gap_item_id": hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16],
            "source_document_id": row.get("source_document_id"),
            "capability_label": label,
            "capability_source": target.get("source") or "UNKNOWN",
            "answer_unit_id": target.get("answer_unit_id"),
            "gap_type": gap_type,
            "gap_label": row.get("source_gap_label") or _source_gap_label(str(gap_type)),
            "gap_precondition": row.get("source_gap_precondition"),
            "gap_layer": row.get("capability_gap_layer") or diagnosis.get("failure_layer") or "",
            "benchmark_tier": tier,
            "decision_support_level": row.get("decision_support_level"),
            "benchmark_evidence_ids": alignment_ids,
            "benchmark_source": benchmark_source,
            "product_truth_ids": row.get("matched_product_truth_ids", []),
            "product_truth_status": row.get("matched_product_truth_status", "UNKNOWN"),
            "relevant_asset_snapshot": row.get("relevant_asset_snapshot") or {},
            "retrieval_candidate_context": row.get("retrieval_candidate_context") or {},
            "evidence_adoption_context": row.get("evidence_adoption_context") or {},
            "observed_run_ids": observed_run_ids,
            "run_coverage_count": len(observed_run_ids),
            "lineage_source": "PHASE2A_ELIGIBLE_ALIGNMENT",
        })
    return items


def _attach_priority_action_routes(rows: list[dict]) -> list[dict]:
    for row in rows:
        row.update(_priority_action_for_row(row))
    return rows


def _priority_action_for_row(row: dict) -> dict:
    tier = (row.get("benchmark_tier") or "").upper()
    gap_type = row.get("source_gap_type")
    if gap_type is None:
        if tier == "REFERENCE_ONLY":
            return _priority_action_payload(
                priority_level="NOT_PRIORITY",
                action_route=None,
                reason="该来源只是 Reference Only，不进入优化机会队列。",
                basis=["REFERENCE_ONLY 不能因 Citation Prominence 高而升级为优先项。"],
            )
        return _priority_action_payload(
            priority_level=None,
            action_route=None,
            reason="该来源未进入对标来源或缺口分析，不判断优先级和处理路径。",
            basis=[],
        )
    gap_type = (gap_type or "").upper()
    if gap_type in {"CONTENT_GAP", "EVIDENCE_GAP", "PRODUCT_GAP"}:
        priority = "PRIORITY_HIGH" if tier == "PRIMARY_BENCHMARK" else "PRIORITY_MEDIUM" if tier == "SECONDARY_BENCHMARK" else None
        route = {
            "CONTENT_GAP": "CONTENT",
            "EVIDENCE_GAP": "EVIDENCE",
            "PRODUCT_GAP": "PRODUCT",
        }[gap_type]
        return _priority_action_payload(
            priority_level=priority,
            action_route=route,
            reason="该来源已进入对标来源且存在可解释来源缺口。",
            basis=[f"对标层级: {tier}", f"来源缺口: {gap_type}"],
        )
    if gap_type == "NO_GAP":
        return _priority_action_payload(
            priority_level="NOT_PRIORITY",
            action_route="NO_ACTION",
            reason="该来源已分析且未发现目标品牌差距。",
            basis=["source_gap_type = NO_GAP"],
        )
    if gap_type == "UNKNOWN" and tier in {"PRIMARY_BENCHMARK", "SECONDARY_BENCHMARK"}:
        return _priority_action_payload(
            priority_level="UNRESOLVED",
            action_route="UNRESOLVED",
            reason="该来源有对标价值，但关键事实不足，暂不能判断优先级和路径。",
            basis=[f"source_gap_precondition = {row.get('source_gap_precondition') or 'UNKNOWN'}"],
        )
    return _priority_action_payload(
        priority_level=None,
        action_route=None,
        reason="该来源不满足优先级判断条件。",
        basis=[],
    )


def _priority_action_payload(
    priority_level: str | None,
    action_route: str | None,
    reason: str,
    basis: list[str],
) -> dict:
    return {
        "priority_level": priority_level,
        "priority_label": _priority_label(priority_level),
        "priority_reason": reason,
        "priority_basis": basis,
        "action_route": action_route,
        "action_route_label": _action_route_label(action_route),
        "action_route_reason": reason,
    }


def _priority_label(priority_level: str | None) -> str:
    return {
        "PRIORITY_HIGH": "高优先级",
        "PRIORITY_MEDIUM": "中优先级",
        "NOT_PRIORITY": "非优先项",
        "UNRESOLVED": "待判断",
    }.get(priority_level or "", "")


def _action_route_label(action_route: str | None) -> str:
    return {
        "CONTENT": "内容路径",
        "EVIDENCE": "证据路径",
        "PRODUCT": "产品路径",
        "NO_ACTION": "无需动作",
        "UNRESOLVED": "待判断",
    }.get(action_route or "", "")


def _priority_rank(priority_level: str | None) -> int:
    return {
        "PRIORITY_HIGH": 1,
        "PRIORITY_MEDIUM": 2,
        "UNRESOLVED": 3,
        "NOT_PRIORITY": 4,
    }.get((priority_level or "").upper(), 5)


def _attach_recommended_actions(
    rows: list[dict],
    project: Project,
    prompt: Prompt | None,
) -> list[dict]:
    for row in rows:
        row["recommended_action"] = _recommended_action_for_row(row, project, prompt)
    return rows


def _recommended_action_for_row(row: dict, project: Project, prompt: Prompt | None) -> dict | None:
    route = (row.get("action_route") or "").upper()
    priority = (row.get("priority_level") or "").upper()
    gap_type = (row.get("source_gap_type") or "").upper()
    if route not in {"CONTENT", "EVIDENCE", "PRODUCT"} or priority not in {"PRIORITY_HIGH", "PRIORITY_MEDIUM"}:
        return None

    prompt_text = (prompt.prompt_text if prompt else "") or "当前 Prompt"
    benchmark_title = row.get("title") or row.get("domain") or "对标来源"
    gap_items = row.get("capability_gap_items") or []
    truth_label = _capability_label_for_strategy_items(gap_items) or _truth_label_for_row(row) or "已确认能力"
    proof_focus = _proof_focus_for_row(row)
    action_key = _stable_action_key(row)

    if route == "CONTENT":
        summary = f"围绕「{prompt_text}」补齐「{truth_label}」的直接说明、适用场景和限制条件。"
        planned_change = (
            f"参考对标来源「{benchmark_title}」的表达方式，在目标品牌资产中新增可摘录段落："
            f"先直接回答用户问题，再说明 {truth_label} 的使用场景、边界、操作步骤和 FAQ。"
        )
        content_requirements = ["直接回答 Prompt", "能力事实说明", "适用场景", "限制条件", "操作步骤", "FAQ"]
    elif route == "EVIDENCE":
        summary = f"为「{truth_label}」补强案例、数据、证明或具体场景。"
        planned_change = (
            f"当前品牌资产已有能力声明，但证据强度弱于对标来源「{benchmark_title}」。"
            f"需要补充 {proof_focus}，并避免无法验证的营销表述。"
        )
        content_requirements = ["真实案例", "数据或结果", "截图/流程证据", "适用条件", "可验证来源"]
    else:
        summary = f"将「{truth_label}」作为产品机会评估，不生成对外能力宣称。"
        planned_change = (
            f"对标来源「{benchmark_title}」对应的真实决策理由目前未被目标品牌事实支持。"
            "该发现应进入产品/运营评估；在目标品牌事实更新前不能创建内容承诺或发布实验。"
        )
        content_requirements = ["产品可行性评估", "能力边界确认", "Product Truth 更新", "再决定是否内容化"]

    return {
        "action_key": action_key,
        "status": "PROPOSAL_ONLY",
        "route": route,
        "route_label": _action_route_label(route),
        "priority_level": priority,
        "priority_label": _priority_label(priority),
        "gap_type": gap_type,
        "gap_label": row.get("source_gap_label") or _source_gap_label(gap_type),
        "title": summary,
        "summary": summary,
        "planned_change": planned_change,
        "content_requirements": content_requirements,
        "gap_items": gap_items,
        "gap_item_ids": [item.get("gap_item_id") for item in gap_items if item.get("gap_item_id")],
        "benchmark_source": _benchmark_source_for_row(row),
        "benchmark_basis": row.get("benchmark_basis", []),
        "decision_support_level": row.get("decision_support_level", "NONE"),
        "source_gap_basis": row.get("source_gap_basis", []),
        "product_truth_ids": row.get("matched_product_truth_ids", []),
        "product_truth_status": row.get("matched_product_truth_status", "UNKNOWN"),
        "channel_opportunity": row.get("channel_opportunity"),
        "execution_boundary": "策略候选 -> 人工确认 -> effective_payload=VALIDATED -> 动作/实验。产品缺口不生成虚假内容宣称。",
    }


def _attach_channel_opportunities(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    brand_platforms = {
        _channel_key_for_row(row)
        for row in rows
        if row.get("ownership") in {"official", "brand_related"} and _channel_key_for_row(row)
    }
    for row in rows:
        channel_key = _channel_key_for_row(row)
        if channel_key:
            grouped[channel_key].append(row)

    qualified_channels: dict[str, dict] = {}
    for channel_key, items in grouped.items():
        benchmark_items = [
            item for item in items
            if item.get("benchmark_tier") in {"PRIMARY_BENCHMARK", "SECONDARY_BENCHMARK"}
            and item.get("decision_support_level") in {"RECOMMENDATION_REASON", "CANDIDATE_OR_EVALUATION"}
            and item.get("priority_level") in {"PRIORITY_HIGH", "PRIORITY_MEDIUM"}
        ]
        if not benchmark_items or channel_key in brand_platforms:
            continue
        qualified_channels[channel_key] = _channel_opportunity_payload(channel_key, benchmark_items)

    for row in rows:
        channel_key = _channel_key_for_row(row)
        row["channel_opportunity"] = qualified_channels.get(channel_key)
    return rows


def _channel_opportunity_payload(channel_key: str, rows: list[dict]) -> dict:
    representative = sorted(rows, key=_source_analysis_sort_key)[:3]
    content_types = []
    for row in representative:
        ctype = _target_content_type_for_row(row)
        if ctype and ctype not in content_types:
            content_types.append(ctype)
    return {
        "opportunity_type": "CHANNEL_OPPORTUNITY",
        "channel": channel_key,
        "channel_label": source_platform_label(channel_key),
        "priority_level": "PRIORITY_HIGH" if any(row.get("priority_level") == "PRIORITY_HIGH" for row in rows) else "PRIORITY_MEDIUM",
        "recommended_content_types": content_types or ["ARTICLE"],
        "basis": [
            "同平台存在核心/辅助对标来源",
            "对标来源具备推荐理由或候选/评价支撑",
            "当前样本未发现目标品牌同平台资产",
        ],
        "representative_sources": [_benchmark_source_for_row(row) for row in representative],
        "human_review_required": True,
        "review_note": "三方平台账号可新注册；仍需人工确认平台规则、账号可控性、内容适配和发布可行性。",
    }


def _stable_action_key(row: dict) -> str:
    gap_item_ids = ",".join(sorted(
        str(item.get("gap_item_id"))
        for item in row.get("capability_gap_items", [])
        if item.get("gap_item_id")
    ))
    raw = "|".join(str(part or "") for part in [
        row.get("source_document_id"),
        row.get("url"),
        row.get("source_gap_type"),
        row.get("action_route"),
        gap_item_ids,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _capability_label_for_strategy_items(items: list[dict]) -> str:
    labels = []
    for item in items:
        label = str(item.get("capability_label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return "、".join(labels[:4])


def _truth_label_for_row(row: dict) -> str:
    suggested = (row.get("suggested_capability_label") or "").strip()
    if suggested:
        return suggested
    basis = " ".join(row.get("source_gap_basis", []) + row.get("decision_support_basis", []))
    match = re.search(r"[\u4e00-\u9fffA-Za-z0-9]{2,40}", basis or "")
    return match.group(0) if match else ""


def _proof_focus_for_row(row: dict) -> str:
    text = " ".join(row.get("source_gap_basis", []) + row.get("benchmark_basis", []))
    if any(token in text for token in ["数据", "成功率", "%", "％"]):
        return "可核验的数据或结果口径"
    if any(token in text for token in ["案例", "客户", "场景"]):
        return "真实案例、客户场景或前后对比"
    return "案例、数据、证明、具体场景或步骤细节"


def _benchmark_source_for_row(row: dict) -> dict:
    return {
        "source_document_id": row.get("source_document_id"),
        "title": row.get("title") or "",
        "url": row.get("url") or "",
        "domain": row.get("domain") or "",
        "platform": _channel_key_for_row(row) or row.get("platform") or "web",
        "platform_label": source_platform_label(_channel_key_for_row(row) or row.get("platform") or "web"),
        "benchmark_tier": row.get("benchmark_tier") or "",
        "decision_support_level": row.get("decision_support_level") or "NONE",
        "supporting_alignment_ids": row.get("supporting_alignment_ids", []),
    }


def _channel_key_for_row(row: dict) -> str:
    raw = str(row.get("platform") or row.get("account_platform") or "").strip()
    if raw and raw.lower() not in {"web", "unknown"}:
        return raw.lower()
    inferred = _platform_from_host(" ".join([row.get("domain") or "", row.get("url") or ""]))
    if inferred and inferred != "web":
        return inferred
    if row.get("ownership") == "official":
        return "owned"
    return raw.lower() if raw else "web"


def _target_content_type_for_row(row: dict) -> str:
    platform = _channel_key_for_row(row)
    content_format = (row.get("content_format") or "").lower()
    if platform in {"bilibili", "douyin"}:
        return "VIDEO"
    if platform == "zhihu":
        return "Q_AND_A" if content_format == "faq" else "ARTICLE"
    if platform in {"baijiahao", "wechat", "sohu", "sina", "csdn", "jianshu", "juejin"}:
        return "ARTICLE"
    if platform == "owned":
        return "PAGE"
    return "ARTICLE"


def _enrich_source_rows_with_metadata(db: Session, rows: list[dict]) -> list[dict]:
    fetched_count = 0
    for row in rows:
        url = row.get("url") or ""
        if not url or (row.get("author_name") and row.get("published_date")):
            continue
        allow_fetch = fetched_count < SOURCE_METADATA_FETCH_LIMIT
        metadata = _source_metadata_for_url(
            db,
            url=url,
            domain=row.get("domain") or "",
            fallback_title=row.get("title") or "",
            allow_fetch=allow_fetch,
        )
        if metadata.get("_fetched_now"):
            fetched_count += 1
        if not metadata:
            continue
        if metadata.get("author_name") and not row.get("author_name"):
            row["author_name"] = metadata["author_name"]
        if metadata.get("published_date") and not row.get("published_date"):
            row["published_date"] = metadata["published_date"]
            row["freshness_signal"] = _freshness_signal(" ".join([row.get("title") or "", row["published_date"]]))
            row["time_signal_detail"] = _time_signal_detail(row["published_date"], row["freshness_signal"])
    return rows


def _source_metadata_for_url(
    db: Session,
    url: str,
    domain: str,
    fallback_title: str,
    allow_fetch: bool,
) -> dict:
    cache_url = _normalize_source_url(url) or url
    fetch_url = _source_fetch_url(url)
    if not _is_fetchable_public_url(fetch_url):
        return {}
    cache = db.query(SourceMetadataCache).filter(SourceMetadataCache.url == cache_url).first()
    if cache and cache.fetched_at:
        should_retry_failed = cache.status == "failed" and (datetime.utcnow() - cache.fetched_at) > timedelta(hours=24)
        should_retry_platform = _is_bilibili_url(fetch_url) and not (cache.author_name or cache.published_date)
        if not should_retry_failed and not should_retry_platform:
            return {
                "author_name": cache.author_name,
                "published_date": cache.published_date,
                "title": cache.title,
                "status": cache.status,
            }
    if not allow_fetch:
        return {}
    if not cache:
        cache = SourceMetadataCache(url=cache_url, domain=domain, title=fallback_title, status="pending")
        db.add(cache)
        db.flush()
    try:
        metadata = _fetch_source_metadata(fetch_url, fallback_title)
        cache.author_name = metadata.get("author_name", "")
        cache.published_date = metadata.get("published_date", "")
        cache.title = metadata.get("title") or fallback_title
        cache.domain = domain or host_from_url(fetch_url)
        cache.raw_metadata_json = dumps(metadata)
        cache.status = "success" if cache.author_name or cache.published_date else "empty"
        cache.error_message = ""
    except Exception as exc:
        metadata = {}
        cache.status = "failed"
        cache.error_message = str(exc)[:500]
    cache.fetched_at = datetime.utcnow()
    db.commit()
    metadata["_fetched_now"] = True
    return metadata


def _source_fetch_url(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if "://" in raw:
        return raw
    return f"https://{raw.lstrip('/')}"


def _is_fetchable_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


def _fetch_source_metadata(url: str, fallback_title: str) -> dict:
    platform_metadata = _fetch_platform_source_metadata(url)
    if platform_metadata.get("author_name") or platform_metadata.get("published_date"):
        return platform_metadata
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": _metadata_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            },
        )
        with urllib.request.urlopen(request, timeout=SOURCE_METADATA_TIMEOUT_SECONDS) as response:
            payload = response.read(1_500_000)
            charset = response.headers.get_content_charset() or "utf-8"
        html = payload.decode(charset, errors="replace")
    except Exception:
        html = _fetch_source_html_with_curl(url)
    return _parse_source_metadata_html(html, fallback_title)


def _fetch_platform_source_metadata(url: str) -> dict:
    if _is_bilibili_url(url):
        return _fetch_bilibili_metadata(url)
    return {}


def _is_bilibili_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host.endswith("bilibili.com") or host == "b23.tv"


def _fetch_bilibili_metadata(url: str) -> dict:
    bvid_match = re.search(r"/video/(BV[0-9A-Za-z]+)", url)
    if not bvid_match:
        bvid_match = re.search(r"/video/(bv[0-9a-z]+)", url, re.I)
    if not bvid_match:
        return {}
    bvid = bvid_match.group(1)
    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    payload = _fetch_json_payload(api_url)
    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return {}
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    author = _clean_author_candidate(str(owner.get("name") or ""))
    published = _normalize_published_date(str(data.get("pubdate") or ""))
    return {
        "title": str(data.get("title") or ""),
        "author_name": author,
        "published_date": published,
        "platform": "bilibili",
        "raw": {"bvid": bvid},
    }


def _fetch_json_payload(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": _metadata_user_agent()})
    try:
        with urllib.request.urlopen(request, timeout=SOURCE_METADATA_TIMEOUT_SECONDS) as response:
            return json.loads(response.read(1_000_000).decode("utf-8", errors="replace"))
    except Exception:
        result = subprocess.run(
            ["curl", "-L", "-sS", "--max-time", str(SOURCE_METADATA_TIMEOUT_SECONDS), "-A", _metadata_user_agent(), url],
            capture_output=True,
            timeout=SOURCE_METADATA_TIMEOUT_SECONDS + 2,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or f"curl failed with code {result.returncode}")
        return json.loads(result.stdout[:1_000_000].decode("utf-8", errors="replace"))


def _metadata_user_agent() -> str:
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121 Safari/537.36 GEOAuditBot/0.1"
    )


def _fetch_source_html_with_curl(url: str) -> str:
    result = subprocess.run(
        [
            "curl",
            "-L",
            "-sS",
            "--compressed",
            "--max-time",
            str(SOURCE_METADATA_TIMEOUT_SECONDS),
            "-A",
            _metadata_user_agent(),
            url,
        ],
        capture_output=True,
        timeout=SOURCE_METADATA_TIMEOUT_SECONDS + 2,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"curl failed with code {result.returncode}")
    return result.stdout[:1_500_000].decode("utf-8", errors="replace")


def _parse_source_metadata_html(page_html: str, fallback_title: str = "") -> dict:
    metadata = _metadata_from_meta_tags(page_html)
    jsonld_metadata = _metadata_from_jsonld(page_html)
    raw_metadata = _metadata_from_raw_json(page_html)
    page_title = _html_title(page_html)
    title = page_title or fallback_title
    author = (
        metadata.get("author_name")
        or jsonld_metadata.get("author_name")
        or raw_metadata.get("author_name")
        or _author_name(title, "", "", _platform_from_title(title.casefold()))
    )
    published = (
        metadata.get("published_date")
        or jsonld_metadata.get("published_date")
        or raw_metadata.get("published_date")
    )
    return {
        "title": title,
        "author_name": author,
        "published_date": _normalize_published_date(published),
        "meta": metadata,
        "jsonld": jsonld_metadata,
        "raw": raw_metadata,
    }


def _metadata_from_meta_tags(page_html: str) -> dict:
    author_keys = {"author", "article:author", "og:article:author", "twitter:creator", "byl"}
    date_keys = {
        "date",
        "pubdate",
        "publishdate",
        "publish_date",
        "published_date",
        "datepublished",
        "article:published_time",
        "article:modified_time",
        "og:published_time",
        "weibo:article:create_at",
    }
    author = ""
    published = ""
    for match in re.finditer(r"<meta\b([^>]+)>", page_html or "", re.I | re.S):
        attrs = _html_attrs(match.group(1))
        key = (attrs.get("name") or attrs.get("property") or attrs.get("itemprop") or "").strip().lower()
        content = html_lib.unescape((attrs.get("content") or "").strip())
        if not key or not content:
            continue
        normalized_key = key.replace("_", "").replace("-", "")
        if not author and key in author_keys:
            author = _clean_author_candidate(content)
        if not published and (key in date_keys or normalized_key in date_keys):
            published = content
    return {"author_name": author, "published_date": _normalize_published_date(published)}


def _metadata_from_jsonld(page_html: str) -> dict:
    author = ""
    published = ""
    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        page_html or "",
        re.I | re.S,
    ):
        raw = html_lib.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for node in _walk_json_nodes(data):
            if not isinstance(node, dict):
                continue
            if not author:
                author = _author_from_json_value(node.get("author") or node.get("creator") or node.get("publisher"))
            if not published:
                published = (
                    node.get("datePublished")
                    or node.get("uploadDate")
                    or node.get("dateCreated")
                    or node.get("dateModified")
                )
            if author and published:
                return {"author_name": author, "published_date": _normalize_published_date(str(published))}
    return {"author_name": author, "published_date": _normalize_published_date(str(published or ""))}


def _metadata_from_raw_json(page_html: str) -> dict:
    author = ""
    published = ""
    patterns = [
        r'"owner"\s*:\s*\{[^{}]*"name"\s*:\s*"([^"]{2,80})"',
        r'"author"\s*:\s*\{[^{}]*"name"\s*:\s*"([^"]{2,80})"',
        r'"authorName"\s*:\s*"([^"]{2,80})"',
        r'"name"\s*:\s*"([^"]{2,80})"\s*,\s*"mid"\s*:',
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html or "", re.S)
        if match:
            author = _clean_author_candidate(_decode_json_string(match.group(1)))
            if author:
                break
    date_patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"uploadDate"\s*:\s*"([^"]+)"',
        r'"publishTime"\s*:\s*"([^"]+)"',
        r'"pubdate"\s*:\s*(\d{10})',
        r'"ctime"\s*:\s*(\d{10})',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, page_html or "", re.S)
        if match:
            published = match.group(1)
            break
    return {"author_name": author, "published_date": _normalize_published_date(published)}


def _html_attrs(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([A-Za-z_:.-]+)\s*=\s*('[^']*'|\"[^\"]*\"|[^\s\"'>/]+)", raw_attrs or ""):
        key = match.group(1).lower()
        value = match.group(2).strip("\"'")
        attrs[key] = value
    return attrs


def _html_title(page_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page_html or "", re.I | re.S)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", html_lib.unescape(match.group(1))).strip()
    return title[:500]


def _walk_json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_nodes(child)


def _author_from_json_value(value) -> str:
    if isinstance(value, str):
        return _clean_author_candidate(value)
    if isinstance(value, dict):
        return _clean_author_candidate(str(value.get("name") or value.get("@id") or ""))
    if isinstance(value, list):
        for item in value:
            author = _author_from_json_value(item)
            if author:
                return author
    return ""


def _decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value


def _normalize_published_date(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{10}", raw):
        try:
            return datetime.fromtimestamp(int(raw)).strftime("%Y-%m-%d")
        except Exception:
            return ""
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})(?:[-/.月](\d{1,2}))?", raw)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = match.group(3)
        if not (2000 <= year <= 2100 and 1 <= month <= 12):
            return ""
        if day:
            day_value = int(day)
            if not 1 <= day_value <= 31:
                return ""
            return f"{year}-{month:02d}-{day_value:02d}"
        return f"{year}-{month:02d}"
    years = _visible_years(raw)
    if years:
        return str(max(years))
    return ""


def _answer_usage_priority(value: str) -> int:
    return {
        "directly_reflected": 5,
        "citation_only": 4,
        "retrieved_context_reflected": 3,
        "not_reflected": 2,
        "unknown": 1,
    }.get(value, 0)


def _attach_cross_source_comparison(rows: list[dict]) -> list[dict]:
    cited_rows = [row for row in rows if row.get("cited")]
    if not cited_rows:
        for row in rows:
            row["cross_source_comparison"] = {
                "score_rank": None,
                "score_percentile": 0,
                "sample_avg_score": 0,
                "above_average": False,
                "leading_factors": ["当前样本暂无最终引用资料，无法做横向资料优势对比。"],
            }
        return rows
    unique_scores = sorted({int(row["source_score"]) for row in cited_rows}, reverse=True)
    avg_score = round(sum(int(row["source_score"]) for row in cited_rows) / len(cited_rows), 2)
    platform_counts = Counter(row["account_platform"] for row in cited_rows if row.get("account_platform"))
    format_counts = Counter(row["content_format"] for row in cited_rows if row.get("content_format"))
    authority_counts = Counter(row["authority_signal"] for row in cited_rows if row.get("authority_signal"))
    structured_count = sum(1 for row in cited_rows if row.get("content_structure_signals"))
    dated_count = sum(1 for row in cited_rows if row.get("published_date") or row.get("freshness_signal") in {"recent", "fresh_claim"})
    for row in rows:
        score = int(row["source_score"])
        rank = unique_scores.index(score) + 1 if score in unique_scores else len(unique_scores) + 1
        percentile = round(1 - ((rank - 1) / max(1, len(unique_scores))), 4)
        leading = []
        if row["ownership"] == "official":
            leading.append("官方来源身份相对普通第三方资料更适合承接事实口径和权威解释。")
        elif row["ownership"] == "brand_related":
            leading.append("可见品牌相关信号，和普通泛行业资料相比更容易承接品牌实体理解。")
        elif row["ownership"] == "competitor":
            leading.append("竞品来源具备明确行业相关性，但也会带来推荐分流风险。")
        if row["account_identity"] in {"confirmed_official", "possible_official_account"}:
            leading.append(f"{source_platform_label(row['account_platform'])} 账号身份具备官方或疑似官方信号，账号可信度强于未核验平台号。")
        platform_share = platform_counts.get(row["account_platform"], 0)
        if row.get("account_platform") != "web" and platform_share == 1:
            leading.append(f"平台类型为 {source_platform_label(row['account_platform'])}，在本组已引用资料中具备平台差异化。")
        format_share = format_counts.get(row["content_format"], 0)
        if row["content_format"] in {"comparison", "guide", "faq", "documentation"}:
            leading.append(f"内容形态优势：{_format_note(row['content_format'])}")
        elif format_share == 1:
            leading.append(f"内容形态差异化：{_format_note(row['content_format'])}")
        if row["content_structure_signals"]:
            structure_note = f"内容结构包含 {', '.join(row['content_structure_signals'][:3])}。"
            if structured_count < len(cited_rows):
                structure_note += "相对无结构信号资料更便于模型抽取答案要点。"
            leading.append(structure_note)
        if row["published_date"]:
            leading.append(f"可见发布日期/年份 {row['published_date']}，时间线索比无日期资料更清晰。")
        if row["freshness_signal"] in {"recent", "fresh_claim"}:
            suffix = "，在本组引用资料中属于较少见信号" if dated_count < len(cited_rows) else ""
            leading.append(f"具备较新的时间/更新信号{suffix}。")
        if row["authority_signal"] in {"high", "medium_high"} and authority_counts.get(row["authority_signal"], 0) <= max(1, len(cited_rows) // 2):
            leading.append("权威或结构化信号强于本组一部分普通网页资料。")
        if row["prompt_overlap_score"] >= 0.18:
            leading.append(f"标题/摘要与 Prompt 有可见主题匹配，匹配度 {round(row['prompt_overlap_score'] * 100)}%。")
        row["cross_source_comparison"] = {
            "score_rank": rank,
            "score_percentile": percentile,
            "sample_avg_score": avg_score,
            "sample_platform_distribution": dict(platform_counts),
            "sample_format_distribution": dict(format_counts),
            "above_average": score >= avg_score,
            "leading_factors": leading or ["相对其他引用资料的可见资料优势不明显，需要打开页面正文进一步确认差异。"],
        }
    return rows


def _global_source_key(url: str, domain: str, title: str) -> tuple:
    normalized_url = _normalize_source_url(url)
    if normalized_url:
        return ("url", normalized_url)
    normalized_title = re.sub(r"\s+", " ", (title or "").strip().lower())
    return ("title", (domain or "").strip().lower(), normalized_title)


def _normalize_source_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"from", "spm", "share_source", "share_medium", "share_plat", "share_session_id"}
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunparse(("", host, path, "", query, "")).lower().rstrip("/")


def _citation_stats(references: list[ReferenceSource], sample_count: int) -> dict[tuple, dict]:
    grouped: dict[tuple, dict] = {}
    for ref in references:
        title = ref.display_title or ref.matched_title or ""
        key = _global_source_key(ref.canonical_url or ref.url, ref.domain, title)
        row = grouped.setdefault(
            key,
            {
                "citation_occurrence_count": 0,
                "cited_run_ids": set(),
                "position_sum": 0,
                "sample_count": sample_count,
            },
        )
        row["citation_occurrence_count"] += 1
        row["cited_run_ids"].add(ref.run_id)
        row["position_sum"] += max(1, int(ref.reference_index or 1))
    result = {}
    for key, row in grouped.items():
        occurrence_count = int(row["citation_occurrence_count"])
        cited_run_count = len(row["cited_run_ids"])
        result[key] = {
            "citation_occurrence_count": occurrence_count,
            "cited_run_count": cited_run_count,
            "answer_citation_rate": round(cited_run_count / sample_count, 4) if sample_count else 0,
            "avg_reference_position": round(row["position_sum"] / occurrence_count, 2) if occurrence_count else 0,
            "sample_count": sample_count,
        }
    return result


def _empty_citation_stats(sample_count: int) -> dict:
    return {
        "citation_occurrence_count": 0,
        "cited_run_count": 0,
        "answer_citation_rate": 0,
        "avg_reference_position": 0,
        "sample_count": sample_count,
    }


def _target_page_conversion(
    runs: list[BrowserMonitorRun],
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate],
    target_url: str,
    eligibility: dict | None = None,
) -> dict:
    normalized_target = _normalize_source_url(target_url)
    run_ids = [run.id for run in runs]
    if eligibility and not run_ids:
        return {
            "target_url": target_url or "",
            "normalized_target_url": normalized_target,
            "retrieved_count": 0,
            "cited_count": 0,
            "conversion_rate": None,
            "not_applicable": False,
            "reason": "没有达到检索指标资格的 Run，不能计算检索转引用率。",
            "retrieved_run_ids": [],
            "cited_run_ids": [],
            "eligible_run_ids": [],
            "excluded_run_ids": eligibility.get("excluded_run_ids_by_metric", {}).get("retrieval", []),
            "exclusion_reasons": eligibility.get("exclusion_reasons", {}).get("retrieval", []),
            "calculation_status": "insufficient_retrieval_candidates",
            "run_drilldown": [],
        }
    if not normalized_target:
        return {
            "target_url": target_url or "",
            "normalized_target_url": "",
            "retrieved_count": 0,
            "cited_count": 0,
            "conversion_rate": None,
            "not_applicable": True,
            "reason": "未设置目标页面 URL，无法计算检索转引用率。",
            "retrieved_run_ids": [],
            "cited_run_ids": [],
            "eligible_run_ids": run_ids,
            "excluded_run_ids": [],
            "exclusion_reasons": [],
            "calculation_status": "not_applicable",
            "run_drilldown": [_target_run_row(run, False, False) for run in runs],
        }
    retrieved_run_ids = {
        item.run_id
        for item in retrievals
        if item.run_id in run_ids and _item_matches_target(item, normalized_target)
    }
    cited_run_ids = {
        item.run_id
        for item in references
        if item.run_id in run_ids and _item_matches_target(item, normalized_target)
    }
    retrieved_count = len(retrieved_run_ids)
    cited_count = len(cited_run_ids)
    conversion_rate = round(cited_count / retrieved_count, 4) if retrieved_count else None
    return {
        "target_url": target_url or "",
        "normalized_target_url": normalized_target,
        "retrieved_count": retrieved_count,
        "cited_count": cited_count,
        "conversion_rate": conversion_rate,
        "not_applicable": retrieved_count == 0,
        "reason": "" if retrieved_count else "目标页面未进入检索候选，不能计算检索转引用率。",
        "retrieved_run_ids": sorted(retrieved_run_ids),
        "cited_run_ids": sorted(cited_run_ids),
        "eligible_run_ids": run_ids,
        "excluded_run_ids": eligibility.get("excluded_run_ids_by_metric", {}).get("retrieval", []) if eligibility else [],
        "exclusion_reasons": eligibility.get("exclusion_reasons", {}).get("retrieval", []) if eligibility else [],
        "calculation_status": "not_applicable" if retrieved_count == 0 else "ok",
        "run_drilldown": [
            _target_run_row(run, run.id in retrieved_run_ids, run.id in cited_run_ids)
            for run in runs
        ],
    }


def _target_page_retrieval(
    runs: list[BrowserMonitorRun],
    retrievals: list[RetrievalCandidate],
    target_url: str,
    eligibility: dict | None = None,
) -> dict:
    normalized_target = _normalize_source_url(target_url)
    run_ids = [run.id for run in runs]
    if eligibility and not run_ids:
        return {
            "target_url": target_url or "",
            "normalized_target_url": normalized_target,
            "valid_run_count": 0,
            "retrieved_run_count": 0,
            "retrieval_rate": None,
            "not_applicable": False,
            "reason": "没有达到检索指标资格的 Run，不能计算目标页面检索进入率。",
            "run_ids": [],
            "retrieved_run_ids": [],
            "eligible_run_ids": [],
            "excluded_run_ids": eligibility.get("excluded_run_ids_by_metric", {}).get("retrieval", []),
            "exclusion_reasons": eligibility.get("exclusion_reasons", {}).get("retrieval", []),
            "calculation_status": "insufficient_retrieval_candidates",
            "run_drilldown": [],
        }
    if not normalized_target:
        return {
            "target_url": target_url or "",
            "normalized_target_url": "",
            "valid_run_count": len(runs),
            "retrieved_run_count": 0,
            "retrieval_rate": None,
            "not_applicable": True,
            "reason": "未设置目标页面 URL，无法计算目标页面检索进入率。",
            "run_ids": run_ids,
            "retrieved_run_ids": [],
            "eligible_run_ids": run_ids,
            "excluded_run_ids": [],
            "exclusion_reasons": [],
            "calculation_status": "not_applicable",
            "run_drilldown": [_target_retrieval_run_row(run, False) for run in runs],
        }
    retrieved_run_ids = {
        item.run_id
        for item in retrievals
        if item.run_id in run_ids and _item_matches_target(item, normalized_target)
    }
    valid_run_count = len(runs)
    retrieved_run_count = len(retrieved_run_ids)
    return {
        "target_url": target_url or "",
        "normalized_target_url": normalized_target,
        "valid_run_count": valid_run_count,
        "retrieved_run_count": retrieved_run_count,
        "retrieval_rate": _rate(retrieved_run_count, valid_run_count),
        "not_applicable": False,
        "reason": "",
        "run_ids": run_ids,
        "retrieved_run_ids": sorted(retrieved_run_ids),
        "eligible_run_ids": run_ids,
        "excluded_run_ids": eligibility.get("excluded_run_ids_by_metric", {}).get("retrieval", []) if eligibility else [],
        "exclusion_reasons": eligibility.get("exclusion_reasons", {}).get("retrieval", []) if eligibility else [],
        "calculation_status": "ok",
        "run_drilldown": [
            _target_retrieval_run_row(run, run.id in retrieved_run_ids)
            for run in runs
        ],
    }


def _target_retrieval_run_row(run: BrowserMonitorRun, retrieved: bool) -> dict:
    return {
        "run_id": run.id,
        "prompt_id": run.prompt_id,
        "platform": run.platform,
        "source_type": run.source_type,
        "adapter": run.adapter,
        "run_sequence": run.run_sequence,
        "sample_index": run.sample_index,
        "retrieved": retrieved,
    }


def _target_run_row(run: BrowserMonitorRun, retrieved: bool, cited: bool) -> dict:
    return {
        "run_id": run.id,
        "prompt_id": run.prompt_id,
        "platform": run.platform,
        "source_type": run.source_type,
        "adapter": run.adapter,
        "run_sequence": run.run_sequence,
        "sample_index": run.sample_index,
        "retrieved": retrieved,
        "cited": cited,
    }


def _item_matches_target(item, normalized_target: str) -> bool:
    candidate_urls = [
        getattr(item, "canonical_url", "") or "",
        getattr(item, "url", "") or "",
    ]
    return any(_normalize_source_url(url) == normalized_target for url in candidate_urls if url)


def _ownership(
    project: Project,
    competitors: list[Competitor],
    domain: str,
    url: str,
    is_official: bool,
    is_competitor: bool,
    brand_domain: str,
) -> str:
    source_domain = (domain or host_from_url(url) if url else domain or "").lower()
    if is_official or (brand_domain and source_domain.endswith(brand_domain)):
        return "official"
    competitor_domains = [host_from_url(item.website_url) for item in competitors if item.website_url]
    if is_competitor or any(item and source_domain.endswith(item) for item in competitor_domains):
        return "competitor"
    if any(name and name.casefold() in f"{source_domain} {url}".casefold() for name in [project.brand_name, *loads(project.brand_aliases_json, [])]):
        return "brand_related"
    return "third_party"


def _content_format(title: str, url: str) -> str:
    text = f"{title} {url}".casefold()
    if any(token in text for token in ["faq", "常见问题", "问答"]):
        return "faq"
    if any(token in text for token in ["教程", "指南", "guide", "how-to", "使用说明", "步骤"]):
        return "guide"
    if any(token in text for token in ["对比", "比较", "排行", "排名", "推荐", "best", "top", "review"]):
        return "comparison"
    if any(token in text for token in ["新闻", "资讯", "公告", "news", "press"]):
        return "news"
    if any(token in text for token in ["文档", "docs", "api", "manual"]):
        return "documentation"
    if re.search(r"/?$", url or "") and len((url or "").strip("/").split("/")) <= 3:
        return "homepage_or_channel"
    return "article"


def _content_structure_signals(title: str, url: str, snippet: str) -> list[str]:
    text = f"{title} {url} {snippet}".casefold()
    signals = []
    checks = [
        ("对比/榜单", ["对比", "比较", "排行", "排名", "推荐", "best", "top", "review"]),
        ("教程步骤", ["教程", "指南", "guide", "how-to", "步骤", "使用说明"]),
        ("FAQ问答", ["faq", "常见问题", "问答", "问题"]),
        ("案例/经验", ["案例", "经验", "实测", "测评", "实践"]),
        ("价格/成本", ["价格", "费用", "收费", "成本", "报价"]),
        ("功能清单", ["功能", "清单", "能力", "特点", "优势"]),
        ("更新时间", ["最新", "更新", "新版", "2024", "2025", "2026"]),
        ("官方说明", ["官方", "官网", "文档", "docs", "manual"]),
    ]
    for label, tokens in checks:
        if any(token in text for token in tokens):
            signals.append(label)
    return signals


def _time_signal_detail(text: str, freshness: str) -> str:
    years = sorted(set(_visible_years(text)), reverse=True)
    if years:
        return f"可见年份信号：{', '.join(str(year) for year in years[:3])}；新鲜度判断：{_freshness_note(freshness)}"
    if freshness == "fresh_claim":
        return "可见“最新/更新/新版”等文本信号，但未识别到明确年份。"
    return "当前标题、URL、摘要中没有明显时间信号。"


def _overlap_score(prompt_text: str, source_text: str) -> float:
    prompt_tokens = _tokens(prompt_text)
    source_tokens = _tokens(source_text)
    if not prompt_tokens or not source_tokens:
        return 0
    return round(len(prompt_tokens & source_tokens) / len(prompt_tokens), 4)


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]", (text or "").casefold())
    stop = {"的", "了", "和", "是", "在", "有", "与", "及", "或", "吗", "哪", "个", "一", "the", "and", "for", "with"}
    return {token for token in raw if token not in stop}


def _brand_signal(project: Project, text: str, ownership: str) -> str:
    aliases = [project.brand_name, *loads(project.brand_aliases_json, [])]
    if ownership == "official":
        return "official_domain"
    if any(alias and alias.casefold() in (text or "").casefold() for alias in aliases):
        return "brand_named"
    return "none"


def _freshness_signal(text: str) -> str:
    years = _visible_years(text)
    if not years:
        if any(token in text for token in ["最新", "更新", "新版", "今日"]):
            return "fresh_claim"
        return "unknown"
    latest = max(years)
    if latest >= 2025:
        return "recent"
    if latest <= 2022:
        return "stale"
    return "dated"


def _authority_signal(ownership: str, domain: str, content_format: str) -> str:
    lowered = (domain or "").lower()
    if ownership == "official":
        return "high"
    if lowered.endswith(".gov") or lowered.endswith(".edu") or "wikipedia" in lowered:
        return "high"
    if content_format in {"documentation", "guide", "comparison"}:
        return "medium_high"
    if any(token in lowered for token in ["zhihu", "douyin", "bilibili", "xiaohongshu", "weixin"]):
        return "medium"
    return "medium"


def _account_identity(project: Project, domain: str, url: str, title: str, ownership: str) -> tuple[str, str, str]:
    host_text = f"{domain} {host_from_url(url) if url else ''} {url}".casefold()
    title_text = (title or "").casefold()
    text = f"{host_text} {title_text}"
    aliases = [project.brand_name, *loads(project.brand_aliases_json, [])]
    brand_named = any(alias and alias.casefold() in text for alias in aliases)
    platform = _platform_from_host(host_text)
    if platform == "web":
        platform = _platform_from_title(title_text)

    if ownership == "official":
        return platform, "confirmed_official", "命中品牌官方域或已标记官方来源。"
    if brand_named and platform != "web":
        return platform, "possible_official_account", f"{source_platform_label(platform)} 来源中出现品牌名/别名，需要人工确认是否为官方号。"
    if brand_named:
        return platform, "brand_named_unverified", "页面可见文本出现品牌名/别名，但未确认来源身份。"
    if platform != "web":
        return platform, "platform_account_unknown", f"识别为 {source_platform_label(platform)} 来源，识别优先依据域名，域名不足时才用标题关键词。"
    return platform, "unknown", "普通网页来源，当前可见数据不足以判断账号身份。"


def _platform_from_host(host_text: str) -> str:
    if any(token in host_text for token in ["bilibili.com", "b23.tv"]):
        return "bilibili"
    if "baijiahao.baidu.com" in host_text or "baijiahao" in host_text:
        platform = "baijiahao"
        return platform
    if "zhihu.com" in host_text:
        return "zhihu"
    if "mp.weixin.qq.com" in host_text or "weixin.qq.com" in host_text:
        return "wechat_official_account"
    if "douyin.com" in host_text:
        return "douyin"
    if "xiaohongshu.com" in host_text:
        return "xiaohongshu"
    return "web"


def _platform_from_title(title_text: str) -> str:
    if "哔哩" in title_text or "b站" in title_text or "bilibili" in title_text:
        return "bilibili"
    if "百家号" in title_text:
        return "baijiahao"
    if "知乎" in title_text:
        return "zhihu"
    if "微信公众号" in title_text or "公众号" in title_text:
        return "wechat_official_account"
    if "抖音" in title_text:
        return "douyin"
    if "小红书" in title_text:
        return "xiaohongshu"
    return "web"


def _author_name(title: str, url: str, domain: str, platform: str) -> str:
    text = " ".join([title or "", url or "", domain or ""])
    patterns = [
        r"(?:作者|发布者|来源|账号|UP主|up主)[:：]\s*([^|｜_\-—,，\s]{2,30})",
        r"[|｜_\-—]\s*([^|｜_\-—]{2,30})\s*(?:的个人主页|主页|官方账号|官方号|百家号|知乎|哔哩哔哩|B站|bilibili)",
        r"@([^@\s]{2,30})的动态",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = _clean_author_candidate(match.group(1))
            if candidate:
                return candidate[:30]
    tail_candidate = _title_tail_source_name(title)
    if tail_candidate:
        return tail_candidate
    if platform == "bilibili" and "/space/" in (url or ""):
        return "B站 UP主（ID见URL）"
    return ""


def _published_date(text: str) -> str:
    raw = text or ""
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})(?:[-/.月](\d{1,2}))?", raw)
    if match:
        year = match.group(1)
        month = int(match.group(2))
        day = match.group(3)
        if day:
            return f"{year}-{month:02d}-{int(day):02d}"
        return f"{year}-{month:02d}"
    years = _visible_years(raw)
    if years:
        return str(max(years))
    return ""


def _visible_years(text: str) -> list[int]:
    raw = text or ""
    values = []
    for match in re.finditer(r"(?<!\d)(20\d{2})(?!\d)", raw):
        year = int(match.group(1))
        if 2000 <= year <= 2100:
            values.append(year)
    return values


def _title_tail_source_name(title: str) -> str:
    raw = (title or "").strip()
    if not raw:
        return ""
    parts = [part.strip() for part in re.split(r"[|｜_\-—]+", raw) if part.strip()]
    if len(parts) < 2:
        return ""
    return _clean_author_candidate(parts[-1])


def _clean_author_candidate(value: str) -> str:
    candidate = re.sub(r"\s+", " ", (value or "").strip(" \t\r\n-—_|｜,，。:："))
    if not candidate:
        return ""
    if len(candidate) > 30:
        return ""
    if re.search(r"https?://|www\.|\.com|\.cn|\.net|\.org", candidate, re.I):
        return ""
    if re.fullmatch(r"20\d{2}.*", candidate):
        return ""
    generic = {"教程", "详细步骤", "抖音", "快手", "知乎", "百度", "百家号", "B站", "哔哩哔哩", "bilibili"}
    if candidate in generic:
        return ""
    return candidate


def source_platform_label(platform: str) -> str:
    return {
        "baijiahao": "百家号",
        "zhihu": "知乎",
        "wechat_official_account": "微信公众号",
        "douyin": "抖音",
        "xiaohongshu": "小红书",
        "bilibili": "B站",
        "web": "网页",
    }.get(platform, platform)


def _answer_usage(title: str, domain: str, answer_text: str, cited: bool) -> tuple[str, str]:
    if not answer_text:
        return "unknown", "该 Run 未保存答案正文，无法判断答案中如何使用该资料。"
    answer_folded = answer_text.casefold()
    title_tokens = [token for token in _tokens(title) if len(token) >= 2]
    matched_tokens = [token for token in title_tokens if token in answer_folded]
    domain_hit = bool(domain and domain.casefold() in answer_folded)
    if cited and (domain_hit or len(matched_tokens) >= 2):
        return "directly_reflected", "引用标题/域名中的关键信号在答案正文中可见，可能被直接用于组织回答。"
    if cited:
        return "citation_only", "该资料进入最终引用，但答案正文未明显复用其标题/域名文本。"
    if domain_hit or len(matched_tokens) >= 2:
        return "retrieved_context_reflected", "资料未进入最终引用，但其标题/域名信号在答案中可见，可能影响了回答背景。"
    return "not_reflected", "答案正文未明显出现该资料的标题或域名信号。"


def _answer_usage_note(value: str) -> str:
    return {
        "directly_reflected": "引用资料的标题/域名信号在答案正文中可见。",
        "citation_only": "资料进入最终引用，但答案正文未明显复用标题或域名文本。",
        "retrieved_context_reflected": "候选资料未进入引用，但其信号可能影响了答案背景。",
        "not_reflected": "答案正文未明显体现该资料信号。",
        "unknown": "答案正文缺失或不足，无法判断。",
    }.get(value, "答案使用关系未知。")


def _citation_prominence(cited: bool, citation_stats: dict) -> tuple[str, list[str], dict]:
    sample_count = int(citation_stats.get("sample_count", 0) or 0)
    cited_run_count = int(citation_stats.get("cited_run_count", 0) or 0)
    occurrence_count = int(citation_stats.get("citation_occurrence_count", 0) or 0)
    citation_rate = float(citation_stats.get("answer_citation_rate", 0) or 0)
    avg_position = float(citation_stats.get("avg_reference_position", 0) or 0)
    position_tier = "none"
    if avg_position:
        if avg_position <= 3:
            position_tier = "front"
        elif avg_position <= 8:
            position_tier = "mid"
        else:
            position_tier = "late"

    if cited and ((citation_rate >= 0.5 and occurrence_count >= 2) or (cited_run_count >= 2 and position_tier == "front")):
        level = "HIGH"
    elif cited or occurrence_count > 0:
        level = "MEDIUM" if citation_rate >= 0.2 or occurrence_count >= 2 or position_tier in {"front", "mid"} else "LOW"
    else:
        level = "LOW"

    basis = [
        f"引用覆盖：{cited_run_count}/{sample_count or 0} 个可引用样本。",
        f"引用频次：累计 {occurrence_count} 次。",
    ]
    if avg_position:
        basis.append(f"引用位置：平均位次 #{round(avg_position, 1)}。")
    if not cited and occurrence_count == 0:
        basis.append("该资料未进入最终引用，不能作为高显著引用来源。")

    breakdown = {
        "sample_count": sample_count,
        "cited_run_count": cited_run_count,
        "citation_occurrence_count": occurrence_count,
        "answer_citation_rate": round(citation_rate, 4),
        "avg_reference_position": avg_position,
        "position_tier": position_tier,
        "uses_only_citation_behavior": True,
    }
    return level, basis, breakdown


def _citation_prominence_rank(level: str | None) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get((level or "LOW").upper(), 1)


def _source_score(
    cited: bool,
    citation_stats: dict,
    ownership: str,
    content_format: str,
    overlap: float,
    freshness: str,
    authority: str,
    account_identity: str,
    answer_usage: str,
    url: str,
) -> tuple[int, dict]:
    citation_rate = float(citation_stats.get("answer_citation_rate", 0) or 0)
    occurrence_count = int(citation_stats.get("citation_occurrence_count", 0) or 0)
    avg_position = float(citation_stats.get("avg_reference_position", 0) or 0)
    position_bonus = 0
    if avg_position:
        if avg_position <= 3:
            position_bonus = 8
        elif avg_position <= 8:
            position_bonus = 5
        else:
            position_bonus = 2
    breakdown = {
        "answer_citation_coverage": round(citation_rate * 30),
        "answer_citation_frequency": min(12, occurrence_count * 4),
        "answer_reference_position": position_bonus,
        "current_row_cited": 5 if cited else 0,
        "answer_usage": {
            "directly_reflected": 10,
            "citation_only": 6,
            "retrieved_context_reflected": 5,
            "not_reflected": 1,
            "unknown": 2,
        }.get(answer_usage, 2),
        "ownership": {"official": 10, "brand_related": 7, "third_party": 6, "competitor": 2}.get(ownership, 4),
        "format": {"comparison": 8, "guide": 8, "faq": 7, "documentation": 7, "article": 5, "news": 4, "homepage_or_channel": 2}.get(content_format, 4),
        "prompt_match": min(10, round(overlap * 25)),
        "freshness": {"recent": 5, "fresh_claim": 4, "dated": 3, "unknown": 2, "stale": 0}.get(freshness, 2),
        "authority": {"high": 8, "medium_high": 6, "medium": 4}.get(authority, 3),
        "account_identity": {
            "confirmed_official": 6,
            "possible_official_account": 4,
            "brand_named_unverified": 3,
            "platform_account_unknown": 1,
            "unknown": 1,
        }.get(account_identity, 2),
        "url_available": 3 if url else 0,
    }
    raw_score = sum(breakdown.values())
    return min(100, int(raw_score)), breakdown


def _score_explanation(
    citation_stats: dict,
    answer_usage: str,
    ownership: str,
    content_format: str,
    overlap: float,
    authority: str,
) -> list[str]:
    sample_count = int(citation_stats.get("sample_count", 0) or 0)
    cited_run_count = int(citation_stats.get("cited_run_count", 0) or 0)
    occurrence_count = int(citation_stats.get("citation_occurrence_count", 0) or 0)
    citation_rate = float(citation_stats.get("answer_citation_rate", 0) or 0)
    avg_position = float(citation_stats.get("avg_reference_position", 0) or 0)
    notes = [
        f"答案引用覆盖：{cited_run_count}/{sample_count} 个样本答案引用该资料，引用率 {round(citation_rate * 100, 1)}%。",
        f"答案引用频次：累计出现 {occurrence_count} 次引用。",
    ]
    if avg_position:
        notes.append(f"引用位置：平均引用位次 #{avg_position}，越靠前通常说明答案依赖更强。")
    if answer_usage in {"directly_reflected", "citation_only"}:
        notes.append(f"答案使用：{_answer_usage_note(answer_usage)}")
    if ownership in {"official", "brand_related"}:
        notes.append(f"来源归属：{_ownership_note(ownership)}")
    if content_format in {"comparison", "guide", "faq", "documentation"}:
        notes.append(f"内容形态：{_format_note(content_format)}")
    if overlap >= 0.18:
        notes.append(f"Prompt 匹配：{_overlap_note(overlap)}")
    if authority in {"high", "medium_high"}:
        notes.append(f"权威信号：{_authority_note(authority)}")
    return notes


def _citation_basis(
    cited: bool,
    citation_stats: dict,
    account_platform: str,
    account_identity: str,
    ownership: str,
    content_format: str,
    content_structure_signals: list[str],
    freshness: str,
    authority: str,
    overlap: float,
) -> list[str]:
    basis = []
    cited_run_count = int(citation_stats.get("cited_run_count", 0) or 0)
    sample_count = int(citation_stats.get("sample_count", 0) or 0)
    occurrence_count = int(citation_stats.get("citation_occurrence_count", 0) or 0)
    if cited:
        basis.append(f"答案实际引用：该资料被 {cited_run_count}/{sample_count} 个答案样本引用，累计 {occurrence_count} 次。")
    elif cited_run_count:
        basis.append(f"样本内其他答案引用过该资料，但当前行所在 Run 未引用。")
    else:
        basis.append("当前仅进入检索候选，未进入最终答案引用。")
    basis.append(f"平台/账号：{source_platform_label(account_platform)}，账号身份判断为 {account_identity}。")
    basis.append(f"来源归属：{_ownership_note(ownership)}")
    basis.append(f"内容结构：{_format_note(content_format)}")
    if content_structure_signals:
        basis.append(f"可见结构信号：{', '.join(content_structure_signals)}。")
    basis.append(f"时间信号：{_freshness_note(freshness)}")
    basis.append(f"权威信号：{_authority_note(authority)}")
    basis.append(f"与 Prompt 匹配：{_overlap_note(overlap)}")
    return basis


def _risk_flags(cited: bool, ownership: str, content_format: str, overlap: float, freshness: str, url: str) -> list[str]:
    flags: list[str] = []
    if not cited and overlap >= 0.35:
        flags.append("high_match_but_not_cited")
    if ownership == "competitor":
        flags.append("competitor_source")
    if ownership == "third_party" and cited:
        flags.append("third_party_dependency")
    if content_format == "homepage_or_channel" and cited:
        flags.append("generic_page_cited")
    if freshness == "stale":
        flags.append("stale_source")
    if not url:
        flags.append("url_missing")
    return flags


def _source_role(ownership: str, content_format: str) -> str:
    if ownership == "official":
        return "official_evidence"
    if ownership == "competitor":
        return "competitive_reference"
    if content_format == "comparison":
        return "selection_frame"
    if content_format in {"guide", "faq", "documentation"}:
        return "answer_support"
    return "context_source"


def _citation_reason(
    cited: bool,
    retrieval_rank: int | None,
    citation_stats: dict,
    ownership: str,
    content_format: str,
    overlap: float,
    freshness: str,
    authority: str,
) -> str:
    cited_run_count = int(citation_stats.get("cited_run_count", 0) or 0)
    sample_count = int(citation_stats.get("sample_count", 0) or 0)
    occurrence_count = int(citation_stats.get("citation_occurrence_count", 0) or 0)
    avg_position = float(citation_stats.get("avg_reference_position", 0) or 0)
    if not cited:
        if cited_run_count:
            return f"该资料在其他样本答案中被引用 {cited_run_count}/{sample_count} 次，本次只是检索候选未进入引用；需要比较本次答案为什么选择了其他资料。"
        if retrieval_rank and retrieval_rank <= 3 and overlap >= 0.25:
            return "检索靠前且主题相关，但最终未进入引用；需要对比它与已引用资料的权威性、标题命中和页面结构。"
        if overlap < 0.15:
            return "主题匹配较弱，可能只是检索扩展结果，未被引用是合理现象。"
        return "进入检索候选但未引用，可能在权威性、可摘录内容或页面可信度上弱于最终引用源。"
    reasons: list[str] = []
    if cited_run_count:
        position_note = f"，平均引用位次 #{avg_position}" if avg_position else ""
        reasons.append(f"在 {cited_run_count}/{sample_count} 个答案样本中被引用，累计 {occurrence_count} 次{position_note}")
    if retrieval_rank and retrieval_rank <= 3:
        reasons.append("检索排序靠前")
    if ownership == "official":
        reasons.append("属于官方来源")
    if content_format in {"guide", "faq", "documentation"}:
        reasons.append("内容形态适合支撑解释/步骤型回答")
    if content_format == "comparison":
        reasons.append("内容形态适合支撑推荐/对比型回答")
    if overlap >= 0.35:
        reasons.append("标题或摘要与 Prompt 高匹配")
    if freshness in {"recent", "fresh_claim"}:
        reasons.append("存在新鲜度信号")
    if authority in {"high", "medium_high"}:
        reasons.append("具备较强权威或结构化信号")
    return "；".join(reasons) or "被引用原因需要结合页面正文进一步确认，当前可见信号不足。"


def _comparison_note(cited: bool, retrieval_rank: int | None, ownership: str, overlap: float) -> str:
    if cited:
        return "已进入最终引用资料，可作为优化对标样本。"
    if retrieval_rank and retrieval_rank <= 5 and overlap >= 0.25:
        return "这是优先分析的未引用候选：它已被检索发现，但缺少进入最终引用的信号。"
    if ownership == "official":
        return "官方资料未被引用时，应优先检查标题、首屏结构、可摘录段落和权威背书。"
    return "可作为检索扩展背景，优先级低于高匹配未引用候选。"


def _ownership_note(value: str) -> str:
    return {
        "official": "品牌自有/官方域，理论上应承担权威解释。",
        "competitor": "竞品来源，可能分流推荐或塑造评价框架。",
        "brand_related": "标题或域名包含品牌信号，但未确认是官方域。",
        "third_party": "第三方来源，常用于补充可信度或对比视角。",
    }.get(value, "来源归属未知。")


def _format_note(value: str) -> str:
    return {
        "guide": "教程/指南更容易支撑步骤和解释。",
        "faq": "FAQ 更容易覆盖具体问法。",
        "comparison": "对比/榜单更容易影响推荐场景。",
        "documentation": "文档类资料适合支撑功能和事实。",
        "news": "资讯类资料提供新鲜度，但未必覆盖决策。",
        "homepage_or_channel": "首页/频道页较泛，需补具体可摘录内容。",
        "article": "文章类资料需要看标题和正文结构。",
    }.get(value, "内容形态未知。")


def _overlap_note(value: float) -> str:
    if value >= 0.35:
        return "与 Prompt 主题高度重叠。"
    if value >= 0.18:
        return "与 Prompt 有部分主题重叠。"
    return "与 Prompt 的可见文本匹配较弱。"


def _freshness_note(value: str) -> str:
    return {
        "recent": "可见年份较新。",
        "fresh_claim": "文本声称最新或已更新。",
        "dated": "有年份信号但不算最新。",
        "stale": "年份较旧，可能影响可信度。",
        "unknown": "没有明显新鲜度信号。",
    }.get(value, "新鲜度未知。")


def _authority_note(value: str) -> str:
    return {
        "high": "官方、机构或百科类权威信号强。",
        "medium_high": "内容结构较适合被模型摘录引用。",
        "medium": "常规网页信号，需要结合正文验证。",
    }.get(value, "权威信号未知。")


def _write_comparison(db: Session, experiment: OptimizationExperiment) -> None:
    baseline = loads(experiment.baseline_metrics_json, {})
    result = loads(experiment.result_metrics_json, {})
    keys = [experiment.primary_metric, *loads(experiment.secondary_metrics_json, [])]
    comparison = {}
    for key in dict.fromkeys(keys):
        comparison[key] = _metric_comparison(key, baseline, result)
    comparison["software_validation_note"] = (
        "该对比仅说明已挂载样本内的指标变化；真实业务结论需要确认发布已生效、冷却期足够且无明显混杂因素。"
    )
    experiment.comparison_json = dumps(comparison)
    experiment.outcome_summary_json = dumps(_recommendation_outcome_summary(db, experiment))
    _write_group_results(db, experiment)


def _recommendation_outcome_summary(db: Session, experiment: OptimizationExperiment) -> dict:
    action = _get_action(db, experiment.action_id)
    issue = _get_issue(db, action.issue_id)
    project = db.get(Project, issue.project_id)
    baseline_ids = loads(experiment.baseline_run_ids_json, [])
    validation_ids = loads(experiment.validation_run_ids_json, [])
    if not project:
        return {
            "status": "INSUFFICIENT_CONTEXT",
            "reason": "Experiment 无法反查 Project，不能生成 Recommendation Outcome。",
        }
    before = _recommendation_outcome_stats(db, project, baseline_ids, action.target_url)
    after = _recommendation_outcome_stats(db, project, validation_ids, action.target_url)
    return {
        "status": "OBSERVED" if baseline_ids and validation_ids else "INSUFFICIENT_SAMPLES",
        "baseline_run_ids": baseline_ids,
        "validation_run_ids": validation_ids,
        "candidate_before_after": _count_delta(before, after, "candidate_run_count"),
        "recommendation_before_after": _count_delta(before, after, "recommendation_run_count"),
        "target_reason_before_after": _count_delta(before, after, "target_reason_run_count"),
        "citation_before_after": _count_delta(before, after, "citation_run_count"),
        "baseline": before,
        "validation": after,
        "human_conclusion_required": True,
        "causality_boundary": "这里只记录固定复测前后观察变化；不能自动宣称优化有效。",
    }


def _recommendation_outcome_stats(
    db: Session,
    project: Project,
    run_ids: list[int],
    target_url: str,
) -> dict:
    runs = _runs_by_ids(db, run_ids, project.id)
    ids = [run.id for run in runs]
    aliases = [project.brand_name, *loads(project.brand_aliases_json, [])]
    events = db.query(RecommendationEvent).filter(RecommendationEvent.run_id.in_(ids)).all() if ids else []
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(ids)).all() if ids else []
    target = _normalize_source_url(target_url or "")

    candidate_run_ids = {
        event.run_id for event in events
        if _event_matches_brand(event, aliases) and (event.speech_act or "").upper() in {"INCLUDE_AS_OPTION", "COMPARE", "RECOMMEND"}
    }
    recommendation_run_ids = {
        event.run_id for event in events
        if _event_matches_brand(event, aliases) and (event.speech_act or "").upper() == "RECOMMEND"
    }
    target_reason_run_ids = {
        event.run_id for event in events
        if _event_matches_brand(event, aliases) and loads(event.reasons_json, [])
    }
    if not candidate_run_ids:
        candidate_run_ids = {run.id for run in runs if run.brand_mentioned}
    if not recommendation_run_ids:
        recommendation_run_ids = {run.id for run in runs if int(run.brand_recommendation_level or 0) >= 2}
    citation_run_ids = {
        ref.run_id for ref in refs
        if (target and _item_matches_target(ref, target)) or (not target and ref.is_official_domain)
    }
    total = len(runs)
    return {
        "total_runs": total,
        "candidate_run_count": len(candidate_run_ids),
        "candidate_rate": _rate(len(candidate_run_ids), total),
        "recommendation_run_count": len(recommendation_run_ids),
        "recommendation_rate": _rate(len(recommendation_run_ids), total),
        "target_reason_run_count": len(target_reason_run_ids),
        "target_reason_rate": _rate(len(target_reason_run_ids), total),
        "citation_run_count": len(citation_run_ids),
        "citation_rate": _rate(len(citation_run_ids), total),
        "candidate_run_ids": sorted(candidate_run_ids),
        "recommendation_run_ids": sorted(recommendation_run_ids),
        "target_reason_run_ids": sorted(target_reason_run_ids),
        "citation_run_ids": sorted(citation_run_ids),
    }


def _event_matches_brand(event: RecommendationEvent, aliases: list[str]) -> bool:
    text = " ".join([event.entity_text or "", event.answer_span or ""]).casefold()
    return any(alias and alias.casefold() in text for alias in aliases)


def _count_delta(before: dict, after: dict, key: str) -> dict:
    before_value = int(before.get(key, 0) or 0)
    after_value = int(after.get(key, 0) or 0)
    if after_value > before_value:
        direction = "OBSERVED_IMPROVEMENT"
    elif after_value < before_value:
        direction = "OBSERVED_DECLINE"
    else:
        direction = "NO_OBSERVED_CHANGE"
    return {
        "baseline": before_value,
        "validation": after_value,
        "delta": after_value - before_value,
        "direction": direction,
    }


def _metric_comparison(key: str, baseline: dict, result: dict) -> dict:
    before = _metric_value(key, baseline)
    after = _metric_value(key, result)
    row = {
        "baseline": before,
        "validation": after,
        "delta": round(after - before, 4) if before is not None and after is not None else None,
        "delta_pp": round((after - before) * 100, 1) if before is not None and after is not None and key.endswith("_rate") else None,
    }
    if key == "target_page_conversion_rate":
        baseline_conversion = baseline.get("target_page_conversion", {})
        result_conversion = result.get("target_page_conversion", {})
        row.update(
            {
                "baseline_retrieved_count": baseline_conversion.get("retrieved_count", baseline.get("target_page_retrieved_count", 0)),
                "baseline_cited_count": baseline_conversion.get("cited_count", baseline.get("target_page_cited_count", 0)),
                "validation_retrieved_count": result_conversion.get("retrieved_count", result.get("target_page_retrieved_count", 0)),
                "validation_cited_count": result_conversion.get("cited_count", result.get("target_page_cited_count", 0)),
                "not_applicable": before is None or after is None,
            }
        )
    if key == "target_page_retrieval_rate":
        baseline_retrieval = baseline.get("target_page_retrieval", {})
        result_retrieval = result.get("target_page_retrieval", {})
        row.update(
            {
                "baseline_valid_run_count": baseline_retrieval.get("valid_run_count", baseline.get("valid_run_count", 0)),
                "baseline_retrieved_run_count": baseline_retrieval.get("retrieved_run_count", baseline.get("target_page_retrieved_run_count", 0)),
                "validation_valid_run_count": result_retrieval.get("valid_run_count", result.get("valid_run_count", 0)),
                "validation_retrieved_run_count": result_retrieval.get("retrieved_run_count", result.get("target_page_retrieved_run_count", 0)),
                "baseline_run_ids": baseline_retrieval.get("run_ids", []),
                "comparison_run_ids": result_retrieval.get("run_ids", []),
                "baseline_retrieved_run_ids": baseline_retrieval.get("retrieved_run_ids", []),
                "validation_retrieved_run_ids": result_retrieval.get("retrieved_run_ids", []),
                "not_applicable": before is None or after is None,
            }
        )
    return row


def _metric_value(key: str, metrics: dict) -> float | None:
    if key == "target_page_retrieval_rate":
        retrieval = metrics.get("target_page_retrieval", {})
        return retrieval.get("retrieval_rate", metrics.get("target_page_retrieval_rate"))
    if key == "target_page_conversion_rate":
        conversion = metrics.get("target_page_conversion", {})
        return conversion.get("conversion_rate", metrics.get("target_page_conversion_rate"))
    value = metrics.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_group_results(db: Session, experiment: OptimizationExperiment) -> None:
    action = _get_action(db, experiment.action_id)
    baseline_runs = _runs_by_ids(db, loads(experiment.baseline_run_ids_json, []))
    validation_runs = _runs_by_ids(db, loads(experiment.validation_run_ids_json, []))
    experiment.per_prompt_results_json = dumps(_compare_grouped_runs(db, baseline_runs, validation_runs, action.target_url, _prompt_group_key))
    experiment.per_environment_results_json = dumps(_compare_grouped_runs(db, baseline_runs, validation_runs, action.target_url, _environment_group_key))


def _compare_grouped_runs(db: Session, baseline_runs: list[BrowserMonitorRun], validation_runs: list[BrowserMonitorRun], target_url: str, key_fn) -> list[dict]:
    grouped_keys = sorted({key_fn(run) for run in [*baseline_runs, *validation_runs]}, key=lambda item: str(item))
    prompt_ids = {run.prompt_id for run in [*baseline_runs, *validation_runs]}
    prompts = {prompt.id: prompt.prompt_text for prompt in db.query(Prompt).filter(Prompt.id.in_(prompt_ids)).all()} if prompt_ids else {}
    rows = []
    for group_key in grouped_keys:
        baseline_group = [run for run in baseline_runs if key_fn(run) == group_key]
        validation_group = [run for run in validation_runs if key_fn(run) == group_key]
        baseline_metrics = metrics_for_runs(db, baseline_group, target_url)
        validation_metrics = metrics_for_runs(db, validation_group, target_url)
        row = {
            "group_key": group_key,
            "baseline_run_ids": [run.id for run in baseline_group],
            "validation_run_ids": [run.id for run in validation_group],
            "baseline_metrics": baseline_metrics,
            "validation_metrics": validation_metrics,
            "comparison": {
                "target_page_conversion_rate": _metric_comparison("target_page_conversion_rate", baseline_metrics, validation_metrics),
                "target_page_retrieval_rate": _metric_comparison("target_page_retrieval_rate", baseline_metrics, validation_metrics),
                "brand_mention_rate": _metric_comparison("brand_mention_rate", baseline_metrics, validation_metrics),
                "brand_recommendation_rate": _metric_comparison("brand_recommendation_rate", baseline_metrics, validation_metrics),
            },
        }
        if isinstance(group_key, int):
            row["prompt_id"] = group_key
            row["prompt_text"] = prompts.get(group_key, "")
        rows.append(row)
    return rows


def _prompt_group_key(run: BrowserMonitorRun) -> int:
    return run.prompt_id


def _environment_group_key(run: BrowserMonitorRun) -> str:
    return f"{run.platform}/{run.source_type}/{run.adapter}"


def _action_payload(payload) -> dict:
    data = payload.model_dump()
    data["content_feature_changes_json"] = dumps(_normalize_feature_changes(data.pop("content_feature_changes")))
    data["status"] = "PLANNED"
    return data


def _normalize_feature_changes(value) -> list[dict]:
    if value is None:
        return []
    result = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            text = item.strip()
            if text:
                result.append({"feature": "LEGACY_NOTE", "description": text, "before": None, "after": None, "location": ""})
            continue
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if isinstance(item, dict):
            feature = str(item.get("feature") or "CUSTOM_CHANGE").strip() or "CUSTOM_CHANGE"
            description = str(item.get("description") or feature).strip()
            result.append(
                {
                    "feature": feature,
                    "before": item.get("before"),
                    "after": item.get("after"),
                    "description": description,
                    "location": str(item.get("location") or "").strip(),
                }
            )
    return result


def _normalize_action_status(value: str) -> str:
    status = (value or "PLANNED").strip()
    return ACTION_STATUS_MAP.get(status, status)


def _normalize_conclusion(value: str) -> str:
    conclusion = (value or "").strip()
    if not conclusion:
        return ""
    mapped = CONCLUSION_MAP.get(conclusion, conclusion)
    return mapped.upper()


def _run_evidence(run: BrowserMonitorRun) -> dict:
    return {
        "id": run.id,
        "prompt_id": run.prompt_id,
        "status": run.status,
        "run_sequence": run.run_sequence,
        "sample_index": run.sample_index,
        "original_query": run.original_query,
        "answer_text": run.answer_text,
        "brand_mentioned": run.brand_mentioned,
        "brand_recommendation_level": run.brand_recommendation_level,
        "reference_complete": run.reference_complete,
        "parsed_reference_count": run.parsed_reference_count,
        "resolved_url_count": run.resolved_url_count,
        "created_at": run.created_at,
    }


def _dedupe_reference_evidence(items: list[ReferenceSource]) -> list[dict]:
    grouped: dict[tuple, list[ReferenceSource]] = defaultdict(list)
    for item in items:
        title = item.display_title or item.matched_title or ""
        grouped[_global_source_key(item.canonical_url or item.url, item.domain, title)].append(item)
    rows = []
    for group_items in grouped.values():
        representative = sorted(group_items, key=lambda item: (int(item.reference_index or 999), item.run_id, item.id))[0]
        row = _reference_evidence(representative)
        row["occurrence_count"] = len(group_items)
        row["run_ids"] = sorted({item.run_id for item in group_items})
        row["reference_indices"] = sorted({int(item.reference_index or 0) for item in group_items if item.reference_index})
        row["is_official_domain"] = any(item.is_official_domain for item in group_items)
        row["is_competitor_domain"] = any(item.is_competitor_domain for item in group_items)
        rows.append(row)
    return sorted(rows, key=lambda row: (row["reference_indices"][0] if row["reference_indices"] else 999, row["domain"], row["display_title"]))


def _dedupe_retrieval_evidence(items: list[RetrievalCandidate]) -> list[dict]:
    grouped: dict[tuple, list[RetrievalCandidate]] = defaultdict(list)
    for item in items:
        grouped[_global_source_key(item.canonical_url or item.url, item.domain, item.title)].append(item)
    rows = []
    for group_items in grouped.values():
        representative = sorted(group_items, key=lambda item: (int(item.rank or 999), item.run_id, item.id))[0]
        row = _retrieval_evidence(representative)
        row["occurrence_count"] = len(group_items)
        row["run_ids"] = sorted({item.run_id for item in group_items})
        row["ranks"] = sorted({int(item.rank or 0) for item in group_items if item.rank})
        rows.append(row)
    return sorted(rows, key=lambda row: (row["ranks"][0] if row["ranks"] else 999, row["domain"], row["title"]))


def _reference_evidence(item: ReferenceSource) -> dict:
    return {
        "id": item.id,
        "run_id": item.run_id,
        "reference_index": item.reference_index,
        "display_title": item.display_title,
        "url": item.canonical_url or item.url,
        "domain": item.domain,
        "is_official_domain": item.is_official_domain,
        "is_competitor_domain": item.is_competitor_domain,
    }


def _retrieval_evidence(item: RetrievalCandidate) -> dict:
    return {
        "id": item.id,
        "run_id": item.run_id,
        "rank": item.rank,
        "title": item.title,
        "url": item.canonical_url or item.url,
        "domain": item.domain,
        "snippet": item.snippet,
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0


def _severity(issue_type: str, sample_count: int, brand_mentions: int, recommendations: int, official_refs: int) -> int:
    if issue_type == "brand_absent":
        return 5 if sample_count >= 3 else 4
    if issue_type == "brand_not_recommended" and recommendations == 0:
        return 4
    if issue_type in {"retrieved_not_cited", "official_source_absent"} and official_refs == 0:
        return 4
    return 3


def _diagnosis(project: Project, prompt: Prompt | None, issue_type: str, facts: dict) -> str:
    prompt_text = f"Prompt「{prompt.prompt_text[:60]}」" if prompt else "该 Prompt"
    if issue_type == "brand_absent":
        return f"{prompt_text} 的有效样本中未出现品牌「{project.brand_name}」，优先补可直接回答该问题的品牌实体内容。"
    if issue_type == "brand_not_recommended":
        return f"{prompt_text} 已出现品牌但推荐不足，下一步应补强推荐理由、对比维度、案例和权威引用信号。"
    if issue_type == "retrieved_not_cited":
        return f"{prompt_text} 中官网/品牌源进入检索候选但未进入引用资料，需分析页面标题、结构和可信度为何弱于被引用来源。"
    if issue_type == "official_source_absent":
        return f"{prompt_text} 的引用资料缺少官方域名，说明模型更依赖第三方来源，需要建设更可引用的官网页面。"
    return f"{prompt_text} 的引用资料完整性不稳定，先排除采集质量问题，再进入内容优化实验。"


def _official_count(items, brand_domain: str) -> int:
    if not brand_domain:
        return 0
    count = 0
    for item in items:
        domain = (getattr(item, "domain", "") or "").lower()
        url_domain = host_from_url(getattr(item, "canonical_url", "") or getattr(item, "url", "")) if getattr(item, "canonical_url", "") or getattr(item, "url", "") else ""
        if domain.endswith(brand_domain) or url_domain.endswith(brand_domain) or getattr(item, "is_official_domain", False):
            count += 1
    return count


def _valid_runs_for_experiment(db: Session, experiment: OptimizationExperiment, run_ids: list[int]) -> list[BrowserMonitorRun]:
    action = _get_action(db, experiment.action_id)
    issue = _get_issue(db, action.issue_id)
    runs = _runs_by_ids(db, run_ids, issue.project_id)
    prompt_scope = set(loads(experiment.target_prompt_scope_json, []))
    if prompt_scope:
        runs = [run for run in runs if run.prompt_id in prompt_scope]
    return [run for run in runs if run.status in VALID_RUN_STATUSES]


def _runs_by_ids(db: Session, run_ids: list[int], project_id: int | None = None) -> list[BrowserMonitorRun]:
    unique_ids = list(dict.fromkeys(int(run_id) for run_id in run_ids))
    if not unique_ids:
        return []
    query = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(unique_ids))
    if project_id is not None:
        query = query.filter(BrowserMonitorRun.project_id == project_id)
    rows = query.all()
    by_id = {run.id: run for run in rows}
    return [by_id[run_id] for run_id in unique_ids if run_id in by_id]


def _run_ids_by_issue(db: Session, issue_ids: list[int]) -> dict[int, list[int]]:
    if not issue_ids:
        return {}
    rows = db.query(OptimizationIssueRun).filter(OptimizationIssueRun.issue_id.in_(issue_ids)).all()
    result: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        result[row.issue_id].append(row.run_id)
    return result


def _issue_run_ids(db: Session, issue_id: int) -> list[int]:
    return [row.run_id for row in db.query(OptimizationIssueRun).filter(OptimizationIssueRun.issue_id == issue_id).order_by(OptimizationIssueRun.id.asc()).all()]


def _get_issue(db: Session, issue_id: int) -> OptimizationIssue:
    issue = db.get(OptimizationIssue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="优化问题不存在")
    return issue


def _get_action(db: Session, action_id: int) -> OptimizationAction:
    action = db.get(OptimizationAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="优化动作不存在")
    return action


def _get_experiment(db: Session, experiment_id: int) -> OptimizationExperiment:
    experiment = db.get(OptimizationExperiment, experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="优化实验不存在")
    return experiment


def _infer_platform_from_domain(domain: str) -> dict:
    """Infer platform from domain using DOMAIN_PLATFORM_MAP.

    Returns: {inferred_platform, method, confidence}
    raw_platform stays as whatever the parser reported.
    """
    d = (domain or "").lower().strip()
    if not d:
        return {"inferred_platform": "UNKNOWN", "method": "NO_DOMAIN", "confidence": "low"}
    # Exact match
    if d in DOMAIN_PLATFORM_MAP:
        return {"inferred_platform": DOMAIN_PLATFORM_MAP[d], "method": "DOMAIN_MAPPING", "confidence": "high"}
    # Suffix match (e.g. xxx.bilibili.com → BILIBILI)
    for map_domain, platform in DOMAIN_PLATFORM_MAP.items():
        if d.endswith("." + map_domain) or d == map_domain:
            return {"inferred_platform": platform, "method": "DOMAIN_SUFFIX_MAPPING", "confidence": "high"}
    return {"inferred_platform": "UNKNOWN", "method": "NO_MAPPING", "confidence": "low"}


# ---------------------------------------------------------------------------
# P0-2: Source Relation Layer — Candidate ↔ Citation mapping
# Role: DIAGNOSTIC_METADATA (not primary strategy evidence)
# ---------------------------------------------------------------------------

def _normalize_for_relation(url: str) -> str:
    """Normalize URL for candidate-citation matching (relation.v1)."""
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/") or "/"
        return f"{netloc}{path}"
    except Exception:
        return (url or "").lower().strip().rstrip("/")


def _build_source_relations(
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate],
) -> dict:
    """Build candidate ↔ citation relation matrix.

    Returns a dict with:
    - per-source relation classification (MATCHED / CITATION_ONLY / CANDIDATE_ONLY / UNKNOWN)
    - aggregate counts and join_rate
    - relation_spec_version for traceability
    """
    matched: list[dict] = []
    citation_only: list[dict] = []
    candidate_only: list[dict] = []
    unknown: list[dict] = []

    # Build lookup: normalized URL -> retrieval candidates
    retrieval_by_norm: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    retrieval_by_canonical: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for item in retrievals:
        retrieval_by_norm[_normalize_for_relation(item.url or item.canonical_url)].append(item)
        if item.canonical_url:
            retrieval_by_canonical[_normalize_for_relation(item.canonical_url)].append(item)

    cited_keys: set[tuple] = set()

    for ref in references:
        norm_url = _normalize_for_relation(ref.canonical_url or ref.url)
        canonical_norm = _normalize_for_relation(ref.canonical_url or "")

        # Try canonical URL match first, then normalized URL
        matched_candidates = retrieval_by_norm.get(norm_url, []) or retrieval_by_canonical.get(canonical_norm, [])

        if matched_candidates:
            candidate = matched_candidates[0]
            matched.append({
                "citation_id": ref.id,
                "candidate_id": candidate.id,
                "run_id": ref.run_id,
                "url": ref.canonical_url or ref.url,
                "canonical_url": ref.canonical_url,
                "domain": ref.domain,
                "title": ref.display_title or ref.matched_title,
                "platform": ref.platform_name,
                "relation": "MATCHED",
                "match_method": "canonical_url" if norm_url == canonical_norm else "normalized_url",
                "confidence": "high",
            })
            cited_keys.add(_source_key(ref.run_id, ref.canonical_url or ref.url, ref.domain, ref.display_title or ref.matched_title))
        else:
            citation_only.append({
                "citation_id": ref.id,
                "run_id": ref.run_id,
                "url": ref.canonical_url or ref.url,
                "canonical_url": ref.canonical_url,
                "domain": ref.domain,
                "title": ref.display_title or ref.matched_title,
                "raw_platform": ref.platform_name or "UNKNOWN",
                "inferred_platform": _infer_platform_from_domain(ref.domain)["inferred_platform"],
                "platform_inference_method": _infer_platform_from_domain(ref.domain)["method"],
                "relation": "CITATION_ONLY",
                "provenance": "UNKNOWN",
                "confidence": "low",
            })
            cited_keys.add(_source_key(ref.run_id, ref.canonical_url or ref.url, ref.domain, ref.display_title or ref.matched_title))

    # Find candidates not matched to any citation
    for item in retrievals:
        key = _source_key(item.run_id, item.canonical_url or item.url, item.domain, item.title)
        if key not in cited_keys:
            candidate_only.append({
                "candidate_id": item.id,
                "run_id": item.run_id,
                "url": item.canonical_url or item.url,
                "canonical_url": item.canonical_url,
                "domain": item.domain,
                "title": item.title,
                "rank": item.rank,
                "relation": "CANDIDATE_ONLY",
                "confidence": "medium",
            })

    total_citations = len(references)
    total_candidates = len(retrievals)
    matched_count = len(matched)
    citation_only_count = len(citation_only)
    candidate_only_count = len(candidate_only)

    run_ids_with_citations = {ref.run_id for ref in references}
    run_ids_with_candidates = {item.run_id for item in retrievals}

    return {
        "role": "DIAGNOSTIC_METADATA",
        "relation_spec_version": SOURCE_RELATION_VERSION,
        "matched_count": matched_count,
        "citation_only_count": citation_only_count,
        "candidate_only_count": candidate_only_count,
        "unknown_count": len(unknown),
        "total_citations": total_citations,
        "total_candidates": total_candidates,
        "join_rate": _rate(matched_count, total_citations) if total_citations else None,
        "citation_run_count": len(run_ids_with_citations),
        "candidate_run_count": len(run_ids_with_candidates),
        "matched": matched[:30],
        "citation_only": citation_only[:30],
        "candidate_only": candidate_only[:30],
        "unknown": unknown[:10],
        "representative_citation_only": _summarize_citation_only(citation_only),
    }


def _summarize_citation_only(rows: list[dict]) -> list[dict]:
    """Group CITATION_ONLY entries by inferred_platform + domain for evidence reporting."""
    grouped: dict[str, dict] = defaultdict(lambda: {
        "raw_platform": "", "inferred_platform": "", "domain": "",
        "count": 0, "titles": [], "run_ids": set(), "citation_ids": [],
    })
    for row in rows:
        domain = row.get("domain", "")
        inferred = row.get("inferred_platform", "UNKNOWN")
        raw = row.get("raw_platform", "UNKNOWN")
        key = f"{inferred}|{domain}"
        g = grouped[key]
        g["raw_platform"] = raw
        g["inferred_platform"] = inferred
        g["domain"] = domain
        g["count"] += 1
        if row.get("title"):
            g["titles"].append(row["title"])
        g["run_ids"].add(row["run_id"])
        if row.get("citation_id"):
            g["citation_ids"].append(row["citation_id"])
    result = []
    for g in sorted(grouped.values(), key=lambda x: (-x["count"], x["inferred_platform"])):
        result.append({
            "raw_platform": g["raw_platform"],
            "inferred_platform": g["inferred_platform"],
            "domain": g["domain"],
            "citation_only_count": g["count"],
            "representative_titles": g["titles"][:3],
            "citation_run_count": len(g["run_ids"]),
            "citation_ids": sorted(g["citation_ids"])[:10],
            "platform_semantics": "INFERRED_FROM_DOMAIN",
        })
    return result


# ---------------------------------------------------------------------------
# P0-3: EvidenceActionContext
# ---------------------------------------------------------------------------

def _build_evidence_action_context(
    db: Session,
    project: Project,
    package: OptimizationEvidencePackage,
    runs: list[BrowserMonitorRun],
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate],
    target_urls: list[str],
) -> dict:
    """Build structured EvidenceActionContext from an Evidence Package.

    This is the single upstream input for all strategy generation.
    It separates FACT (directly observed) from INFERENCE (derived judgment).
    """
    evidence = loads(package.package_payload_json, {})
    eligibility = evidence.get("run_metric_eligibility", {})
    metrics = evidence.get("metrics", [])
    metric_snapshot = evidence.get("metric_snapshot", {})
    platform_matrix = evidence.get("platform_gap_matrix", [])
    content_types = evidence.get("content_type_distribution", [])
    time_dist = evidence.get("time_distribution", [])
    retrieval_coverage = evidence.get("retrieval_coverage_summary", {})
    source_relations = _build_source_relations(references, retrievals)

    # --- Citation Landscape (uses inferred_platform from domain) ---
    citation_domains = Counter(ref.domain for ref in references if ref.domain).most_common(20)
    citation_inferred_platforms: Counter[str] = Counter()
    for ref in references:
        inferred = _infer_platform_from_domain(ref.domain)["inferred_platform"]
        citation_inferred_platforms[inferred] += 1
    citation_inferred_top = citation_inferred_platforms.most_common(15)

    # --- Citation Content Patterns (unavailable until content body capture is implemented) ---
    citation_content_patterns = {
        "available": False,
        "reason": "CONTENT_BODY_UNAVAILABLE",
        "message": "Citation content body analysis is not available — only source-level (title/domain/URL) evidence exists. Content structure patterns (steps, FAQ, limitations, author type, etc.) cannot be determined.",
    }

    # --- Retrieval Landscape ---
    retrieval_domains = Counter(item.domain for item in retrievals if item.domain).most_common(20)

    # --- Brand Channel Gaps (using inferred_platform) ---
    brand_domain = host_from_url(project.website_url) if project.website_url else ""
    brand_channels = _analyze_brand_channel_gaps(platform_matrix, brand_domain, project)

    # --- Official Site Fit ---
    official_site_fit = _analyze_official_site_fit(
        platform_matrix,
        content_types,
        metrics,
        target_urls[0] if target_urls else "",
        brand_domain,
        source_relations,
        run_count=len(runs),
    )

    # --- Content Type Patterns ---
    content_type_patterns = _extract_content_type_patterns(content_types)

    # --- Platform Patterns ---
    platform_patterns = _extract_platform_patterns(platform_matrix)

    # --- Answer Strategy Signals ---
    answer_strategy_signals = _extract_answer_strategy_signals(db, project, package, runs)

    # --- Time Patterns ---
    time_patterns = _extract_time_patterns(time_dist)

    # --- Structured Facts ---
    facts = _extract_structured_facts(
        project=project,
        prompt_text=(evidence.get("prompt") or {}).get("prompt_text", ""),
        runs=runs,
        metrics=metrics,
        metric_snapshot=metric_snapshot,
        platform_matrix=platform_matrix,
        content_types=content_types,
        source_relations=source_relations,
        eligibility=eligibility,
        target_urls=target_urls,
    )

    # --- Missing Evidence ---
    missing_evidence = _identify_missing_evidence(source_relations, platform_matrix, content_types, brand_channels)

    # --- Decision Capability ---
    decision_capability = _determine_decision_capability(
        citation_content_patterns_available=citation_content_patterns["available"],
        content_type_patterns=content_type_patterns,
        source_relations=source_relations,
    )

    return {
        "evidence_action_version": EVIDENCE_ACTION_VERSION,
        "package_id": package.id,
        "prompt_id": package.prompt_id,
        "prompt_text": (evidence.get("prompt") or {}).get("prompt_text", ""),
        "source_run_ids": loads(package.source_run_ids_json, []),
        "target_page_urls": target_urls,

        "citation_landscape": {
            "total_citation_runs": len(eligibility.get("citation_eligible_run_ids", [])),
            "top_domains": [{"domain": d, "count": c} for d, c in citation_domains[:10]],
            "top_platforms_raw": [
                {"raw_platform": p, "count": c}
                for p, c in Counter(ref.platform_name or "UNKNOWN" for ref in references).most_common(10)
            ],
            "top_platforms_inferred": [
                {
                    "inferred_platform": p,
                    "count": c,
                    "platform_semantics": "INFERRED_FROM_DOMAIN",
                }
                for p, c in citation_inferred_top[:10]
            ],
            "platform_semantics_note": "raw_platform comes from parser; inferred_platform is derived from domain via DOMAIN_PLATFORM_MAP. Brand channel gaps use inferred_platform.",
        },
        "retrieval_landscape": {
            "total_retrieval_runs": len(eligibility.get("retrieval_eligible_run_ids", [])),
            "retrieval_metrics_status": evidence.get("retrieval_metrics_status", "unknown"),
            "top_domains": [{"domain": d, "count": c} for d, c in retrieval_domains[:10]],
            "coverage_summary": retrieval_coverage,
        },
        "source_relation_landscape": {
            "role": source_relations.get("role", "DIAGNOSTIC_METADATA"),
            "relation_spec_version": source_relations["relation_spec_version"],
            "total_citations": source_relations.get("total_citations", 0),
            "total_candidates": source_relations.get("total_candidates", 0),
            "citation_run_count": source_relations.get("citation_run_count", 0),
            "candidate_run_count": source_relations.get("candidate_run_count", 0),
            "matched_count": source_relations["matched_count"],
            "citation_only_count": source_relations["citation_only_count"],
            "candidate_only_count": source_relations["candidate_only_count"],
            "join_rate": source_relations["join_rate"],
            "representative_citation_only": source_relations.get("representative_citation_only", []),
        },

        "citation_content_patterns": citation_content_patterns,
        "citation_content_analysis_available": citation_content_patterns["available"],
        "content_type_patterns": content_type_patterns,
        "platform_patterns": platform_patterns,
        "answer_strategy_signals": answer_strategy_signals,
        "time_patterns": time_patterns,

        "brand_presence": {
            "brand_name": project.brand_name,
            "brand_mention_rate": metric_snapshot.get("brand_mention_rate", 0),
            "brand_recommendation_rate": metric_snapshot.get("brand_recommendation_rate", 0),
            "official_reference_rate": metric_snapshot.get("official_reference_rate", 0),
        },
        "brand_channel_gaps": brand_channels,
        "official_site_fit": official_site_fit,

        "decision_capability": decision_capability,

        "evidence_facts": facts,
        "representative_sources": evidence.get("representative_sources", []),
        "evidence_confidence": _assess_evidence_confidence(source_relations, eligibility, runs),
        "missing_evidence": missing_evidence,
    }


def _determine_decision_capability(
    citation_content_patterns_available: bool,
    content_type_patterns: dict,
    source_relations: dict,
) -> str:
    """Determine what level of strategy decision the current evidence can support."""
    has_content_direction = bool(
        content_type_patterns.get("high_citation_types")
        or content_type_patterns.get("low_citation_types")
    )

    if not has_content_direction:
        return "NEEDS_MORE_EVIDENCE"

    if citation_content_patterns_available:
        return "PLATFORM_AND_CONTENT_DIRECTION"

    return "CONTENT_DIRECTION_ONLY"


def _analyze_brand_channel_gaps(
    platform_matrix: list[dict],
    brand_domain: str,
    project: Project,
) -> list[dict]:
    """Identify platforms where AI citations exist but brand has no confirmed presence."""
    gaps = []
    for row in platform_matrix:
        if row.get("citation_run_count", 0) == 0:
            continue
        platform = row.get("platform_label") or row.get("platform", "")
        brand_candidate = row.get("brand_candidate_count", 0)
        brand_citation = row.get("brand_citation_count", 0)
        competitor_citation = row.get("competitor_citation_count", 0)

        gap = {
            "platform": platform,
            "citation_run_count": row["citation_run_count"],
            "brand_presence": "PRESENT" if (brand_candidate + brand_citation) > 0 else "ABSENT",
            "brand_candidate_count": brand_candidate,
            "brand_citation_count": brand_citation,
            "competitor_citation_count": competitor_citation,
            "gap_severity": "CRITICAL" if brand_citation == 0 and row["citation_run_count"] >= 6 else "MODERATE" if brand_citation == 0 else "NONE",
        }
        gaps.append(gap)
    return sorted(gaps, key=lambda g: (-g["citation_run_count"], g["gap_severity"]))


def _analyze_official_site_fit(
    platform_matrix: list[dict],
    content_types: list[dict],
    metrics: list[dict],
    target_url: str,
    brand_domain: str,
    source_relations: dict,
    run_count: int = 0,
) -> dict:
    """Analyze whether official site content is a good fit for this prompt's citation patterns."""
    # Target page performance
    retrieval_rate = None
    for m in metrics:
        if m.get("metric_name") == "target_page_retrieval_rate":
            retrieval_rate = m
            break

    # Official domain citation
    official_citation_runs = 0
    for row in platform_matrix:
        if row.get("brand_citation_count", 0) > 0:
            official_citation_runs = max(official_citation_runs, row["citation_run_count"])

    # TOOL_PAGE performance
    tool_page_perf = {"candidate_run_count": 0, "citation_run_count": 0}
    for ct in content_types:
        if ct.get("content_type") == "TOOL_PAGE":
            tool_page_perf["candidate_run_count"] = ct.get("candidate_run_count", 0)
            tool_page_perf["citation_run_count"] = ct.get("citation_run_count", 0)

    # High-performing content types for owned-site potential
    high_performing_types = []
    for ct in content_types:
        if ct.get("citation_run_count", 0) >= 6:
            content_type = ct.get("content_type", "")
            if content_type in {"TUTORIAL", "RULE_EXPLANATION", "Q_AND_A", "TROUBLESHOOTING", "VIDEO"}:
                high_performing_types.append(content_type)

    # Overall fit assessment
    if tool_page_perf["citation_run_count"] == 0 and tool_page_perf["candidate_run_count"] >= 10:
        tool_page_fit = "LOW — tool pages are retrieved but never cited; strengthening existing tool pages alone is unlikely to improve citation"
    elif tool_page_perf["citation_run_count"] > 0:
        tool_page_fit = "MODERATE — tool pages show some citation signal"
    else:
        tool_page_fit = "UNKNOWN — insufficient tool page data"

    owned_content_opportunity = len(high_performing_types) > 0

    return {
        "target_url": target_url,
        "target_page_retrieval_rate": retrieval_rate.get("value") if retrieval_rate else None,
        "target_page_retrieval_status": retrieval_rate.get("calculation_status") if retrieval_rate else "unknown",
        "official_domain_cited_runs": official_citation_runs,
        "official_reference_rate": 0.0,
        "tool_page_candidate_coverage": f"{tool_page_perf['candidate_run_count']}/{run_count}",
        "tool_page_citation_coverage": f"{tool_page_perf['citation_run_count']}/{run_count}",
        "tool_page_fit_assessment": tool_page_fit,
        "high_performing_owned_content_types": high_performing_types,
        "owned_content_extension_viable": owned_content_opportunity,
        "assessment": (
            "Tool pages are retrieved but not cited. "
            "However, tutorial/rule-explanation/QA content types show strong citation signals. "
            "Creating new informational content assets (not just tool pages) on the owned site is a viable option. "
            "Simply modifying the existing tool page is less likely to be effective than creating new supporting content."
            if owned_content_opportunity
            else "Insufficient evidence to recommend owned-site content changes."
        ),
        "source_relation_note": (
            f"Of {source_relations.get('total_citations', 0)} total citations, "
            f"{source_relations.get('citation_only_count', 0)} have no matching retrieval candidate "
            f"(join_rate={source_relations.get('join_rate')})."
        ),
    }


def _extract_content_type_patterns(content_types: list[dict]) -> dict:
    high_citation = []
    low_citation = []
    for ct in content_types:
        content_type = ct.get("content_type")
        if not content_type:
            continue
        if content_type in {"OTHER", "UNCATEGORIZED"}:
            continue
        if ct.get("citation_run_count", 0) >= 6:
            high_citation.append(content_type)
        if ct.get("candidate_run_count", 0) >= 6 and ct.get("citation_run_count", 0) == 0:
            low_citation.append(content_type)
    return {
        "high_citation_types": high_citation,
        "low_citation_types": low_citation,
        "dominant_pattern": (
            "TUTORIAL/VIDEO/QA/RULE_EXPLANATION types dominate citations; "
            "TOOL_PAGE/NEWS types show divergent candidate-vs-citation behavior."
        ),
    }


def _extract_platform_patterns(platform_matrix: list[dict]) -> dict:
    citation_platforms = []
    for row in platform_matrix:
        platform = row.get("platform", "")
        citation_run_count = row.get("citation_run_count", 0) or 0
        if not platform or platform in {"UNKNOWN", "unknown"} or citation_run_count <= 0:
            continue
        citation_platforms.append({
            "platform": platform,
            "platform_label": row.get("platform_label") or source_platform_label(platform),
            "citation_run_count": citation_run_count,
            "candidate_run_count": row.get("candidate_run_count", 0) or 0,
            "citation_occurrence_count": row.get("citation_occurrence_count", 0) or 0,
            "representative_cited_urls": (row.get("representative_cited_urls") or [])[:3],
        })
    citation_platforms.sort(
        key=lambda item: (
            -item["citation_run_count"],
            -item["citation_occurrence_count"],
            -item["candidate_run_count"],
            item["platform_label"],
        )
    )
    return {
        "top_citation_platforms": citation_platforms[:5],
        "recommendation_basis": "按最终引用覆盖 Run、引用出现次数和候选覆盖排序；检索候选不足时不解释为完整候选漏斗转化。",
    }


def _signal_level_label(level: str) -> str:
    return {
        "ANSWER_RECOMMENDATION_CONTEXT": "答案明确推荐上下文",
        "SELECTION_REASON_CONTEXT": "选择理由上下文",
        "ANSWER_CITATION_CONTEXT": "答案引用上下文",
        "CITATION_FALLBACK": "普通引用分布",
    }.get(level, level or "未知信号")


def _signal_level_rank(level: str) -> int:
    return {
        "ANSWER_RECOMMENDATION_CONTEXT": 4,
        "SELECTION_REASON_CONTEXT": 3,
        "ANSWER_CITATION_CONTEXT": 2,
        "CITATION_FALLBACK": 1,
    }.get(level, 0)


def _extract_answer_strategy_signals(
    db: Session,
    project: Project,
    package: OptimizationEvidencePackage,
    runs: list[BrowserMonitorRun],
) -> dict:
    run_ids = sorted({run.id for run in runs})
    if not run_ids or not package.prompt_id:
        return {
            "available": False,
            "reason": "NO_PROMPT_RUN_SCOPE",
            "signal_priority_note": "无 Prompt/Run 范围，无法读取答案推荐上下文。",
            "top_answer_platforms": [],
            "recommended_content_types": [],
        }

    snapshots = db.query(RecommendationIntelligenceSnapshot).filter(
        RecommendationIntelligenceSnapshot.project_id == project.id,
        RecommendationIntelligenceSnapshot.prompt_id == package.prompt_id,
    ).order_by(RecommendationIntelligenceSnapshot.id.desc()).limit(20).all()
    snapshot = None
    run_id_set = set(run_ids)
    for candidate_snapshot in snapshots:
        snapshot_run_ids = set(loads(candidate_snapshot.source_run_ids_json, []))
        if snapshot_run_ids and snapshot_run_ids.isdisjoint(run_id_set):
            continue
        snapshot = candidate_snapshot
        break
    if not snapshot:
        return {
            "available": False,
            "reason": "NO_RECOMMENDATION_SNAPSHOT",
            "signal_priority_note": "尚未生成与当前证据包 Run 重叠的决策诊断快照，策略只能退回普通引用分布。",
            "top_answer_platforms": [],
            "recommended_content_types": [],
        }

    claims = db.query(RecommendationClaim).filter(
        RecommendationClaim.snapshot_id == snapshot.id,
        RecommendationClaim.run_id.in_(run_ids),
    ).all()
    recommendation_claim_ids = {
        claim.id
        for claim in claims
        if claim.recommendation_type in {"POSITIVE_RECOMMENDATION", "TOP_RECOMMENDATION"}
    }
    adoptions = db.query(DecisionEvidenceAdoption).filter(
        DecisionEvidenceAdoption.snapshot_id == snapshot.id,
        DecisionEvidenceAdoption.run_id.in_(run_ids),
        DecisionEvidenceAdoption.cited.is_(True),
    ).all()
    refs_by_id = {
        ref.id: ref
        for ref in db.query(ReferenceSource).filter(
            ReferenceSource.id.in_([row.citation_id for row in adoptions if row.citation_id])
        ).all()
    } if adoptions else {}

    grouped: dict[str, dict] = {}
    content_counter: Counter[str] = Counter()
    for adoption in adoptions:
        ref = refs_by_id.get(adoption.citation_id)
        if not ref:
            continue
        title = ref.display_title or ref.matched_title or adoption.source_title or ref.url
        url = ref.canonical_url or ref.url or adoption.source_url
        domain = ref.domain or adoption.source_domain or host_from_url(url)
        platform = _item_platform(project, ref, title, url, domain)
        if not platform or platform in {"UNKNOWN", "unknown"}:
            platform = "web"
        content_type = _classify_content_type(title, url, "", domain)["content_type"]
        if content_type not in {"OTHER", "UNCATEGORIZED", "NEWS"}:
            content_counter[content_type] += 1

        if adoption.recommendation_claim_id in recommendation_claim_ids:
            level = "ANSWER_RECOMMENDATION_CONTEXT"
        elif adoption.associated_with_selection_reason:
            level = "SELECTION_REASON_CONTEXT"
        else:
            level = "ANSWER_CITATION_CONTEXT"

        row = grouped.setdefault(platform, {
            "platform": platform,
            "platform_label": source_platform_label(platform),
            "signal_level": level,
            "recommendation_context_run_ids": set(),
            "selection_reason_context_run_ids": set(),
            "answer_citation_context_run_ids": set(),
            "occurrence_count": 0,
            "content_type_counts": Counter(),
            "representative_sources": [],
        })
        if _signal_level_rank(level) > _signal_level_rank(row["signal_level"]):
            row["signal_level"] = level
        row["occurrence_count"] += 1
        row["answer_citation_context_run_ids"].add(adoption.run_id)
        if level == "ANSWER_RECOMMENDATION_CONTEXT":
            row["recommendation_context_run_ids"].add(adoption.run_id)
        if level in {"ANSWER_RECOMMENDATION_CONTEXT", "SELECTION_REASON_CONTEXT"}:
            row["selection_reason_context_run_ids"].add(adoption.run_id)
        row["content_type_counts"][content_type] += 1
        if len(row["representative_sources"]) < 3:
            row["representative_sources"].append({
                "title": title,
                "url": url,
                "domain": domain,
                "run_id": adoption.run_id,
                "signal_level": _signal_level_label(level),
                "answer_span": (adoption.answer_span or "")[:240],
            })

    rows = []
    for row in grouped.values():
        content_types = [
            content_type
            for content_type, _ in row["content_type_counts"].most_common()
            if content_type not in {"OTHER", "UNCATEGORIZED", "NEWS"}
        ]
        rows.append({
            "platform": row["platform"],
            "platform_label": row["platform_label"],
            "signal_level": row["signal_level"],
            "signal_level_label": _signal_level_label(row["signal_level"]),
            "recommendation_context_run_count": len(row["recommendation_context_run_ids"]),
            "selection_reason_context_run_count": len(row["selection_reason_context_run_ids"]),
            "answer_citation_context_run_count": len(row["answer_citation_context_run_ids"]),
            "occurrence_count": row["occurrence_count"],
            "content_types": content_types[:5],
            "content_type_labels": [_strategy_content_type_label(item) for item in content_types[:5]],
            "representative_sources": row["representative_sources"],
        })
    rows.sort(
        key=lambda row: (
            -_signal_level_rank(row["signal_level"]),
            -row["recommendation_context_run_count"],
            -row["selection_reason_context_run_count"],
            -row["answer_citation_context_run_count"],
            -row["occurrence_count"],
            row["platform_label"],
        )
    )
    recommended_content_types = [
        content_type
        for content_type, _ in content_counter.most_common()
        if content_type not in {"OTHER", "UNCATEGORIZED", "NEWS"}
    ]

    # --- Decision space signals: 这个问题值不值得做 ---
    facts = db.query(AnswerSemanticFact).filter(
        AnswerSemanticFact.snapshot_id == snapshot.id,
        AnswerSemanticFact.run_id.in_(run_ids),
    ).all()
    fact_runs: dict[str, set[int]] = defaultdict(set)
    for fact in facts:
        if fact.fact_value:
            fact_runs[fact.fact_type].add(fact.run_id)

    def _rate(fact_type: str) -> str:
        return f"{len(fact_runs.get(fact_type, set()))}/{len(run_ids)}"

    has_choice_slot = _rate("has_choice_slot")
    has_brand_mention = _rate("has_brand_mention")
    has_explicit_rec = _rate("has_explicit_recommendation")
    has_comparison = _rate("has_comparison")

    # 值不值得做判定：
    # - 有选择空间（AI 在推荐/选择方案）→ 有干预价值
    # - 无选择空间 → 该问题答案天然不推荐任何实体，品牌优化空间有限
    choice_n = len(fact_runs.get("has_choice_slot", set()))
    if choice_n == 0:
        worth_level = "LOW_WORTH"
        worth_note = "答案不存在选择空间：AI 在回答该问题时没有表现出推荐任何品牌/工具的意向，品牌优化收益可能有限。"
    elif len(fact_runs.get("has_explicit_recommendation", set())) == 0:
        worth_level = "UNCERTAIN_WORTH"
        worth_note = "答案存在选择空间，但当前样本中没有出现任何明确推荐：值得观察答案是否以候选/提及方式给品牌留出进入空间。"
    else:
        worth_level = "WORTH_PURSUING"
        worth_note = "答案存在选择空间且出现明确推荐：该问题是品牌 GEO 干预的直接机会点。"

    decision_space = {
        "worth_level": worth_level,
        "worth_note": worth_note,
        "has_choice_slot": has_choice_slot,
        "has_choice_slot_label": "答案选择空间",
        "has_brand_mention": has_brand_mention,
        "has_brand_mention_label": "目标品牌被提及",
        "has_explicit_recommendation": has_explicit_rec,
        "has_explicit_recommendation_label": "出现明确推荐",
        "has_comparison": has_comparison,
        "has_comparison_label": "出现对比判断",
        "eligible_run_count": len(run_ids),
        "fact_review_status": "UNREVIEWED" if any(f.review_status == "UNREVIEWED" for f in facts) else "REVIEWED",
    }

    return {
        "available": bool(rows),
        "snapshot_id": snapshot.id,
        "reason": "OK" if rows else "NO_CITED_RECOMMENDATION_CONTEXT",
        "signal_priority_note": "策略信号优先级：答案明确推荐上下文 > 选择理由上下文 > 答案引用上下文 > 普通引用分布。",
        "decision_space": decision_space,
        "top_answer_platforms": rows[:5],
        "recommended_content_types": recommended_content_types[:6],
    }


def _strategy_content_type_label(content_type: str) -> str:
    return {
        "VIDEO": "视频教程",
        "Q_AND_A": "问答内容",
        "TUTORIAL": "操作教程",
        "RULE_EXPLANATION": "规则说明",
        "TROUBLESHOOTING": "排障说明",
        "COMPARISON": "对比评测",
        "TOOL_PAGE": "工具说明页",
        "NEWS": "新闻资讯",
    }.get(content_type, "其他内容")


def _retrieval_metric_is_usable(metric_fact: dict | None) -> bool:
    if not metric_fact:
        return False
    status = str(metric_fact.get("calculation_status") or "unknown")
    return status not in UNAVAILABLE_RETRIEVAL_METRIC_STATUSES


def _strategy_recommended_content_types(content_types: list[str], preserve_order: bool = False) -> list[str]:
    priority = ["TUTORIAL", "Q_AND_A", "TROUBLESHOOTING", "VIDEO", "RULE_EXPLANATION", "COMPARISON", "TOOL_PAGE"]
    usable = [item for item in content_types if item not in {"OTHER", "UNCATEGORIZED", "NEWS"}]
    if preserve_order:
        ordered = []
        for item in usable:
            if item not in ordered:
                ordered.append(item)
    else:
        ordered = [item for item in priority if item in usable]
    if not ordered and "NEWS" in content_types:
        ordered = ["TUTORIAL", "Q_AND_A", "RULE_EXPLANATION"]
    return ordered[:4] or ["TUTORIAL", "Q_AND_A", "RULE_EXPLANATION"]


def _strategy_platform_content_focus(platform: str, recommended_content_types: list[str]) -> list[str]:
    platform_key = (platform or "").lower()
    focus_map = {
        "bilibili": ["VIDEO", "TUTORIAL", "TROUBLESHOOTING"],
        "douyin": ["VIDEO", "TUTORIAL", "Q_AND_A"],
        "zhihu": ["Q_AND_A", "TUTORIAL", "COMPARISON"],
        "baijiahao": ["TUTORIAL", "Q_AND_A", "RULE_EXPLANATION"],
        "wechat_official_account": ["RULE_EXPLANATION", "TUTORIAL", "Q_AND_A"],
        "xiaohongshu": ["TUTORIAL", "Q_AND_A", "VIDEO"],
        "web": ["TUTORIAL", "Q_AND_A", "RULE_EXPLANATION"],
    }
    preferred = focus_map.get(platform_key, ["TUTORIAL", "Q_AND_A", "RULE_EXPLANATION"])
    ordered = [item for item in preferred if item in recommended_content_types]
    ordered.extend(item for item in recommended_content_types if item not in ordered)
    return ordered[:2] or preferred[:2]


def _strategy_platform_action(platform_label: str, content_focus: list[str]) -> str:
    focus_text = "、".join(_strategy_content_type_label(item) for item in content_focus)
    if "B站" in platform_label:
        return f"在{platform_label}发布{focus_text}，重点做完整操作录屏、卡片配置演示、失败排查和风险提醒"
    if "知乎" in platform_label:
        return f"在{platform_label}发布{focus_text}，重点回答怎么做、工具选择、限制条件、常见失败原因和安全合规问题"
    if "抖音" in platform_label:
        return f"在{platform_label}发布{focus_text}，重点展示卡片效果、配置步骤、适用场景和跳转限制"
    if "百家号" in platform_label or "网页" in platform_label:
        return f"在{platform_label}发布{focus_text}，重点沉淀可索引的步骤说明、FAQ、平台规则和排障清单"
    return f"在{platform_label}发布{focus_text}，围绕当前 Prompt 的定义、步骤、限制、FAQ 和案例证据组织内容"


def _strategy_platform_recommendations(
    platform_patterns: dict,
    recommended_content_types: list[str],
    answer_strategy_signals: dict | None = None,
) -> list[dict]:
    recommendations = []
    answer_rows = (answer_strategy_signals or {}).get("top_answer_platforms", [])
    source_rows = answer_rows if answer_rows else (platform_patterns or {}).get("top_citation_platforms", [])
    for row in source_rows[:3]:
        platform = row.get("platform", "")
        platform_label = row.get("platform_label") or source_platform_label(platform)
        row_content_types = row.get("content_types") or recommended_content_types
        content_focus = _strategy_platform_content_focus(platform, row_content_types)
        signal_level = row.get("signal_level") or "CITATION_FALLBACK"
        signal_level_label = row.get("signal_level_label") or _signal_level_label(signal_level)
        citation_run_count = row.get("citation_run_count", row.get("answer_citation_context_run_count", 0))
        occurrence_count = row.get("citation_occurrence_count", row.get("occurrence_count", 0))
        representative_sources = row.get("representative_sources") or row.get("representative_cited_urls", [])
        if signal_level != "CITATION_FALLBACK":
            evidence_basis = (
                f"信号等级：{signal_level_label}；推荐上下文覆盖 {row.get('recommendation_context_run_count', 0)} 个 Run，"
                f"选择理由上下文覆盖 {row.get('selection_reason_context_run_count', 0)} 个 Run，"
                f"答案引用上下文覆盖 {row.get('answer_citation_context_run_count', 0)} 个 Run。"
            )
        else:
            evidence_basis = (
                f"{platform_label} 在当前样本中覆盖 {citation_run_count} 个引用 Run，"
                f"引用出现 {occurrence_count} 次。"
            )
        recommendations.append({
            "platform": platform,
            "platform_label": platform_label,
            "signal_level": signal_level,
            "signal_level_label": signal_level_label,
            "content_types": content_focus,
            "content_type_labels": [_strategy_content_type_label(item) for item in content_focus],
            "recommendation_context_run_count": row.get("recommendation_context_run_count", 0),
            "selection_reason_context_run_count": row.get("selection_reason_context_run_count", 0),
            "answer_citation_context_run_count": row.get("answer_citation_context_run_count", 0),
            "citation_run_count": citation_run_count,
            "candidate_run_count": row.get("candidate_run_count", 0),
            "citation_occurrence_count": occurrence_count,
            "representative_sources": representative_sources,
            "recommended_action": _strategy_platform_action(platform_label, content_focus),
            "evidence_basis": evidence_basis,
        })
    return recommendations


def _strategy_platform_direction(platform_recommendations: list[dict]) -> str:
    if not platform_recommendations:
        return (
            "当前证据不足以形成平台优先级；三方平台账号可新注册，不以历史内容或账号存量作为前置条件。"
            "请先补齐引用/候选平台证据，再决定发布平台。"
        )
    summary = "；".join(
        f"{item['platform_label']}（{item.get('signal_level_label', '普通引用分布')}），适合发{'、'.join(item['content_type_labels'])}"
        for item in platform_recommendations
    )
    actions = "；".join(item["recommended_action"] for item in platform_recommendations)
    return (
        f"基于当前答案信号分层，优先平台建议为：{summary}。"
        f"建议执行组合：{actions}。"
        "排序规则：答案明确推荐上下文优先，其次选择理由上下文，再其次普通引用分布。"
        "三方平台账号可新注册，不以历史内容或账号存量作为前置条件；最终平台、账号和 target_url 仍需人工审核确认。"
    )


def _extract_time_patterns(time_dist: list[dict]) -> dict:
    buckets = {}
    for t in time_dist:
        buckets[t.get("freshness_bucket", "UNKNOWN")] = {
            "candidate_runs": t.get("candidate_run_count", 0),
            "citation_runs": t.get("citation_run_count", 0),
            "unknown_date_ratio": t.get("unknown_ratio", 0),
        }
    high_unknown = buckets.get("UNKNOWN", {}).get("unknown_date_ratio", 0) > 0.3
    return {
        "buckets": buckets,
        "high_date_uncertainty": high_unknown,
        "pattern_note": (
            "High proportion of sources have unknown publish dates; "
            "freshness signal is insufficient to drive content strategy decisions."
            if high_unknown
            else "Freshness distribution is adequate for strategy input."
        ),
    }


def _extract_structured_facts(
    project: Project,
    prompt_text: str,
    runs: list[BrowserMonitorRun],
    metrics: list[dict],
    metric_snapshot: dict,
    platform_matrix: list[dict],
    content_types: list[dict],
    source_relations: dict,
    eligibility: dict,
    target_urls: list[str],
) -> list[dict]:
    """Extract structured FACTS (not inferences) from evidence."""
    facts: list[dict] = []
    run_ids = sorted([run.id for run in runs])
    fact_id = 1

    def _add(metric_name: str, numerator, denominator, value, **extra):
        nonlocal fact_id
        facts.append({
            "fact_id": f"FACT-{fact_id:03d}",
            "fact_type": "METRIC",
            "metric_name": metric_name,
            "numerator": numerator,
            "denominator": denominator,
            "value": value,
            "source_run_ids": extra.pop("source_run_ids", run_ids),
            "confidence": "HIGH",
            **extra,
        })
        fact_id += 1

    # Core metrics
    _add("valid_run_count", metric_snapshot.get("valid_run_count", 0), len(runs), metric_snapshot.get("valid_run_count", 0))
    _add("brand_mention_rate", metric_snapshot.get("brand_mention_count", 0), len(runs), metric_snapshot.get("brand_mention_rate", 0))
    _add("brand_recommendation_rate", metric_snapshot.get("brand_recommendation_count", 0), len(runs), metric_snapshot.get("brand_recommendation_rate", 0))
    _add("official_reference_rate", metric_snapshot.get("official_reference_count", 0), metric_snapshot.get("citation_eligible_run_count", 0), metric_snapshot.get("official_reference_rate", 0))

    # Target page metrics
    target_retrieval = metric_snapshot.get("target_page_retrieval", {})
    target_conversion = metric_snapshot.get("target_page_conversion", {})
    _add("target_page_retrieval_rate",
         target_retrieval.get("retrieved_run_count", 0),
         target_retrieval.get("valid_run_count", 0),
         target_retrieval.get("retrieval_rate"),
         target_url=target_urls[0] if target_urls else "",
         calculation_status=target_retrieval.get("calculation_status", "unknown"))
    _add("target_page_conversion_rate",
         target_conversion.get("cited_count", 0),
         target_conversion.get("retrieved_count", 0),
         target_conversion.get("conversion_rate"),
         calculation_status=target_conversion.get("calculation_status", "not_applicable"))

    # Platform facts
    for row in platform_matrix:
        facts.append({
            "fact_id": f"FACT-{fact_id:03d}",
            "fact_type": "PLATFORM_COVERAGE",
            "metric_name": "platform_citation_run_coverage",
            "numerator": row.get("citation_run_count", 0),
            "denominator": len(runs),
            "value": _rate(row.get("citation_run_count", 0), len(runs)),
            "platform": row.get("platform_label") or row.get("platform", ""),
            "platform_key": row.get("platform", ""),
            "candidate_run_count": row.get("candidate_run_count", 0),
            "citation_run_count": row.get("citation_run_count", 0),
            "source_run_ids": run_ids,
            "confidence": "HIGH",
        })
        fact_id += 1

    # Content type facts
    for ct in content_types:
        facts.append({
            "fact_id": f"FACT-{fact_id:03d}",
            "fact_type": "CONTENT_TYPE_DISTRIBUTION",
            "metric_name": "content_type_citation_run_coverage",
            "numerator": ct.get("citation_run_count", 0),
            "denominator": len(runs),
            "value": _rate(ct.get("citation_run_count", 0), len(runs)),
            "content_type": ct.get("content_type", ""),
            "candidate_run_count": ct.get("candidate_run_count", 0),
            "citation_run_count": ct.get("citation_run_count", 0),
            "source_run_ids": run_ids,
            "confidence": "MEDIUM",
        })
        fact_id += 1

    # Source relation facts
    facts.append({
        "fact_id": f"FACT-{fact_id:03d}",
        "fact_type": "SOURCE_RELATION",
        "metric_name": "candidate_citation_join_rate",
        "numerator": source_relations.get("matched_count", 0),
        "denominator": source_relations.get("total_citations", 0),
        "value": source_relations.get("join_rate"),
        "citation_only_count": source_relations.get("citation_only_count", 0),
        "candidate_only_count": source_relations.get("candidate_only_count", 0),
        "relation_spec_version": SOURCE_RELATION_VERSION,
        "source_run_ids": run_ids,
        "confidence": "HIGH",
    })
    fact_id += 1

    return facts


def _identify_missing_evidence(
    source_relations: dict,
    platform_matrix: list[dict],
    content_types: list[dict],
    brand_channels: list[dict],
) -> list[dict]:
    """Identify what evidence is missing to make confident strategy decisions."""
    missing = []

    # Citation-only provenance gaps
    cit_only = source_relations.get("representative_citation_only", [])
    seen_platforms = set()
    for g in cit_only:
        platform = g.get("platform", "unknown")
        if g.get("citation_run_count", 0) >= 8 and platform not in seen_platforms:
            seen_platforms.add(platform)
            missing.append({
                "category": "CITATION_PROVENANCE",
                "platform": platform,
                "domain": g.get("domain", ""),
                "citation_only_count": g.get("citation_only_count", 0),
                "reason": f"Platform {platform} shows citations but zero retrieval candidates — cannot determine if citations come from model internal knowledge or are sourced from search results the parser cannot capture.",
                "recommended_action": "Investigate citation source: review answer text for explicit references; check if domain appears in DOM-level reference elements.",
            })

    # Brand absence
    for ch in brand_channels:
        if ch.get("gap_severity") == "CRITICAL" and ch.get("citation_run_count", 0) >= 8:
            missing.append({
                "category": "BRAND_ASSET_UNKNOWN",
                "platform": ch.get("platform", "unknown"),
                "reason": f"Brand has no confirmed presence on {ch.get('platform')} which has {ch.get('citation_run_count')} citation runs. Third-party accounts can be registered, but the platform choice and publishing rules still need human review.",
                "recommended_action": "Confirm whether to register or use an account on this platform, then review publishing rules, account controllability, and content fit.",
            })

    # Content body availability
    missing.append({
        "category": "CONTENT_BODY_UNAVAILABLE",
        "reason": "Page content body analysis is not available — only source-level (title/domain/URL) evidence is captured. Citation reasons and content structure signals cannot be verified at paragraph level.",
        "recommended_action": "Enable full page body capture and structured content analysis for cited sources.",
    })

    return missing


def _assess_evidence_confidence(
    source_relations: dict,
    eligibility: dict,
    runs: list[BrowserMonitorRun],
) -> str:
    """Assess overall confidence level of evidence for strategy decisions."""
    factors = []
    valid_count = len(eligibility.get("citation_eligible_run_ids", []))
    if valid_count >= 12:
        factors.append("sufficient sample size")
    elif valid_count >= 6:
        factors.append("moderate sample size")
    else:
        factors.append("small sample size")

    join_rate = source_relations.get("join_rate") or 0
    if join_rate >= 0.5:
        factors.append("good candidate-citation alignment")
    elif join_rate >= 0.2:
        factors.append("partial candidate-citation alignment")
    else:
        factors.append("low candidate-citation alignment — many citation-only sources")

    cit_only = source_relations.get("citation_only_count", 0)
    if cit_only >= 30:
        factors.append("significant citation-only sources with unknown provenance")
    elif cit_only >= 10:
        factors.append("notable citation-only sources")

    if "small sample size" in factors and "low candidate-citation alignment" in factors:
        return "LOW"
    elif "significant citation-only sources" in factors:
        return "MEDIUM"
    return "MEDIUM"


# ---------------------------------------------------------------------------
# P0-5 corrected: Evidence-driven deterministic strategy generation
# Methodology: Citation Intelligence (primary) + Retrieval Intelligence (auxiliary)
# ---------------------------------------------------------------------------

class EvidenceDrivenStrategyProvider:
    """Deterministic, evidence-driven strategy provider.

    Methodology:
    - Citation Intelligence = primary evidence (what does AI actually cite?)
    - Retrieval Intelligence = auxiliary diagnosis (is target page visible?)
    - Source Relation = DIAGNOSTIC_METADATA (not strategy evidence)
    - Separates FACT / INFERENCE / ACTION strictly
    - Separates evidence_fit from execution_feasibility
    - target_platform = UNRESOLVED is a valid state
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.provider = settings.strategy_llm_provider
        self.model = settings.strategy_llm_model
        self.prompt_version = "strategy_prompt.v2"

    def generate_from_context(
        self,
        project: Project,
        package: OptimizationEvidencePackage,
        context: dict,
    ) -> dict:
        """Generate strategy options from EvidenceActionContext."""
        facts = context.get("evidence_facts", [])
        facts_by_id = {f["fact_id"]: f for f in facts}
        confidence = context.get("evidence_confidence", "MEDIUM")
        decision_capability = context.get("decision_capability", "CONTENT_DIRECTION_ONLY")
        content_patterns = context.get("content_type_patterns", {})
        platform_patterns = context.get("platform_patterns", {})
        answer_strategy_signals = context.get("answer_strategy_signals", {})
        brand_presence = context.get("brand_presence", {})
        brand_gaps = context.get("brand_channel_gaps", [])
        source_relations = context.get("source_relation_landscape", {})
        target_urls = context.get("target_page_urls", [])
        citation_content_available = context.get("citation_content_analysis_available", False)

        # --- Build INFERENCE layer ---
        inferences = self._derive_inferences(context, facts_by_id)

        # --- Missing evidence ---
        missing_evidence = list(context.get("missing_evidence", []))

        # --- Generate options ---
        options = []

        # --- Option A: Evidence-driven platform + content direction ---
        high_citation_types = content_patterns.get("high_citation_types", [])
        low_citation_types = content_patterns.get("low_citation_types", [])
        answer_signal_content_types = answer_strategy_signals.get("recommended_content_types", [])
        strategy_content_types = answer_signal_content_types or high_citation_types

        if strategy_content_types:
            fact_refs = self._find_fact_refs(facts, content_types=strategy_content_types)
            recommended_content_types = _strategy_recommended_content_types(
                strategy_content_types,
                preserve_order=bool(answer_signal_content_types),
            )
            platform_recommendations = _strategy_platform_recommendations(platform_patterns, recommended_content_types, answer_strategy_signals)
            platform_direction = _strategy_platform_direction(platform_recommendations)
            observed_content_types_str = "、".join(_strategy_content_type_label(item) for item in strategy_content_types[:5])
            content_signal_source = "答案推荐/选择理由上下文" if answer_signal_content_types else "引用资料"
            recommended_content_types_str = "、".join(_strategy_content_type_label(item) for item in recommended_content_types)

            # --- Dynamic evidence from context, never hardcoded ---
            run_count = len(context.get('source_run_ids', []))
            brand_rate = brand_presence.get('brand_mention_rate', 0)
            target_url = target_urls[0] if target_urls else None

            # Brand mention — read structured FACT directly, never reverse-engineer
            brand_mention_fact = next((f for f in facts if f.get('metric_name') == 'brand_mention_rate'), None)
            brand_mention_n = brand_mention_fact.get('numerator') if brand_mention_fact else None
            brand_mention_d = brand_mention_fact.get('denominator') if brand_mention_fact else None
            brand_mention_str = f"{brand_mention_n}/{brand_mention_d}" if (brand_mention_n is not None and brand_mention_d is not None) else str(brand_rate)

            # TOOL_PAGE data — only if present in facts
            tool_page_fact = next((f for f in facts if f.get('content_type') == 'TOOL_PAGE'), None)
            has_tool_page = tool_page_fact is not None

            # Citation-only count from context
            cit_only = source_relations.get('citation_only_count', 0)
            total_cit = source_relations.get('total_citations', 0)
            run_count_str = str(run_count)

            # When retrieval metrics are unavailable, use answer-level brand
            # visibility instead of generating a strategy that validation must reject.
            retrieval_status = context.get("retrieval_landscape", {}).get("retrieval_metrics_status")
            retrieval_fact = next((f for f in facts if f.get('metric_name') == 'target_page_retrieval_rate'), None)
            if retrieval_status == "insufficient_retrieval_candidates" or not _retrieval_metric_is_usable(retrieval_fact):
                target_metric_name = "brand_mention_rate"
            else:
                target_metric_name = INTERVENTION_METRIC_MAP.get("OFFICIAL_NEW_PAGE", "target_page_retrieval_rate")
            target_metric_fact = next((f for f in facts if f.get('metric_name') == target_metric_name), None)
            if target_metric_fact:
                tn = target_metric_fact.get('numerator')
                td = target_metric_fact.get('denominator')
                baseline = f"{tn}/{td}" if (tn is not None and td is not None) else f"?/{run_count_str}"
            else:
                baseline = f"?/{run_count_str}"

            # Prompt topic
            prompt_info = context.get('citation_landscape', {})

            # Build observed_problem dynamically
            parts = [f"品牌「{project.brand_name}」在 {run_count} 次采样中的品牌提及率为 {brand_mention_str}。"]
            if has_tool_page:
                tc = tool_page_fact.get('candidate_run_count', 0)
                tc2 = tool_page_fact.get('citation_run_count', 0)
                parts.append(f"工具页在 {tc}/{run_count} 次采样中进入了检索候选，但引用次数为 {tc2}。")
            if target_url:
                parts.append(f"当前目标页面为 {target_url}。")
            parts.append(f"{content_signal_source}中高频出现的内容形态包括：{observed_content_types_str}。")
            observed = "".join(parts)

            # Evidence summary
            summary_parts = [
                f"证据 #{package.id}：{run_count} 次采样。",
                f"品牌提及率：{brand_mention_str}。",
                f"{content_signal_source}内容形态：{observed_content_types_str}。",
            ]
            if has_tool_page:
                tc2 = tool_page_fact.get('citation_run_count', 0)
                summary_parts.append(f"工具页引用覆盖：{tc2}/{run_count}。")
            if total_cit > 0:
                summary_parts.append(f"引用来源：{total_cit} 条引用，其中 {cit_only} 条仅引用无候选。")
            evidence_summary_str = "".join(summary_parts)

            option_a = {
                "intervention_type": "UNRESOLVED",
                "target_platform": "UNRESOLVED",
                "target_asset": "NEW_INFORMATIONAL_CONTENT",
                "target_content_type": recommended_content_types[0] if recommended_content_types else "TUTORIAL",
                "target_url": target_url,
                "content_direction": f"{content_signal_source}显示，当前问题更需要{observed_content_types_str}；建议优先补齐{recommended_content_types_str}。",
                "answer_signal_priority_note": answer_strategy_signals.get("signal_priority_note", "未读取到答案推荐上下文，退回普通引用分布。"),
                "decision_space": answer_strategy_signals.get("decision_space"),
                "platform_direction": platform_direction,
                "platform_recommendations": platform_recommendations,
                "evidence_fit": "MEDIUM",
                "execution_feasibility": "UNASSESSED",
                "observed_problem": observed,
                "hypothesized_cause": (
                    "AI 在回答此类信息型意图的问题时，可能更倾向于选择教程、问答、规则解释等信息型内容，"
                    "而非纯工具/交易类页面。即使工具页能够进入检索候选，"
                    "也可能因为缺少 AI 组织答案所需的结构化解释信息而未被选中为引用来源。"
                ),
                "core_mechanism": (
                    "创建能够直接回应问题意图的信息型内容（教程/问答/规则解释），"
                    "使其具备清晰、可被引用的结构化信息。"
                    "核心机制：内容类型匹配 AI 引用偏好 → 更高的被引用概率。"
                ),
                "recommended_action": {
                    "content_direction": f"围绕「{context.get('prompt_text') or '当前问题'}」制作{recommended_content_types_str}，重点回答定义、适用场景、操作步骤、风险限制和常见失败原因。",
                    "platform_direction": platform_direction,
                    "asset_direction": "新建或改造一份可公开访问的中文内容资产。建议包含：概念定义、平台规则、操作步骤、常见失败原因、FAQ、案例截图或视频说明。",
                },
                "changed_features": [
                    {"feature": "DIRECT_ANSWER_BLOCK", "description": "新增直接回答定义、适用场景和平台限制", "location": "正文顶部"},
                    {"feature": "STEP_BY_STEP_GUIDE", "description": "补充可核验的操作步骤和配置流程", "location": "正文主体"},
                    {"feature": "RISK_AND_FAQ", "description": "补充跳转失败、审核限制、合规风险和常见问题", "location": "FAQ/排障模块"},
                ],
                "recommended_title": f"{context.get('prompt_text') or '当前问题'}怎么做？使用场景、操作步骤与常见问题",
                "recommended_outline": ["直接回答", "适用场景", "平台规则和限制", "操作步骤", "常见失败原因", "FAQ", "案例截图或视频说明"],
                "required_sections": ["定义与边界", "适用场景", "平台限制", "操作步骤", "失败排查", "FAQ"],
                "evidence_fact_ids": fact_refs,
                "inferences": self._select_inferences(inferences, ["content_type_pattern", "tool_page_gap"]),
                "target_metric": target_metric_name,
                "expected_secondary_metrics": ["brand_mention_rate", "brand_recommendation_rate"],
                "metric_availability": (
                    "当前检索候选不足，不能使用完整候选漏斗；本轮先用「品牌提及率」验证是否进入回答认知。"
                    if target_metric_name == "brand_mention_rate"
                    else "「目标页面检索进入率」仅适用于自有站点资产；外部平台内容暂以「品牌提及率」作为代理指标。"
                ),
                "baseline_value": baseline,
                "expected_direction": "increase",
                "priority": "HIGH",
                "evidence_support_level": "SOURCE_LEVEL_ONLY",
                "confidence": "MEDIUM",
                "blocking_evidence": [],
                "decision_capability": decision_capability,
                "validation_plan": {
                    "entry_observed_condition": "新信息型内容资产已发布并确认为可公开访问。",
                    "sustained_improvement_condition": "目标资产或品牌在独立复采中出现在检索候选或引用中。",
                    "minimum_sample_count": run_count,
                },
                "invalidating_result": f"复采后新信息资产未被检索或引用；品牌提及率无变化。",
                "evidence_summary": evidence_summary_str,
                "reason_for_not_choosing_alternatives": (
                    "平台推荐来自当前引用平台分布和内容形态信号；仍不直接物化为执行平台，原因：(1) 引用内容正文分析尚不可用，"
                    "无法确认什么内容结构驱动了引用；(2) 大多数域名的引用来源无法确认；"
                    "(3) 平台账号可新注册，但具体账号、发布规则、target_url 和发布时间仍需人工审核。"
                    "当前策略给出「优先在哪些平台发布什么内容」；正式执行仍需 effective_payload 确认。"
                )
            }
            options.append(option_a)

        # Determine decision status
        if options:
            decision_status = "OPTIONS_AVAILABLE"
        else:
            decision_status = "NEEDS_MORE_EVIDENCE"
            missing_evidence.append({
                "category": "NO_VIABLE_OPTIONS",
                "reason": "Current evidence does not support any intervention type with sufficient confidence.",
            })

        return {
            "decision_status": decision_status,
            "decision_capability": decision_capability,
            "strategy_options": options,
            "missing_evidence": missing_evidence,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "generated_at": datetime.utcnow(),
            "context_snapshot": {
                "evidence_confidence": confidence,
                "decision_capability": decision_capability,
                "citation_content_analysis_available": citation_content_available,
                "facts_count": len(facts),
                "inferences_count": len(inferences),
                "source_relation_join_rate": source_relations.get("join_rate"),
            },
        }

    def _derive_inferences(self, context: dict, facts_by_id: dict) -> list[dict]:
        """Derive structured INFERENCE objects with supporting_fact_ids, confidence, and limitations."""
        inferences = []
        facts = context.get("evidence_facts", [])

        # INF-001: Content type citation pattern
        high_citation_types = context.get("content_type_patterns", {}).get("high_citation_types", [])
        low_citation_types = context.get("content_type_patterns", {}).get("low_citation_types", [])
        if high_citation_types:
            fact_ids = [f["fact_id"] for f in facts if f.get("fact_type") == "CONTENT_TYPE_DISTRIBUTION"]
            observed_content_types_str = "、".join(_strategy_content_type_label(item) for item in high_citation_types[:5])
            run_count = len(context.get("source_run_ids", []))
            inferences.append({
                "inference_id": "INF-001",
                "inference_type": "content_type_citation_pattern",
                "statement": (
                    f"该问题的智能回答引用资料与{observed_content_types_str}等内容形态关联更强。"
                    f"工具页虽能进入检索候选，但几乎不被最终引用。"
                ),
                "confidence": "MEDIUM",
                "supporting_fact_ids": fact_ids[:8],
                "limitations": [
                    "内容类型分类基于规则（content_classifier.v1），非正文内容分析。",
                    f"仅 {run_count} 次采样、单个问题、单个模型（文心）。",
                ],
            })

        # INF-002: Tool page citation gap
        official_fit = context.get("official_site_fit", {})
        if official_fit.get("tool_page_fit_assessment", "").startswith("LOW"):
            inferences.append({
                "inference_id": "INF-002",
                "inference_type": "tool_page_citation_gap",
                "statement": (
                    "工具页在检索可见性方面表现良好，但几乎从未被 AI 选为引用来源。"
                    "这可能表明 AI 在组织信息型回答时，更倾向于选择解释型/教程型内容，而非纯工具/交易类页面。"
                ),
                "confidence": "MEDIUM",
                "supporting_fact_ids": [f["fact_id"] for f in facts if f.get("content_type") == "TOOL_PAGE"][:6],
                "limitations": [
                    "仅单个 Prompt、单个模型 —— 无法排除模型特有行为。",
                    "工具页正文内容未被分析 —— 仅有标题/域名/URL 级别证据。",
                ],
            })

        # INF-003: Brand visibility
        brand_presence = context.get("brand_presence", {})
        if brand_presence.get("brand_mention_rate", 0) == 0:
            run_count = len(context.get("source_run_ids", []))
            inferences.append({
                "inference_id": "INF-003",
                "inference_type": "brand_visibility_gap",
                "statement": (
                    f"品牌「{brand_presence.get('brand_name', '')}」在全部 {run_count} 次智能回答中均未被提及。"
                    f"引用来源中未出现任何品牌自有内容。该品牌当前不存在于 AI 对该 Prompt 意图的引用池中。"
                ),
                "confidence": "HIGH",
                "supporting_fact_ids": [f["fact_id"] for f in facts if f.get("metric_name") == "brand_mention_rate"][:3],
                "limitations": [
                    "仅 12 次采样、单个 Prompt、单个模型。",
                    "品牌缺失可能是该 Prompt 意图领域特有的；其他 Prompt 可能表现不同。",
                ],
            })

        # INF-004: Source relation diagnostic (NOT strategy evidence)
        src_relations = context.get("source_relation_landscape", {})
        if src_relations.get("join_rate", 1.0) < 0.2:
            inferences.append({
                "inference_id": "INF-004",
                "inference_type": "source_relation_diagnostic",
                "statement": (
                    f"引用与候选的 URL 匹配率极低（{src_relations.get('join_rate', 0):.1%}）。"
                    f"这是诊断性观察 —— 不直接用于平台或内容策略决策。"
                    f"它表明检索解析器可见的候选池与 AI 最终引用池在很大程度上是不同的集合。"
                ),
                "confidence": "HIGH",
                "supporting_fact_ids": [f["fact_id"] for f in facts if f.get("fact_type") == "SOURCE_RELATION"][:3],
                "limitations": [
                    "这是许多 AI 搜索平台的正常行为，不代表解析器存在 bug。",
                    "请勿将 join_rate 作为主要策略证据使用。",
                ],
            })

        return inferences

    def _find_fact_refs(self, facts: list[dict], content_types: list[str] | None = None, platforms: list[str] | None = None) -> list[str]:
        """Find fact_ids matching given content types or platforms."""
        refs = set()
        for f in facts:
            if content_types and f.get("content_type") in content_types:
                refs.add(f["fact_id"])
            if platforms and f.get("platform") in platforms:
                refs.add(f["fact_id"])
        return sorted(refs)

    def _select_inferences(self, inferences: list[dict], types: list[str]) -> list[dict]:
        """Select inferences matching given inference types."""
        return [inf for inf in inferences if inf.get("inference_type") in types]


# ---------------------------------------------------------------------------
# P0-5: Updated generate_strategy_candidates flow
# ---------------------------------------------------------------------------

def generate_strategy_candidates_v2(db: Session, project_id: int, payload) -> list[dict]:
    """V2: Evidence-driven strategy generation using EvidenceActionContext."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    package = db.get(OptimizationEvidencePackage, payload.evidence_package_id)
    if not package or package.project_id != project_id:
        raise HTTPException(status_code=404, detail="证据事实包不存在")

    # Build evidence context
    evidence = loads(package.package_payload_json, {})
    run_ids = loads(package.source_run_ids_json, [])
    runs = _runs_by_ids(db, run_ids, project_id)
    valid_runs = [run for run in runs if run.status in VALID_RUN_STATUSES]
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all()
    target_urls = loads(package.target_page_urls_json, [])

    context = _build_evidence_action_context(
        db, project, package, valid_runs, references, retrievals, target_urls
    )

    # Generate strategy options
    provider = EvidenceDrivenStrategyProvider()
    result = provider.generate_from_context(project, package, context)

    # Persist strategy candidates (only for OPTIONS_AVAILABLE)
    created = []
    if result["decision_status"] == "OPTIONS_AVAILABLE":
        target_url = payload.target_url or (target_urls[0] if target_urls else "")
        snapshot = _latest_success_snapshot(db, project_id, target_url, "PRE_RELEASE", payload.experiment_id)

        for option in result["strategy_options"][:payload.max_hypotheses]:
            # Run validators
            evidence_result = validate_strategy_evidence(package, snapshot, option)
            hypothesis_result = validate_strategy_hypothesis(option, evidence_result)

            review_status = (
                "PENDING_REVIEW"
                if evidence_result["status"] == "VALIDATED" and hypothesis_result["status"] == "VALIDATED"
                else "VALIDATION_FAILED"
            )

            candidate = OptimizationStrategyCandidate(
                project_id=project_id,
                experiment_id=None,  # V2: Strategies are NOT auto-bound to experiments
                evidence_package_id=package.id,
                target_url=option.get("target_url") or "",
                provider=result["provider"],
                model=result["model"],
                prompt_version=result["prompt_version"],
                prompt_text="",
                generated_at=result["generated_at"],
                generation_status="GENERATED",
                # P0-3: Formal identity columns
                intervention_type=option.get("intervention_type"),
                target_platform=option.get("target_platform"),
                target_asset=option.get("target_asset"),
                target_content_type=option.get("target_content_type"),
                expected_primary_metric=option.get("target_metric"),
                source_package_id=package.id,
                # JSON payloads for complex structured data
                original_llm_payload_json=dumps(option),
                structured_payload_json=dumps(option),
                human_edited_payload_json=dumps({}),
                # effective_payload = structured at birth (no human edits yet)
                effective_payload_json=dumps(option),
                effective_payload_version=EFFECTIVE_PAYLOAD_VERSION,
                effective_validation_status="VALIDATED" if review_status == "PENDING_REVIEW" else "VALIDATION_FAILED",
                evidence_validation_status=evidence_result["status"],
                evidence_validation_errors_json=dumps(evidence_result["errors"]),
                evidence_validation_warnings_json=dumps(evidence_result["warnings"]),
                evidence_validated_at=evidence_result["validated_at"],
                evidence_validator_version=EVIDENCE_VALIDATOR_VERSION,
                hypothesis_validation_status=hypothesis_result["status"],
                hypothesis_validation_errors_json=dumps(hypothesis_result["errors"]),
                hypothesis_validation_warnings_json=dumps(hypothesis_result["warnings"]),
                hypothesis_validated_at=hypothesis_result["validated_at"],
                hypothesis_validator_version=HYPOTHESIS_VALIDATOR_VERSION,
                review_status=review_status,
            )
            db.add(candidate)
            created.append(candidate)
        db.commit()
        for candidate in created:
            db.refresh(candidate)

    return {
        "decision_status": result["decision_status"],
        "decision_capability": result.get("decision_capability", "UNKNOWN"),
        "citation_content_analysis_available": result["context_snapshot"].get("citation_content_analysis_available", False),
        "strategy_options_count": len(result["strategy_options"]),
        "candidates": [strategy_candidate_to_read(c) for c in created],
        "missing_evidence": result["missing_evidence"],
        "context_summary": {
            "evidence_confidence": result["context_snapshot"]["evidence_confidence"],
            "decision_capability": result["context_snapshot"].get("decision_capability", "UNKNOWN"),
            "citation_content_analysis_available": result["context_snapshot"].get("citation_content_analysis_available", False),
            "facts_count": result["context_snapshot"]["facts_count"],
            "inferences_count": result["context_snapshot"]["inferences_count"],
            "source_relation_join_rate": result["context_snapshot"]["source_relation_join_rate"],
        },
    }


def _ownership_from_ref(project: Project, ref: ReferenceSource) -> str:
    return _ownership(
        project,
        [],
        ref.domain,
        ref.url or ref.canonical_url,
        bool(ref.is_official_domain),
        bool(ref.is_competitor_domain),
        host_from_url(project.website_url) if project.website_url else "",
    )

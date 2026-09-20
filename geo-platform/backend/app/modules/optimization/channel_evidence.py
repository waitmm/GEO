"""Read-only Channel Evidence Landscape for the frozen Step 7 run scope.

Observed channels and evidence roles are descriptive inputs only.  This module
must never resolve execution channels or mutate StrategyCandidate state.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    EvidenceAlignment,
    OptimizationEvidencePackage,
    OptimizationStrategyCandidate,
    Project,
    RecommendationEvent,
    ReferenceSource,
    RetrievalCandidate,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.evidence_lineage import eligible_evidence_alignments_for_v1
from app.modules.optimization.passage_retrieval import FORMAL_V1_1_INPUT_VERSION
from app.modules.optimization.service import _infer_platform_from_domain, source_platform_label
from app.modules.optimization.source_mapping import build_source_mapping_report
from app.modules.optimization.source_qualification import resolve_ownership
from app.services.serialization import loads
from app.services.url_identity import build_url_identity


class CitationRole(StrEnum):
    DECISION_CITATION = "DECISION_CITATION"
    ANSWER_SUPPORT_CITATION = "ANSWER_SUPPORT_CITATION"
    PERIPHERAL_CITATION = "PERIPHERAL_CITATION"
    RETRIEVAL_ONLY = "RETRIEVAL_ONLY"


class AggregationHealthState(StrEnum):
    HEALTHY = "HEALTHY"
    WARN = "WARN"
    INVALID = "INVALID"


_DECISION_BINDING_ROLES = {"DIRECT_REASON", "SUPPORTING_REASON"}
_CHANNEL_LABELS = {
    "BAIJIAHAO": "百家号",
    "BILIBILI": "B站",
    "CSDN": "CSDN",
    "DOUYIN": "抖音",
    "JIANSHU": "简书",
    "JUEJIN": "掘金",
    "SINA": "新浪",
    "SOHU": "搜狐",
    "TENCENT": "腾讯",
    "WECHAT": "微信",
    "XIAOHONGSHU": "小红书",
    "ZHIHU": "知乎",
}


def _active_package(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None,
) -> OptimizationEvidencePackage:
    query = db.query(OptimizationEvidencePackage).filter(
        OptimizationEvidencePackage.project_id == project_id,
        OptimizationEvidencePackage.prompt_id == prompt_id,
    )
    if evidence_package_id is not None:
        package = query.filter(OptimizationEvidencePackage.id == evidence_package_id).first()
    else:
        package = (
            query.filter(OptimizationEvidencePackage.status == "active")
            .order_by(OptimizationEvidencePackage.version.desc(), OptimizationEvidencePackage.id.desc())
            .first()
        )
    if package is None:
        raise ValueError("CURRENT_EVIDENCE_PACKAGE_NOT_FOUND")
    return package


def _record_identity(record: ReferenceSource | RetrievalCandidate) -> dict:
    raw_url = (record.url or record.canonical_url or "").strip()
    identity = build_url_identity(raw_url, record.canonical_url or raw_url)
    if not identity.valid and raw_url:
        identity = build_url_identity(raw_url)
    canonical = identity.canonical_url if identity.valid else raw_url
    identity_key = identity.canonical_url_hash if identity.valid else f"invalid:{record.id}"
    domain = (record.domain or "").strip().lower()
    if not domain and canonical:
        domain = urlparse(canonical if "://" in canonical else f"https://{canonical}").netloc.lower()
        domain = domain[4:] if domain.startswith("www.") else domain
    return {
        "canonical_url": canonical,
        "canonical_url_hash": identity.canonical_url_hash if identity.valid else "",
        "identity_key": identity_key,
        "domain": domain,
        "valid": identity.valid,
    }


def _observation_groups(records: list[ReferenceSource | RetrievalCandidate]) -> dict[tuple[int, str], dict]:
    groups: dict[tuple[int, str], dict] = {}
    for record in records:
        identity = _record_identity(record)
        key = (int(record.run_id), identity["identity_key"])
        entry = groups.setdefault(key, {
            "key": key,
            "run_id": int(record.run_id),
            "canonical_url": identity["canonical_url"],
            "canonical_url_hash": identity["canonical_url_hash"],
            "domain": identity["domain"],
            "record_ids": set(),
            "raw_urls": set(),
            "records": [],
        })
        entry["record_ids"].add(int(record.id))
        if record.url:
            entry["raw_urls"].add(record.url)
        entry["records"].append(record)
    return groups


def _safe_channel_key(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")
    return normalized or "UNKNOWN"


def _channel_identity(db: Session, project: Project, url: str, domain: str) -> dict:
    ownership = resolve_ownership(db, project, url, domain)
    source_role = ownership.get("source_role") or "UNKNOWN"
    owner = ownership.get("source_owner_entity") or "UNKNOWN"
    if source_role == "TARGET_FIRST_PARTY":
        return {
            "channel_key": "OFFICIAL_SITE",
            "channel_label": "官网",
            "source_role": source_role,
            "source_owner_entity": owner,
        }
    if source_role == "COMPETITOR_FIRST_PARTY":
        return {
            "channel_key": f"COMPETITOR_{_safe_channel_key(domain)}",
            "channel_label": owner,
            "source_role": source_role,
            "source_owner_entity": owner,
        }

    inferred = _infer_platform_from_domain(domain)
    platform = inferred.get("inferred_platform") or "UNKNOWN"
    if platform != "UNKNOWN":
        return {
            "channel_key": platform,
            "channel_label": _CHANNEL_LABELS.get(platform, source_platform_label(platform.lower())),
            "source_role": source_role,
            "source_owner_entity": owner,
        }
    if not domain or "." not in domain:
        return {
            "channel_key": "UNKNOWN",
            "channel_label": "未知来源",
            "source_role": source_role,
            "source_owner_entity": owner,
        }
    label = domain or "未知网页"
    return {
        "channel_key": f"WEB_{_safe_channel_key(domain)}" if domain else "UNKNOWN",
        "channel_label": label,
        "source_role": source_role,
        "source_owner_entity": owner,
    }


def _compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").casefold())


def _entity_bucket(
    project: Project,
    competitor_names: set[str],
    entity_text: str,
    *,
    source_role: str = "",
) -> str:
    key = _compact(entity_text)
    target_keys = {_compact(project.brand_name), *(_compact(item) for item in loads(project.brand_aliases_json, []))}
    target_keys.discard("")
    competitor_keys = {_compact(item) for item in competitor_names if _compact(item)}
    if key and key in target_keys:
        return "target_brand"
    if key and key in competitor_keys:
        return "competitor"
    if source_role == "TARGET_FIRST_PARTY":
        return "target_brand"
    if source_role == "COMPETITOR_FIRST_PARTY":
        return "competitor"
    return "unknown"


def _semantic_claim_key(claim: SourceClaim | None) -> str:
    if claim is None:
        return "missing-claim"
    parts = [
        claim.subject_entity,
        claim.subject_text,
        claim.predicate,
        claim.object_text,
        claim.normalized_claim,
        claim.polarity,
    ]
    return "|".join(_compact(str(part or "")) for part in parts)


def _decision_level(event: RecommendationEvent | None) -> str:
    if event is None:
        return "FACT_ONLY"
    speech_act = (event.speech_act or "").upper()
    strength = (event.recommendation_strength or "").upper()
    polarity = (event.polarity or "").upper()
    if speech_act == "RECOMMEND":
        return "RECOMMENDATION_REASON"
    if speech_act in {"INCLUDE_AS_OPTION", "COMPARE"} or strength in {"MODERATE", "STRONG"} or polarity == "POSITIVE":
        return "CANDIDATE_OR_EVALUATION"
    return "FACT_ONLY"


def _eligible_support_relations(
    db: Session,
    project_id: int,
    prompt_id: int,
    run_ids: set[int],
) -> tuple[list[dict], dict]:
    candidates = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project_id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.run_id.in_(run_ids),
        EvidenceAlignment.relation == "SUPPORTS",
        EvidenceAlignment.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
        EvidenceAlignment.machine_payload_json.like(f'%"formal_input_version": "{FORMAL_V1_1_INPUT_VERSION}"%'),
    ).all() if run_ids else []
    eligible, eligibility_by_id = eligible_evidence_alignments_for_v1(
        db,
        candidates,
        allowed_run_ids=run_ids,
        include_answer_binding_v1_1=True,
    )

    claim_ids = {int(item.source_claim_id) for item in eligible if item.source_claim_id}
    event_ids = {int(item.recommendation_event_id) for item in eligible if item.recommendation_event_id}
    payloads = {int(item.id): loads(item.machine_payload_json, {}) for item in eligible}
    binding_ids = {
        int(payload.get("decision_binding_id"))
        for payload in payloads.values()
        if payload.get("decision_binding_id")
    }
    unit_ids = {
        int(payload.get("answer_unit_id"))
        for payload in payloads.values()
        if payload.get("answer_unit_id")
    }
    claims = db.query(SourceClaim).filter(SourceClaim.id.in_(claim_ids)).all() if claim_ids else []
    events = db.query(RecommendationEvent).filter(RecommendationEvent.id.in_(event_ids)).all() if event_ids else []
    bindings = db.query(AnswerDecisionBinding).filter(AnswerDecisionBinding.id.in_(binding_ids)).all() if binding_ids else []
    units = db.query(AnswerUnit).filter(AnswerUnit.id.in_(unit_ids)).all() if unit_ids else []
    claim_by_id = {int(item.id): item for item in claims}
    event_by_id = {int(item.id): item for item in events}
    binding_by_id = {int(item.id): item for item in bindings}
    unit_by_id = {int(item.id): item for item in units}

    relations = []
    for alignment in eligible:
        payload = payloads[int(alignment.id)]
        eligibility = eligibility_by_id[int(alignment.id)]
        binding_id = int(payload.get("decision_binding_id") or 0)
        unit_id = int(payload.get("answer_unit_id") or 0)
        binding = binding_by_id.get(binding_id)
        event = event_by_id.get(int(alignment.recommendation_event_id or 0))
        claim = claim_by_id.get(int(alignment.source_claim_id or 0))
        unit = unit_by_id.get(unit_id)
        is_decision = (
            binding is not None
            and (binding.decision_role or "").upper() in _DECISION_BINDING_ROLES
            and _decision_level(event) in {"RECOMMENDATION_REASON", "CANDIDATE_OR_EVALUATION"}
        )
        role = CitationRole.DECISION_CITATION.value if is_decision else CitationRole.ANSWER_SUPPORT_CITATION.value
        reason_key = str(payload.get("semantic_reason_key") or "").strip()
        if not reason_key:
            reason_text = (unit.unit_text_normalized or unit.unit_text_original or "").strip() if unit else ""
            reason_key = f"{reason_text}|ENTITY_SPECIFIC|{event.entity_text if event else ''}"
        relations.append({
            "role": role,
            "role_basis": "ANSWER_DECISION_BINDING_ELIGIBLE_SUPPORTS" if is_decision else "ANSWER_UNIT_ELIGIBLE_SUPPORTS",
            "alignment_id": int(alignment.id),
            "reference_source_id": int(eligibility.reference_source_id or 0),
            "source_document_id": int(alignment.source_document_id or 0),
            "source_claim_id": int(alignment.source_claim_id or 0),
            "recommendation_event_id": int(alignment.recommendation_event_id or 0),
            "decision_binding_id": binding_id,
            "answer_unit_id": unit_id,
            "run_id": int(alignment.run_id or 0),
            "reason_key": reason_key,
            "reason_text": (unit.unit_text_normalized or unit.unit_text_original or "").strip() if unit else reason_key.split("|", 1)[0],
            "decision_role": binding.decision_role if binding else "",
            "entity_text": event.entity_text if event else (claim.subject_entity if claim else ""),
            "semantic_relation_key": f"{reason_key}::{_semantic_claim_key(claim)}",
        })
    audit = {
        "formal_support_candidates": len(candidates),
        "eligible_support_alignments": len(eligible),
        "ineligible_support_alignments": len(candidates) - len(eligible),
        "ineligibility_reasons": dict(sorted(_count_ineligibility_reasons(eligibility_by_id).items())),
    }
    return relations, audit


def _count_ineligibility_reasons(eligibility_by_id: dict) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for result in eligibility_by_id.values():
        if result.eligible_for_v1:
            continue
        for reason in result.ineligibility_reasons:
            counts[reason] += 1
    return counts


def _mapping_multiplicity(report: dict, docs_by_id: dict[int, SourceDocument]) -> dict:
    multi = []
    one = 0
    maximum = 0
    reference_document_ids: set[int] = set()
    reference_document_memberships = 0
    for outcome in report.get("outcomes", []):
        doc_ids = [int(item) for item in outcome.get("source_document_ids", [])]
        reference_document_ids.update(doc_ids)
        reference_document_memberships += len(doc_ids)
        maximum = max(maximum, len(doc_ids))
        if len(doc_ids) == 1:
            one += 1
        if len(doc_ids) <= 1:
            continue
        docs = [docs_by_id[item] for item in doc_ids if item in docs_by_id]
        content_hashes = {doc.clean_text_hash for doc in docs if doc.clean_text_hash}
        if len(content_hashes) > 1:
            reason = "SAME_URL_DISTINCT_CONTENT_SNAPSHOTS"
        elif len(content_hashes) == 1:
            reason = "SAME_URL_DUPLICATE_DOCUMENT_ROWS"
        else:
            reason = "SAME_URL_MULTIPLE_DOCUMENT_ROWS_WITHOUT_CONTENT_HASH"
        multi.append({
            "raw_url": outcome.get("raw_url") or "",
            "canonical_url": outcome.get("canonical_url") or "",
            "matched_source_document_ids": doc_ids,
            "mapping_outcome": outcome.get("outcome"),
            "mapping_reason": outcome.get("reason"),
            "multiplicity_reason": reason,
            "documents": [{
                "source_document_id": int(doc.id),
                "canonical_url_hash": doc.canonical_url_hash or "",
                "clean_text_hash": doc.clean_text_hash or "",
                "fetch_time": doc.fetch_time.isoformat() if doc.fetch_time else None,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            } for doc in docs],
        })
    total = int(report.get("total_unique_reference_urls") or 0)
    all_document_ids = {int(item) for item in report.get("source_document_ids", [])}
    retrieval_additional_document_ids = all_document_ids - reference_document_ids
    return {
        "unique_reference_urls": total,
        "urls_with_1_document": one,
        "urls_with_multiple_documents": len(multi),
        "urls_with_no_document": total - one - len(multi),
        "max_documents_per_url": maximum,
        "reference_document_memberships": reference_document_memberships,
        "unique_reference_mapped_documents": len(reference_document_ids),
        "retrieval_additional_mapped_documents": len(retrieval_additional_document_ids),
        "retrieval_additional_source_document_ids": sorted(retrieval_additional_document_ids),
        "aggregation_input_documents": len(all_document_ids),
        "aggregation_input_explanation": (
            f"{len(reference_document_ids)} unique documents mapped from references + "
            f"{len(retrieval_additional_document_ids)} additional retrieval-only documents = "
            f"{len(all_document_ids)} aggregation input documents. Mapping memberships are not evidence counts."
        ),
        "multi_mapped_urls": multi,
    }


def _empty_role_accumulator() -> dict:
    return {
        "observations": set(),
        "urls": set(),
        "runs": set(),
        "semantic_relations": set(),
        "source_document_ids": set(),
        "reference_source_ids": set(),
        "retrieval_candidate_ids": set(),
        "source_claim_ids": set(),
        "alignment_ids": set(),
        "decision_binding_ids": set(),
        "answer_unit_ids": set(),
        "recommendation_event_ids": set(),
        "role_bases": set(),
        "entities": {
            "target_brand": {"observations": set(), "urls": set()},
            "competitor": {"observations": set(), "urls": set()},
            "unknown": {"observations": set(), "urls": set()},
        },
    }


def _empty_channel(channel: dict) -> dict:
    return {
        **channel,
        "domains": set(),
        "roles": {role.value: _empty_role_accumulator() for role in CitationRole},
        "entities": {
            "target_brand": {"observations": set(), "urls": set()},
            "competitor": {"observations": set(), "urls": set()},
            "unknown": {"observations": set(), "urls": set()},
        },
    }


def _add_to_role(
    entry: dict,
    role: str,
    observation: dict,
    relations: list[dict],
    *,
    entity: str | None = None,
) -> None:
    target = entry["roles"][role]
    observation_key = f"{observation['run_id']}:{observation['canonical_url_hash'] or observation['key'][1]}"
    target["observations"].add(observation_key)
    if observation["canonical_url"]:
        target["urls"].add(observation["canonical_url"])
    target["runs"].add(int(observation["run_id"]))
    if entity in target["entities"]:
        target["entities"][entity]["observations"].add(observation_key)
        if observation["canonical_url"]:
            target["entities"][entity]["urls"].add(observation["canonical_url"])
    target["reference_source_ids"].update(int(item) for item in observation.get("reference_source_ids", []))
    target["retrieval_candidate_ids"].update(int(item) for item in observation.get("retrieval_candidate_ids", []))
    target["source_document_ids"].update(int(item) for item in observation.get("source_document_ids", []))
    for relation in relations:
        target["semantic_relations"].add(relation["semantic_relation_key"])
        target["source_document_ids"].add(relation["source_document_id"])
        target["source_claim_ids"].add(relation["source_claim_id"])
        target["alignment_ids"].add(relation["alignment_id"])
        target["decision_binding_ids"].add(relation["decision_binding_id"])
        target["answer_unit_ids"].add(relation["answer_unit_id"])
        target["recommendation_event_ids"].add(relation["recommendation_event_id"])
        target["role_bases"].add(relation["role_basis"])
    if not relations:
        target["role_bases"].add("OBSERVED_REFERENCE_WITHOUT_ELIGIBLE_SUPPORT" if role == CitationRole.PERIPHERAL_CITATION.value else "OBSERVED_RETRIEVAL_WITHOUT_SAME_RUN_CITATION")


def _finalize_role(payload: dict, run_denominator: int) -> dict:
    observed_runs = sorted(payload["runs"])
    return {
        "observation_count": len(payload["observations"]),
        "semantic_relation_count": len(payload["semantic_relations"]),
        "unique_url_count": len(payload["urls"]),
        "observed_run_count": len(observed_runs),
        "run_coverage_rate": (len(observed_runs) / run_denominator) if run_denominator else 0.0,
        "observed_run_ids": observed_runs,
        "role_basis": sorted(payload["role_bases"]),
        "role_source_ids": {
            "reference_source_ids": sorted(payload["reference_source_ids"]),
            "retrieval_candidate_ids": sorted(payload["retrieval_candidate_ids"]),
            "source_document_ids": sorted(item for item in payload["source_document_ids"] if item),
            "source_claim_ids": sorted(item for item in payload["source_claim_ids"] if item),
            "evidence_alignment_ids": sorted(item for item in payload["alignment_ids"] if item),
            "decision_binding_ids": sorted(item for item in payload["decision_binding_ids"] if item),
            "answer_unit_ids": sorted(item for item in payload["answer_unit_ids"] if item),
            "recommendation_event_ids": sorted(item for item in payload["recommendation_event_ids"] if item),
        },
        "entity_counts": {
            key: {
                "observation_count": len(value["observations"]),
                "unique_url_count": len(value["urls"]),
            }
            for key, value in payload["entities"].items()
        },
    }


def _finalize_channel(entry: dict, run_denominator: int) -> dict:
    roles = {role.value: _finalize_role(entry["roles"][role.value], run_denominator) for role in CitationRole}
    return {
        "channel_key": entry["channel_key"],
        "channel_label": entry["channel_label"],
        "domains": sorted(entry["domains"]),
        "source_roles": sorted(entry.get("source_roles", set())),
        "source_owner_entities": sorted(entry.get("source_owner_entities", set())),
        "role_counts": roles,
        "entity_counts": {
            key: {
                "observation_count": len(value["observations"]),
                "unique_url_count": len(value["urls"]),
            }
            for key, value in entry["entities"].items()
        },
        "total_observation_count": sum(item["observation_count"] for item in roles.values()),
    }


def _reason_catalog(
    db: Session,
    project_id: int,
    prompt_id: int,
    run_ids: set[int],
    relations: list[dict],
) -> dict[str, dict]:
    relation_key_by_binding_id = {
        int(item["decision_binding_id"]): item["reason_key"]
        for item in relations
        if item.get("decision_binding_id")
    }
    relation_key_by_unit_id = {
        int(item["answer_unit_id"]): item["reason_key"]
        for item in relations
        if item.get("answer_unit_id")
    }
    shadow_run_ids = []
    for relation in relations:
        alignment = db.get(EvidenceAlignment, relation["alignment_id"])
        payload = loads(alignment.machine_payload_json, {}) if alignment else {}
        if payload.get("shadow_run_id"):
            shadow_run_ids.append(int(payload["shadow_run_id"]))
    if not shadow_run_ids:
        formal_alignments = db.query(EvidenceAlignment).filter(
            EvidenceAlignment.project_id == project_id,
            EvidenceAlignment.prompt_id == prompt_id,
            EvidenceAlignment.run_id.in_(run_ids),
            EvidenceAlignment.machine_payload_json.like(f'%"formal_input_version": "{FORMAL_V1_1_INPUT_VERSION}"%'),
        ).all() if run_ids else []
        for alignment in formal_alignments:
            shadow_id = loads(alignment.machine_payload_json, {}).get("shadow_run_id")
            if shadow_id:
                shadow_run_ids.append(int(shadow_id))
    current_shadow_id = max(shadow_run_ids) if shadow_run_ids else None
    query = db.query(AnswerDecisionBinding).filter(
        AnswerDecisionBinding.project_id == project_id,
        AnswerDecisionBinding.prompt_id == prompt_id,
        AnswerDecisionBinding.run_id.in_(run_ids),
        AnswerDecisionBinding.review_status != "HUMAN_REJECTED",
        AnswerDecisionBinding.decision_role.in_(_DECISION_BINDING_ROLES),
    )
    if current_shadow_id:
        query = query.filter(AnswerDecisionBinding.shadow_run_id == current_shadow_id)
    bindings = query.all() if run_ids else []
    unit_ids = {int(item.answer_unit_id) for item in bindings if item.answer_unit_id}
    event_ids = {int(item.recommendation_event_id) for item in bindings if item.recommendation_event_id}
    units = db.query(AnswerUnit).filter(AnswerUnit.id.in_(unit_ids)).all() if unit_ids else []
    events = db.query(RecommendationEvent).filter(RecommendationEvent.id.in_(event_ids)).all() if event_ids else []
    unit_by_id = {int(item.id): item for item in units}
    event_by_id = {int(item.id): item for item in events}
    catalog: dict[str, dict] = {}
    for binding in bindings:
        unit = unit_by_id.get(int(binding.answer_unit_id or 0))
        event = event_by_id.get(int(binding.recommendation_event_id or 0))
        reason_text = (unit.unit_text_normalized or unit.unit_text_original or "").strip() if unit else ""
        if not reason_text:
            continue
        key = (
            relation_key_by_binding_id.get(int(binding.id))
            or relation_key_by_unit_id.get(int(binding.answer_unit_id or 0))
            or f"{reason_text}|ENTITY_SPECIFIC|{event.entity_text if event else ''}"
        )
        row = catalog.setdefault(key, {
            "reason_key": key,
            "reason_text": reason_text,
            "entity_text": event.entity_text if event else "",
            "decision_roles": set(),
            "observed_run_ids": set(),
            "decision_binding_ids": set(),
            "answer_unit_ids": set(),
            "recommendation_event_ids": set(),
            "current_shadow_run_id": current_shadow_id,
        })
        row["decision_roles"].add(binding.decision_role)
        row["observed_run_ids"].add(int(binding.run_id))
        row["decision_binding_ids"].add(int(binding.id))
        row["answer_unit_ids"].add(int(binding.answer_unit_id))
        row["recommendation_event_ids"].add(int(binding.recommendation_event_id))
    for relation in relations:
        catalog.setdefault(relation["reason_key"], {
            "reason_key": relation["reason_key"],
            "reason_text": relation["reason_text"],
            "entity_text": relation["entity_text"],
            "decision_roles": set(),
            "observed_run_ids": set(),
            "decision_binding_ids": set(),
            "answer_unit_ids": set(),
            "recommendation_event_ids": set(),
            "current_shadow_run_id": current_shadow_id,
        })
    return catalog


def build_channel_evidence_landscape(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None = None,
    *,
    include_observations: bool = False,
) -> dict:
    """Build a deterministic read-only landscape for one current package."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("PROJECT_NOT_FOUND")
    package = _active_package(db, project_id, prompt_id, evidence_package_id)
    candidate_query = db.query(OptimizationStrategyCandidate).filter(
        OptimizationStrategyCandidate.project_id == project_id,
        OptimizationStrategyCandidate.evidence_package_id == package.id,
    )
    candidate_ids_before = [int(item.id) for item in candidate_query.order_by(OptimizationStrategyCandidate.id).all()]
    run_ids = {int(item) for item in loads(package.source_run_ids_json, []) if item}
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all() if run_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all() if run_ids else []
    mapping = build_source_mapping_report(db, references, retrievals)
    mapped_doc_ids = {int(item) for item in mapping["source_document_ids"]}
    docs = db.query(SourceDocument).filter(SourceDocument.id.in_(mapped_doc_ids)).all() if mapped_doc_ids else []
    docs_by_id = {int(item.id): item for item in docs}
    multiplicity = _mapping_multiplicity(mapping, docs_by_id)

    relations, relation_audit = _eligible_support_relations(db, project_id, prompt_id, run_ids)
    relations_by_ref: dict[int, list[dict]] = defaultdict(list)
    for relation in relations:
        if relation["reference_source_id"]:
            relations_by_ref[relation["reference_source_id"]].append(relation)

    mapping_by_raw_url = {
        str(outcome.get("raw_url") or outcome.get("canonical_url") or ""): outcome
        for outcome in mapping.get("outcomes", [])
    }
    competitors = {item.name for item in project.competitors}
    citation_groups = _observation_groups(references)
    retrieval_groups = _observation_groups(retrievals)
    channel_entries: dict[str, dict] = {}
    citation_audit = []

    for observation in citation_groups.values():
        observation_relations = [
            relation
            for reference_id in observation["record_ids"]
            for relation in relations_by_ref.get(reference_id, [])
        ]
        decision_relations = [item for item in observation_relations if item["role"] == CitationRole.DECISION_CITATION.value]
        support_relations = [item for item in observation_relations if item["role"] == CitationRole.ANSWER_SUPPORT_CITATION.value]
        if decision_relations:
            role = CitationRole.DECISION_CITATION.value
            selected_relations = decision_relations
        elif support_relations:
            role = CitationRole.ANSWER_SUPPORT_CITATION.value
            selected_relations = support_relations
        else:
            role = CitationRole.PERIPHERAL_CITATION.value
            selected_relations = []

        source_doc_ids = set()
        for raw_url in observation["raw_urls"] or {observation["canonical_url"]}:
            outcome = mapping_by_raw_url.get(raw_url)
            if outcome:
                source_doc_ids.update(int(item) for item in outcome.get("source_document_ids", []))
        channel = _channel_identity(db, project, observation["canonical_url"], observation["domain"])
        entry = channel_entries.setdefault(channel["channel_key"], _empty_channel(channel))
        entry.setdefault("source_roles", set()).add(channel["source_role"])
        entry.setdefault("source_owner_entities", set()).add(channel["source_owner_entity"])
        if observation["domain"]:
            entry["domains"].add(observation["domain"])
        role_observation = {
            **observation,
            "reference_source_ids": sorted(observation["record_ids"]),
            "retrieval_candidate_ids": [],
            "source_document_ids": sorted(source_doc_ids),
        }
        relation_entities = {
            _entity_bucket(project, competitors, item["entity_text"])
            for item in selected_relations
        }
        entity = next(iter(relation_entities)) if len(relation_entities) == 1 else _entity_bucket(
            project,
            competitors,
            channel["source_owner_entity"],
            source_role=channel["source_role"],
        )
        _add_to_role(entry, role, role_observation, selected_relations, entity=entity)
        obs_key = f"{observation['run_id']}:{observation['identity_key'] if 'identity_key' in observation else observation['key'][1]}"
        entry["entities"][entity]["observations"].add(obs_key)
        if observation["canonical_url"]:
            entry["entities"][entity]["urls"].add(observation["canonical_url"])
        citation_audit.append({
            "run_id": observation["run_id"],
            "canonical_url": observation["canonical_url"],
            "channel_key": channel["channel_key"],
            "role": role,
            "role_basis": sorted({item["role_basis"] for item in selected_relations}) or ["OBSERVED_REFERENCE_WITHOUT_ELIGIBLE_SUPPORT"],
            "role_source_ids": {
                "reference_source_ids": sorted(observation["record_ids"]),
                "source_document_ids": sorted(source_doc_ids),
                "source_claim_ids": sorted({item["source_claim_id"] for item in selected_relations}),
                "evidence_alignment_ids": sorted({item["alignment_id"] for item in selected_relations}),
                "decision_binding_ids": sorted({item["decision_binding_id"] for item in selected_relations}),
                "answer_unit_ids": sorted({item["answer_unit_id"] for item in selected_relations}),
                "recommendation_event_ids": sorted({item["recommendation_event_id"] for item in selected_relations}),
            },
            "entity_bucket": entity,
        })

    citation_keys = set(citation_groups)
    retrieval_only_audit = []
    for observation in retrieval_groups.values():
        if observation["key"] in citation_keys:
            continue
        channel = _channel_identity(db, project, observation["canonical_url"], observation["domain"])
        entry = channel_entries.setdefault(channel["channel_key"], _empty_channel(channel))
        entry.setdefault("source_roles", set()).add(channel["source_role"])
        entry.setdefault("source_owner_entities", set()).add(channel["source_owner_entity"])
        if observation["domain"]:
            entry["domains"].add(observation["domain"])
        role_observation = {
            **observation,
            "reference_source_ids": [],
            "retrieval_candidate_ids": sorted(observation["record_ids"]),
            "source_document_ids": [],
        }
        entity = _entity_bucket(
            project,
            competitors,
            channel["source_owner_entity"],
            source_role=channel["source_role"],
        )
        _add_to_role(
            entry,
            CitationRole.RETRIEVAL_ONLY.value,
            role_observation,
            [],
            entity=entity,
        )
        obs_key = f"{observation['run_id']}:{observation['key'][1]}"
        entry["entities"][entity]["observations"].add(obs_key)
        if observation["canonical_url"]:
            entry["entities"][entity]["urls"].add(observation["canonical_url"])
        retrieval_only_audit.append({
            "run_id": observation["run_id"],
            "canonical_url": observation["canonical_url"],
            "channel_key": channel["channel_key"],
            "role": CitationRole.RETRIEVAL_ONLY.value,
            "role_basis": ["OBSERVED_RETRIEVAL_WITHOUT_SAME_RUN_CITATION"],
            "role_source_ids": {"retrieval_candidate_ids": sorted(observation["record_ids"])},
            "entity_bucket": entity,
        })

    channels = [_finalize_channel(item, len(run_ids)) for item in channel_entries.values()]
    channels.sort(key=lambda item: (-item["total_observation_count"], item["channel_label"], item["channel_key"]))

    catalog = _reason_catalog(db, project_id, prompt_id, run_ids, relations)
    reason_breakdown = []
    for reason_key, reason in sorted(catalog.items(), key=lambda item: (item[1]["reason_text"], item[0])):
        reason_relations = [item for item in relations if item["reason_key"] == reason_key]
        by_channel: dict[str, dict] = {}
        for relation in reason_relations:
            ref = db.get(ReferenceSource, relation["reference_source_id"])
            if ref is None:
                continue
            identity = _record_identity(ref)
            channel = _channel_identity(db, project, identity["canonical_url"], identity["domain"])
            item = by_channel.setdefault(channel["channel_key"], {
                "channel_key": channel["channel_key"],
                "channel_label": channel["channel_label"],
                "roles": {
                    CitationRole.DECISION_CITATION.value: _empty_role_accumulator(),
                    CitationRole.ANSWER_SUPPORT_CITATION.value: _empty_role_accumulator(),
                },
            })
            obs = {
                "key": (int(ref.run_id), identity["identity_key"]),
                "run_id": int(ref.run_id),
                "canonical_url": identity["canonical_url"],
                "canonical_url_hash": identity["canonical_url_hash"],
                "reference_source_ids": [int(ref.id)],
                "retrieval_candidate_ids": [],
                "source_document_ids": [relation["source_document_id"]],
            }
            wrapper = {"roles": item["roles"]}
            _add_to_role(wrapper, relation["role"], obs, [relation])
        reason_breakdown.append({
            "reason_key": reason_key,
            "reason_text": reason["reason_text"],
            "entity_text": reason["entity_text"],
            "decision_roles": sorted(reason["decision_roles"]),
            "observed_run_ids": sorted(reason["observed_run_ids"]),
            "has_semantic_evidence": bool(reason_relations),
            "channels": [
                {
                    "channel_key": item["channel_key"],
                    "channel_label": item["channel_label"],
                    "role_counts": {
                        role: _finalize_role(payload, len(run_ids))
                        for role, payload in item["roles"].items()
                    },
                }
                for item in sorted(by_channel.values(), key=lambda value: value["channel_label"])
            ],
            "unattributed_roles": [CitationRole.PERIPHERAL_CITATION.value, CitationRole.RETRIEVAL_ONLY.value],
            "reason_source_ids": {
                "decision_binding_ids": sorted(reason["decision_binding_ids"]),
                "answer_unit_ids": sorted(reason["answer_unit_ids"]),
                "recommendation_event_ids": sorted(reason["recommendation_event_ids"]),
            },
            "current_shadow_run_id": reason["current_shadow_run_id"],
        })

    role_totals = {
        role.value: sum(channel["role_counts"][role.value]["observation_count"] for channel in channels)
        for role in CitationRole
    }
    citation_role_sum = sum(role_totals[role.value] for role in (
        CitationRole.DECISION_CITATION,
        CitationRole.ANSWER_SUPPORT_CITATION,
        CitationRole.PERIPHERAL_CITATION,
    ))
    citation_conservation = {
        "unique_citation_identities": len(citation_groups),
        "decision_plus_support_plus_peripheral": citation_role_sum,
        "valid": len(citation_groups) == citation_role_sum,
    }
    health_reasons = []
    if mapping["data_health_state"] == "INVALID":
        health_reasons.append("SOURCE_MAPPING_INVALID")
    if mapped_doc_ids and citation_groups and not channels:
        health_reasons.append("MAPPED_CITATIONS_PRESENT_BUT_AGGREGATION_EMPTY")
    if not citation_conservation["valid"]:
        health_reasons.append("CITATION_ROLE_CONSERVATION_FAILED")
    if health_reasons:
        health = AggregationHealthState.INVALID
    elif mapping["data_health_state"] == "WARN":
        health = AggregationHealthState.WARN
        health_reasons.append("SOURCE_MAPPING_WARN")
    else:
        health = AggregationHealthState.HEALTHY

    candidate_ids_after = [int(item.id) for item in candidate_query.order_by(OptimizationStrategyCandidate.id).all()]
    return {
        "schema_version": "channel_evidence_landscape.v1",
        "boundary": {
            "observed_channel_is_recommended_channel": False,
            "channel_resolution_performed": False,
            "strategy_candidate_mutated": False,
            "external_llm_calls": 0,
        },
        "project_id": project_id,
        "prompt_id": prompt_id,
        "evidence_package_id": int(package.id),
        "evidence_package_version": int(package.version or 0),
        "run_ids": sorted(run_ids),
        "global": {
            "run_count": len(run_ids),
            "raw_reference_rows": len(references),
            "unique_citation_identities": len(citation_groups),
            "unique_reference_urls": int(mapping["total_unique_reference_urls"]),
            "mapped_documents": int(mapping["aggregation_input_documents"]),
            "raw_retrieval_rows": len(retrievals),
            "unique_retrieval_identities": len(retrieval_groups),
            "retrieval_only_observations": role_totals[CitationRole.RETRIEVAL_ONLY.value],
            "semantic_evidence_relations": len({item["semantic_relation_key"] for item in relations}),
            "channel_count": len(channels),
        },
        "mapping_multiplicity": multiplicity,
        "mapping_health": {
            "state": mapping["data_health_state"],
            "reasons": mapping["data_health_reasons"],
            "coverage": mapping["mapping_coverage"],
            "conservation": mapping["conservation"],
        },
        "aggregation_health": {
            "state": health.value,
            "reasons": health_reasons,
        },
        "role_totals": role_totals,
        "citation_role_conservation": citation_conservation,
        "raw_row_explosion_audit": {
            "raw_reference_rows": len(references),
            "unique_citation_identities": len(citation_groups),
            "unique_reference_urls": int(mapping["total_unique_reference_urls"]),
            "semantic_evidence_relations": len({item["semantic_relation_key"] for item in relations}),
            "document_memberships": sum(
                len(item.get("source_document_ids", []))
                for item in mapping.get("outcomes", [])
            ),
            "unique_document_identities": len({
                (doc.canonical_url_hash or doc.canonical_url or doc.url, doc.clean_text_hash or f"document:{doc.id}")
                for doc in docs
            }),
        },
        "semantic_lineage_audit": relation_audit,
        "channels": channels,
        "decision_reason_breakdown": reason_breakdown,
        "observation_details_included": include_observations,
        "citation_role_observations": (
            sorted(citation_audit, key=lambda item: (item["run_id"], item["canonical_url"]))
            if include_observations else []
        ),
        "retrieval_only_role_observations": (
            sorted(retrieval_only_audit, key=lambda item: (item["run_id"], item["canonical_url"]))
            if include_observations else []
        ),
        "read_only_audit": {
            "strategy_candidate_ids_before": candidate_ids_before,
            "strategy_candidate_ids_after": candidate_ids_after,
            "mutated": candidate_ids_before != candidate_ids_after,
        },
    }

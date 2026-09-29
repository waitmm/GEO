"""Human Gold comparison for the bounded Model B Critic Shadow results."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    SinglePromptQualificationCriticExecution,
    SinglePromptQualificationCriticGoldReview,
    SinglePromptQualificationCriticResult,
)
from app.services.serialization import dumps, loads


CRITIC_GOLD_CONTRACT_VERSION = "single_prompt_v2.qualification_critic_gold.b1.v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise HTTPException(status_code=409, detail={"code": code, "detail": detail})


def _result_row(
    db: Session,
    *,
    critic_id: str,
    result_version: str,
) -> SinglePromptQualificationCriticResult:
    row = db.query(SinglePromptQualificationCriticResult).filter_by(
        critic_id=critic_id,
        result_version=result_version,
    ).one_or_none()
    _require(row is not None, "CRITIC_GOLD_RESULT_MISSING", "精确 Critic ResultVersion 不存在")
    return row


def _machine_identity(output: dict[str, Any], candidate_type: str) -> dict[str, str]:
    if candidate_type == "CITATION_RELATION":
        evidence_result = (
            ((output.get("single_model_baseline") or {}).get("evidence_scope") or {}).get("result") or {}
        )
        return {
            "result_version": str(evidence_result.get("result_version") or ""),
            "result_hash": str(evidence_result.get("result_hash") or ""),
        }
    identity = output.get("input_identity") or {}
    return {
        "result_version": str(identity.get("diagnosis_result_version") or ""),
        "result_hash": str(identity.get("diagnosis_result_hash") or ""),
    }


def _gold_candidate(
    *,
    analysis_id: str,
    critic_result: SinglePromptQualificationCriticResult,
    output: dict[str, Any],
    signal: dict[str, Any],
    cohort: str,
) -> dict[str, Any]:
    machine = _machine_identity(output, str(signal.get("candidate_type") or ""))
    identity = {
        "analysis_id": analysis_id,
        "machine_result_version": machine["result_version"],
        "machine_result_hash": machine["result_hash"],
        "critic_result_version": critic_result.result_version,
        "critic_result_hash": critic_result.output_hash,
        "object_id": str(signal.get("object_id") or ""),
        "input_hash": str(signal.get("input_hash") or ""),
    }
    issue_types = list(signal.get("issue_types") or [])
    return {
        **identity,
        "gold_identity": _hash(identity),
        "cohort": cohort,
        "candidate_type": signal.get("candidate_type"),
        "task_id": signal.get("task_id"),
        "model_a_judgment": signal.get("model_a_baseline") or {},
        "rule_signals": signal.get("rule_signals") or {},
        "qwen_signal": {
            "critic_verdict": signal.get("critic_verdict"),
            "primary_issue": signal.get("primary_issue") or (issue_types[0] if issue_types else "NONE"),
            "issue_types": issue_types,
            "counterexample": signal.get("counterexample"),
            "rationale": signal.get("rationale"),
        },
        "review_context": signal.get("critic_input") or {},
    }


def build_critic_gold_review_set(
    db: Session,
    *,
    analysis_id: str,
    phase_a_critic_id: str,
    phase_a_result_version: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    execution = db.query(SinglePromptQualificationCriticExecution).filter_by(
        critic_id=phase_a_critic_id,
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    ).one_or_none()
    _require(execution is not None, "CRITIC_GOLD_PHASE_A_EXECUTION_MISSING", "Phase A Execution 不存在")
    phase_a_result = _result_row(
        db,
        critic_id=phase_a_critic_id,
        result_version=phase_a_result_version,
    )
    phase_a_output = loads(phase_a_result.output_json, {})
    candidates = [
        _gold_candidate(
            analysis_id=analysis_id,
            critic_result=phase_a_result,
            output=phase_a_output,
            signal=signal,
            cohort="PHASE_A_ORIGINAL",
        )
        for signal in phase_a_output.get("signals") or []
        if signal.get("processing_status") == "DONE"
    ]

    supplemental_versions: list[str] = []
    supplemental_rows = (
        db.query(SinglePromptQualificationCriticResult)
        .join(
            SinglePromptQualificationCriticExecution,
            SinglePromptQualificationCriticExecution.critic_id
            == SinglePromptQualificationCriticResult.critic_id,
        )
        .filter(SinglePromptQualificationCriticExecution.analysis_id == analysis_id)
        .order_by(SinglePromptQualificationCriticResult.id.asc())
        .all()
    )
    for row in supplemental_rows:
        output = loads(row.output_json, {})
        identity = output.get("input_identity") or {}
        if output.get("phase") != "SHADOW_PHASE_A_CONTRACT_RECOVERY":
            continue
        if identity.get("parent_critic_id") != phase_a_critic_id:
            continue
        if identity.get("parent_result_version") != phase_a_result_version:
            continue
        admitted = [signal for signal in output.get("signals") or [] if signal.get("processing_status") == "DONE"]
        if not admitted:
            continue
        supplemental_versions.append(row.result_version)
        candidates.extend(
            _gold_candidate(
                analysis_id=analysis_id,
                critic_result=row,
                output=output,
                signal=signal,
                cohort="SUPPLEMENTAL",
            )
            for signal in admitted
        )

    candidates = sorted(candidates, key=lambda item: (item["cohort"], item["candidate_type"], item["object_id"]))
    object_ids = [item["object_id"] for item in candidates]
    _require(len(object_ids) == len(set(object_ids)), "CRITIC_GOLD_DUPLICATE_OBJECT", "Gold 候选包含重复对象，必须显式消歧")
    _require(bool(candidates), "CRITIC_GOLD_EMPTY_SET", "没有可进入 Human Gold 的合法 Critic Signal")
    reviewable_identity = {
        "contract_version": CRITIC_GOLD_CONTRACT_VERSION,
        "analysis_id": analysis_id,
        "phase_a_critic_id": phase_a_critic_id,
        "phase_a_result_version": phase_a_result.result_version,
        "phase_a_result_hash": phase_a_result.output_hash,
        "supplemental_result_versions": supplemental_versions,
        "candidates": [
            {
                "object_id": item["object_id"],
                "gold_identity": item["gold_identity"],
                "machine_result_version": item["machine_result_version"],
                "critic_result_version": item["critic_result_version"],
                "input_hash": item["input_hash"],
            }
            for item in candidates
        ],
    }
    reviewable_set_hash = _hash(reviewable_identity)
    reviews = (
        db.query(SinglePromptQualificationCriticGoldReview)
        .filter_by(
            phase_a_result_version=phase_a_result_version,
            reviewable_set_hash=reviewable_set_hash,
        )
        .order_by(SinglePromptQualificationCriticGoldReview.version_number.asc())
        .all()
    )
    return {
        "phase": "SHADOW_PHASE_B1_INCREMENTAL_VALUE_HUMAN_GOLD",
        "contract_version": CRITIC_GOLD_CONTRACT_VERSION,
        "analysis_id": analysis_id,
        "phase_a_critic_id": phase_a_critic_id,
        "phase_a_result_version": phase_a_result.result_version,
        "phase_a_result_hash": phase_a_result.output_hash,
        "supplemental_result_versions": supplemental_versions,
        "reviewable_set_hash": reviewable_set_hash,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "reviews": [
            {
                "review_id": row.review_id,
                "version_number": row.version_number,
                "parent_review_id": row.parent_review_id,
                "reviewer": row.reviewer,
                "note": row.note,
                "decisions": loads(row.decisions_json, []),
                "metrics": loads(row.metrics_json, {}),
                "created_at": row.created_at.isoformat(),
            }
            for row in reviews
        ],
        "allowed_actions": ["COMPLETE_HUMAN_GOLD"] if not reviews else ["REVISE_HUMAN_GOLD"],
        "boundary": {
            "external_llm_calls": 0,
            "formal_qualification_effect": "NONE",
            "formal_strategy_effect": "NONE",
            "production_critic_enabled": False,
            "overall_qwen_accuracy_claim_allowed": False,
        },
    }


def _derive_decision(candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    qwen = candidate["qwen_signal"]
    verdict = qwen.get("critic_verdict")
    challenge_validity = decision["gold_qwen_challenge_valid"]
    if verdict == "DISAGREE" and challenge_validity == "YES":
        challenge_classification = "TRUE_POSITIVE"
    elif verdict == "DISAGREE" and challenge_validity == "NO":
        challenge_classification = "FALSE_CHALLENGE"
    else:
        challenge_classification = "NEUTRAL"

    if verdict != "DISAGREE":
        qualification_effect = "NO_CHANGE"
    elif challenge_validity == "YES" and not decision["gold_model_a_correct"]:
        qualification_effect = "IMPROVES" if decision["should_change_qualification"] else "NO_CHANGE"
    elif challenge_validity == "NO" and decision["gold_model_a_correct"]:
        qualification_effect = "DEGRADES"
    else:
        qualification_effect = "UNCERTAIN"
    return {
        **decision,
        "challenge_classification": challenge_classification,
        "simulated_qualification_effect": qualification_effect,
    }


def _metrics(candidates: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    by_object = {item["object_id"]: item for item in candidates}
    classifications = Counter(item["challenge_classification"] for item in decisions)
    effects = Counter(item["simulated_qualification_effect"] for item in decisions)
    by_issue: dict[str, Counter] = defaultdict(Counter)
    for decision in decisions:
        candidate = by_object[decision["object_id"]]
        issue = str((candidate.get("qwen_signal") or {}).get("primary_issue") or "NONE")
        by_issue[issue][decision["challenge_classification"]] += 1
    correct_fixes = [
        item["object_id"]
        for item in decisions
        if item["simulated_qualification_effect"] == "IMPROVES"
    ]
    erroneous_downgrades = [
        item["object_id"]
        for item in decisions
        if item["simulated_qualification_effect"] == "DEGRADES"
    ]
    supplemental = [item for item in decisions if by_object[item["object_id"]]["cohort"] == "SUPPLEMENTAL"]
    strategy = [item for item in decisions if by_object[item["object_id"]]["candidate_type"] == "STRATEGY_DIRECTION"]
    qwen_issue_counts = Counter(
        str((by_object[item["object_id"]].get("qwen_signal") or {}).get("primary_issue") or "NONE")
        for item in decisions
    )
    human_issue_counts = Counter(str(item["gold_issue_type"]) for item in decisions)

    def issue_summary(issue: str) -> dict[str, Any]:
        rows = [
            item for item in decisions
            if str((by_object[item["object_id"]].get("qwen_signal") or {}).get("primary_issue") or "NONE") == issue
        ]
        return {
            "object_count": len(rows),
            "true_challenge_count": sum(item["challenge_classification"] == "TRUE_POSITIVE" for item in rows),
            "false_challenge_count": sum(item["challenge_classification"] == "FALSE_CHALLENGE" for item in rows),
            "neutral_count": sum(item["challenge_classification"] == "NEUTRAL" for item in rows),
            "object_ids": [item["object_id"] for item in rows],
        }

    strategy_scope_confusion_ids = [
        item["object_id"]
        for item in strategy
        if item["gold_qwen_challenge_valid"] == "NO"
        and item["gold_effective_relation_or_strategy_judgment"] in {
            "STRATEGY_DIRECTION_VALID",
            "PUBLIC_CLAIM_ONLY_BLOCKED",
        }
    ]
    supplemental_confirmed = [
        item["object_id"] for item in supplemental if item["gold_qwen_challenge_valid"] == "YES"
    ]
    supplemental_rejected = [
        item["object_id"] for item in supplemental if item["gold_qwen_challenge_valid"] == "NO"
    ]
    return {
        "gold_object_count": len(decisions),
        "qwen_true_challenges": classifications["TRUE_POSITIVE"],
        "qwen_false_challenges": classifications["FALSE_CHALLENGE"],
        "qwen_neutral_or_insufficient": classifications["NEUTRAL"],
        "simulated_qualification_effect": dict(sorted(effects.items())),
        "by_issue_type": {
            issue: dict(sorted(counts.items())) for issue, counts in sorted(by_issue.items())
        },
        "qwen_issue_type_distribution": dict(sorted(qwen_issue_counts.items())),
        "human_issue_type_distribution": dict(sorted(human_issue_counts.items())),
        "correctly_fixed_object_ids": correct_fixes,
        "erroneously_downgraded_object_ids": erroneous_downgrades,
        "brand_subject_extrapolation": [
            item for item in decisions if item["gold_issue_type"] == "SUBJECT_MISMATCH"
        ],
        "support_strength_challenges": [
            item for item in decisions if item["gold_issue_type"] == "OVERSTATED_SUPPORT"
        ],
        "strategy_role_check": strategy,
        "supplemental_check": supplemental,
        "core_questions": {
            "brand_subject_extrapolation": issue_summary("SUBJECT_MISMATCH"),
            "support_strength_challenge": issue_summary("OVERSTATED_SUPPORT"),
            "strategy_direction_vs_public_claim_confusion_object_ids": strategy_scope_confusion_ids,
            "supplemental_overstated_support_confirmed_object_ids": supplemental_confirmed,
            "supplemental_overstated_support_rejected_object_ids": supplemental_rejected,
            "qualification_if_qwen_adopted": {
                "correctly_fixed_object_ids": correct_fixes,
                "erroneously_downgraded_object_ids": erroneous_downgrades,
            },
        },
        "overall_accuracy": "NOT_COMPUTED_BY_CONTRACT",
        "production_decision": "NOT_AUTHORIZED_FROM_B1",
    }


def complete_critic_gold_review(
    db: Session,
    *,
    analysis_id: str,
    phase_a_critic_id: str,
    phase_a_result_version: str,
    project_id: int,
    prompt_id: int,
    expected_phase_a_result_hash: str,
    expected_reviewable_set_hash: str,
    expected_prior_review_id: str | None,
    decisions: list[dict[str, Any]],
    reviewer: str,
    note: str,
) -> dict[str, Any]:
    review_set = build_critic_gold_review_set(
        db,
        analysis_id=analysis_id,
        phase_a_critic_id=phase_a_critic_id,
        phase_a_result_version=phase_a_result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )
    _require(review_set["phase_a_result_hash"] == expected_phase_a_result_hash, "CRITIC_GOLD_PHASE_A_STALE", "Phase A Result hash 已变化")
    _require(review_set["reviewable_set_hash"] == expected_reviewable_set_hash, "CRITIC_GOLD_SET_STALE", "Human Gold 候选集合已变化")
    prior = review_set["reviews"][-1] if review_set["reviews"] else None
    _require((prior or {}).get("review_id") == expected_prior_review_id, "CRITIC_GOLD_PRIOR_REVIEW_STALE", "Human Gold 前置版本不一致")
    candidates = {item["object_id"]: item for item in review_set["candidates"]}
    submitted = {item["object_id"]: item for item in decisions}
    _require(len(submitted) == len(decisions), "CRITIC_GOLD_DUPLICATE_DECISION", "Human Gold 对象不得重复")
    _require(set(submitted) == set(candidates), "CRITIC_GOLD_SET_INCOMPLETE", "必须处理全部且仅处理冻结的 Human Gold 对象")

    normalized: list[dict[str, Any]] = []
    for object_id in sorted(candidates):
        candidate = candidates[object_id]
        decision = dict(submitted[object_id])
        _require(decision["gold_identity"] == candidate["gold_identity"], "CRITIC_GOLD_IDENTITY_MISMATCH", f"{object_id} Gold identity 不一致")
        verdict = candidate["qwen_signal"]["critic_verdict"]
        if verdict == "AGREE":
            _require(decision["gold_qwen_challenge_valid"] == "NOT_APPLICABLE", "CRITIC_GOLD_AGREE_HAS_CHALLENGE", "AGREE 对象没有可确认的质疑")
        if verdict == "DISAGREE":
            _require(decision["gold_qwen_challenge_valid"] in {"YES", "NO", "INSUFFICIENT_CONTEXT"}, "CRITIC_GOLD_DISAGREE_VALIDITY_REQUIRED", "DISAGREE 必须判断质疑是否成立")
        normalized.append(_derive_decision(candidate, decision))

    metrics = _metrics(review_set["candidates"], normalized)
    version_number = (prior or {}).get("version_number", 0) + 1
    row = SinglePromptQualificationCriticGoldReview(
        review_id=f"critic-gold-review-{uuid4()}",
        analysis_id=analysis_id,
        phase_a_critic_id=phase_a_critic_id,
        phase_a_result_version=phase_a_result_version,
        phase_a_result_hash=review_set["phase_a_result_hash"],
        supplemental_result_versions_json=dumps(review_set["supplemental_result_versions"]),
        reviewable_set_hash=review_set["reviewable_set_hash"],
        version_number=version_number,
        parent_review_id=(prior or {}).get("review_id"),
        candidate_set_json=dumps(review_set["candidates"]),
        decisions_json=dumps(normalized),
        metrics_json=dumps(metrics),
        reviewer=reviewer,
        note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return build_critic_gold_review_set(
        db,
        analysis_id=analysis_id,
        phase_a_critic_id=phase_a_critic_id,
        phase_a_result_version=phase_a_result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )

"""Server-owned validation and conservative SC-GRADED-DELIVERY-001 grading."""

from __future__ import annotations

from typing import Any

from .contracts import AgentArtifact, EvidenceKind


def validate_and_grade(
    artifact: AgentArtifact, scope: dict[str, Any], tool_observations: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    issues: list[dict[str, str]] = []
    run_index = {str(row["run_id"]): row for row in scope["runs"]}
    citation_ids = {
        f"run:{row['run_id']}:reference:{ref['reference_id']}"
        for row in scope["runs"] for ref in (row.get("references") or [])
    }
    source_index = {row["snapshot_id"]: row for row in scope["source_snapshots"]}
    truth_index = {str(row.get("truth_id", row.get("id"))): row for row in scope["product_truth"]["facts"]}
    observed_ids = {row.get("observation_id") for row in tool_observations}
    read_answers: dict[str, list[tuple[int, int]]] = {}
    read_passages: set[tuple[str, str]] = set()
    listed_citations = False
    truth_read = False
    for observation in tool_observations:
        data = observation.get("data") or {}
        if observation.get("tool_name") == "read_answer":
            read_answers.setdefault(str(data.get("run_id")), []).append((int(data.get("start", 0)), int(data.get("end", 0))))
        elif observation.get("tool_name") == "read_source" and data.get("passage"):
            read_passages.add((str(data.get("snapshot_id")), str(data["passage"].get("passage_id"))))
        elif observation.get("tool_name") == "list_citations":
            listed_citations = True
        elif observation.get("tool_name") == "read_product_truth":
            truth_read = True

    refs = [ref for assertion in [*artifact.observations, *artifact.diagnosis]
            for ref in assertion.evidence_refs]
    refs.extend(ref for action in artifact.actions for ref in action.evidence_refs)
    for ref in refs:
        if ref.kind == EvidenceKind.ANSWER_SPAN:
            row = run_index.get(str(ref.run_id))
            if not row or ref.end > len(str(row.get("answer_text") or "")):
                issues.append({"code": "ANSWER_SPAN_OUT_OF_SCOPE", "detail": str(ref.run_id)})
            elif not any(start <= ref.start and end >= ref.end for start, end in read_answers.get(str(ref.run_id), [])):
                issues.append({"code": "ANSWER_SPAN_NOT_READ", "detail": str(ref.run_id)})
        elif ref.kind == EvidenceKind.CITATION_OCCURRENCE:
            if ref.citation_occurrence_id not in citation_ids or not listed_citations:
                issues.append({"code": "CITATION_NOT_OBSERVED", "detail": str(ref.citation_occurrence_id)})
        elif ref.kind == EvidenceKind.SOURCE_PASSAGE:
            source = source_index.get(str(ref.snapshot_id))
            valid = bool(source and any(str(row.get("passage_id")) == str(ref.passage_id) for row in source["passages"]))
            if not valid or (str(ref.snapshot_id), str(ref.passage_id)) not in read_passages:
                issues.append({"code": "SOURCE_PASSAGE_NOT_READ", "detail": f"{ref.snapshot_id}:{ref.passage_id}"})
        elif ref.kind == EvidenceKind.TRUTH_FACT:
            truth = truth_index.get(str(ref.truth_fact_id))
            version = str((truth or {}).get("truth_correction_version", 0))
            if not truth or not truth_read or str(ref.truth_version_id) != version:
                issues.append({"code": "TRUTH_FACT_NOT_READ_OR_VERSION_MISMATCH", "detail": str(ref.truth_fact_id)})
        elif ref.kind == EvidenceKind.KNOWLEDGE_PASSAGE:
            issues.append({"code": "KNOWLEDGE_POINTER_UNAVAILABLE", "detail": str(ref.knowledge_passage_id)})
        elif ref.kind == EvidenceKind.TOOL_OBSERVATION and ref.observation_id not in observed_ids:
            issues.append({"code": "TOOL_OBSERVATION_UNKNOWN", "detail": str(ref.observation_id)})

    if any(len(row.body_markdown.strip()) < 120 for row in artifact.deliverables):
        issues.append({"code": "DELIVERABLE_TOO_SHORT", "detail": "完整稿件至少需要 120 个字符"})
    authoritative_refs = [ref for ref in refs if ref.kind in {EvidenceKind.SOURCE_PASSAGE, EvidenceKind.TRUTH_FACT}]
    evidence_capable = bool(scope["source_snapshots"] or scope["product_truth"]["facts"])
    grade = "L2_PARTIALLY_GROUNDED" if evidence_capable and authoritative_refs else "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
    if grade == "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS":
        if any(row.classification == "VERIFIED_FACT" for row in [*artifact.observations, *artifact.diagnosis]):
            issues.append({"code": "L3_VERIFIED_FACT_NOT_ALLOWED", "detail": "L3 不得生成未经核实的品牌事实"})
        if any(row.readiness == "READY" for row in artifact.actions):
            issues.append({"code": "L3_READY_NOT_ALLOWED", "detail": "L3 action 必须 VERIFY_FIRST 或 EXPERIMENTAL"})
    validation = {"contract_version": "geo.agent.validation.v1", "status": "PASS" if not issues else "FAIL",
                  "issues": issues, "checked_ref_count": len(refs), "server_validated": True}
    eligibility = {
        "evidence_grade": grade,
        "public_claim_eligibility": "VERIFY_FIRST" if grade == "L2_PARTIALLY_GROUNDED" else "NOT_CONSUMABLE",
        "publication_eligibility": "VERIFY_FIRST",
    }
    return validation, eligibility

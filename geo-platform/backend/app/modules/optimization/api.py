from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.optimization.schemas import (
    ActionReleasePayload,
    EvidencePackageCreate,
    EvidencePackageRead,
    ExperimentConclusionPayload,
    ExperimentRetestCreate,
    ExperimentRetestRead,
    ExperimentRunsPayload,
    IssueStatusPayload,
    OptimizationActionCreate,
    OptimizationActionRead,
    OptimizationActionUpdate,
    OptimizationEvidenceChainRead,
    OptimizationExperimentCreate,
    OptimizationExperimentRead,
    OptimizationHypothesisCreate,
    OptimizationHypothesisRead,
    OptimizationIssueCreate,
    OptimizationIssueRead,
    PageSnapshotCreate,
    PageSnapshotRead,
    ReleaseAuditRead,
    ReleaseConfirmationPayload,
    StrategyCandidateRead,
    StrategyCandidateReviewPayload,
    StrategyGenerationCreate,
    ExperimentPlanRead,
)
from app.modules.optimization.service import (
    action_to_read,
    analyze_experiment,
    attach_validation_runs,
    capture_page_snapshot,
    confirm_conclusion,
    confirm_experiment_release,
    confirm_issue,
    create_action,
    create_evidence_package,
    create_experiment,
    create_hypothesis,
    create_issue,
    evidence_chain,
    evidence_package_to_read,
    experiment_to_read,
    generate_candidate_issues,
    generate_strategy_candidates,
    generate_strategy_candidates_v2,
    get_evidence_package,
    issue_to_read,
    list_evidence_packages,
    list_hypotheses,
    list_issue_reads,
    list_page_snapshots,
    list_strategy_candidates,
    lock_baseline,
    page_snapshot_to_read,
    hypothesis_to_read,
    queue_retest_task,
    reject_issue,
    release_action,
    review_strategy_candidate,
    start_validation,
    strategy_to_experiment_plan,
    update_action,
)
from app.modules.optimization.ranking import run_citation_evidence_ranking_v0
from app.modules.optimization.recommendation import (
    create_decision_market_experiment_draft,
    get_recommendation_landscape,
    list_answer_semantic_facts,
    list_capability_claims,
    list_evidence_adoptions,
    list_gap_diagnoses,
    list_passage_support_summary,
    list_recommendation_entities,
    list_recommendation_claims,
    list_recommendation_reason_claims,
    list_recommendation_snapshots,
    list_selection_criteria,
    list_target_brand_capability_truths,
    review_answer_semantic_fact,
    review_capability_claim,
    review_evidence_adoption,
    review_gap_diagnosis,
    review_recommendation_claim,
    review_recommendation_entity,
    review_recommendation_reason_claim,
    review_selection_criterion,
    run_recommendation_analysis,
    upsert_target_brand_capability_truth,
)


router = APIRouter(prefix="/api/optimization", tags=["optimization"])


@router.get("/projects/{project_id}/issues", response_model=list[OptimizationIssueRead])
def list_issues(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return list_issue_reads(db, project_id)


@router.get("/projects/{project_id}/evidence-packages", response_model=list[EvidencePackageRead])
def list_project_evidence_packages(project_id: int, prompt_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return list_evidence_packages(db, project_id, prompt_id)


@router.post("/projects/{project_id}/evidence-packages", response_model=EvidencePackageRead)
def create_project_evidence_package(project_id: int, payload: EvidencePackageCreate, db: Session = Depends(get_db)) -> dict:
    return evidence_package_to_read(db, create_evidence_package(db, project_id, payload))


@router.get("/projects/{project_id}/strategy-candidates", response_model=list[StrategyCandidateRead])
def list_project_strategy_candidates(
    project_id: int,
    experiment_id: int | None = None,
    evidence_package_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_strategy_candidates(db, project_id, experiment_id, evidence_package_id)


@router.post("/projects/{project_id}/strategy-candidates/generate", response_model=list[StrategyCandidateRead])
def generate_project_strategy_candidates(project_id: int, payload: StrategyGenerationCreate, db: Session = Depends(get_db)) -> list[dict]:
    return generate_strategy_candidates(db, project_id, payload)


@router.post("/projects/{project_id}/strategy-candidates/generate-v2")
def generate_project_strategy_candidates_v2(project_id: int, payload: StrategyGenerationCreate, db: Session = Depends(get_db)):
    return generate_strategy_candidates_v2(db, project_id, payload)


@router.post("/strategy-candidates/{candidate_id}/review", response_model=StrategyCandidateRead)
def review_strategy_candidate_endpoint(candidate_id: int, payload: StrategyCandidateReviewPayload, db: Session = Depends(get_db)) -> dict:
    return review_strategy_candidate(db, candidate_id, payload)


@router.post("/strategy-candidates/{candidate_id}/experiment-plan", response_model=ExperimentPlanRead)
def strategy_to_experiment_plan_endpoint(candidate_id: int, db: Session = Depends(get_db)) -> dict:
    return strategy_to_experiment_plan(db, candidate_id)


@router.get("/evidence-packages/{package_id}", response_model=EvidencePackageRead)
def get_project_evidence_package(package_id: int, db: Session = Depends(get_db)) -> dict:
    return get_evidence_package(db, package_id)


@router.get("/projects/{project_id}/page-snapshots", response_model=list[PageSnapshotRead])
def list_project_page_snapshots(project_id: int, experiment_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return list_page_snapshots(db, project_id, experiment_id)


@router.post("/projects/{project_id}/page-snapshots", response_model=PageSnapshotRead)
def capture_project_page_snapshot(project_id: int, payload: PageSnapshotCreate, db: Session = Depends(get_db)) -> dict:
    return page_snapshot_to_read(capture_page_snapshot(db, project_id, payload))


@router.post("/projects/{project_id}/issues/generate-candidates", response_model=list[OptimizationIssueRead])
def generate_issues(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    issues = generate_candidate_issues(db, project_id)
    return [issue_to_read(issue) for issue in issues]


@router.post("/issues", response_model=OptimizationIssueRead)
def create_manual_issue(payload: OptimizationIssueCreate, db: Session = Depends(get_db)) -> dict:
    issue = create_issue(db, payload)
    row = issue_to_read(issue)
    row["run_ids"] = payload.run_ids
    return row


@router.get("/issues/{issue_id}", response_model=OptimizationIssueRead)
def get_issue(issue_id: int, db: Session = Depends(get_db)) -> dict:
    return evidence_chain(db, issue_id)["issue"]


@router.post("/issues/{issue_id}/confirm", response_model=OptimizationIssueRead)
def confirm_issue_endpoint(issue_id: int, db: Session = Depends(get_db)) -> dict:
    issue = confirm_issue(db, issue_id)
    return evidence_chain(db, issue.id)["issue"]


@router.post("/issues/{issue_id}/reject", response_model=OptimizationIssueRead)
def reject_issue_endpoint(issue_id: int, payload: IssueStatusPayload, db: Session = Depends(get_db)) -> dict:
    issue = reject_issue(db, issue_id, payload.note)
    return evidence_chain(db, issue.id)["issue"]


@router.post("/issues/{issue_id}/actions", response_model=OptimizationActionRead)
def create_action_endpoint(issue_id: int, payload: OptimizationActionCreate, db: Session = Depends(get_db)) -> dict:
    return action_to_read(create_action(db, issue_id, payload))


@router.patch("/actions/{action_id}", response_model=OptimizationActionRead)
def update_action_endpoint(action_id: int, payload: OptimizationActionUpdate, db: Session = Depends(get_db)) -> dict:
    return action_to_read(update_action(db, action_id, payload))


@router.post("/actions/{action_id}/release", response_model=OptimizationActionRead)
def release_action_endpoint(action_id: int, payload: ActionReleasePayload, db: Session = Depends(get_db)) -> dict:
    return action_to_read(release_action(db, action_id, payload))


@router.post("/actions/{action_id}/experiments", response_model=OptimizationExperimentRead)
def create_experiment_endpoint(action_id: int, payload: OptimizationExperimentCreate, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(create_experiment(db, action_id, payload))


@router.get("/experiments/{experiment_id}/hypotheses", response_model=list[OptimizationHypothesisRead])
def list_experiment_hypotheses(experiment_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return list_hypotheses(db, experiment_id)


@router.post("/experiments/{experiment_id}/hypotheses", response_model=OptimizationHypothesisRead)
def create_experiment_hypothesis(experiment_id: int, payload: OptimizationHypothesisCreate, db: Session = Depends(get_db)) -> dict:
    return hypothesis_to_read(create_hypothesis(db, experiment_id, payload))


@router.post("/experiments/{experiment_id}/lock-baseline", response_model=OptimizationExperimentRead)
def lock_baseline_endpoint(experiment_id: int, payload: ExperimentRunsPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(lock_baseline(db, experiment_id, payload.run_ids))


@router.post("/experiments/{experiment_id}/start-validation", response_model=OptimizationExperimentRead)
def start_validation_endpoint(experiment_id: int, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(start_validation(db, experiment_id))


@router.post("/experiments/{experiment_id}/release-confirmation", response_model=OptimizationExperimentRead)
def confirm_release_endpoint(experiment_id: int, payload: ReleaseConfirmationPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(confirm_experiment_release(db, experiment_id, payload))


@router.post("/experiments/{experiment_id}/queue-retest", response_model=ExperimentRetestRead)
def queue_retest_endpoint(experiment_id: int, payload: ExperimentRetestCreate, db: Session = Depends(get_db)) -> dict:
    return queue_retest_task(db, experiment_id, payload)


@router.post("/experiments/{experiment_id}/attach-validation-runs", response_model=OptimizationExperimentRead)
def attach_validation_runs_endpoint(experiment_id: int, payload: ExperimentRunsPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(attach_validation_runs(db, experiment_id, payload.run_ids))


@router.post("/experiments/{experiment_id}/analyze", response_model=OptimizationExperimentRead)
def analyze_experiment_endpoint(experiment_id: int, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(analyze_experiment(db, experiment_id))


@router.post("/experiments/{experiment_id}/confirm-conclusion", response_model=OptimizationExperimentRead)
def confirm_conclusion_endpoint(experiment_id: int, payload: ExperimentConclusionPayload, db: Session = Depends(get_db)) -> dict:
    return experiment_to_read(confirm_conclusion(db, experiment_id, payload))


@router.get("/issues/{issue_id}/evidence-chain", response_model=OptimizationEvidenceChainRead)
def evidence_chain_endpoint(issue_id: int, db: Session = Depends(get_db)) -> dict:
    return evidence_chain(db, issue_id)


@router.get("/evidence-packages/{package_id}/citation-ranking")
def citation_evidence_ranking_endpoint(package_id: int, db: Session = Depends(get_db)):
    return run_citation_evidence_ranking_v0(db, package_id)


# --- Recommendation Market Intelligence V1 ---

@router.post("/projects/{project_id}/recommendation-analysis")
def generate_recommendation_analysis(project_id: int, payload: dict, db: Session = Depends(get_db)):
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        raise HTTPException(status_code=400, detail="请提供问题编号")
    return run_recommendation_analysis(db, project_id, int(prompt_id), payload.get("run_ids"))


@router.get("/projects/{project_id}/recommendation-landscape")
def recommendation_landscape(project_id: int, prompt_id: int, snapshot_id: int | None = None, db: Session = Depends(get_db)):
    return get_recommendation_landscape(db, project_id, prompt_id, snapshot_id)


@router.get("/projects/{project_id}/recommendation-snapshots")
def recommendation_snapshots(project_id: int, prompt_id: int | None = None, limit: int = 30, db: Session = Depends(get_db)):
    return list_recommendation_snapshots(db, project_id, prompt_id, limit)


@router.get("/projects/{project_id}/decision-market/{prompt_id}/summary")
def decision_market_summary(project_id: int, prompt_id: int, snapshot_id: int | None = None, db: Session = Depends(get_db)):
    data = get_recommendation_landscape(db, project_id, prompt_id, snapshot_id)
    return {
        "snapshot_id": data["id"],
        "project_id": project_id,
        "prompt_id": prompt_id,
        "prompt_text": data.get("prompt_text", ""),
        "run_ids": data.get("run_ids", []),
        "run_count": data.get("run_count", 0),
        "decision_market": data.get("decision_market", {}),
    }


@router.get("/projects/{project_id}/decision-market/{prompt_id}/action-package")
def decision_market_action_package(project_id: int, prompt_id: int, snapshot_id: int | None = None, db: Session = Depends(get_db)):
    data = get_recommendation_landscape(db, project_id, prompt_id, snapshot_id)
    return {
        "snapshot_id": data["id"],
        "project_id": project_id,
        "prompt_id": prompt_id,
        "action_package": (data.get("decision_market") or {}).get("action_package", {}),
    }


@router.get("/recommendation-claims")
def recommendation_claims(snapshot_id: int, db: Session = Depends(get_db)):
    return list_recommendation_claims(db, snapshot_id)


@router.get("/recommendation-entities")
def recommendation_entities(snapshot_id: int, db: Session = Depends(get_db)):
    return list_recommendation_entities(db, snapshot_id)


@router.post("/recommendation-entities/{entity_id}/review")
def recommendation_entity_review(entity_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_recommendation_entity(db, entity_id, payload)


@router.post("/recommendation-claims/{claim_id}/review")
def recommendation_claim_review(claim_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_recommendation_claim(db, claim_id, payload)


@router.get("/recommendation-reasons")
def recommendation_reasons(snapshot_id: int, db: Session = Depends(get_db)):
    return list_recommendation_reason_claims(db, snapshot_id)


@router.post("/recommendation-reasons/{reason_id}/review")
def recommendation_reason_review(reason_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_recommendation_reason_claim(db, reason_id, payload)


@router.get("/decision-market/selection-criteria")
def decision_market_selection_criteria(snapshot_id: int, db: Session = Depends(get_db)):
    return list_selection_criteria(db, snapshot_id)


@router.get("/decision-market/answer-semantic-facts")
def decision_market_answer_semantic_facts(snapshot_id: int, db: Session = Depends(get_db)):
    return list_answer_semantic_facts(db, snapshot_id)


@router.get("/decision-market/passage-support")
def decision_market_passage_support(snapshot_id: int, db: Session = Depends(get_db)):
    return list_passage_support_summary(db, snapshot_id)


@router.post("/decision-market/answer-semantic-facts/{fact_id}/review")
def decision_market_answer_semantic_fact_review(fact_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_answer_semantic_fact(db, fact_id, payload)


@router.post("/decision-market/selection-criteria/{criterion_id}/review")
def decision_market_selection_criterion_review(criterion_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_selection_criterion(db, criterion_id, payload)


@router.get("/decision-market/capability-claims")
def decision_market_capability_claims(snapshot_id: int, db: Session = Depends(get_db)):
    return list_capability_claims(db, snapshot_id)


@router.post("/decision-market/capability-claims/{claim_id}/review")
def decision_market_capability_claim_review(claim_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_capability_claim(db, claim_id, payload)


@router.get("/projects/{project_id}/target-brand-capability-truths")
def target_brand_capability_truths(project_id: int, db: Session = Depends(get_db)):
    return list_target_brand_capability_truths(db, project_id)


@router.post("/projects/{project_id}/target-brand-capability-truths")
def target_brand_capability_truth_upsert(project_id: int, payload: dict, db: Session = Depends(get_db)):
    return upsert_target_brand_capability_truth(db, project_id, payload)


@router.get("/decision-market/evidence-adoptions")
def decision_market_evidence_adoptions(snapshot_id: int, db: Session = Depends(get_db)):
    return list_evidence_adoptions(db, snapshot_id)


@router.post("/decision-market/evidence-adoptions/{adoption_id}/review")
def decision_market_evidence_adoption_review(adoption_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_evidence_adoption(db, adoption_id, payload)


@router.get("/decision-market/gaps")
def decision_market_gaps(snapshot_id: int, db: Session = Depends(get_db)):
    return list_gap_diagnoses(db, snapshot_id)


@router.post("/decision-market/gaps/{gap_id}/review")
def decision_market_gap_review(gap_id: int, payload: dict, db: Session = Depends(get_db)):
    return review_gap_diagnosis(db, gap_id, payload)


@router.post("/decision-market/snapshots/{snapshot_id}/experiment-draft")
def decision_market_experiment_draft(snapshot_id: int, payload: dict | None = None, db: Session = Depends(get_db)):
    return create_decision_market_experiment_draft(db, snapshot_id, payload or {})


# --- Citation Passage Intelligence V0 ---

from app.modules.optimization.passage_service import (
    run_golden_case_pipeline,
    acquire_cited_sources,
    acquire_brand_asset,
    extract_answer_claims,
    segment_all_documents,
    align_claims_to_passages,
    generate_answer_need_map,
    analyze_brand_information_gap,
)
from app.models import AnswerClaim, PassageAlignment, ReferenceSource, RetrievalCandidate, SourceDocument
from app.services.serialization import dumps, loads
from datetime import datetime
import hashlib
import html as _html
import re
from urllib.parse import urlparse
from collections import defaultdict


def _parse_required_run_ids(run_ids: str) -> list[int]:
    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="请提供run_ids")
    return ids


def _source_document_query_for_runs(db: Session, run_ids: list[int]):
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    citation_urls = set()
    for ref in refs:
        raw = ref.url or ""
        canonical = ref.canonical_url or ""
        if raw:
            citation_urls.add(raw)
        if canonical:
            citation_urls.add(canonical)
    if not citation_urls:
        return []
    docs = db.query(SourceDocument).filter(
        SourceDocument.original_url.in_(citation_urls)
    ).order_by(SourceDocument.fetch_status, SourceDocument.id).all()
    if not docs:
        docs = db.query(SourceDocument).filter(
            SourceDocument.url.in_(citation_urls)
        ).order_by(SourceDocument.fetch_status, SourceDocument.id).all()
    return docs


def _build_golden_case_manual_todos(
    claims: list[AnswerClaim],
    docs: list[SourceDocument],
    alignments: list[PassageAlignment],
) -> list[dict]:
    todos: list[dict] = []
    if not claims:
        todos.append({
            "code": "NO_CLAIMS",
            "severity": "warning",
            "title": "当前还没有回答主张",
            "detail": "自动抽取未产出可审核主张，需要先确认采样回答是否为空，或人工筛选代表性采样后再继续。",
            "items": [],
        })
        return todos

    failed_docs = [doc for doc in docs if doc.fetch_status == "FETCH_FAILED"]
    empty_docs = [doc for doc in docs if doc.fetch_status in {"SUCCESS", "PARTIAL"} and not (doc.clean_text or "").strip()]
    if failed_docs or empty_docs:
        items = [
            {
                "url": doc.url or doc.original_url or "",
                "domain": doc.domain or "",
                "status": doc.fetch_status,
                "reason": doc.failure_reason or ("页面正文为空，建议人工补录正文或源码" if doc in empty_docs else ""),
            }
            for doc in (failed_docs + empty_docs)[:12]
        ]
        todos.append({
            "code": "DOCUMENTS_NEED_MANUAL_INPUT",
            "severity": "warning",
            "title": "部分引用页面无法自动形成可用正文",
            "detail": "这些链接需要人工补录正文或页面源码，否则后续正文对齐和证据判断会持续为空。",
            "items": items,
        })

    anchorless_claims = [claim for claim in claims if not loads(claim.citation_ids_json, []) and not claim.citation_anchor]
    if anchorless_claims:
        todos.append({
            "code": "CLAIMS_WITHOUT_CITATION_ANCHOR",
            "severity": "info",
            "title": "多数回答主张没有显式引用锚点",
            "detail": f"当前 {len(anchorless_claims)}/{len(claims)} 条主张没有 citation anchor。系统会尝试在全部引用正文里自动匹配，但准确率有限，建议优先人工审核代表性主张。",
            "items": [],
        })

    resolved_alignments = [alignment for alignment in alignments if alignment.alignment_level != "L5_UNRESOLVED"]
    if claims and not resolved_alignments:
        todos.append({
            "code": "NO_PASSAGE_ALIGNMENT",
            "severity": "warning",
            "title": "自动正文对齐没有命中有效结果",
            "detail": "这通常意味着回答措辞与引用正文没有直接文本重叠，或引用正文质量不足。请优先补录失败页面，再人工核对高频主张与代表性来源。",
            "items": [],
        })

    return todos


def _golden_case_prepare_response(
    db: Session,
    run_ids: list[int],
    acquisition_result: dict | None = None,
    claim_result: dict | None = None,
    alignment_result: dict | None = None,
) -> dict:
    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(run_ids)).order_by(AnswerClaim.run_id, AnswerClaim.claim_index).all()
    docs = _source_document_query_for_runs(db, run_ids)
    alignments = db.query(PassageAlignment).filter(PassageAlignment.run_id.in_(run_ids)).order_by(PassageAlignment.id).all()
    summary = golden_case_summary(run_ids=",".join(str(run_id) for run_id in run_ids), db=db)
    manual_todos = _build_golden_case_manual_todos(claims, docs, alignments)
    return {
        "run_ids": run_ids,
        "summary": summary,
        "automation": {
            "claims": claim_result or {"claims_extracted": len(claims)},
            "acquisition": acquisition_result or {"created": 0, "failed": 0},
            "alignment": alignment_result or {"claims_processed": len(claims), "alignments_created": len([row for row in alignments if row.alignment_level != "L5_UNRESOLVED"])},
        },
        "manual_todos": manual_todos,
    }


@router.post("/golden-case/run")
def golden_case_run(payload: dict, db: Session = Depends(get_db)):
    run_ids = payload.get("run_ids", [])
    if not run_ids:
        raise HTTPException(status_code=400, detail="请提供run_ids")
    brand_url = payload.get("brand_url", "")
    if not brand_url:
        raise HTTPException(status_code=400, detail="请提供brand_url")
    return run_golden_case_pipeline(db, run_ids, brand_url)


@router.post("/golden-case/prepare")
def golden_case_prepare(payload: dict, db: Session = Depends(get_db)):
    run_ids = payload.get("run_ids", [])
    if not run_ids:
        raise HTTPException(status_code=400, detail="请提供run_ids")
    skip_acquire = bool(payload.get("skip_acquire", False))

    existing_claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(run_ids)).count()
    claim_result = extract_answer_claims(db, run_ids) if existing_claims == 0 else {"claims_extracted": existing_claims, "status": "existing"}

    acquisition_result = {"created": 0, "failed": 0, "skipped": 0, "status": "skipped"} if skip_acquire else acquire_cited_sources(db, run_ids)
    segment_all_documents(db)
    alignment_result = align_claims_to_passages(db, run_ids)

    return _golden_case_prepare_response(
        db,
        run_ids,
        acquisition_result=acquisition_result,
        claim_result=claim_result,
        alignment_result=alignment_result,
    )


@router.get("/golden-case/claims")
def golden_case_claims(run_ids: str = "", db: Session = Depends(get_db)):
    ids = _parse_required_run_ids(run_ids)
    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(ids)).order_by(AnswerClaim.run_id, AnswerClaim.claim_index).all()
    return [{"id": c.id, "run_id": c.run_id, "claim_index": c.claim_index, "raw_text": c.raw_text,
             "claim_type": c.claim_type, "citation_anchor": c.citation_anchor,
             "citation_ids": loads(c.citation_ids_json, []),
             "answer_position": c.answer_position, "epistemic_status": c.epistemic_status,
             "provenance": c.provenance, "review_status": c.review_status,
             "reviewer": c.reviewer, "review_note": c.review_note} for c in claims]


@router.get("/golden-case/alignments")
def golden_case_alignments(run_ids: str = "", db: Session = Depends(get_db)):
    ids = _parse_required_run_ids(run_ids)
    als = db.query(PassageAlignment).filter(PassageAlignment.run_id.in_(ids)).order_by(PassageAlignment.id).all()
    result = []
    for a in als:
        claim = db.query(AnswerClaim).get(a.answer_claim_id) if a.answer_claim_id else None
        doc = db.query(SourceDocument).get(a.source_document_id) if a.source_document_id else None
        result.append({
            "id": a.id, "answer_claim_id": a.answer_claim_id, "run_id": a.run_id,
            "citation_id": a.citation_id, "source_document_id": a.source_document_id,
            "passage_index": a.passage_index, "alignment_level": a.alignment_level,
            "alignment_method": a.alignment_method, "score": a.score, "evidence": a.evidence,
            "claim_text": claim.raw_text if claim else "",
            "doc_title": doc.title if doc else "", "doc_url": doc.url if doc else "",
            "epistemic_status": a.epistemic_status, "provenance": a.provenance,
            "review_status": a.review_status,
        })
    return result


@router.get("/golden-case/documents")
def golden_case_documents(run_ids: str = "", db: Session = Depends(get_db)):
    if run_ids:
        ids = _parse_required_run_ids(run_ids)
        docs = _source_document_query_for_runs(db, ids)
    else:
        docs = db.query(SourceDocument).order_by(SourceDocument.fetch_status, SourceDocument.id).all()
    return [{"id": d.id, "url": d.url or d.original_url, "domain": d.domain, "source_type": d.source_type,
             "fetch_status": d.fetch_status, "title": d.title, "clean_text_len": len(d.clean_text or ""),
             "blocks_count": len(loads(d.content_blocks_json, [])),
             "failure_reason": d.failure_reason} for d in docs]


@router.get("/golden-case/need-map")
def golden_case_need_map(run_ids: str = "", db: Session = Depends(get_db)):
    ids = _parse_required_run_ids(run_ids)
    return generate_answer_need_map(db, ids)


@router.get("/golden-case/brand-gap")
def golden_case_brand_gap(run_ids: str = "", brand_url: str = "", db: Session = Depends(get_db)):
    ids = _parse_required_run_ids(run_ids)
    if not brand_url:
        raise HTTPException(status_code=400, detail="请提供brand_url")
    need_map = generate_answer_need_map(db, ids)
    return analyze_brand_information_gap(db, brand_url, need_map["answer_need_map"], ids)


@router.post("/golden-case/extract-claims")
def golden_case_extract_claims(payload: dict, db: Session = Depends(get_db)):
    run_ids = payload.get("run_ids", [])
    if not run_ids:
        raise HTTPException(status_code=400, detail="请提供run_ids")
    result = extract_answer_claims(db, run_ids)
    return result


@router.post("/golden-case/acquire")
def golden_case_acquire(payload: dict, db: Session = Depends(get_db)):
    run_ids = payload.get("run_ids", [])
    if not run_ids:
        raise HTTPException(status_code=400, detail="请提供run_ids")
    result = acquire_cited_sources(db, run_ids)
    segment_all_documents(db)
    return result


# --- Answer Intelligence: Atomic Claim Extraction ---

@router.post("/golden-case/extract-atomic-claims")
def extract_atomic_claims(payload: dict, db: Session = Depends(get_db)):
    from app.modules.optimization.claim_extraction import run_claim_extraction, list_atomic_claims
    run_ids = payload.get("run_ids", [])
    if not run_ids:
        raise HTTPException(status_code=400, detail="请提供run_ids")
    result = run_claim_extraction(db, run_ids)
    return result


@router.get("/golden-case/atomic-claims")
def get_atomic_claims(run_ids: str = "", db: Session = Depends(get_db)):
    from app.modules.optimization.claim_extraction import list_atomic_claims
    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()] if run_ids else None
    return list_atomic_claims(db, ids)


@router.post("/golden-case/atomic-claims/{claim_id}/review")
def review_atomic_claim_endpoint(claim_id: int, payload: dict, db: Session = Depends(get_db)):
    from app.modules.optimization.claim_extraction import review_atomic_claim
    try:
        return review_atomic_claim(db, claim_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/golden-case/extract-primary")
def golden_case_extract_primary(payload: dict, db: Session = Depends(get_db)):
    doc_ids = payload.get("doc_ids", [])
    if doc_ids:
        docs = db.query(SourceDocument).filter(SourceDocument.id.in_(doc_ids)).all()
    else:
        docs = db.query(SourceDocument).filter(
            SourceDocument.fetch_status.in_(["SUCCESS", "PARTIAL"]),
            SourceDocument.raw_html.isnot(None), SourceDocument.raw_html != "",
        ).all()
    from app.modules.optimization.primary_content import extract_from_html
    from app.modules.optimization.passage_service import segment_document
    results = []
    for doc in docs:
        r = extract_from_html(doc.raw_html or "", doc.url or "")
        old_len = len(doc.clean_text or "")
        if r["primary_content_length"] > 100 and r["extraction_status"] != "SUSPECT":
            doc.clean_text = r["primary_content"]
        doc.title = doc.title or _extract_title_from_html(doc.raw_html or "")
        results.append({"id": doc.id, "url": doc.url, "old_len": old_len,
                        "new_len": r["primary_content_length"], "status": r["extraction_status"],
                        "type": r["content_type"], "confidence": r["extraction_confidence"]})
    db.commit()
    return {"processed": len(results), "results": results}


def _extract_title_from_html(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip()) if m else ""


@router.post("/golden-case/refetch")
def golden_case_refetch(payload: dict, db: Session = Depends(get_db)):
    urls = payload.get("urls", [])
    if not urls:
        raise HTTPException(status_code=400, detail="请提供urls")
    from app.modules.optimization.passage_service import fetch_page_playwright
    results = fetch_page_playwright(urls)
    for r in results:
        existing = db.query(SourceDocument).filter(
            (SourceDocument.original_url == r["url"]) | (SourceDocument.url == r["url"])
        ).first()
        if existing:
            existing.clean_text = r["clean_text"][:200000]
            existing.raw_html = r.get("raw_html", "")[:500000]
            existing.title = r["title"] or existing.title
            existing.fetch_status = r["fetch_status"]
            existing.failure_reason = r.get("failure_reason", "")
        elif r["fetch_status"] == "SUCCESS" and len(r["clean_text"]) > 50:
            doc = SourceDocument(
                url=r.get("canonical_url", r["url"]), original_url=r["url"],
                domain=r["domain"], source_type="CITED",
                fetch_status=r["fetch_status"], title=r["title"],
                raw_html=r.get("raw_html", "")[:500000],
                clean_text=r["clean_text"][:200000],
                clean_text_hash="", fetch_time=r["fetch_time"],
            )
            db.add(doc)
    db.commit()
    return {"refetched": len(urls), "results": [{"url": r["url"], "status": r["fetch_status"]} for r in results]}


@router.get("/golden-case/summary")
def golden_case_summary(run_ids: str = "", db: Session = Depends(get_db)):
    ids = _parse_required_run_ids(run_ids) if run_ids else []
    docs = len(_source_document_query_for_runs(db, ids)) if ids else db.query(SourceDocument).count()
    claim_query = db.query(AnswerClaim)
    alignment_query = db.query(PassageAlignment)
    if ids:
        claim_query = claim_query.filter(AnswerClaim.run_id.in_(ids))
        alignment_query = alignment_query.filter(PassageAlignment.run_id.in_(ids))
    claims = claim_query.count()
    als = alignment_query.count()
    l1 = alignment_query.filter(PassageAlignment.alignment_level == "L1_EXACT_OVERLAP").count()
    l2 = alignment_query.filter(PassageAlignment.alignment_level == "L2_NEAR_DUPLICATE").count()
    reviewed = claim_query.filter(AnswerClaim.review_status != "PENDING").count()
    return {"source_documents": docs, "answer_claims": claims, "alignments": als,
            "l1_exact": l1, "l2_near_duplicate": l2,
            "claims_reviewed": reviewed,
            "eligibility": "CITATION_ONLY", "note": "Candidate-citation URL overlap ~3%"}


@router.post("/golden-case/claims/{claim_id}/review")
def review_claim(claim_id: int, payload: dict, db: Session = Depends(get_db)):
    claim = db.get(AnswerClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    claim.review_status = payload.get("review_status", "CONFIRMED")
    claim.human_labels_json = dumps(payload.get("human_labels", []))
    claim.claim_type = payload.get("claim_type", claim.claim_type)
    claim.reviewer = payload.get("reviewer", "human")
    claim.reviewed_at = datetime.utcnow()
    claim.review_note = payload.get("review_note", "")
    db.commit()
    return {"id": claim.id, "review_status": claim.review_status, "human_labels": loads(claim.human_labels_json, [])}


@router.get("/golden-case/need-map-validated")
def golden_case_need_map_validated(run_ids: str = "", db: Session = Depends(get_db)):
    ids = _parse_required_run_ids(run_ids)
    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(ids)).all()
    total = len(claims)
    reviewed = [c for c in claims if c.review_status != "PENDING"]
    confirmed = [c for c in claims if c.review_status == "CONFIRMED"]
    refined = [c for c in claims if c.review_status == "REFINED"]
    mislabeled = [c for c in claims if c.review_status == "MISLABELED"]
    ambiguous = [c for c in claims if c.review_status == "AMBIGUOUS"]

    # Build validated need counts from human labels
    rule_map = generate_answer_need_map(db, ids)
    human_needs = defaultdict(lambda: {"claim_count": 0, "run_ids": set()})
    for c in reviewed:
        labels = loads(c.human_labels_json, []) or [c.claim_type]
        for label in labels:
            if label:
                human_needs[label]["claim_count"] += 1
                human_needs[label]["run_ids"].add(c.run_id)

    validated = []
    for name, data in sorted(human_needs.items(), key=lambda x: -x[1]["claim_count"]):
        rule_data = next((r for r in rule_map["answer_need_map"] if r["need_name"] == name), None)
        validated.append({
            "need_name": name,
            "rule_count": rule_data["claim_count"] if rule_data else 0,
            "human_count": data["claim_count"],
            "run_coverage": f"{len(data['run_ids'])}/{len(set(ids))}",
        })

    return {
        "total_claims": total,
        "reviewed": len(reviewed),
        "confirmed": len(confirmed),
        "refined": len(refined),
        "mislabeled": len(mislabeled),
        "ambiguous": len(ambiguous),
        "validated_needs": validated,
    }


@router.post("/golden-case/documents/manual")
def add_manual_document(payload: dict, db: Session = Depends(get_db)):
    url = payload.get("url", "")
    html = payload.get("raw_html", "")
    text = payload.get("clean_text", "")
    title = payload.get("title", "")
    is_empty_page = bool(payload.get("is_empty_page"))

    # If HTML provided, extract clean text from it
    import re as _re
    if html and not is_empty_page:
        # Always extract from HTML as primary source
        s = _re.sub(r"<(script|style|noscript|iframe)[^>]*>.*?</\1>", " ", html, flags=_re.DOTALL | _re.IGNORECASE)
        s = _re.sub(r"<!--.*?-->", " ", s, flags=_re.DOTALL)
        s = _re.sub(r"<[^>]+>", "\n", s)
        s = _re.sub(r"&[a-z]+;|&#\d+;", " ", s)
        s = _re.sub(r"\n\s*\n", "\n\n", s)
        s = _re.sub(r"[ \t]{2,}", " ", s)
        html_text = s.strip()
        if not text or len(html_text) > len(text):
            text = html_text
        # Extract title
        if not title:
            tm = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.IGNORECASE | _re.DOTALL)
            if tm:
                title = _re.sub(r"<[^>]+>", "", tm.group(1)).strip()
    if is_empty_page:
        html = ""
        text = ""
        if not title:
            title = "页面已删除或无可用正文"
    if not title:
        title = payload.get("title", url)

    # Normalize URL for matching: extract path+query as the resource key
    from urllib.parse import urlparse as _up
    def _url_key(u: str) -> str:
        p = _up(u if "://" in u else "https://"+u)
        return (p.netloc.replace("www.","").lower() + p.path.rstrip("/") + ("?"+p.query if p.query else "")).lower()

    target_key = _url_key(url)
    # Find ALL documents sharing the same normalized URL key (http/https/www variants)
    all_docs = db.query(SourceDocument).filter(
        SourceDocument.fetch_status != "SUCCESS"
    ).all()
    updated = 0
    for d in all_docs:
        if (_url_key(d.url) == target_key or _url_key(d.original_url or d.url) == target_key):
            d.clean_text = text[:200000] if text else ""
            d.raw_html = html[:500000] if html else ""
            d.title = title or d.title
            d.fetch_status = "MANUAL_EMPTY" if is_empty_page else "SUCCESS"
            d.failure_reason = "页面已删除或无可用正文（人工标记）" if is_empty_page else ""
            d.clean_text_hash = hashlib.sha256(text.encode()).hexdigest()[:16] if text else ""
            d.fetch_time = datetime.utcnow()
            updated += 1
            if updated == 1:
                doc = d
    if updated == 0:
        doc = SourceDocument(
            url=url, original_url=url, domain=urlparse(url).netloc.lower() if url else "",
            source_type=payload.get("source_type", "CITED"),
            fetch_status="MANUAL_EMPTY" if is_empty_page else "SUCCESS", title=title,
            failure_reason="页面已删除或无可用正文（人工标记）" if is_empty_page else "",
            raw_html=html[:500000] if html else "",
            clean_text=text[:200000],
            clean_text_hash=hashlib.sha256(text.encode()).hexdigest()[:16] if text else "",
            fetch_time=datetime.utcnow(),
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
    # Segment
    from app.modules.optimization.passage_service import segment_document
    blocks = segment_document(doc)
    doc.content_blocks_json = dumps(blocks)
    db.commit()
    return {"id": doc.id, "url": doc.url, "blocks": len(blocks), "updated_count": updated, "status": "MANUAL_CAPTURE"}


@router.get("/golden-case/url-audit")
def golden_case_url_audit(run_ids: str = "", db: Session = Depends(get_db)):
    from app.modules.optimization.passage_service import _normalize_for_match, _normalize_url_for_fetch
    ids = _parse_required_run_ids(run_ids)
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(ids)).all()
    cands = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(ids)).all()

    # Deduplicate
    ref_urls = list(set((ref.canonical_url or ref.url) for ref in refs if (ref.canonical_url or ref.url)))
    cand_urls = list(set((c.canonical_url or c.url) for c in cands if (c.canonical_url or c.url)))

    # Raw overlap
    ref_set = set(ref_urls)
    cand_set = set(cand_urls)
    raw_overlap = ref_set & cand_set

    # Normalized overlap
    norm_ref = {_normalize_for_match(u) for u in ref_urls}
    norm_cand = {_normalize_for_match(u) for u in cand_urls}
    norm_overlap = norm_ref & norm_cand

    return {
        "raw": {"cited": len(ref_urls), "candidates": len(cand_urls), "overlap": len(raw_overlap), "overlap_rate": f"{len(raw_overlap)}/{len(ref_urls)}"},
        "normalized": {"cited": len(norm_ref), "candidates": len(norm_cand), "overlap": len(norm_overlap), "overlap_rate": f"{len(norm_overlap)}/{len(norm_ref)}"},
        "eligibility": "CITATION_ONLY",
        "note": "Even after normalization, candidate-citation URL pools remain largely disjoint. This is accepted as a platform characteristic, not a parser bug.",
    }


# --- 人工审核工作流 ---

@router.get("/workflow/{project_id}/{prompt_id}/status")
def workflow_status_endpoint(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from app.models import Project
    from app.modules.optimization.workflow import workflow_status
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return workflow_status(db, project, prompt_id)


@router.get("/workflow/{project_id}/{prompt_id}/review-queue")
def workflow_review_queue_endpoint(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from app.models import Project
    from app.modules.optimization.workflow import review_queue
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return review_queue(db, project, prompt_id)


@router.get("/workflow/{project_id}/{prompt_id}/competitor-candidates")
def competitor_candidates_endpoint(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from app.models import Project
    from app.modules.optimization.workflow import discover_competitor_candidates
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return discover_competitor_candidates(db, project, prompt_id)


@router.post("/workflow/{project_id}/competitor-candidates/confirm")
def competitor_confirm_endpoint(project_id: int, payload: dict, db: Session = Depends(get_db)):
    from app.models import Project
    from app.modules.optimization.workflow import confirm_competitor
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return confirm_competitor(db, project, payload.get("name", ""), payload.get("website_url", ""))


@router.post("/workflow/review/events/confirm-batch")
def batch_confirm_events_endpoint(payload: dict, db: Session = Depends(get_db)):
    from app.modules.optimization.workflow import batch_confirm_events
    return batch_confirm_events(db, payload.get("event_ids", []), payload.get("reviewer", "human"))


@router.post("/workflow/review/events/reject-batch")
def batch_reject_events_endpoint(payload: dict, db: Session = Depends(get_db)):
    from app.models import RecommendationEvent
    updated = 0
    for eid in payload.get("event_ids", []):
        e = db.get(RecommendationEvent, eid)
        if e:
            e.review_status = "HUMAN_REJECTED"
            e.reviewer = payload.get("reviewer", "human")
            updated += 1
    db.commit()
    return {"updated": updated}


@router.post("/workflow/review/alignments/{alignment_id}/confirm")
def confirm_alignment_endpoint(alignment_id: int, payload: dict, db: Session = Depends(get_db)):
    from app.modules.optimization.workflow import confirm_alignment
    return confirm_alignment(db, alignment_id, payload.get("relation", "SUPPORTS"), payload.get("reviewer", "human"))


@router.get("/workflow/{project_id}/default-prompt")
def workflow_default_prompt(project_id: int, db: Session = Depends(get_db)):
    """返回该项目机器分析进度最好的 Prompt（按语义事件数倒序），
    无分析数据时返回采集最新的 Prompt。"""
    from app.models import Project, RecommendationEvent, BrowserMonitorRun
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 有语义事件的 prompt，按事件数倒序（Python 侧排序，避免复杂 SQL）
    rows = db.query(RecommendationEvent.prompt_id).filter(
        RecommendationEvent.project_id == project_id,
    ).all()
    if rows:
        from collections import Counter
        counts = Counter(r[0] for r in rows)
        best_prompt = counts.most_common(1)[0][0]
        return {"prompt_id": best_prompt, "reason": "HAS_SEMANTIC_EVENTS"}
    # 否则取采集最新（runs 按 id 倒序第一个）
    run = db.query(BrowserMonitorRun).filter(
        BrowserMonitorRun.project_id == project_id,
    ).order_by(BrowserMonitorRun.id.desc()).first()
    return {"prompt_id": run.prompt_id if run else None, "reason": "LATEST_RUN" if run else "NO_DATA"}


@router.post("/workflow/{project_id}/{prompt_id}/continue")
def workflow_continue_analysis(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    """审核完成后继续分析：Gap 推导 + Action Candidate 生成。

    前置检查：事件与 SUPPORTS 对齐必须已全部人工审核。
    """
    from app.models import Project, RecommendationEvent, EvidenceAlignment
    from app.modules.optimization.gap_action import derive_gap, build_action_candidate
    from app.modules.optimization.workflow import workflow_status

    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    status = workflow_status(db, project, prompt_id)
    if not status["all_reviews_done"]:
        raise HTTPException(
            status_code=400,
            detail=f"审核尚未完成（{status['pending_review_steps']} 步待处理），不能继续分析",
        )

    run_ids = [
        r.id for r in db.query(__import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun).filter(
            __import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun.project_id == project_id,
            __import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun.prompt_id == prompt_id,
        ).all()
    ]
    gap = derive_gap(db, project, prompt_id, run_ids)
    action = build_action_candidate(db, project, prompt_id, run_ids, gap)
    return {"gap": gap, "action": action}


@router.post("/workflow/{project_id}/{prompt_id}/confirm-decision")
def workflow_confirm_decision(project_id: int, prompt_id: int, payload: dict, db: Session = Depends(get_db)):
    """确认/拒绝 Gap 或 Action 决策（step_key: gap / action）。"""
    import sqlite3
    step_key = payload.get("step_key")
    if step_key not in {"gap", "action"}:
        raise HTTPException(status_code=400, detail="step_key 仅支持 gap / action")
    decision = payload.get("decision_status", "CONFIRMED")
    conn = sqlite3.connect('geo_v0.db')
    conn.execute(
        """INSERT OR REPLACE INTO workflow_confirmations
           (project_id, prompt_id, step_key, decision_status, decision_note, reviewer, reviewed_at)
           VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (project_id, prompt_id, step_key, decision, payload.get("note", ""), payload.get("reviewer", "human")),
    )
    conn.commit()
    conn.close()
    return {"status": "OK", "step_key": step_key, "decision_status": decision}


@router.post("/workflow/{project_id}/{prompt_id}/select-channel")
def workflow_select_channel(project_id: int, prompt_id: int, payload: dict, db: Session = Depends(get_db)):
    """渠道选择 → 创建 Experiment 草案。"""
    from app.models import Project, Prompt
    from app.modules.optimization.content_brief import create_experiment_draft
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt:
        raise HTTPException(status_code=404, detail="Project/Prompt not found")
    run_ids = [r.id for r in db.query(__import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun).filter(
        __import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun.prompt_id == prompt_id,
    ).all()]
    return create_experiment_draft(db, project, prompt, run_ids, payload.get("channel", "OWNED_NEW_PAGE"), payload.get("target_url", ""))


@router.post("/workflow/{project_id}/{prompt_id}/generate-outline")
def workflow_generate_outline(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from app.models import Project
    from app.modules.optimization.content_brief import ContentBriefGenerator, _collect_evidence_context
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    context = _collect_evidence_context(db, project, prompt_id)
    generator = ContentBriefGenerator()
    try:
        return generator.generate_outline(context, db=db)
    except SemanticLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/workflow/{project_id}/{prompt_id}/generate-brief")
def workflow_generate_brief(project_id: int, prompt_id: int, payload: dict, db: Session = Depends(get_db)):
    from app.models import Project
    from app.modules.optimization.content_brief import ContentBriefGenerator, _collect_evidence_context
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    context = _collect_evidence_context(db, project, prompt_id)
    generator = ContentBriefGenerator()
    try:
        return generator.generate_brief(payload.get("outline", {}), context, db=db)
    except SemanticLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Intervention Plan → per-channel Experiment → Benchmark → Release/Retest/Outcome ---

@router.post("/workflow/{project_id}/{prompt_id}/plan")
def workflow_create_plan(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from app.models import Project, Prompt
    from app.modules.optimization.intervention import InterventionPlanService
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt:
        raise HTTPException(status_code=404, detail="Project/Prompt not found")
    run_ids = [r.id for r in db.query(__import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun).filter(
        __import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun.prompt_id == prompt_id,
    ).all()]
    return InterventionPlanService(db, project, prompt).get_or_create_plan(run_ids)


@router.get("/workflow/{project_id}/{prompt_id}/channels")
def workflow_channel_options(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from app.modules.optimization.intervention import CHANNEL_OPTIONS
    # 每渠道的 Evidence 观察数（SUPPORTS 文档按域名匹配）
    from app.models import Project, EvidenceAlignment, SourceDocument
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project_id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
    ).all()
    doc_ids = {a.source_document_id for a in supports}
    docs = db.query(SourceDocument).filter(SourceDocument.id.in_(doc_ids)).all() if doc_ids else []
    domain_map = {
        "ZHIHU": ["zhihu.com"], "BILIBILI": ["bilibili.com"], "BAIJIAHAO": ["baijiahao.baidu.com"],
        "OWNED_NEW_PAGE": ["aifabu.com"], "OWNED_UPDATE": ["aifabu.com"],
    }
    result = []
    for c in CHANNEL_OPTIONS:
        domains = domain_map.get(c["key"], [])
        count = sum(1 for d in docs if any(d.domain and (d.domain == dm or d.domain.endswith("." + dm)) for dm in domains))
        result.append({**c, "evidence_source_count": count})
    return result


@router.post("/workflow/{project_id}/{prompt_id}/experiments")
def workflow_create_experiment(project_id: int, prompt_id: int, payload: dict, db: Session = Depends(get_db)):
    """为一个渠道创建一个 Experiment（channel 单选在此调用）。"""
    from app.models import Project, Prompt
    from app.modules.optimization.intervention import InterventionPlanService
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt:
        raise HTTPException(status_code=404, detail="Project/Prompt not found")
    run_ids = [r.id for r in db.query(__import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun).filter(
        __import__('app.models', fromlist=['BrowserMonitorRun']).BrowserMonitorRun.prompt_id == prompt_id,
    ).all()]
    service = InterventionPlanService(db, project, prompt)
    plan = service.get_or_create_plan(run_ids)
    return service.create_per_channel_experiment(plan["plan_id"], payload.get("channel", "ZHIHU"), run_ids)


@router.get("/workflow/{project_id}/{prompt_id}/experiments")
def workflow_list_experiments(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    from app.models import OptimizationExperiment
    exps = db.query(OptimizationExperiment).filter(
        OptimizationExperiment.intervention_plan_id.isnot(None),
        OptimizationExperiment.target_prompt_scope_json.like(f'%{prompt_id}%'),
    ).order_by(OptimizationExperiment.id.desc()).all()
    result = []
    for e in exps:
        result.append({
            "id": e.id, "channel": e.channel, "experiment_mode": e.experiment_mode,
            "hypothesis": e.hypothesis_text or e.hypothesis,
            "status": e.status, "release_blocked": bool(e.release_blocked),
            "release_blocked_reason": e.release_blocked_reason,
            "target_asset_type": e.target_asset_type, "target_asset_url": e.target_asset_url,
            "release_url": e.release_url, "released_at": e.released_at,
        })
    return result


@router.get("/workflow/experiments/{experiment_id}/benchmark")
def workflow_benchmark_checklist(experiment_id: int, db: Session = Depends(get_db)):
    from app.models import OptimizationExperiment, Project
    from app.modules.optimization.intervention import generate_benchmark_checklist
    exp = db.get(OptimizationExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    project = db.get(Project, exp.project_id) if hasattr(exp, "project_id") else None
    if not project:
        # experiment 没有 project_id 字段（旧表），从 action 反查
        from app.models import OptimizationAction, OptimizationIssue
        action = db.get(OptimizationAction, exp.action_id)
        issue = db.get(OptimizationIssue, action.issue_id) if action else None
        project = db.get(Project, issue.project_id) if issue else None
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return generate_benchmark_checklist(db, project, 19, experiment_id)


@router.post("/workflow/experiments/{experiment_id}/release")
def workflow_release_experiment(experiment_id: int, payload: dict, db: Session = Depends(get_db)):
    """人工确认发布：填写 release_url 后进入 WAITING_FOR_RETEST。"""
    from app.models import OptimizationExperiment
    exp = db.get(OptimizationExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if exp.review_status if hasattr(exp, "review_status") else False:
        pass
    if exp.status not in {"draft", "APPROVED", "READY_FOR_RELEASE"}:
        raise HTTPException(status_code=400, detail=f"当前状态 {exp.status} 不允许发布")
    release_url = payload.get("release_url", "")
    if not release_url:
        raise HTTPException(status_code=400, detail="必须填写真实发布 URL")
    exp.release_url = release_url
    exp.release_notes = payload.get("release_notes", "")
    exp.released_at = datetime.utcnow()
    exp.status = "RELEASED"
    exp.release_blocked = False
    exp.release_blocked_reason = ""
    db.commit()
    return {"status": "RELEASED", "experiment_id": experiment_id}


@router.post("/workflow/experiments/{experiment_id}/retest")
def workflow_retest_experiment(experiment_id: int, payload: dict, db: Session = Depends(get_db)):
    """复测：挂载 post-release runs（人工采集后回填）。"""
    from app.models import OptimizationExperiment
    exp = db.get(OptimizationExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if exp.status != "RELEASED":
        raise HTTPException(status_code=400, detail=f"当前状态 {exp.status} 不允许复测（需先 RELEASED）")
    post_ids = payload.get("post_run_ids", [])
    if not post_ids:
        raise HTTPException(status_code=400, detail="必须提供 post-release run IDs")
    exp.post_run_ids_json = dumps([int(x) for x in post_ids])
    exp.status = "RETESTED"
    db.commit()
    return {"status": "RETESTED", "experiment_id": experiment_id}


@router.post("/workflow/experiments/{experiment_id}/outcome")
def workflow_outcome_experiment(experiment_id: int, payload: dict, db: Session = Depends(get_db)):
    """Outcome：基于 baseline vs post 的品牌提及对比（简单统计，不宣称因果）。"""
    from app.models import OptimizationExperiment, BrowserMonitorRun
    exp = db.get(OptimizationExperiment, experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if exp.status != "RETESTED":
        raise HTTPException(status_code=400, detail=f"当前状态 {exp.status} 不允许生成 Outcome（需先 RETESTED）")
    baseline_ids = loads(exp.baseline_run_ids_json, []) or list(range(173, 185))
    post_ids = loads(exp.post_run_ids_json, [])
    if not post_ids:
        raise HTTPException(status_code=400, detail="缺少 post runs")

    def brand_stats(ids):
        runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(ids)).all()
        n = len(runs)
        if not n:
            return {"total": 0, "mentioned": 0, "recommended": 0}
        return {
            "total": n,
            "mentioned": sum(1 for r in runs if r.brand_mentioned),
            "recommended": sum(1 for r in runs if int(r.brand_recommendation_level or 0) >= 2),
        }

    base = brand_stats(baseline_ids)
    post = brand_stats(post_ids)
    # 小样本：只给方向，不给显著性
    def direction(a, b):
        if b > a:
            return "OBSERVED_IMPROVEMENT"
        if b < a:
            return "OBSERVED_DECLINE"
        return "NO_OBSERVED_CHANGE"

    outcome = {
        "baseline": base,
        "post": post,
        "mention_direction": direction(base["mentioned"], post["mentioned"]),
        "recommendation_direction": direction(base["recommended"], post["recommended"]),
        "sample_note": "小样本观察值，不代表统计显著性；仅作 Pipeline Result，不宣称干预有效",
        "conclusion": payload.get("conclusion", "INCONCLUSIVE"),
    }
    exp.outcome_summary_json = dumps(outcome)
    exp.status = "OUTCOME_READY"
    db.commit()
    return outcome


@router.get("/workflow/{project_id}/{prompt_id}/decision-market")
def workflow_decision_market(project_id: int, prompt_id: int, db: Session = Depends(get_db)):
    """决策诊断主路径数据：实体 + 行为 + 理由 + SUPPORTS 证据（语义版）。"""
    from app.models import RecommendationEvent, EvidenceAlignment, SourceClaim
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project_id,
        RecommendationEvent.prompt_id == prompt_id,
    ).all()
    if not events:
        return {"entities": []}

    total_runs = len({e.run_id for e in events})
    from collections import defaultdict
    entities: dict[str, dict] = defaultdict(lambda: {
        "entity_text": "", "relationship": "UNKNOWN_ENTITY",
        "speech_act": "", "run_ids": set(), "reasons": [],
    })
    seen_reasons: set[str] = set()
    for e in events:
        row = entities[e.entity_text]
        row["entity_text"] = e.entity_text
        row["speech_act"] = e.speech_act or row["speech_act"]
        row["run_ids"].add(e.run_id)
        for r in loads(e.reasons_json, []):
            rtext = r.get("normalized_reason") or ""
            if rtext in seen_reasons:
                continue
            seen_reasons.add(rtext)
            row["reasons"].append({
                "normalized_reason": rtext,
                "reason_span": r.get("reason_span") or e.answer_span,
                "review_status": e.review_status,
                "supporting_claims": [],
            })

    # 目标品牌/竞品关系
    from app.models import Project, Competitor
    project = db.get(Project, project_id)
    known = {project.brand_name, *(c.name for c in db.query(Competitor).filter(Competitor.project_id == project_id).all())}
    for name, row in entities.items():
        if name == project.brand_name:
            row["relationship"] = "TARGET"
        elif name in known:
            row["relationship"] = "CONFIRMED_COMPETITOR"

    # SUPPORTS 证据关联到 reason（按 claim 主体近似匹配）
    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project_id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
    ).all()
    claim_by_id = {c.id: c for c in db.query(SourceClaim).filter(
        SourceClaim.id.in_([a.source_claim_id for a in supports])
    ).all()}
    for name, row in entities.items():
        for r in row["reasons"]:
            for a in supports:
                claim = claim_by_id.get(a.source_claim_id)
                if claim and name in (claim.subject_entity or ""):
                    r["supporting_claims"].append({
                        "normalized_claim": claim.normalized_claim,
                        "source_document_id": claim.source_document_id,
                    })

    return {
        "entities": [
            {
                "entity_text": row["entity_text"],
                "relationship": row["relationship"],
                "speech_act": row["speech_act"],
                "run_coverage": f"{len(row['run_ids'])}/{total_runs}",
                "reasons": row["reasons"],
            }
            for row in entities.values()
        ],
    }


@router.post("/workflow/{project_id}/{prompt_id}/run-analysis")
def workflow_run_analysis(project_id: int, prompt_id: int, payload: dict, db: Session = Depends(get_db)):
    """一键运行机器分析五层管道（Answer Semantic → Source Qualification → Retrieval → Source Claim → Alignment）。"""
    from app.models import Project, Prompt, BrowserMonitorRun
    from app.modules.optimization.answer_semantic import run_answer_semantic
    from app.modules.optimization.source_qualification import run_source_qualification
    from app.modules.optimization.source_claim import run_source_claim_extraction
    from app.modules.optimization.evidence_alignment import run_evidence_alignment

    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt:
        raise HTTPException(status_code=404, detail="Project/Prompt not found")

    run_ids = payload.get("run_ids") or [
        r.id for r in db.query(BrowserMonitorRun).filter(
            BrowserMonitorRun.project_id == project_id,
            BrowserMonitorRun.prompt_id == prompt_id,
            BrowserMonitorRun.status.in_(["success", "partial_success"]),
        ).all()
    ]
    if not run_ids:
        raise HTTPException(status_code=400, detail="该 Prompt 没有可用的采集 Run")

    results = {}
    results["layer1"] = run_answer_semantic(db, project, prompt, run_ids)
    results["layer2"] = run_source_qualification(db, project)
    results["layer4"] = run_source_claim_extraction(db, project, prompt_id, run_ids)
    results["layer5"] = run_evidence_alignment(db, project, prompt_id, run_ids)
    return results

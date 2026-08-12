from __future__ import annotations

from fastapi import APIRouter, Depends
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


@router.post("/golden-case/run")
def golden_case_run(payload: dict, db: Session = Depends(get_db)):
    run_ids = payload.get("run_ids", list(range(173, 185)))
    brand_url = payload.get("brand_url", "https://www.aifabu.com/card")
    return run_golden_case_pipeline(db, run_ids, brand_url)


@router.get("/golden-case/claims")
def golden_case_claims(run_ids: str = "173,174,175,176,177,178,179,180,181,182,183,184", db: Session = Depends(get_db)):
    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(ids)).order_by(AnswerClaim.run_id, AnswerClaim.claim_index).all()
    return [{"id": c.id, "run_id": c.run_id, "claim_index": c.claim_index, "raw_text": c.raw_text,
             "claim_type": c.claim_type, "citation_anchor": c.citation_anchor,
             "citation_ids": loads(c.citation_ids_json, []),
             "answer_position": c.answer_position, "epistemic_status": c.epistemic_status,
             "provenance": c.provenance, "review_status": c.review_status,
             "reviewer": c.reviewer, "review_note": c.review_note} for c in claims]


@router.get("/golden-case/alignments")
def golden_case_alignments(run_ids: str = "173,174,175,176,177,178,179,180,181,182,183,184", db: Session = Depends(get_db)):
    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
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
        ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
        refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(ids)).all()
        # Build set of citation URLs (both raw and normalized)
        cit_urls = set()
        for r in refs:
            raw = r.url or ""
            can = r.canonical_url or ""
            if raw: cit_urls.add(raw)
            if can: cit_urls.add(can)
        # Match documents by original_url matching citation URL
        all_docs = db.query(SourceDocument).filter(
            SourceDocument.original_url.in_(cit_urls)
        ).order_by(SourceDocument.fetch_status, SourceDocument.id).all()
        # Also match by url if original_url is empty
        if not all_docs:
            all_docs = db.query(SourceDocument).filter(
                SourceDocument.url.in_(cit_urls)
            ).order_by(SourceDocument.fetch_status, SourceDocument.id).all()
        docs = all_docs
    else:
        docs = db.query(SourceDocument).order_by(SourceDocument.fetch_status, SourceDocument.id).all()
    return [{"id": d.id, "url": d.url or d.original_url, "domain": d.domain, "source_type": d.source_type,
             "fetch_status": d.fetch_status, "title": d.title, "clean_text_len": len(d.clean_text or ""),
             "blocks_count": len(loads(d.content_blocks_json, [])),
             "failure_reason": d.failure_reason} for d in docs]


@router.get("/golden-case/need-map")
def golden_case_need_map(run_ids: str = "173,174,175,176,177,178,179,180,181,182,183,184", db: Session = Depends(get_db)):
    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
    return generate_answer_need_map(db, ids)


@router.get("/golden-case/brand-gap")
def golden_case_brand_gap(db: Session = Depends(get_db)):
    ids = list(range(173, 185))
    need_map = generate_answer_need_map(db, ids)
    return analyze_brand_information_gap(db, "https://www.aifabu.com/card", need_map["answer_need_map"], ids)


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
def golden_case_summary(db: Session = Depends(get_db)):
    docs = db.query(SourceDocument).count()
    claims = db.query(AnswerClaim).count()
    als = db.query(PassageAlignment).count()
    l1 = db.query(PassageAlignment).filter(PassageAlignment.alignment_level == "L1_EXACT_OVERLAP").count()
    l2 = db.query(PassageAlignment).filter(PassageAlignment.alignment_level == "L2_NEAR_DUPLICATE").count()
    reviewed = db.query(AnswerClaim).filter(AnswerClaim.review_status != "PENDING").count()
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
def golden_case_need_map_validated(run_ids: str = "173,174,175,176,177,178,179,180,181,182,183,184", db: Session = Depends(get_db)):
    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
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
            "run_coverage": f"{len(data['run_ids'])}/12",
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

    # If HTML provided, extract clean text from it
    import re as _re
    if html:
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
            d.clean_text = text[:200000] if text else d.clean_text
            d.raw_html = html[:500000] if html else d.raw_html
            d.title = title or d.title
            d.fetch_status = "SUCCESS"
            d.fetch_time = datetime.utcnow()
            updated += 1
            if updated == 1:
                doc = d
    if updated == 0:
        doc = SourceDocument(
            url=url, original_url=url, domain=urlparse(url).netloc.lower() if url else "",
            source_type=payload.get("source_type", "CITED"),
            fetch_status="SUCCESS", title=title,
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
def golden_case_url_audit(db: Session = Depends(get_db)):
    from app.modules.optimization.passage_service import _normalize_for_match, _normalize_url_for_fetch
    run_ids = list(range(173, 185))
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    cands = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all()

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

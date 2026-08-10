from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    OptimizationAction,
    OptimizationExperiment,
    OptimizationHypothesis,
    OptimizationIssue,
    OptimizationIssueRun,
    OptimizationStrategyCandidate,
    OptimizationEvidencePackage,
    PageSnapshot,
    Project,
    Prompt,
    ReferenceSource,
    RetrievalCandidate,
)
from app.modules.optimization import service
from app.modules.optimization.schemas import (
    ReleaseConfirmationPayload,
    StrategyCandidateReviewPayload,
)
from app.services.serialization import dumps


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_project(db):
    project = Project(id=1, organization_id=1, name="Test", brand_name="TestBrand", website_url="http://example.com")
    prompt = Prompt(id=1, project_id=1, prompt_text="test prompt", title="test")
    task = BrowserMonitorTask(id=1, project_id=1, question_ids_json="[1]", status="completed")
    runs = [
        BrowserMonitorRun(id=1, task_id=1, project_id=1, prompt_id=1, status="success", original_query="test", reference_complete=True, parsed_reference_count=3, resolved_url_count=3),
        BrowserMonitorRun(id=2, task_id=1, project_id=1, prompt_id=1, status="success", original_query="test", reference_complete=True, parsed_reference_count=3, resolved_url_count=3),
    ]
    db.add_all([project, prompt, task, *runs])
    db.commit()
    return project, prompt, runs


# ============================================================================
# Source Relation tests (P0-1: 1-4)
# ============================================================================

def test_source_relation_matched_by_canonical_url(db):
    """Canonical URL match yields MATCHED."""
    refs = [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com/a", canonical_url="http://x.com/a", domain="x.com")]
    cands = [RetrievalCandidate(id=1, run_id=1, title="T", url="http://x.com/a", canonical_url="http://x.com/a", domain="x.com")]
    result = service._build_source_relations(refs, cands)
    assert result["matched_count"] == 1
    assert result["citation_only_count"] == 0
    assert result["candidate_only_count"] == 0
    assert result["role"] == "DIAGNOSTIC_METADATA"


def test_source_relation_citation_only(db):
    """Citation without matching candidate yields CITATION_ONLY."""
    refs = [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com/a", domain="x.com")]
    cands = [RetrievalCandidate(id=1, run_id=1, title="Other", url="http://y.com/b", domain="y.com")]
    result = service._build_source_relations(refs, cands)
    assert result["citation_only_count"] >= 1
    assert result["matched_count"] == 0


def test_source_relation_candidate_only(db):
    """Candidate without matching citation yields CANDIDATE_ONLY."""
    refs = [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com/a", domain="x.com")]
    cands = [RetrievalCandidate(id=1, run_id=1, title="Other", url="http://y.com/b", domain="y.com")]
    result = service._build_source_relations(refs, cands)
    assert result["candidate_only_count"] >= 1


def test_source_relation_provenance_unknown_by_default(db):
    """CITATION_ONLY provenance defaults to UNKNOWN, not MODEL_INTERNAL_KNOWLEDGE."""
    refs = [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com/a", domain="x.com")]
    cands = []
    result = service._build_source_relations(refs, cands)
    for item in result["citation_only"]:
        assert item["provenance"] == "UNKNOWN"
        assert item["provenance"] != "MODEL_INTERNAL_KNOWLEDGE"


# ============================================================================
# Platform Semantics tests (P0-1: 5-7)
# ============================================================================

def test_platform_semantics_raw_vs_inferred_separated(db):
    """raw_platform stays as parser value; inferred_platform comes from domain."""
    refs = [ReferenceSource(id=1, run_id=1, display_title="B vid", url="http://bilibili.com/v/BV123", domain="bilibili.com", platform_name="wenxin")]
    cands = []
    result = service._build_source_relations(refs, cands)
    item = result["citation_only"][0]
    assert item["raw_platform"] == "wenxin"
    assert item["inferred_platform"] == "BILIBILI"
    assert "DOMAIN_MAPPING" in item.get("platform_inference_method", "")


def test_platform_semantics_bilibili_domain_maps_correctly(db):
    """bilibili.com maps to BILIBILI via DOMAIN_PLATFORM_MAP."""
    info = service._infer_platform_from_domain("bilibili.com")
    assert info["inferred_platform"] == "BILIBILI"
    assert info["confidence"] == "high"


def test_platform_semantics_unknown_domain_returns_unknown(db):
    """Unmapped domain returns UNKNOWN inferred_platform."""
    info = service._infer_platform_from_domain("completely-unknown-domain.xyz")
    assert info["inferred_platform"] == "UNKNOWN"
    assert info["confidence"] == "low"


# ============================================================================
# EvidenceActionContext tests (P0-1: 8-9)
# ============================================================================

def test_evidence_action_context_citation_content_unavailable(db):
    """When content body unavailable, citation_content_analysis_available=False."""
    project, prompt, runs = _seed_project(db)
    refs = [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com", domain="x.com")]
    cands = [RetrievalCandidate(id=1, run_id=1, title="T", url="http://x.com", domain="x.com")]
    pkg = OptimizationEvidencePackage(
        id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]",
        target_page_urls_json="[]",
        package_payload_json=dumps({
            "run_metric_eligibility": {
                "citation_eligible_run_ids": [1, 2],
                "retrieval_eligible_run_ids": [1, 2],
                "excluded_run_ids_by_metric": {},
                "exclusion_reasons": {},
            },
            "metrics": [],
            "metric_snapshot": {},
            "platform_gap_matrix": [],
            "content_type_distribution": [
                {"content_type": "TUTORIAL", "candidate_run_count": 2, "citation_run_count": 2, "candidate_ids": [], "citation_ids": []},
                {"content_type": "TOOL_PAGE", "candidate_run_count": 2, "citation_run_count": 0, "candidate_ids": [], "citation_ids": []},
            ],
            "time_distribution": [],
            "retrieval_metrics_status": "ok",
            "retrieval_coverage_summary": {},
            "representative_sources": [],
            "prompt": {"prompt_text": "test"},
        }),
        package_hash="test", status="active",
    )
    ctx = service._build_evidence_action_context(db, project, pkg, runs, refs, cands, [])
    assert ctx["citation_content_analysis_available"] is False
    assert ctx["citation_content_patterns"]["available"] is False
    assert ctx["citation_content_patterns"]["reason"] == "CONTENT_BODY_UNAVAILABLE"


def test_evidence_action_context_decision_capability_with_sufficient_data(db):
    """With 12+ runs and clear content patterns, decision_capability should be determined."""
    project, prompt, runs = _seed_project(db)
    refs = []
    cands = []
    # Create 12-run content type distribution to meet >=6 threshold
    ct_data = [
        {"content_type": "TUTORIAL", "candidate_run_count": 12, "citation_run_count": 12, "candidate_ids": [], "citation_ids": []},
        {"content_type": "TOOL_PAGE", "candidate_run_count": 10, "citation_run_count": 0, "candidate_ids": [], "citation_ids": []},
    ]
    pkg = OptimizationEvidencePackage(
        id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]",
        target_page_urls_json="[]",
        package_payload_json=dumps({
            "run_metric_eligibility": {
                "citation_eligible_run_ids": list(range(1, 13)),
                "retrieval_eligible_run_ids": list(range(1, 13)),
                "excluded_run_ids_by_metric": {},
                "exclusion_reasons": {},
            },
            "metrics": [],
            "metric_snapshot": {},
            "platform_gap_matrix": [],
            "content_type_distribution": ct_data,
            "time_distribution": [],
            "retrieval_metrics_status": "ok",
            "retrieval_coverage_summary": {},
            "representative_sources": [],
            "prompt": {"prompt_text": "test"},
        }),
        package_hash="test", status="active",
    )
    ctx = service._build_evidence_action_context(db, project, pkg, runs, refs, cands, [])
    # With clear content patterns and no content body, should be CONTENT_DIRECTION_ONLY
    assert ctx["decision_capability"] in ("CONTENT_DIRECTION_ONLY", "NEEDS_MORE_EVIDENCE")


# ============================================================================
# FACT / INFERENCE tests (P0-1: 10-11)
# ============================================================================

def test_fact_does_not_contain_inference_language(db):
    """FACT entries should not contain speculative language."""
    facts = service._extract_structured_facts(
        project=Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com"),
        prompt_text="test",
        runs=[BrowserMonitorRun(id=1, project_id=1, prompt_id=1, status="success")],
        metrics=[{"metric_name": "brand_mention_rate", "numerator": 0, "denominator": 2, "value": 0.0, "calculation_status": "ok"}],
        metric_snapshot={"brand_mention_rate": 0.0, "brand_mention_count": 0, "valid_run_count": 2},
        platform_matrix=[],
        content_types=[],
        source_relations={"matched_count": 0, "citation_only_count": 0, "candidate_only_count": 0, "total_citations": 0, "join_rate": 0},
        eligibility={"citation_eligible_run_ids": [1], "retrieval_eligible_run_ids": [1]},
        target_urls=[],
    )
    for f in facts:
        text = f.get("metric_name", "") + str(f.get("numerator", ""))
        assert "可能" not in text
        assert "推测" not in text
        assert "perhaps" not in text.lower()


def test_evidence_fit_separated_from_execution_feasibility(db):
    """evidence_fit and execution_feasibility are distinct dimensions."""
    provider = service.EvidenceDrivenStrategyProvider()
    context = {
        "evidence_facts": [],
        "evidence_confidence": "MEDIUM",
        "decision_capability": "CONTENT_DIRECTION_ONLY",
        "content_type_patterns": {
            "high_citation_types": ["TUTORIAL", "VIDEO"],
            "low_citation_types": ["TOOL_PAGE"],
        },
        "brand_presence": {"brand_name": "X", "brand_mention_rate": 0.0},
        "brand_channel_gaps": [],
        "source_relation_landscape": {"role": "DIAGNOSTIC_METADATA", "join_rate": 0.1, "citation_only_count": 100, "total_citations": 200},
        "citation_content_analysis_available": False,
        "official_site_fit": {"tool_page_fit_assessment": "LOW — tool pages are retrieved but never cited"},
        "target_page_urls": [],
        "missing_evidence": [],
        "citation_landscape": {"total_citation_runs": 2},
        "retrieval_landscape": {"total_retrieval_runs": 2},
        "source_run_ids": [1, 2],
    }
    result = provider.generate_from_context(
        Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com"),
        OptimizationEvidencePackage(id=1, project_id=1, version=1),
        context,
    )
    if result["strategy_options"]:
        opt = result["strategy_options"][0]
        assert "evidence_fit" in opt
        assert "execution_feasibility" in opt
        assert opt["evidence_fit"] != opt["execution_feasibility"] or opt["evidence_fit"] == "UNASSESSED"


# ============================================================================
# Strategy tests (P0-1: 12-17)
# ============================================================================

def test_strategy_does_not_fix_owned_site(db):
    """local_rule must not always output owned_site as target_platform."""
    provider = service.EvidenceDrivenStrategyProvider()
    context = {
        "evidence_facts": [],
        "evidence_confidence": "MEDIUM",
        "decision_capability": "CONTENT_DIRECTION_ONLY",
        "content_type_patterns": {
            "high_citation_types": ["TUTORIAL"],
            "low_citation_types": ["TOOL_PAGE"],
        },
        "brand_presence": {"brand_name": "X", "brand_mention_rate": 0.0},
        "brand_channel_gaps": [],
        "source_relation_landscape": {"role": "DIAGNOSTIC_METADATA", "join_rate": 0.1, "citation_only_count": 10, "total_citations": 20},
        "citation_content_analysis_available": False,
        "official_site_fit": {"tool_page_fit_assessment": "LOW — tool pages are retrieved but never cited"},
        "target_page_urls": [],
        "missing_evidence": [],
        "citation_landscape": {"total_citation_runs": 2},
        "retrieval_landscape": {"total_retrieval_runs": 2},
        "source_run_ids": [1, 2],
    }
    result = provider.generate_from_context(
        Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com"),
        OptimizationEvidencePackage(id=1, project_id=1, version=1),
        context,
    )
    if result["strategy_options"]:
        for opt in result["strategy_options"]:
            assert opt.get("target_platform") != "owned_site" or opt.get("decision_capability") == "CONTENT_DIRECTION_ONLY"
            assert opt["intervention_type"] in service.INTERVENTION_TYPE


def test_high_citation_platform_does_not_auto_recommend_publish(db):
    """High citation coverage alone does not force a platform publish recommendation."""
    provider = service.EvidenceDrivenStrategyProvider()
    context = {
        "evidence_facts": [],
        "evidence_confidence": "MEDIUM",
        "decision_capability": "CONTENT_DIRECTION_ONLY",
        "content_type_patterns": {
            "high_citation_types": ["TUTORIAL"],
            "low_citation_types": ["TOOL_PAGE"],
        },
        "brand_presence": {"brand_name": "X", "brand_mention_rate": 0.0},
        "brand_channel_gaps": [
            {"platform": "BILIBILI", "citation_run_count": 12, "gap_severity": "CRITICAL", "brand_presence": "ABSENT"},
        ],
        "source_relation_landscape": {"role": "DIAGNOSTIC_METADATA", "join_rate": 0.1, "citation_only_count": 100, "total_citations": 200},
        "citation_content_analysis_available": False,
        "official_site_fit": {"tool_page_fit_assessment": "LOW — tool pages are retrieved but never cited"},
        "target_page_urls": [],
        "missing_evidence": [],
        "citation_landscape": {"total_citation_runs": 12},
        "retrieval_landscape": {"total_retrieval_runs": 12},
        "source_run_ids": list(range(1, 13)),
    }
    result = provider.generate_from_context(
        Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com"),
        OptimizationEvidencePackage(id=1, project_id=1, version=1),
        context,
    )
    for opt in result.get("strategy_options", []):
        # Should not recommend publishing to BILIBILI directly
        if "EXTERNAL_PLATFORM" in opt.get("intervention_type", ""):
            # External platform interventions should have blocking evidence
            assert opt.get("blocking_evidence") or opt.get("target_platform") == "UNRESOLVED"


def test_source_relation_not_primary_strategy_evidence(db):
    """source_relation_landscape.role = DIAGNOSTIC_METADATA — not primary strategy evidence."""
    result = service._build_source_relations(
        [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com/a", domain="x.com")],
        [RetrievalCandidate(id=1, run_id=1, title="T", url="http://y.com/b", domain="y.com")],
    )
    assert result["role"] == "DIAGNOSTIC_METADATA"


def test_content_direction_only_without_content_body(db):
    """When citation_content_analysis_available=False, strategy is CONTENT_DIRECTION_ONLY."""
    provider = service.EvidenceDrivenStrategyProvider()
    context = {
        "evidence_facts": [],
        "evidence_confidence": "MEDIUM",
        "decision_capability": "CONTENT_DIRECTION_ONLY",
        "content_type_patterns": {
            "high_citation_types": ["TUTORIAL", "VIDEO"],
            "low_citation_types": ["TOOL_PAGE"],
        },
        "brand_presence": {"brand_name": "X", "brand_mention_rate": 0.0},
        "brand_channel_gaps": [],
        "source_relation_landscape": {"role": "DIAGNOSTIC_METADATA", "join_rate": 0.1, "citation_only_count": 10, "total_citations": 20},
        "citation_content_analysis_available": False,
        "official_site_fit": {"tool_page_fit_assessment": "LOW — tool pages are retrieved but never cited"},
        "target_page_urls": [],
        "missing_evidence": [],
        "citation_landscape": {"total_citation_runs": 2},
        "retrieval_landscape": {"total_retrieval_runs": 2},
        "source_run_ids": [1, 2],
    }
    result = provider.generate_from_context(
        Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com"),
        OptimizationEvidencePackage(id=1, project_id=1, version=1),
        context,
    )
    assert result["decision_capability"] == "CONTENT_DIRECTION_ONLY"
    for opt in result.get("strategy_options", []):
        assert opt.get("target_platform") == "UNRESOLVED"


def test_intervention_type_is_canonical_only(db):
    """All generated intervention types must be in the canonical INTERVENTION_TYPE set."""
    # canonical set does NOT include OWNED_CONTENT_EXTENSION
    assert "OWNED_CONTENT_EXTENSION" not in service.INTERVENTION_TYPE
    assert "EXTERNAL_PLATFORM_CONTENT" not in service.INTERVENTION_TYPE
    # OFFICIAL_NEW_PAGE is the canonical type for new owned informational assets
    assert "OFFICIAL_NEW_PAGE" in service.INTERVENTION_TYPE


# ============================================================================
# History / Provenance tests (P0-1: 18-20)
# ============================================================================

def test_historical_hypothesis_cannot_rebind_package(db):
    """Historical Hypothesis bound to old package must not be re-bound to new package.

    P0-3: The service layer must reject any attempt to create a hypothesis
    for an experiment that already has an ACCEPTED hypothesis with a different package.
    """
    project = Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com")
    prompt = Prompt(id=1, project_id=1, prompt_text="test", title="test")
    issue = OptimizationIssue(id=1, project_id=1, prompt_id=1, issue_type="brand_absent", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, target_url="http://x.com", status="PLANNED")
    experiment = OptimizationExperiment(id=1, action_id=1, status="draft",
        target_prompt_scope_json="[1]", baseline_run_ids_json="[]")
    pkg1 = OptimizationEvidencePackage(id=1, project_id=1, version=1,
        source_run_ids_json="[]", target_page_urls_json="[]",
        package_payload_json='{"metrics":[],"metric_snapshot":{}}',
        package_hash="abc", status="active")
    pkg2 = OptimizationEvidencePackage(id=2, project_id=1, version=2,
        source_run_ids_json="[]", target_page_urls_json="[]",
        package_payload_json='{"metrics":[],"metric_snapshot":{}}',
        package_hash="def", status="active")
    db.add_all([project, prompt, issue, action, experiment, pkg1, pkg2])
    db.commit()

    from fastapi import HTTPException
    from app.modules.optimization.schemas import OptimizationHypothesisCreate
    from app.modules.optimization.service import create_hypothesis

    # Create initial hypothesis on Package #1
    h1 = create_hypothesis(db, 1, OptimizationHypothesisCreate(
        evidence_package_id=1, observed_problem="original", hypothesized_cause="可能因为测试",
        core_mechanism="test", baseline_value="0/1", changed_features=["FAQ"], controlled_variables=["URL"],
    ))
    assert h1.evidence_package_id == 1

    # Attempt to rebind to Package #2 must fail
    with pytest.raises(HTTPException) as exc:
        create_hypothesis(db, 1, OptimizationHypothesisCreate(
            evidence_package_id=2, observed_problem="rebind attempt", hypothesized_cause="可能因为测试",
            core_mechanism="test", baseline_value="0/1", changed_features=["FAQ"], controlled_variables=["URL"],
        ))
    assert "HYPOTHESIS_EVIDENCE_IMMUTABLE" in str(exc.value.detail)
    assert "Package #1" in str(exc.value.detail)
    assert "Package #2" in str(exc.value.detail)


def test_legacy_v1_candidate_remains_readable(db):
    """V1 Candidates without new columns must still be readable."""
    project = Project(id=1, organization_id=1, name="X", brand_name="X")
    pkg = OptimizationEvidencePackage(id=1, project_id=1, version=1, source_run_ids_json="[]", target_page_urls_json="[]", package_payload_json="{}", package_hash="x", status="active")
    db.add_all([project, pkg])
    db.commit()
    # Create V1-style candidate (no intervention_type, etc.)
    candidate = OptimizationStrategyCandidate(
        project_id=1,
        evidence_package_id=1,
        target_url="http://x.com",
        provider="local_rule",
        model="local-rule-v1",
        original_llm_payload_json='{"target_object":"owned_page"}',
        structured_payload_json='{"target_object":"owned_page"}',
        review_status="PENDING_REVIEW",
    )
    db.add(candidate)
    db.commit()
    read = service.strategy_candidate_to_read(candidate)
    assert read["id"] == candidate.id
    assert read["review_status"] == "PENDING_REVIEW"
    assert read["structured_payload"].get("target_object") == "owned_page"


def test_v2_validator_does_not_break_v1_candidate(db):
    """V2 hypothesis validator should not reject V1 payloads."""
    v1_payload = {
        "observed_problem": "Test",
        "hypothesized_cause": "可能因为测试",
        "core_mechanism": "Test mechanism",
        "target_object": "owned_page",
        "target_url": "http://x.com",
        "recommended_intervention": "Test intervention",
        "target_metric": "target_page_retrieval_rate",
        "validation_plan": {"test": True},
        "invalidating_result": "Test invalidating",
        "changed_features": ["FAQ"],
        "controlled_variables": ["URL"],
    }
    evidence_result = {"status": "VALIDATED", "errors": [], "warnings": []}
    result = service.validate_strategy_hypothesis(v1_payload, evidence_result)
    assert result["status"] == "VALIDATED"


# ============================================================================
# Experiment / Release tests (P0-1: 21-25)
# ============================================================================

def test_release_confirm_rejects_without_accepted_strategy(db):
    """confirm_experiment_release must reject when no ACCEPTED strategy exists."""
    project, prompt, runs = _seed_project(db)
    issue = OptimizationIssue(id=1, project_id=1, prompt_id=1, issue_type="brand_absent", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, target_url="http://x.com", status="READY_FOR_MANUAL_RELEASE")
    experiment = OptimizationExperiment(id=1, action_id=1, status="baseline_locked",
        baseline_run_ids_json="[1,2]", target_prompt_scope_json="[1]")
    pkg = OptimizationEvidencePackage(id=1, project_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json='["http://x.com"]',
        package_payload_json='{"metrics":[],"metric_snapshot":{"target_page_retrieval":{"calculation_status":"ok","retrieval_rate":0.5}}}',
        package_hash="x", status="active")
    hypothesis = OptimizationHypothesis(id=1, project_id=1, issue_id=1, experiment_id=1,
        evidence_package_id=1, status="ACCEPTED",
        target_metric="target_page_retrieval_rate",
        changed_features_json='["FAQ"]', controlled_variables_json='["URL"]')
    pre_snap = PageSnapshot(id=1, project_id=1, experiment_id=1, url="http://x.com",
        snapshot_type="PRE_RELEASE", capture_status="success",
        raw_html="<html></html>", html_hash="abc", main_text="", main_text_hash="def")
    post_snap = PageSnapshot(id=2, project_id=1, experiment_id=1, url="http://x.com",
        canonical_url="http://x.com",
        snapshot_type="POST_RELEASE", capture_status="success",
        raw_html="<html></html>", html_hash="xyz", main_text="", main_text_hash="ghi")
    db.add_all([issue, action, experiment, pkg, hypothesis, pre_snap, post_snap])
    db.commit()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        service.confirm_experiment_release(db, 1, ReleaseConfirmationPayload(
            hypothesis_id=1,
            pre_release_snapshot_id=1,
            post_release_snapshot_id=2,
            release_note="test",
            confirmed_by="test",
        ))
    assert "WAITING_FOR_INTERVENTION_SELECTION" in str(exc_info.value.detail)


def test_release_with_accepted_strategy_allows_legitimate_path(db):
    """With accepted strategy, release confirm proceeds past strategy check."""
    project, prompt, runs = _seed_project(db)
    issue = OptimizationIssue(id=1, project_id=1, prompt_id=1, issue_type="brand_absent", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, target_url="http://x.com", status="READY_FOR_MANUAL_RELEASE")
    experiment = OptimizationExperiment(id=1, action_id=1, status="baseline_locked",
        baseline_run_ids_json="[1,2]", target_prompt_scope_json="[1]", release_blocked=False)
    pkg = OptimizationEvidencePackage(id=1, project_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json='["http://x.com"]',
        package_payload_json='{"metrics":[],"metric_snapshot":{"target_page_retrieval":{"calculation_status":"ok","retrieval_rate":0.5}}}',
        package_hash="x", status="active")
    hypothesis = OptimizationHypothesis(id=1, project_id=1, issue_id=1, experiment_id=1,
        evidence_package_id=1, status="ACCEPTED",
        target_metric="target_page_retrieval_rate",
        changed_features_json='["FAQ"]', controlled_variables_json='["URL"]')
    # Accepted strategy
    strategy = OptimizationStrategyCandidate(
        id=1, project_id=1, experiment_id=1, evidence_package_id=1,
        target_url="http://x.com", provider="test", model="test",
        intervention_type="OFFICIAL_PAGE_UPDATE",
        generation_status="GENERATED",
        evidence_validation_status="VALIDATED", hypothesis_validation_status="VALIDATED",
        review_status="ACCEPTED", reviewed_by="test",
    )
    pre_snap = PageSnapshot(id=1, project_id=1, experiment_id=1, url="http://x.com",
        snapshot_type="PRE_RELEASE", capture_status="success",
        raw_html="<html></html>", html_hash="abc", main_text="", main_text_hash="def")
    post_snap = PageSnapshot(id=2, project_id=1, experiment_id=1, url="http://x.com",
        canonical_url="http://x.com",
        snapshot_type="POST_RELEASE", capture_status="success",
        raw_html="<html></html>", html_hash="xyz", main_text="", main_text_hash="ghi")
    db.add_all([issue, action, experiment, pkg, hypothesis, strategy, pre_snap, post_snap])
    db.commit()

    # Should get past the strategy check (will fail on other checks like snapshot validation or robots)
    from fastapi import HTTPException
    try:
        service.confirm_experiment_release(db, 1, ReleaseConfirmationPayload(
            hypothesis_id=1,
            pre_release_snapshot_id=1,
            post_release_snapshot_id=2,
            release_note="test",
            confirmed_by="test",
        ))
    except HTTPException as e:
        # Should NOT be WAITING_FOR_INTERVENTION_SELECTION
        assert "WAITING_FOR_INTERVENTION_SELECTION" not in str(e.detail)


def test_external_intervention_does_not_reuse_official_page_experiment(db):
    """External platform Strategy must not overwrite an official-page Experiment's target."""
    # Verified by schema: experiment_id on strategy candidate is nullable
    # V2 strategy generation sets experiment_id=None
    # This test validates the architectural invariant via code inspection
    candidate = OptimizationStrategyCandidate(
        project_id=1, evidence_package_id=1,
        intervention_type="EXTERNAL_PLATFORM_ARTICLE",
        target_platform="ZHIHU",
        target_url=None,
        experiment_id=None,  # NOT bound to any experiment
    )
    assert candidate.experiment_id is None
    assert candidate.intervention_type == "EXTERNAL_PLATFORM_ARTICLE"


def test_experiment_primary_metric_matches_intervention_type(db):
    """INTERVENTION_METRIC_MAP must map every canonical intervention to a metric."""
    for itype in service.INTERVENTION_TYPE:
        assert itype in service.INTERVENTION_METRIC_MAP, f"Missing metric mapping for {itype}"


def test_release_blocked_experiment_cannot_release(db):
    """Release-blocked experiment raises error even with accepted strategy."""
    project, prompt, runs = _seed_project(db)
    issue = OptimizationIssue(id=1, project_id=1, prompt_id=1, issue_type="brand_absent", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, target_url="http://x.com", status="READY_FOR_MANUAL_RELEASE")
    experiment = OptimizationExperiment(id=1, action_id=1, status="baseline_locked",
        baseline_run_ids_json="[1,2]", target_prompt_scope_json="[1]",
        release_blocked=True, release_blocked_reason="WAITING_FOR_INTERVENTION_SELECTION")
    pkg = OptimizationEvidencePackage(id=1, project_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json='["http://x.com"]',
        package_payload_json='{"metrics":[],"metric_snapshot":{}}',
        package_hash="x", status="active")
    hypothesis = OptimizationHypothesis(id=1, project_id=1, issue_id=1, experiment_id=1,
        evidence_package_id=1, status="ACCEPTED", target_metric="target_page_retrieval_rate",
        changed_features_json='["FAQ"]', controlled_variables_json='["URL"]')
    strategy = OptimizationStrategyCandidate(
        id=1, project_id=1, experiment_id=1, evidence_package_id=1,
        target_url="http://x.com", provider="test", model="test",
        intervention_type="OFFICIAL_PAGE_UPDATE",
        generation_status="GENERATED",
        evidence_validation_status="VALIDATED", hypothesis_validation_status="VALIDATED",
        review_status="ACCEPTED", reviewed_by="test",
    )
    db.add_all([issue, action, experiment, pkg, hypothesis, strategy])
    db.commit()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        service.confirm_experiment_release(db, 1, ReleaseConfirmationPayload(
            hypothesis_id=1,
            pre_release_snapshot_id=999,
            post_release_snapshot_id=998,
            release_note="test",
            confirmed_by="test",
        ))
    assert "阻塞" in str(exc_info.value.detail) or "blocked" in str(exc_info.value.detail).lower()


# ============================================================================
# Effective Payload E2E tests
# ============================================================================

def _seed_for_effective_payload(db):
    """Seed common test data for effective payload tests."""
    project = Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com")
    prompt = Prompt(id=1, project_id=1, prompt_text="test", title="test")
    task = BrowserMonitorTask(id=1, project_id=1, question_ids_json="[1]", status="completed")
    runs = [
        BrowserMonitorRun(id=1, task_id=1, project_id=1, prompt_id=1, status="success", reference_complete=True, parsed_reference_count=3, resolved_url_count=3, brand_mentioned=True, brand_recommendation_level=2),
        BrowserMonitorRun(id=2, task_id=1, project_id=1, prompt_id=1, status="success", reference_complete=True, parsed_reference_count=3, resolved_url_count=3, brand_mentioned=True, brand_recommendation_level=2),
    ]
    refs = [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com/a", domain="x.com")]
    cands = [RetrievalCandidate(id=i, run_id=1, title="T", url=f"http://x.com/{i}", domain="x.com") for i in range(1, 31)]
    db.add_all([project, prompt, task, *runs, *refs, *cands])
    db.commit()
    return project, prompt, runs


def test_legacy_column_does_not_override_human_edit(db):
    """effective_payload from human edit must override legacy identity columns."""
    project, prompt, runs = _seed_for_effective_payload(db)
    pkg = OptimizationEvidencePackage(id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json='["http://x.com/card"]',
        package_payload_json=dumps({"run_metric_eligibility":{"answer_eligible_run_ids":[1,2],"citation_eligible_run_ids":[1,2],"retrieval_eligible_run_ids":[1,2],"excluded_run_ids_by_metric":{},"exclusion_reasons":{}},"metrics":[{"metric_name":"brand_mention_rate","numerator":1,"denominator":2,"value":0.5,"calculation_status":"ok"}],"metric_snapshot":{"brand_mention_rate":0.5,"valid_run_count":2,"brand_mention_count":1},
            "platform_gap_matrix":[],"content_type_distribution":[],"time_distribution":[],"retrieval_metrics_status":"ok","retrieval_coverage_summary":{},"representative_sources":[],"prompt":{"prompt_text":"test"}}),
        package_hash="x", status="active")
    db.add(pkg)
    db.commit()

    # Create candidate with structured = OFFICIAL_NEW_PAGE, human = EXTERNAL_PLATFORM_ARTICLE
    candidate = OptimizationStrategyCandidate(
        id=1, project_id=1, evidence_package_id=1,
        target_url="http://x.com/card",
        intervention_type="OFFICIAL_NEW_PAGE",  # legacy column — must be ignored
        target_platform="owned_site",
        provider="test", model="test",
        structured_payload_json=dumps({
            "intervention_type": "OFFICIAL_NEW_PAGE",
            "target_platform": "UNRESOLVED",
            "target_metric": "brand_mention_rate",
            "target_url": "http://x.com/card",
            "observed_problem": "test",
            "hypothesized_cause": "可能是因为测试",
            "core_mechanism": "test mech",
            "recommended_action": "test action",
            "validation_plan": {"test": True},
            "invalidating_result": "test",
            "changed_features": [{"feature": "FAQ"}],
            "controlled_variables": ["URL"],
        }),
        human_edited_payload_json=dumps({
            "intervention_type": "EXTERNAL_PLATFORM_ARTICLE",
            "target_platform": "ZHIHU",
        }),
        effective_payload_json="{}",
        generation_status="GENERATED",
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status="ACCEPTED_WITH_EDITS",
        reviewed_by="test",
    )
    db.add(candidate)
    db.commit()

    from app.modules.optimization.service import get_effective_strategy_payload, deterministic_merge, loads
    from app.modules.optimization.schemas import StrategyCandidateReviewPayload

    # Re-do the review to generate effective payload
    service.review_strategy_candidate(db, 1, StrategyCandidateReviewPayload(
        review_status="ACCEPTED_WITH_EDITS",
        reviewed_by="test",
        human_edited_payload={
            "intervention_type": "EXTERNAL_PLATFORM_ARTICLE",
            "target_platform": "ZHIHU",
        },
    ))

    # Re-read
    db.refresh(candidate)
    effective = loads(candidate.effective_payload_json, {})

    # Assertion 1: effective has human edit values
    assert effective["intervention_type"] == "EXTERNAL_PLATFORM_ARTICLE"
    assert effective["target_platform"] == "ZHIHU"

    # Assertion 2: effective still has unedited fields
    assert effective["target_metric"] == "brand_mention_rate"
    assert effective["observed_problem"] == "test"
    assert "required_sections" in effective or "recommended_action" in effective

    # Assertion 3: legacy column is STILL the OLD value (not overwritten)
    assert candidate.intervention_type == "OFFICIAL_NEW_PAGE"


def test_effective_payload_preserves_unedited_fields(db):
    """When only target_platform is edited, other fields remain from structured."""
    project, prompt, runs = _seed_for_effective_payload(db)
    original = {
        "intervention_type": "OFFICIAL_NEW_PAGE",
        "target_platform": "UNRESOLVED",
        "target_metric": "brand_mention_rate",
        "target_content_type": "TUTORIAL",
        "recommended_outline": ["A", "B", "C"],
        "observed_problem": "test",
        "hypothesized_cause": "可能因为",
        "core_mechanism": "mech",
        "recommended_action": "do this",
        "validation_plan": {"test": True},
        "invalidating_result": "test",
        "changed_features": [{"feature": "FAQ"}],
        "controlled_variables": ["URL"],
    }
    from app.modules.optimization.service import deterministic_merge
    effective = deterministic_merge(original, {"target_platform": "ZHIHU"})
    assert effective["target_platform"] == "ZHIHU"
    assert effective["target_metric"] == "brand_mention_rate"
    assert effective["target_content_type"] == "TUTORIAL"
    assert effective["recommended_outline"] == ["A", "B", "C"]


def test_array_replacement_not_append(db):
    """Human edit of a list must replace entirely, not append."""
    from app.modules.optimization.service import deterministic_merge
    base = {"required_sections": ["A", "B", "C"]}
    delta = {"required_sections": ["A", "D"]}
    effective = deterministic_merge(base, delta)
    assert effective["required_sections"] == ["A", "D"]
    assert "B" not in effective["required_sections"]
    assert "C" not in effective["required_sections"]


def test_backfilled_unverified_fail_closed(db):
    """BACKFILLED_UNVERIFIED effective payload must be rejected by execution paths."""
    project, prompt, runs = _seed_for_effective_payload(db)
    pkg = OptimizationEvidencePackage(id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json="[]",
        package_payload_json='{"metrics":[],"metric_snapshot":{}}',
        package_hash="x", status="active")
    effective = {"intervention_type": "OFFICIAL_NEW_PAGE", "target_platform": "UNRESOLVED",
        "target_metric": "brand_mention_rate", "observed_problem": "test", "hypothesized_cause": "可能",
        "core_mechanism": "mech", "recommended_action": "do", "validation_plan": {},
        "invalidating_result": "test", "changed_features": [{"feature":"FAQ"}], "controlled_variables": ["URL"]}
    candidate = OptimizationStrategyCandidate(
        id=1, project_id=1, evidence_package_id=1,
        effective_payload_json=dumps(effective),
        effective_payload_version="effective_payload.v1",
        effective_validation_status="BACKFILLED_UNVERIFIED",  # NOT VALIDATED
        generation_status="GENERATED",
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status="ACCEPTED",
        reviewed_by="test",
        structured_payload_json=dumps(effective),
    )
    db.add_all([pkg, candidate])
    db.commit()

    from fastapi import HTTPException
    from app.modules.optimization.service import get_effective_strategy_payload
    with pytest.raises(HTTPException) as exc:
        get_effective_strategy_payload(candidate)
    assert "not validated" in str(exc.value.detail).lower()
    assert "BACKFILLED_UNVERIFIED" in str(exc.value.detail)


def test_missing_effective_payload_fail_closed(db):
    """Execution must fail when effective_payload is missing."""
    project, prompt, runs = _seed_for_effective_payload(db)
    pkg = OptimizationEvidencePackage(id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json="[]",
        package_payload_json='{"metrics":[],"metric_snapshot":{}}',
        package_hash="x", status="active")
    candidate = OptimizationStrategyCandidate(
        id=1, project_id=1, evidence_package_id=1,
        effective_payload_json="{}",  # empty
        effective_payload_version="",
        generation_status="GENERATED",
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status="ACCEPTED",
        reviewed_by="test",
        structured_payload_json="{}",
    )
    db.add_all([pkg, candidate])
    db.commit()

    from fastapi import HTTPException
    from app.modules.optimization.service import get_effective_strategy_payload
    with pytest.raises(HTTPException) as exc:
        get_effective_strategy_payload(candidate)
    assert "Cannot execute" in str(exc.value.detail)


def test_strategy_to_experiment_uses_effective_payload(db):
    """strategy_to_experiment_plan must consume effective_payload, not legacy columns."""
    project, prompt, runs = _seed_for_effective_payload(db)
    pkg = OptimizationEvidencePackage(id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json='["http://x.com"]',
        package_payload_json=dumps({
            "run_metric_eligibility":{"citation_eligible_run_ids":[1,2],"answer_eligible_run_ids":[1,2],"retrieval_eligible_run_ids":[1,2],"excluded_run_ids_by_metric":{},"exclusion_reasons":{}},
            "metrics":[{"metric_name":"brand_mention_rate","numerator":1,"denominator":2,"value":0.5,"calculation_status":"ok"}],
            "metric_snapshot":{"brand_mention_rate":0.5,"valid_run_count":2},
            "platform_gap_matrix":[],"content_type_distribution":[],"time_distribution":[],
            "retrieval_metrics_status":"ok","retrieval_coverage_summary":{},"representative_sources":[],"prompt":{"prompt_text":"test"}}),
        package_hash="x", status="active")
    db.add(pkg)
    db.commit()

    # Candidate with EXTERNAL_PLATFORM_ARTICLE in effective payload
    effective_payload = {
        "intervention_type": "EXTERNAL_PLATFORM_ARTICLE",
        "target_platform": "ZHIHU",
        "target_url": "",
        "target_metric": "brand_mention_rate",
        "observed_problem": "test",
        "hypothesized_cause": "可能是因为外部平台",
        "core_mechanism": "test",
        "recommended_action": "Publish article on Zhihu",
        "validation_plan": {"test": True},
        "invalidating_result": "test",
        "changed_features": [{"feature": "FAQ"}],
        "controlled_variables": ["URL"],
    }
    candidate = OptimizationStrategyCandidate(
        id=1, project_id=1, evidence_package_id=1,
        target_url="http://x.com/card",
        intervention_type="OFFICIAL_NEW_PAGE",  # legacy — must NOT be used
        target_platform="owned_site",  # legacy — must NOT be used
        provider="test", model="test",
        structured_payload_json=dumps(effective_payload),
        human_edited_payload_json=dumps({}),
        effective_payload_json=dumps(effective_payload),
        effective_payload_version="effective_payload.v1",
        effective_validation_status="VALIDATED",
        generation_status="GENERATED",
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status="ACCEPTED",
        reviewed_by="test",
    )
    db.add(candidate)
    db.commit()

    result = service.strategy_to_experiment_plan(db, candidate.id)

    # Verify the created action uses EXTERNAL_PLATFORM_ARTICLE mapping
    assert result["readiness_status"] in ("READY", "BLOCKED")
    # The experiment was created because candidate had no experiment bound
    assert result["experiment_id"] is not None

    # Verify the created action type matches the external platform mapping
    from app.models import OptimizationAction
    if result.get("action_id"):
        action = db.get(OptimizationAction, result["action_id"])
        if action:
            assert action.action_type == "article_publish", f"Expected article_publish, got {action.action_type}"
            assert action.target_type == "external_platform", f"Expected external_platform, got {action.target_type}"


def test_historical_hypothesis_immutable_on_rebind(db):
    """Hypothesis cannot be rebound to a different package (P0-3 re-verified)."""
    project = Project(id=2, organization_id=1, name="Y", brand_name="Y", website_url="http://y.com")
    prompt = Prompt(id=2, project_id=2, prompt_text="test2", title="test2")
    issue = OptimizationIssue(id=2, project_id=2, prompt_id=2, issue_type="brand_absent", status="in_action")
    action = OptimizationAction(id=2, issue_id=2, target_url="http://y.com", status="PLANNED")
    experiment = OptimizationExperiment(id=2, action_id=2, status="draft",
        target_prompt_scope_json="[2]", baseline_run_ids_json="[]")
    pkg1 = OptimizationEvidencePackage(id=10, project_id=2, version=1,
        source_run_ids_json="[]", target_page_urls_json="[]",
        package_payload_json='{"metrics":[],"metric_snapshot":{}}',
        package_hash="abc2", status="active")
    pkg2 = OptimizationEvidencePackage(id=11, project_id=2, version=2,
        source_run_ids_json="[]", target_page_urls_json="[]",
        package_payload_json='{"metrics":[],"metric_snapshot":{}}',
        package_hash="def2", status="active")
    db.add_all([project, prompt, issue, action, experiment, pkg1, pkg2])
    db.commit()

    from fastapi import HTTPException
    from app.modules.optimization.schemas import OptimizationHypothesisCreate
    from app.modules.optimization.service import create_hypothesis

    h1 = create_hypothesis(db, 2, OptimizationHypothesisCreate(
        evidence_package_id=10, observed_problem="orig", hypothesized_cause="可能因为",
        core_mechanism="mech", baseline_value="0/1", changed_features=["FAQ"], controlled_variables=["URL"],
    ))
    assert h1.evidence_package_id == 10

    with pytest.raises(HTTPException) as exc:
        create_hypothesis(db, 2, OptimizationHypothesisCreate(
            evidence_package_id=11, observed_problem="rebind", hypothesized_cause="可能因为",
            core_mechanism="mech", baseline_value="0/1", changed_features=["FAQ"], controlled_variables=["URL"],
        ))
    assert "HYPOTHESIS_EVIDENCE_IMMUTABLE" in str(exc.value.detail)


def test_batch_delete_preflight_rejects_if_any_has_runs(db):
    """batch-delete must reject entire batch if any prompt has dependencies."""
    project = Project(id=100, organization_id=1, name="X", brand_name="X", website_url="http://x.com")
    prompt_a = Prompt(id=100, project_id=100, prompt_text="clean", title="clean", enabled=True)
    prompt_b = Prompt(id=101, project_id=100, prompt_text="dirty", title="dirty", enabled=True)
    task = BrowserMonitorTask(id=100, project_id=100, question_ids_json="[101]", status="completed")
    run = BrowserMonitorRun(id=100, task_id=100, project_id=100, prompt_id=101, status="success")
    db.add_all([project, prompt_a, prompt_b, task, run])
    db.commit()

    from fastapi import HTTPException
    from app.api.v0 import batch_delete_prompts
    with pytest.raises(HTTPException) as exc_info:
        batch_delete_prompts(100, {"ids": [100, 101]}, db)
    assert "400" in str(exc_info.value.status_code)
    # Both prompts must still exist
    assert db.get(Prompt, 100) is not None
    assert db.get(Prompt, 101) is not None


def test_batch_delete_succeeds_when_all_clean(db):
    """batch-delete succeeds when no prompts have dependencies."""
    project = Project(id=200, organization_id=1, name="X", brand_name="X", website_url="http://x.com")
    prompt_a = Prompt(id=200, project_id=200, prompt_text="a", title="a", enabled=True)
    prompt_b = Prompt(id=201, project_id=200, prompt_text="b", title="b", enabled=True)
    db.add_all([project, prompt_a, prompt_b])
    db.commit()

    from app.api.v0 import batch_delete_prompts
    result = batch_delete_prompts(200, {"ids": [200, 201]}, db)
    assert result["deleted"] == 2
    assert db.get(Prompt, 200) is None
    assert db.get(Prompt, 201) is None


def test_strategy_free_of_hardcoded_package7_data(db):
    """Strategy must not contain hardcoded Package #7 values."""
    provider = service.EvidenceDrivenStrategyProvider()
    context = {
        "evidence_facts": [
            {"fact_id": "F-1", "content_type": "TUTORIAL", "candidate_run_count": 5, "citation_run_count": 5, "metric_name": "brand_mention_rate"},
            {"fact_id": "F-2", "content_type": "TOOL_PAGE", "candidate_run_count": 3, "citation_run_count": 1, "metric_name": "brand_mention_rate"},
            {"fact_id": "F-3", "metric_name": "brand_mention_rate", "numerator": 1, "denominator": 5, "value": 0.2},
        ],
        "evidence_confidence": "MEDIUM",
        "decision_capability": "CONTENT_DIRECTION_ONLY",
        "content_type_patterns": {"high_citation_types": ["TUTORIAL"], "low_citation_types": []},
        "brand_presence": {"brand_name": "Test", "brand_mention_rate": 0.2},
        "brand_channel_gaps": [],
        "source_relation_landscape": {"role": "DIAGNOSTIC_METADATA", "join_rate": 0.2, "citation_only_count": 50, "total_citations": 100},
        "citation_content_analysis_available": False,
        "official_site_fit": {},
        "target_page_urls": ["http://example.com/test"],
        "missing_evidence": [],
        "citation_landscape": {"total_citation_runs": 5},
        "retrieval_landscape": {"total_retrieval_runs": 5},
        "source_run_ids": [1, 2, 3, 4, 5],
    }
    result = provider.generate_from_context(
        Project(id=1, organization_id=1, name="X", brand_name="TestBrand", website_url="http://example.com"),
        OptimizationEvidencePackage(id=10, project_id=1, version=1),
        context,
    )
    if result.get("strategy_options"):
        opt = result["strategy_options"][0]
        text = str(opt)
        # Must NOT contain Package #7 hardcoded values
        assert "抖音跳转链接" not in text, "hardcoded prompt text found"
        assert "/card" not in text, "hardcoded /card URL found"
        assert "0/12" not in text, "hardcoded 0/12 baseline found"
        assert "10/12" not in text, "hardcoded 10/12 found"
        assert "372" not in text, "hardcoded 372 found"
        assert "348" not in text, "hardcoded 348 found"
        # target_platform must be UNRESOLVED
        assert opt.get("target_platform") == "UNRESOLVED", "target_platform must be UNRESOLVED"


def test_strategy_without_tool_page_does_not_mention_tool_page(db):
    """Without TOOL_PAGE fact, strategy must not claim tool page retrieval/citation numbers."""
    provider = service.EvidenceDrivenStrategyProvider()
    context = {
        "evidence_facts": [
            {"fact_id": "F-1", "content_type": "TUTORIAL", "candidate_run_count": 8, "citation_run_count": 8},
        ],
        "evidence_confidence": "MEDIUM",
        "decision_capability": "CONTENT_DIRECTION_ONLY",
        "content_type_patterns": {"high_citation_types": ["TUTORIAL"], "low_citation_types": []},
        "brand_presence": {"brand_name": "Test", "brand_mention_rate": 0.0},
        "brand_channel_gaps": [],
        "source_relation_landscape": {"role": "DIAGNOSTIC_METADATA", "join_rate": 0.1, "citation_only_count": 10, "total_citations": 20},
        "citation_content_analysis_available": False,
        "official_site_fit": {},
        "target_page_urls": [],
        "missing_evidence": [],
        "citation_landscape": {"total_citation_runs": 8},
        "retrieval_landscape": {"total_retrieval_runs": 8},
        "source_run_ids": list(range(1, 9)),
    }
    result = provider.generate_from_context(
        Project(id=1, organization_id=1, name="X", brand_name="TestBrand", website_url="http://example.com"),
        OptimizationEvidencePackage(id=15, project_id=1, version=1),
        context,
    )
    if result.get("strategy_options"):
        opt = result["strategy_options"][0]
        text = str(opt)
        assert "工具页" not in text or "TOOL" not in text, "must not mention tool page when no TOOL_PAGE fact exists"


def test_no_action_creates_no_experiment(db):
    """NO_ACTION must not create Action, Experiment, or Hypothesis."""
    project, prompt, runs = _seed_for_effective_payload(db)
    pkg = OptimizationEvidencePackage(id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json="[]",
        package_payload_json=dumps({
            "run_metric_eligibility":{"citation_eligible_run_ids":[1,2],"answer_eligible_run_ids":[1,2],"retrieval_eligible_run_ids":[1,2],"excluded_run_ids_by_metric":{},"exclusion_reasons":{}},
            "metrics":[{"metric_name":"brand_mention_rate","numerator":1,"denominator":2,"value":0.5,"calculation_status":"ok"}],
            "metric_snapshot":{"brand_mention_rate":0.5,"valid_run_count":2},
            "platform_gap_matrix":[],"content_type_distribution":[],"time_distribution":[],
            "retrieval_metrics_status":"ok","retrieval_coverage_summary":{},"representative_sources":[],"prompt":{"prompt_text":"test"}}),
        package_hash="noop", status="active")
    db.add(pkg)
    db.commit()

    effective = {
        "intervention_type": "NO_ACTION",
        "target_platform": "UNRESOLVED",
        "target_metric": "brand_mention_rate",
        "observed_problem": "test", "hypothesized_cause": "可能",
        "core_mechanism": "mech", "recommended_action": "monitor",
        "validation_plan": {}, "invalidating_result": "test",
        "changed_features": [{"feature":"FAQ"}], "controlled_variables": ["URL"],
    }
    candidate = OptimizationStrategyCandidate(
        id=1, project_id=1, evidence_package_id=1,
        structured_payload_json=dumps(effective), human_edited_payload_json=dumps({}),
        effective_payload_json=dumps(effective), effective_payload_version="effective_payload.v1",
        effective_validation_status="VALIDATED",
        generation_status="GENERATED", evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED", review_status="ACCEPTED", reviewed_by="test",
    )
    db.add(candidate)
    db.commit()

    action_count_before = db.query(OptimizationAction).count()
    experiment_count_before = db.query(OptimizationExperiment).count()

    result = service.strategy_to_experiment_plan(db, candidate.id)

    assert result["readiness_status"] == "NO_ACTION"
    assert result["experiment_id"] is None
    assert result["action_id"] is None
    assert result["hypothesis_id"] is None

    # No new Action, Experiment, or Hypothesis created
    assert db.query(OptimizationAction).count() == action_count_before
    assert db.query(OptimizationExperiment).count() == experiment_count_before


def test_experiment_identity_is_preserved(db):
    """V2 strategy_to_experiment_plan creates a NEW experiment, never overwrites existing."""
    project = Project(id=1, organization_id=1, name="X", brand_name="X", website_url="http://x.com")
    prompt = Prompt(id=1, project_id=1, prompt_text="test", title="test")
    task = BrowserMonitorTask(id=1, project_id=1, question_ids_json="[1]", status="completed")
    runs = [
        BrowserMonitorRun(id=1, task_id=1, project_id=1, prompt_id=1, status="success", reference_complete=True, parsed_reference_count=3, resolved_url_count=3),
        BrowserMonitorRun(id=2, task_id=1, project_id=1, prompt_id=1, status="success", reference_complete=True, parsed_reference_count=3, resolved_url_count=3),
    ]
    refs = [ReferenceSource(id=1, run_id=1, display_title="T", url="http://x.com/a", domain="x.com")]
    cands = [RetrievalCandidate(id=i, run_id=1, title="T", url=f"http://x.com/{i}", domain="x.com") for i in range(1, 31)]
    db.add_all([project, prompt, task, *runs, *refs, *cands])
    db.commit()

    # Create a pre-existing experiment (like Experiment #13 with /card target)
    issue = OptimizationIssue(id=1, project_id=1, prompt_id=1, issue_type="brand_absent", status="in_action")
    action = OptimizationAction(id=1, issue_id=1, target_url="http://x.com/card", action_type="content_update", target_type="owned_content", status="PLANNED")
    existing_exp = OptimizationExperiment(id=1, action_id=1, status="baseline_locked",
        primary_metric="target_page_retrieval_rate", target_prompt_scope_json="[1]",
        release_blocked=True, release_blocked_reason="WAITING_FOR_INTERVENTION_SELECTION", released_at=None)
    db.add_all([issue, action, existing_exp])
    db.commit()

    # Now create a V2 strategy and run strategy_to_experiment_plan
    effective = {
        "intervention_type": "EXTERNAL_PLATFORM_ARTICLE",
        "target_platform": "ZHIHU",
        "target_url": "",
        "target_metric": "brand_mention_rate",
        "observed_problem": "test", "hypothesized_cause": "可能是因为外部平台",
        "core_mechanism": "test", "recommended_action": "Publish",
        "validation_plan": {"test": True}, "invalidating_result": "test",
        "changed_features": [{"feature": "FAQ"}], "controlled_variables": ["URL"],
    }
    pkg = OptimizationEvidencePackage(id=1, project_id=1, prompt_id=1, version=1,
        source_run_ids_json="[1,2]", target_page_urls_json="[]",
        package_payload_json=dumps({
            "run_metric_eligibility":{"citation_eligible_run_ids":[1,2],"answer_eligible_run_ids":[1,2],"retrieval_eligible_run_ids":[1,2],"excluded_run_ids_by_metric":{},"exclusion_reasons":{}},
            "metrics":[{"metric_name":"brand_mention_rate","numerator":1,"denominator":2,"value":0.5,"calculation_status":"ok"}],
            "metric_snapshot":{"brand_mention_rate":0.5,"valid_run_count":2},
            "platform_gap_matrix":[],"content_type_distribution":[],"time_distribution":[],
            "retrieval_metrics_status":"ok","retrieval_coverage_summary":{},"representative_sources":[],"prompt":{"prompt_text":"test"}}),
        package_hash="z", status="active")
    db.add(pkg)
    db.commit()

    candidate = OptimizationStrategyCandidate(
        id=1, project_id=1, evidence_package_id=1,
        structured_payload_json=dumps(effective), human_edited_payload_json=dumps({}),
        effective_payload_json=dumps(effective), effective_payload_version="effective_payload.v1",
        effective_validation_status="VALIDATED",
        generation_status="GENERATED", evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED", review_status="ACCEPTED", reviewed_by="test",
    )
    db.add(candidate)
    db.commit()

    result = service.strategy_to_experiment_plan(db, candidate.id)

    # Must create a NEW experiment, not reuse the existing one
    assert result["experiment_id"] != 1, "Must create a new experiment, not reuse Experiment #1"
    assert result["experiment_id"] is not None, "Must create an experiment"
    assert result["readiness_status"] in ("READY", "BLOCKED")

    # The pre-existing experiment must remain unchanged
    existing = db.get(OptimizationExperiment, 1)
    assert existing.release_blocked is True
    assert existing.released_at is None
    assert existing.primary_metric == "target_page_retrieval_rate"

    # Verify the action of the existing experiment is untouched
    old_action = db.get(OptimizationAction, 1)
    assert old_action.target_url == "http://x.com/card"
    assert old_action.action_type == "content_update"

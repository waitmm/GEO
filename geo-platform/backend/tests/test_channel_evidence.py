from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Competitor,
    EvidenceAlignment,
    OptimizationEvidencePackage,
    OptimizationStrategyCandidate,
    Organization,
    Project,
    Prompt,
    RecommendationEvent,
    ReferenceSource,
    RetrievalCandidate,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.channel_evidence import build_channel_evidence_landscape
from app.modules.optimization.passage_retrieval import (
    ANSWER_BINDING_REASON_SOURCE,
    FORMAL_V1_1_INPUT_VERSION,
)
from app.services.serialization import dumps
from app.services.url_identity import CANONICALIZATION_VERSION, build_url_identity


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def scope(db):
    org = Organization(name="PR2 org")
    db.add(org)
    db.flush()
    project = Project(
        organization_id=org.id,
        name="PR2 project",
        brand_name="目标品牌",
        brand_aliases_json=dumps(["目标产品"]),
        website_url="https://target.example.com",
    )
    db.add(project)
    db.flush()
    db.add(Competitor(project_id=project.id, name="竞品甲", website_url="https://competitor.example.com"))
    prompt = Prompt(project_id=project.id, prompt_text="测试问题")
    other_prompt = Prompt(project_id=project.id, prompt_text="其它问题")
    db.add_all([prompt, other_prompt])
    db.flush()
    task = BrowserMonitorTask(project_id=project.id)
    db.add(task)
    db.flush()
    return {
        "project": project,
        "prompt": prompt,
        "other_prompt": other_prompt,
        "task": task,
        "runs": [],
    }


def _run(db, scope, *, prompt=None):
    row = BrowserMonitorRun(
        task_id=scope["task"].id,
        project_id=scope["project"].id,
        prompt_id=(prompt or scope["prompt"]).id,
        status="success",
        run_sequence=len(scope["runs"]) + 1,
    )
    db.add(row)
    db.flush()
    scope["runs"].append(row)
    return row


def _package(db, scope, runs=None):
    row = OptimizationEvidencePackage(
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        version=1,
        source_run_ids_json=dumps([item.id for item in (runs or scope["runs"])]),
        package_hash="pr2-package",
        status="active",
    )
    db.add(row)
    db.flush()
    return row


def _document(db, url, *, clean_hash="content-v1"):
    identity = build_url_identity(url)
    row = SourceDocument(
        url=url,
        canonical_url=identity.canonical_url,
        canonical_url_hash=identity.canonical_url_hash,
        canonicalization_version=CANONICALIZATION_VERSION,
        domain=url.split("/")[2],
        clean_text="正文",
        clean_text_hash=clean_hash,
        fetch_status="fetched",
    )
    db.add(row)
    db.flush()
    return row


def _reference(db, run, url, *, index=1):
    identity = build_url_identity(url)
    row = ReferenceSource(
        run_id=run.id,
        reference_index=index,
        url=url,
        canonical_url=identity.canonical_url,
        canonical_url_hash=identity.canonical_url_hash,
        canonicalization_version=CANONICALIZATION_VERSION,
        domain=url.split("/")[2],
    )
    db.add(row)
    db.flush()
    return row


def _retrieval(db, run, url):
    identity = build_url_identity(url)
    row = RetrievalCandidate(
        run_id=run.id,
        url=url,
        canonical_url=identity.canonical_url,
        canonical_url_hash=identity.canonical_url_hash,
        canonicalization_version=CANONICALIZATION_VERSION,
        domain=url.split("/")[2],
    )
    db.add(row)
    db.flush()
    return row


def _support(
    db,
    scope,
    run,
    document,
    *,
    reason="选择理由 A",
    entity="竞品甲",
    binding_role="DIRECT_REASON",
    claim=None,
):
    event = RecommendationEvent(
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        run_id=run.id,
        entity_text=entity,
        entity_type="BRAND",
        speech_act="RECOMMEND",
        recommendation_strength="MODERATE",
        polarity="POSITIVE",
    )
    db.add(event)
    db.flush()
    answer_claim_id = 10_000 + event.id
    unit = AnswerUnit(
        shadow_run_id=None,
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        run_id=run.id,
        answer_claim_id=answer_claim_id,
        unit_text_original=reason,
        unit_text_normalized=reason,
        semantic_type="REASON",
    )
    db.add(unit)
    db.flush()
    binding = AnswerDecisionBinding(
        shadow_run_id=None,
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        run_id=run.id,
        recommendation_event_id=event.id,
        answer_unit_id=unit.id,
        decision_role=binding_role,
        binding_strength="HIGH",
        review_status="MACHINE_GROUNDED",
    )
    db.add(binding)
    db.flush()
    if claim is None:
        claim = SourceClaim(
            project_id=scope["project"].id,
            source_document_id=document.id,
            subject_entity=entity,
            subject_text=entity,
            predicate="支持",
            object_text="能力 A",
            normalized_claim=f"{entity}支持能力 A",
            review_status="HUMAN_CONFIRMED",
        )
        db.add(claim)
        db.flush()
    payload = {
        "reason_source": ANSWER_BINDING_REASON_SOURCE,
        "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
        "answer_unit_id": unit.id,
        "decision_binding_id": binding.id,
        "decision_role": binding_role,
        "binding_strength": "HIGH",
        "semantic_reason_key": f"{reason}|ENTITY_SPECIFIC|{entity}",
    }
    alignment = EvidenceAlignment(
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        run_id=run.id,
        recommendation_event_id=event.id,
        recommendation_reason_id=f"reason:{reason}",
        source_document_id=document.id,
        source_claim_id=claim.id,
        relation="SUPPORTS",
        machine_payload_json=dumps(payload),
        review_status="HUMAN_CONFIRMED",
    )
    db.add(alignment)
    db.flush()
    return alignment, claim


def _channel(result, key):
    return next(item for item in result["channels"] if item["channel_key"] == key)


def test_same_citation_in_ten_runs_keeps_one_semantic_relation(db, scope):
    url = "https://zhihu.com/question/1"
    document = _document(db, url)
    shared_claim = None
    for _ in range(10):
        run = _run(db, scope)
        _reference(db, run, url)
        _, shared_claim = _support(db, scope, run, document, claim=shared_claim)
    _package(db, scope)

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    decision = _channel(result, "ZHIHU")["role_counts"]["DECISION_CITATION"]
    assert decision["observation_count"] == 10
    assert decision["unique_url_count"] == 1
    assert decision["observed_run_count"] == 10
    assert decision["semantic_relation_count"] == 1
    assert decision["entity_counts"]["competitor"]["observation_count"] == 10


def test_multiple_documents_for_same_url_do_not_multiply_evidence(db, scope):
    run = _run(db, scope)
    url = "https://zhihu.com/question/2"
    _reference(db, run, url)
    _document(db, url, clean_hash="snapshot-a")
    _document(db, url, clean_hash="snapshot-b")
    _package(db, scope)

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    peripheral = _channel(result, "ZHIHU")["role_counts"]["PERIPHERAL_CITATION"]
    assert peripheral["observation_count"] == 1
    assert result["mapping_multiplicity"]["urls_with_multiple_documents"] == 1
    assert result["mapping_multiplicity"]["reference_document_memberships"] == 2


def test_decision_role_outranks_answer_support_for_same_citation(db, scope):
    run = _run(db, scope)
    url = "https://zhihu.com/question/3"
    document = _document(db, url)
    _reference(db, run, url)
    _support(db, scope, run, document, binding_role="CONTEXT")
    _support(db, scope, run, document, binding_role="DIRECT_REASON")
    _package(db, scope)

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    roles = _channel(result, "ZHIHU")["role_counts"]
    assert roles["DECISION_CITATION"]["observation_count"] == 1
    assert roles["ANSWER_SUPPORT_CITATION"]["observation_count"] == 0
    assert result["citation_role_conservation"]["valid"] is True


def test_answer_support_outranks_peripheral(db, scope):
    run = _run(db, scope)
    url = "https://zhihu.com/question/4"
    document = _document(db, url)
    _reference(db, run, url)
    _support(db, scope, run, document, binding_role="CONTEXT")
    _package(db, scope)

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    roles = _channel(result, "ZHIHU")["role_counts"]
    assert roles["ANSWER_SUPPORT_CITATION"]["observation_count"] == 1
    assert roles["PERIPHERAL_CITATION"]["observation_count"] == 0


def test_retrieval_without_same_run_citation_is_retrieval_only(db, scope):
    run = _run(db, scope)
    url = "https://www.bilibili.com/video/1"
    _retrieval(db, run, url)
    _document(db, url)
    _package(db, scope)

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    retrieval = _channel(result, "BILIBILI")["role_counts"]["RETRIEVAL_ONLY"]
    assert retrieval["observation_count"] == 1
    assert retrieval["unique_url_count"] == 1


def test_prompt_scope_does_not_leak_other_prompt_reference(db, scope):
    current_run = _run(db, scope)
    other_run = _run(db, scope, prompt=scope["other_prompt"])
    _reference(db, current_run, "https://zhihu.com/question/current")
    _reference(db, other_run, "https://www.bilibili.com/video/other")
    _document(db, "https://zhihu.com/question/current")
    _document(db, "https://www.bilibili.com/video/other")
    _package(db, scope, runs=[current_run])

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    assert result["global"]["raw_reference_rows"] == 1
    assert {item["channel_key"] for item in result["channels"]} == {"ZHIHU"}


def test_reason_a_evidence_does_not_enter_reason_b(db, scope):
    run = _run(db, scope)
    url = "https://zhihu.com/question/reasons"
    document = _document(db, url)
    _reference(db, run, url)
    _support(db, scope, run, document, reason="选择理由 A")
    event = RecommendationEvent(
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        run_id=run.id,
        entity_text="竞品甲",
        speech_act="RECOMMEND",
    )
    db.add(event)
    db.flush()
    unit = AnswerUnit(
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        run_id=run.id,
        answer_claim_id=99_999,
        unit_text_original="选择理由 B",
        unit_text_normalized="选择理由 B",
    )
    db.add(unit)
    db.flush()
    db.add(AnswerDecisionBinding(
        project_id=scope["project"].id,
        prompt_id=scope["prompt"].id,
        run_id=run.id,
        recommendation_event_id=event.id,
        answer_unit_id=unit.id,
        decision_role="DIRECT_REASON",
    ))
    _package(db, scope)

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    by_reason = {item["reason_text"]: item for item in result["decision_reason_breakdown"]}
    assert by_reason["选择理由 A"]["has_semantic_evidence"] is True
    assert by_reason["选择理由 B"]["has_semantic_evidence"] is False
    assert by_reason["选择理由 B"]["channels"] == []


def test_landscape_does_not_mutate_strategy_candidate(db, scope):
    run = _run(db, scope)
    _reference(db, run, "https://zhihu.com/question/read-only")
    _document(db, "https://zhihu.com/question/read-only")
    package = _package(db, scope)
    candidate = OptimizationStrategyCandidate(
        project_id=scope["project"].id,
        evidence_package_id=package.id,
        structured_payload_json=dumps({"planned_channels": ["OFFICIAL_SITE"]}),
        review_status="PENDING_REVIEW",
    )
    db.add(candidate)
    db.flush()
    before = candidate.structured_payload_json

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    db.refresh(candidate)
    assert candidate.structured_payload_json == before
    assert result["read_only_audit"]["mutated"] is False
    assert result["boundary"]["channel_resolution_performed"] is False


def test_six_run_regression_scope_keeps_decision_signal_and_conservation(db, scope):
    url = "https://zhihu.com/question/stable"
    document = _document(db, url)
    shared_claim = None
    for _ in range(6):
        run = _run(db, scope)
        _reference(db, run, url)
        _, shared_claim = _support(db, scope, run, document, claim=shared_claim)
    _package(db, scope)

    result = build_channel_evidence_landscape(db, scope["project"].id, scope["prompt"].id)
    decision = _channel(result, "ZHIHU")["role_counts"]["DECISION_CITATION"]
    assert result["global"]["run_count"] == 6
    assert decision["observed_run_count"] == 6
    assert decision["semantic_relation_count"] == 1
    assert result["citation_role_conservation"] == {
        "unique_citation_identities": 6,
        "decision_plus_support_plus_peripheral": 6,
        "valid": True,
    }

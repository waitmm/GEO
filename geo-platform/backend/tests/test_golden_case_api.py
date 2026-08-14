from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AnswerClaim, Base, BrowserMonitorRun, BrowserMonitorTask, PassageAlignment, Project, Prompt, ReferenceSource, SourceDocument
from app.modules.optimization import api
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


def _seed_claim_runs(db):
    project = Project(id=1, organization_id=1, name="Golden", brand_name="Brand")
    prompt = Prompt(id=16, project_id=1, prompt_text="抖音卡片", title="抖音卡片")
    task = BrowserMonitorTask(id=1, project_id=1, question_ids_json="[16]", status="completed")
    runs = [
        BrowserMonitorRun(id=47, task_id=1, project_id=1, prompt_id=16, status="success", original_query=prompt.prompt_text),
        BrowserMonitorRun(id=48, task_id=1, project_id=1, prompt_id=16, status="success", original_query=prompt.prompt_text),
        BrowserMonitorRun(id=173, task_id=1, project_id=1, prompt_id=19, status="success", original_query="抖音跳转链接"),
    ]
    claims = [
        AnswerClaim(
            id=1,
            run_id=47,
            claim_index=1,
            raw_text="点击生成抖音卡片",
            claim_type="操作步骤",
            review_status="CONFIRMED",
            human_labels_json=dumps(["操作步骤"]),
        ),
        AnswerClaim(
            id=2,
            run_id=48,
            claim_index=1,
            raw_text="选择抖音卡片工具",
            claim_type="操作步骤",
            review_status="CONFIRMED",
            human_labels_json=dumps(["操作步骤"]),
        ),
        AnswerClaim(
            id=3,
            run_id=173,
            claim_index=1,
            raw_text="抖音跳转链接设置",
            claim_type="操作步骤",
            review_status="PENDING",
        ),
    ]
    db.add_all([project, prompt, task, *runs, *claims])
    db.commit()


def test_golden_case_requires_explicit_run_ids():
    with pytest.raises(HTTPException):
        api._parse_required_run_ids("")


def test_golden_case_summary_is_scoped_to_run_ids(db):
    _seed_claim_runs(db)

    summary = api.golden_case_summary(run_ids="47,48", db=db)

    assert summary["answer_claims"] == 2
    assert summary["claims_reviewed"] == 2


def test_golden_case_need_map_uses_dynamic_run_denominator(db):
    _seed_claim_runs(db)

    result = api.golden_case_need_map_validated(run_ids="47,48", db=db)

    assert result["total_claims"] == 2
    assert result["validated_needs"][0]["run_coverage"] == "2/2"


def test_build_golden_case_manual_todos_flags_missing_docs_and_alignment(db):
    _seed_claim_runs(db)
    db.add(ReferenceSource(id=1, run_id=47, reference_index=1, url="https://example.com/a", canonical_url="https://example.com/a", domain="example.com"))
    db.add(SourceDocument(id=1, original_url="https://example.com/a", url="https://example.com/a", domain="example.com", source_type="CITED", fetch_status="FETCH_FAILED", failure_reason="timeout"))
    db.commit()

    claims = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_([47, 48])).all()
    docs = db.query(SourceDocument).all()
    alignments = db.query(PassageAlignment).all()

    todos = api._build_golden_case_manual_todos(claims, docs, alignments)
    codes = {item["code"] for item in todos}

    assert "DOCUMENTS_NEED_MANUAL_INPUT" in codes
    assert "NO_PASSAGE_ALIGNMENT" in codes
    assert "CLAIMS_WITHOUT_CITATION_ANCHOR" in codes


def test_add_manual_document_supports_empty_page_marker(db):
    doc = SourceDocument(
        id=1,
        original_url="https://example.com/deleted",
        url="https://example.com/deleted",
        domain="example.com",
        source_type="CITED",
        fetch_status="FETCH_FAILED",
        failure_reason="404",
    )
    db.add(doc)
    db.commit()

    result = api.add_manual_document(
        {
            "url": "https://example.com/deleted",
            "source_type": "CITED",
            "is_empty_page": True,
        },
        db=db,
    )

    refreshed = db.query(SourceDocument).filter(SourceDocument.id == 1).one()

    assert result["status"] == "MANUAL_CAPTURE"
    assert refreshed.fetch_status == "MANUAL_EMPTY"
    assert refreshed.failure_reason == "页面已删除或无可用正文（人工标记）"
    assert refreshed.clean_text == ""
    assert refreshed.content_blocks_json == "[]"

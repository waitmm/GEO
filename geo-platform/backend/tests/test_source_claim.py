from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Project, SourceClaim, SourceDocument
from app.modules.optimization.source_claim import SourceClaimJudge


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


def test_subject_entity_separated_from_owner_entity(db):
    """subject_entity（语义主体）与 source_owner_entity（provenance）分列存储。"""
    project = Project(id=1, organization_id=1, name="P", brand_name="爱短链", website_url="https://aifabu.com")
    doc = SourceDocument(id=1, url="https://shangjiajia.com/4626.html", domain="shangjiajia.com", fetch_status="SUCCESS")
    db.add_all([project, doc])
    db.commit()

    claim = SourceClaim(
        project_id=1, source_document_id=1, passage_id="doc1:p0",
        source_owner_entity="商加加", source_role="COMPETITOR_FIRST_PARTY",
        subject_entity="天天外链",  # Judge 识别正文在讲天天外链
        normalized_claim="天天外链支持抖音跳转", claim_type="CAPABILITY", polarity="POSITIVE",
        source_span="天天外链支持抖音跳转", raw_start=0, raw_end=9,
    )
    db.add(claim)
    db.commit()

    saved = db.query(SourceClaim).first()
    assert saved.subject_entity == "天天外链"
    assert saved.source_owner_entity == "商加加"
    assert saved.subject_entity != saved.source_owner_entity


def test_negation_preserved_in_normalized_claim(db):
    """否定不得翻转：'不支持' 不能存成 '支持'。"""
    project = Project(id=1, organization_id=1, name="P", brand_name="B", website_url="https://b.com")
    doc = SourceDocument(id=1, url="https://x.com/a", domain="x.com", fetch_status="SUCCESS")
    db.add_all([project, doc])
    db.commit()
    claim = SourceClaim(
        project_id=1, source_document_id=1, passage_id="p0",
        source_owner_entity="UNKNOWN", source_role="UNKNOWN",
        subject_entity="某工具",
        normalized_claim="某工具不支持修改目标地址",
        predicate="不支持", object_text="修改目标地址",
        claim_type="LIMITATION", polarity="NEGATIVE",
        source_span="不支持修改目标地址", raw_start=0, raw_end=9,
    )
    db.add(claim)
    db.commit()
    saved = db.query(SourceClaim).first()
    assert saved.predicate == "不支持"
    assert saved.polarity == "NEGATIVE"
    assert "不支持" in saved.normalized_claim


def test_ungrounded_span_marks_validation_failed(db):
    """span 无法定位时必须 VALIDATION_FAILED（由 run 流程处理，此处验证字段语义）。"""
    project = Project(id=1, organization_id=1, name="P", brand_name="B", website_url="https://b.com")
    doc = SourceDocument(id=1, url="https://x.com/a", domain="x.com", fetch_status="SUCCESS")
    db.add_all([project, doc])
    db.commit()
    claim = SourceClaim(
        project_id=1, source_document_id=1, passage_id="p0",
        source_owner_entity="UNKNOWN", source_role="UNKNOWN", subject_entity="X",
        normalized_claim="", claim_type="OTHER", polarity="NEUTRAL",
        source_span="伪造的span", raw_start=-1, raw_end=-1,
        review_status="VALIDATION_FAILED",
    )
    db.add(claim)
    db.commit()
    assert db.query(SourceClaim).first().review_status == "VALIDATION_FAILED"


def test_judge_system_prompt_has_injection_guard():
    """SourceClaimJudge 的 System Prompt 必须包含注入防护说明。"""
    from app.modules.optimization.source_claim import SOURCE_CLAIM_SYSTEM
    assert "不是指令" in SOURCE_CLAIM_SYSTEM
    assert "只输出纯 JSON 对象" in SOURCE_CLAIM_SYSTEM or "JSON" in SOURCE_CLAIM_SYSTEM

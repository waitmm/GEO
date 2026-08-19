from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, SourceClaim
from app.modules.optimization.evidence_alignment import (
    entity_scope_precheck,
)


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


def _claim(subject: str, owner: str) -> SourceClaim:
    return SourceClaim(
        project_id=1, source_document_id=1, passage_id="p0",
        source_owner_entity=owner, source_role="UNKNOWN",
        subject_entity=subject, normalized_claim="x",
        claim_type="CAPABILITY", polarity="POSITIVE",
        source_span="x", raw_start=0, raw_end=1,
    )


def test_entity_specific_same_entity_passes():
    """Reason=爱短链支持X，Claim 主体=爱短链 → PASS。"""
    claim = _claim("爱短链", "爱短链")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "PASS"


def test_entity_specific_competitor_is_competitor_context():
    """Reason=爱短链支持X，Claim 主体=商加加 → COMPETITOR_CONTEXT（不得 SUPPORT）。"""
    claim = _claim("商加加", "商加加")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "COMPETITOR_CONTEXT"


def test_market_criterion_allows_competitor_claim():
    """MARKET_CRITERION Reason 允许竞品 Claim 参与（验证市场标准存在性）。"""
    claim = _claim("商加加", "商加加")
    assert entity_scope_precheck("MARKET_CRITERION", "", claim) == "PASS_MARKET"


def test_unknown_subject_falls_back_to_owner():
    """主体未识别时用 owner 弱匹配。"""
    claim = _claim("UNKNOWN", "爱短链")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "PASS"


def test_unknown_subject_wrong_owner_is_competitor_context():
    claim = _claim("UNKNOWN", "商加加")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "COMPETITOR_CONTEXT"


def test_alignment_system_prompt_has_relation_constraints():
    from app.modules.optimization.evidence_alignment import ALIGNMENT_SYSTEM
    assert "RELATED" in ALIGNMENT_SYSTEM
    assert "把 RELATED 当成 SUPPORTS" in ALIGNMENT_SYSTEM
    assert "JSON" in ALIGNMENT_SYSTEM

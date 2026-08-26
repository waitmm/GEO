from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Competitor, Project, SourceDocument
from app.modules.optimization.source_qualification import (
    _content_hash,
    assess_quality,
    derive_content_status,
    resolve_ownership,
)
from app.modules.optimization.api import _find_source_document_by_url, _source_document_read
from app.modules.optimization.passage_service import _canonicalize_acquired_url, _normalize_url_for_fetch


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


def _project(db) -> Project:
    p = Project(id=1, organization_id=1, name="P", brand_name="爱短链", website_url="https://www.aifabu.com")
    db.add(p)
    db.add_all([
        Competitor(project_id=1, name="商加加", aliases_json="[]", website_url="https://shangjiajia.com"),
        Competitor(project_id=1, name="天天外链", aliases_json="[]", website_url="https://ttw.com"),
    ])
    db.commit()
    return p


# ---------------------------------------------------------------------------
# Source URL acquisition normalization
# ---------------------------------------------------------------------------


def test_fetch_normalization_does_not_prefix_www_to_platform_subdomains():
    assert _normalize_url_for_fetch("zhuanlan.zhihu.com/p/123") == "https://zhuanlan.zhihu.com/p/123"
    assert _normalize_url_for_fetch("baijiahao.baidu.com/s?id=1") == "https://baijiahao.baidu.com/s?id=1"
    assert _normalize_url_for_fetch("jingyan.baidu.com/article/1.html") == "https://jingyan.baidu.com/article/1.html"


def test_fetch_normalization_preserves_explicit_official_www():
    assert _normalize_url_for_fetch("http://www.aifabu.com/card") == "https://www.aifabu.com/card"


def test_acquired_canonical_url_strips_leading_www_without_touching_inner_www():
    assert _canonicalize_acquired_url("https://www.zhihu.com/question/1") == "https://zhihu.com/question/1"
    assert _canonicalize_acquired_url("https://gjzwfw.www.gov.cn/fwmh/ifam/qrcode.do") == "https://gjzwfw.www.gov.cn/fwmh/ifam/qrcode.do"


def test_source_document_action_url_normalizes_legacy_synthetic_www(db):
    doc = SourceDocument(
        url="https://www.zhuanlan.zhihu.com/p/123",
        original_url="https://zhuanlan.zhihu.com/p/123",
        domain="www.zhuanlan.zhihu.com",
        source_type="CITED",
        fetch_status="FETCH_FAILED",
        failure_reason="ERR_NAME_NOT_RESOLVED",
    )
    db.add(doc)
    db.commit()

    payload = _source_document_read(doc)
    assert payload["action_url"] == "https://zhuanlan.zhihu.com/p/123"
    assert _find_source_document_by_url(db, "https://zhuanlan.zhihu.com/p/123").id == doc.id


# ---------------------------------------------------------------------------
# Ownership Resolver
# ---------------------------------------------------------------------------

def test_target_first_party_ownership(db):
    p = _project(db)
    r = resolve_ownership(db, p, "https://www.aifabu.com/details/42089")
    assert r["source_role"] == "TARGET_FIRST_PARTY"
    assert r["source_owner_entity"] == "爱短链"


def test_competitor_first_party_ownership(db):
    p = _project(db)
    r = resolve_ownership(db, p, "https://shangjiajia.com/4626.html")
    assert r["source_role"] == "COMPETITOR_FIRST_PARTY"
    assert r["source_owner_entity"] == "商加加"


def test_ugc_community_ownership(db):
    p = _project(db)
    r = resolve_ownership(db, p, "https://zhuanlan.zhihu.com/p/123")
    assert r["source_role"] == "UGC_COMMUNITY"
    assert r["source_owner_entity"] == "UNKNOWN"


def test_platform_native_ownership(db):
    p = _project(db)
    r = resolve_ownership(db, p, "http://bilibili.com/video/BV123")
    assert r["source_role"] == "PLATFORM_NATIVE"


def test_unknown_ownership(db):
    p = _project(db)
    r = resolve_ownership(db, p, "https://some-random-site.example.com/x")
    assert r["source_role"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Content Quality — 与 fetch_status 分层
# ---------------------------------------------------------------------------

def _doc(clean_text: str, fetch_status: str = "SUCCESS") -> SourceDocument:
    return SourceDocument(
        url="https://example.com/x", domain="example.com", source_type="CITED",
        fetch_status=fetch_status, clean_text=clean_text, clean_text_hash=_content_hash(clean_text),
    )


def test_quality_valid_content(db):
    doc = _doc("抖音跳转链接是指将用户引导到指定页面的功能。本文介绍三种制作方式。第一种是普通分享链接，打开抖音找到目标视频点击分享即可。第二种是合规外链工具，通过第三方平台生成。第三种是深度唤醒链接。")
    q = assess_quality(doc)
    assert q.content_quality_status == "CONTENT_VALID"


def test_quality_css_noise(db):
    doc = _doc("@keyframes fade{0%{opacity:0}}@-webkit-keyframes x{from{left:0}}body{margin:0}.nav{width:100%}" * 20)
    q = assess_quality(doc)
    assert q.content_quality_status == "NOISY"
    assert "CSS" in q.quality_reason


def test_quality_empty_content(db):
    q = assess_quality(_doc(""))
    assert q.content_quality_status == "EMPTY"


def test_quality_fetch_failed_keeps_fetch_status(db):
    doc = _doc("", fetch_status="FETCH_FAILED")
    q = assess_quality(doc)
    assert q.content_quality_status == "FETCH_FAILED"
    # 不改写 fetch_status 本身
    assert doc.fetch_status == "FETCH_FAILED"


def test_content_status_distinguishes_pending_from_unavailable():
    empty_success = _doc("", fetch_status="SUCCESS")
    manual_empty = _doc("", fetch_status="MANUAL_EMPTY")
    failed = _doc("", fetch_status="FETCH_FAILED")

    assert derive_content_status(empty_success)["content_status"] == "CONTENT_PENDING"
    assert derive_content_status(manual_empty)["content_status"] == "CONTENT_UNAVAILABLE"
    assert derive_content_status(failed)["content_status"] == "CONTENT_UNAVAILABLE"


def test_quality_binds_hash_and_version(db):
    doc = _doc("正常正文内容。" * 10)
    q = assess_quality(doc, "content_quality.v1_rule_zh")
    assert q.clean_text_hash == _content_hash(doc.clean_text)
    assert q.extractor_version == "content_quality.v1_rule_zh"

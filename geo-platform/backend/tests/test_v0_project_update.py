from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Competitor, Project
from app.schemas.v0 import ProjectUpdate
from app.api.v0 import update_project


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


def _seed(db):
    project = Project(id=1, organization_id=1, name="P", brand_name="B", website_url="https://b.com")
    db.add(project)
    db.add_all([
        Competitor(project_id=1, name="竞品A", aliases_json='["A"]', website_url="https://a.com"),
        Competitor(project_id=1, name="竞品B", aliases_json='["B"]', website_url="https://b.cn"),
        Competitor(project_id=1, name="竞品C", aliases_json='["C"]', website_url="https://c.com"),
    ])
    db.commit()


def test_update_project_competitors_not_provided_keeps_existing(db):
    """competitors=None（未提供）时不得触碰现有竞品。"""
    _seed(db)
    update_project(1, ProjectUpdate(name="新名字"), db)
    names = {c.name for c in db.query(Competitor).filter(Competitor.project_id == 1).all()}
    assert names == {"竞品A", "竞品B", "竞品C"}


def test_update_project_competitors_empty_name_fails_closed(db):
    """竞品名称为空时 fail-closed，不得删除任何现有竞品。"""
    _seed(db)
    with pytest.raises(HTTPException):
        update_project(1, ProjectUpdate(competitors=[{"name": "", "aliases": [], "website_url": "https://x.com"}]), db)
    db.rollback()
    names = {c.name for c in db.query(Competitor).filter(Competitor.project_id == 1).all()}
    assert names == {"竞品A", "竞品B", "竞品C"}, "失败请求不得破坏现有数据"


def test_update_project_competitors_valid_payload_replaces_all(db):
    """合法 payload 全量替换竞品（textarea 模型语义）。"""
    _seed(db)
    update_project(1, ProjectUpdate(competitors=[{"name": "新竞品", "aliases": ["n"], "website_url": "https://new.com"}]), db)
    names = {c.name for c in db.query(Competitor).filter(Competitor.project_id == 1).all()}
    assert names == {"新竞品"}


def test_update_project_competitors_url_preserves_https_colon(db):
    """URL 含 '://' 不得被截断成 'https'。"""
    _seed(db)
    update_project(1, ProjectUpdate(competitors=[{"name": "X", "aliases": [], "website_url": "https://x.example.com/path?a=1"}]), db)
    comp = db.query(Competitor).filter(Competitor.project_id == 1, Competitor.name == "X").first()
    assert comp.website_url == "https://x.example.com/path?a=1"

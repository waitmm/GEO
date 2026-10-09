"""Explicit optional brand context, never an implicit Product Truth source."""
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BrandContextVersion, Project


def context_view(row: BrandContextVersion) -> dict:
    return {"context_version_id": row.context_version_id, "project_id": row.project_id,
            "version_number": row.version_number, "title": row.title, "content": row.content,
            "source_reference": row.source_reference, "content_hash": row.content_hash,
            "created_at": row.created_at.isoformat(), "verification_state": "USER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"}


def save_context(db: Session, *, project_id: int, expected_version: int, title: str, content: str, source_reference: str) -> BrandContextVersion:
    if not db.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    rows = db.query(BrandContextVersion).filter_by(project_id=project_id).order_by(BrandContextVersion.version_number.desc()).all()
    current = rows[0] if rows else None
    if expected_version != (current.version_number if current else 0):
        raise HTTPException(409, "品牌资料已更新，请读取当前版本后重新提交")
    row = BrandContextVersion(context_version_id=f"brand-context-{uuid4()}", project_id=project_id,
                              version_number=expected_version + 1, title=title.strip(), content=content.strip(),
                              source_reference=source_reference.strip(), content_hash=hashlib.sha256(content.strip().encode()).hexdigest())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "品牌资料发生并发修改")
    return row


def load_context(db: Session, *, project_id: int, context_version_id: str | None) -> dict:
    if not context_version_id:
        return {"mode": "EMPTY", "project_id": project_id, "context_version_id": None, "passages": [], "limitations": ["未选择补充品牌资料"]}
    row = db.query(BrandContextVersion).filter_by(project_id=project_id, context_version_id=context_version_id).one_or_none()
    if not row:
        raise HTTPException(404, "品牌资料版本不存在或不属于当前项目")
    if hashlib.sha256(row.content.encode()).hexdigest() != row.content_hash:
        raise HTTPException(409, "品牌资料内容hash不匹配")
    passages = [{"passage_id": f"{row.context_version_id}:{i}", "text": part, "source_reference": row.source_reference}
                for i, part in enumerate(row.content.split('\n\n'), 1) if part.strip()]
    return {**context_view(row), "mode": "BASIC", "passages": passages,
            "limitations": ["用户提供的资料，不自动成为已核实品牌事实或公开声明资格", "资料更新不覆盖本版本；时效和冲突尚需按用途检查"]}


def select_context(db: Session, *, project_id: int, context_version_id: str | None, query: str) -> dict:
    loaded = load_context(db, project_id=project_id, context_version_id=context_version_id)
    tokens = set(re.findall(r'[a-z0-9]{2,}', query.lower()))
    for word in re.findall(r'[\u4e00-\u9fff]+', query):
        tokens.update(word[i:i + 2] for i in range(max(1, len(word) - 1)))
    ranked = sorted(loaded['passages'], key=lambda p: (-sum(t in p['text'].lower() for t in tokens), p['passage_id']))
    selected, total = [], 0
    for passage in ranked:
        if not any(t in passage['text'].lower() for t in tokens):
            continue
        if total + len(passage['text']) > 6000:
            continue
        selected.append(passage)
        total += len(passage['text'])
        if len(selected) == 5:
            break
    return {key: value for key, value in {**loaded, 'passages': selected,
        'selection_contract': 'brand-context-relevance.v1', 'query': query,
        'selection_status': 'SELECTED' if selected else 'NO_RELEVANT_PASSAGE' if context_version_id else 'EMPTY',
        'allowed_use': 'INTERNAL_CONTEXT_NOT_PUBLIC_FACT'}.items() if key != 'content'}

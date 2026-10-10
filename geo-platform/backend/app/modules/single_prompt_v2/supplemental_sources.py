"""Explicit project-owned public sources, never original answer citations."""
from datetime import datetime
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models import Project, SupplementalSourceAcquisition
from app.modules.optimization.passage_service import fetch_page_playwright
from app.services.serialization import loads
from .delivery_text import digest, text_digest
from .source_preparation import _is_fetchable_public_url, _content_block_reason, _validate_acquisition_receipt


LABELS = {'QUEUED': '等待获取', 'RUNNING': '正在获取', 'READY': '已获取完整正文',
    'PARTIAL': '正文不完整', 'FAILED': '获取失败', 'INTERRUPTED': '获取中断，未自动重试'}


def request_identity(project_id, url):
    return {'contract_version': 'supplemental-public-acquisition.v1', 'project_id': project_id,
        'url': url, 'fetch_authorized': True, 'attempts_per_url_ceiling': 2,
        'automatic_task_retry': 0, 'credentials': 'NONE', 'authority_source': 'EXPLICIT_USER_REQUEST'}


def source_view(row):
    snapshot = loads(row.snapshot_json, {})
    return {'source_id': row.source_id, 'project_id': row.project_id, 'requested_url': row.requested_url,
        'status': row.status, 'status_label': LABELS[row.status], 'snapshot_hash': row.snapshot_hash,
        'request_hash': row.request_hash, 'authorization': loads(row.request_json, {}),
        'title': snapshot.get('title'), 'acquired_at': snapshot.get('acquired_at'),
        'text': snapshot.get('text'), 'failure_detail': row.failure_detail,
        'source_role': 'SUPPLEMENTAL_PUBLIC_SOURCE', 'original_citation_count': 0,
        'created_at': row.created_at.isoformat(), 'attempts_per_url_ceiling': 2}


def queue_source(db, *, project_id, url, idempotency_key, fetch_authorized):
    if not db.get(Project, project_id):
        raise HTTPException(404, '项目不存在')
    if not fetch_authorized or not _is_fetchable_public_url(url):
        raise HTTPException(422, '需要明确授权获取公开 HTTP(S) 页面；不接受本机或内网地址')
    existing = db.query(SupplementalSourceAcquisition).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if existing:
        if existing.requested_url != url:
            raise HTTPException(409, '请求标识已绑定其他来源')
        return existing, False
    inputs = request_identity(project_id, url)
    row = SupplementalSourceAcquisition(source_id=f'supplemental-source-{uuid4()}', project_id=project_id,
        requested_url=url, idempotency_key=idempotency_key,
        request_json=json.dumps(inputs, sort_keys=True), request_hash=digest(inputs))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SupplementalSourceAcquisition).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
        if not existing or existing.requested_url != url:
            raise HTTPException(409, '来源请求发生并发冲突，请刷新后核对')
        return existing, False
    return row, True


def recover_interrupted_sources(db):
    count = db.query(SupplementalSourceAcquisition).filter_by(status='RUNNING').update({
        'status': 'INTERRUPTED', 'failure_detail': '服务中断，获取是否完成未知；保留请求，不自动重复访问。',
        'finished_at': datetime.utcnow()}, synchronize_session=False)
    db.commit()
    return count


def execute_source(source_id, *, session_factory, fetcher=fetch_page_playwright):
    db = session_factory()
    try:
        claimed = db.query(SupplementalSourceAcquisition).filter_by(source_id=source_id, status='QUEUED').update(
            {'status': 'RUNNING', 'started_at': datetime.utcnow()}, synchronize_session=False)
        db.commit()
        if not claimed:
            return
        row = db.query(SupplementalSourceAcquisition).filter_by(source_id=source_id).one()
        try:
            inputs = loads(row.request_json, {})
            if digest(inputs) != row.request_hash or inputs != request_identity(row.project_id, row.requested_url):
                raise ValueError('获取输入或授权契约不匹配，未发起访问')
            values = fetcher([row.requested_url])
            if len(values) != 1:
                raise ValueError('获取结果数量不匹配')
            value = values[0]
            if value.get('url') != row.requested_url:
                raise ValueError('获取结果URL不匹配')
            if value.get('fetch_status') not in {'SUCCESS', 'PARTIAL'}:
                raise ValueError(value.get('failure_reason') or '页面获取失败')
            text = (value.get('clean_text') or '').strip()
            title = value.get('title') or ''
            if not text or _content_block_reason(title, text):
                raise ValueError('页面没有可消费正文，或为验证/拦截页面')
            receipt = value.get('acquisition_receipt') or {}
            acquired = value.get('fetch_time')
            if not isinstance(acquired, datetime) or not receipt:
                raise ValueError('缺少可核验的获取记录')
            _validate_acquisition_receipt(receipt, text_hash=text_digest(text), source_url=row.requested_url,
                acquired_at=acquired, method='AUTO_FETCH')
            snapshot = {'snapshot_id': row.source_id, 'project_id': row.project_id,
                'source_role': 'SUPPLEMENTAL_PUBLIC_SOURCE', 'url': row.requested_url,
                'acquisition_request_hash': row.request_hash,
                'title': title, 'text': text, 'content_hash': text_digest(text),
                'acquired_at': acquired.isoformat(), 'acquisition_method': 'AUTO_FETCH',
                'coverage_scope': 'FULL_PAGE' if value['fetch_status'] == 'SUCCESS' else 'PARTIAL',
                'acquisition_receipt': receipt}
            row.snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            row.snapshot_hash = digest(snapshot)
            row.status = 'READY' if value['fetch_status'] == 'SUCCESS' else 'PARTIAL'
            row.failure_detail = value.get('failure_reason') or ''
        except Exception as exc:
            row.status = 'FAILED'
            row.failure_detail = str(exc)[:1000]
        row.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def frozen_sources(db, *, project_id, source_ids):
    if len(source_ids) > 5 or len(set(source_ids)) != len(source_ids):
        raise HTTPException(422, '每次明确选择最多5份不同补充资料')
    result = []
    for identity in sorted(source_ids):
        row = db.query(SupplementalSourceAcquisition).filter_by(project_id=project_id, source_id=identity).one_or_none()
        if not row or row.status not in {'READY', 'PARTIAL'}:
            raise HTTPException(409, '补充资料不存在、不属于当前项目或尚无可固定的正文')
        snapshot = loads(row.snapshot_json, {})
        if (digest(snapshot) != row.snapshot_hash or text_digest(snapshot['text']) != snapshot['content_hash']
                or snapshot.get('snapshot_id') != row.source_id or snapshot.get('project_id') != project_id
                or snapshot.get('source_role') != 'SUPPLEMENTAL_PUBLIC_SOURCE'
                or digest(loads(row.request_json, {})) != row.request_hash
                or snapshot.get('acquisition_request_hash') != row.request_hash):
            raise HTTPException(409, '补充资料内容hash不匹配')
        result.append(snapshot)
    return result

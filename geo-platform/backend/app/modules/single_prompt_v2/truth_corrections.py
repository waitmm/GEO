"""Explicit human fact corrections, separate from machine results and reviews."""
from __future__ import annotations

import copy
from datetime import datetime
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models import (SinglePromptTruthCorrection, TargetBrandCapabilityTruth,
    SinglePromptDiagnosisResult, SinglePromptDiagnosisExecution, SinglePromptStrategyResult, SinglePromptOptimizationTask)
from app.services.serialization import loads
from .delivery_text import digest


def project_truths(db, project_id: int) -> list[dict]:
    from .diagnosis import _snapshot_truth
    current = {row.id: _snapshot_truth(row) for row in db.query(TargetBrandCapabilityTruth)
        .filter_by(project_id=project_id).order_by(TargetBrandCapabilityTruth.id)}
    versions = {truth_id: 0 for truth_id in current}
    for correction in db.query(SinglePromptTruthCorrection).filter_by(project_id=project_id).order_by(
            SinglePromptTruthCorrection.truth_id, SinglePromptTruthCorrection.version_number):
        base, output = _validated(correction)
        if (base != current.get(correction.truth_id) or digest(base) != correction.base_hash
                or digest(output) != correction.output_hash or output.get('truth_id') != correction.truth_id
                or correction.version_number != versions.get(correction.truth_id, -1) + 1
                or output.get('correction_id') != correction.correction_id):
            raise HTTPException(409, '事实纠错历史身份或 hash 不一致，不能消费')
        current[correction.truth_id] = output
        versions[correction.truth_id] = correction.version_number
    return list(current.values())


def _validated(row):
    base, output = loads(row.base_json, {}), loads(row.output_json, {})
    request, impact = loads(row.request_json, {}), loads(row.impact_json, {})
    required = {'capability_label', 'product_truth_status', 'source_reference', 'reason', 'prompt_id',
        'expected_set_hash', 'preview_hash', 'parent_task_id', 'actor', 'truth_id', 'project_id', 'base_hash'}
    if (not isinstance(request, dict) or not required.issubset(request)
            or not isinstance(base, dict) or not isinstance(output, dict) or not isinstance(impact, dict)):
        raise HTTPException(409, '事实纠错审计结构不完整，不能消费')
    replacement = _replacement(base, **{k: request[k] for k in (
        'capability_label', 'product_truth_status', 'source_reference', 'reason')})
    preview = {'project_id': row.project_id, 'prompt_id': request['prompt_id'], 'truth_id': row.truth_id,
        'base': base, 'replacement': replacement, 'expected_set_hash': request['expected_set_hash'], 'impact': impact}
    expected_output = {**replacement, 'correction_id': row.correction_id, 'truth_correction_version': row.version_number,
        'truth_source': 'MANUAL_CONFIRMED', 'reviewed_by': row.actor, 'reviewed_at': row.created_at.isoformat(),
        'row_updated_at': row.created_at.isoformat()}
    if (digest(base) != row.base_hash or digest(output) != row.output_hash or digest(request) != row.request_hash
            or digest(preview) != request.get('preview_hash') or output != expected_output
            or request.get('actor') != row.actor or request.get('truth_id') != row.truth_id
            or request.get('project_id') != row.project_id or request.get('base_hash') != row.base_hash
            or request.get('reason', '').strip() != row.reason
            or request.get('parent_task_id') != impact.get('parent_task_id')):
        raise HTTPException(409, '事实纠错内容或预览 hash 不一致')
    return base, output


def correction_view(row):
    base, output = _validated(row)
    return {'correction_id': row.correction_id, 'version_number': row.version_number,
        'base': base, 'base_hash': row.base_hash, 'output': output, 'output_hash': row.output_hash,
        'impact': loads(row.impact_json, {}), 'actor': row.actor, 'created_at': row.created_at.isoformat()}


def task_truths(db, *, parent_task_id, project_id, prompt_id):
    from .automatic_delivery import require_task
    parent = require_task(db, parent_task_id, project_id, prompt_id)
    current = project_truths(db, project_id)
    fixed = loads(parent.input_json, {})
    original = fixed.get('truth_snapshot') or []
    index = {t['truth_id']: t for t in current}
    return {'task_id': parent.task_id, 'input_hash': parent.input_hash, 'current_set_hash': digest(current),
        'truths': [{'frozen': t, 'current': index.get(t['truth_id']), 'base_hash': digest(index.get(t['truth_id'])),
            'can_correct': index.get(t['truth_id']) == t and not fixed.get('delivery_revision')} for t in original],
        'history': [correction_view(row) for row in db.query(SinglePromptTruthCorrection).filter(
            SinglePromptTruthCorrection.project_id == project_id,
            SinglePromptTruthCorrection.truth_id.in_([t['truth_id'] for t in original]))
            .order_by(SinglePromptTruthCorrection.created_at)]}


def _replacement(base, *, capability_label, product_truth_status, source_reference, reason):
    from .diagnosis import _truth_statement_eligibility, _truth_statement_issues
    label, source, reason = capability_label.strip(), source_reference.strip(), reason.strip()
    key = re.sub(r'[\s\W_]+', '', label.lower())
    if (not key or len(label) > 160 or _truth_statement_issues(label) or not reason or len(reason) > 2000
            or len(source) > 2000 or product_truth_status not in {'SUPPORTED', 'PARTIALLY_SUPPORTED', 'NOT_SUPPORTED', 'UNKNOWN'}):
        raise HTTPException(422, '请提交单项完整事实、明确状态及纠错依据')
    if product_truth_status in {'SUPPORTED', 'PARTIALLY_SUPPORTED'} and not source:
        raise HTTPException(422, '正向或部分支持的事实需要明确出处和适用条件')
    output = {**copy.deepcopy(base), 'capability_key': key, 'capability_label': label,
        'product_truth_status': product_truth_status, 'source_reference': source, 'note': reason}
    output['statement_eligibility'] = _truth_statement_eligibility(capability_label=label,
        product_truth_status=product_truth_status, source_reference=source)
    return output


def _task_impact(db, parent, base, replacement) -> dict:
    from .diagnosis import _diagnose_truths
    fixed, progress = loads(parent.input_json, {}), loads(parent.progress_json, {})
    old_truths = fixed.get('truth_snapshot') or []
    old = next((t for t in old_truths if t['truth_id'] == base['truth_id']), None)
    if old != base:
        raise HTTPException(409, '所选任务使用的事实不是当前版本；旧任务保留，请选择准确的事实版本任务')
    objects = progress.get('objects') or {}
    execution = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=objects.get('diagnosis_id'),
        analysis_id=parent.analysis_id, context_id=parent.context_id, project_id=parent.project_id,
        prompt_id=parent.prompt_id).one_or_none()
    result = db.query(SinglePromptDiagnosisResult).filter_by(diagnosis_id=objects.get('diagnosis_id'),
        result_version=objects.get('answer_result_version'), output_hash=objects.get('answer_result_hash')).one_or_none()
    if not execution or not result or digest(loads(result.output_json, {})) != result.output_hash:
        raise HTTPException(409, '所选任务尚未形成可核对的回答结果，不能预览局部影响')
    answer = loads(result.output_json, {}).get('answer_diagnosis') or {}
    brand = fixed['brand']
    new_truths = [replacement if t['truth_id'] == base['truth_id'] else t for t in old_truths]
    before, after = [_diagnose_truths(answer, truths,
        target_brand={'brand_name': brand['brand_name'], 'aliases': brand.get('brand_aliases') or []})
        for truths in (old_truths, new_truths)]
    affected = set()
    for group in ('relationships', 'reason_capability_coverage', 'external_capability_signals'):
        left, right = {}, {}
        for rows, index in ((before[group], left), (after[group], right)):
            for row in rows:
                index.setdefault(row['reason_id'], []).append(row)
        affected.update(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))
    strategy = db.query(SinglePromptStrategyResult).filter_by(strategy_id=objects.get('strategy_id'),
        result_version=objects.get('strategy_result_version'), output_hash=objects.get('strategy_result_hash')).one_or_none()
    if not strategy or digest(loads(strategy.output_json, {})) != strategy.output_hash:
        raise HTTPException(409, '所选任务尚未形成可核对的策略版本，不能预览局部影响')
    directions = loads(strategy.output_json, {}).get('directions') or []
    related = [d['strategy_id'] for d in directions if str(base['truth_id']) in {str(t) for t in d.get('truth_ids', [])}
        or affected.intersection(d.get('reason_ids') or [])]
    return {'parent_task_id': parent.task_id, 'parent_input_hash': parent.input_hash,
        'analysis_id': parent.analysis_id, 'context_id': parent.context_id, 'run_ids': fixed['run_ids'],
        'answer_result_version': result.result_version, 'answer_result_hash': result.output_hash,
        'strategy_result_version': strategy.result_version, 'strategy_result_hash': strategy.output_hash,
        'affected_reason_ids': sorted(affected), 'affected_direction_ids': sorted(related),
        'unaffected_direction_ids': sorted(d['strategy_id'] for d in directions if d['strategy_id'] not in related),
        'source_refetches': 0, 'external_calls': 0, 'old_results_modified': False}


def preview_correction(db, *, parent_task_id, project_id, prompt_id, truth_id, base_hash,
                       expected_set_hash, capability_label, product_truth_status, source_reference, reason):
    from .automatic_delivery import require_task
    parent = require_task(db, parent_task_id, project_id, prompt_id)
    if loads(parent.input_json, {}).get('delivery_revision'):
        raise HTTPException(409, '事实纠错请从原分析任务进入，不使用仅文本修改任务代替分析身份')
    truths = project_truths(db, project_id)
    base = next((t for t in truths if t['truth_id'] == truth_id), None)
    if not base:
        raise HTTPException(404, '事实不存在或不属于当前项目')
    if digest(truths) != expected_set_hash or digest(base) != base_hash:
        raise HTTPException(409, '事实版本已变化，请重新读取后提交')
    replacement = _replacement(base, capability_label=capability_label, product_truth_status=product_truth_status,
        source_reference=source_reference, reason=reason)
    if any(t['truth_id'] != truth_id and t['capability_key'] == replacement['capability_key'] for t in truths):
        raise HTTPException(409, '同一能力已有另一条事实，请核对对象')
    if all(base.get(k) == replacement.get(k) for k in ('capability_label', 'product_truth_status', 'source_reference', 'note')):
        raise HTTPException(422, '事实没有变化，无需建立纠错版本')
    payload = {'project_id': project_id, 'prompt_id': prompt_id, 'truth_id': truth_id,
        'base': base, 'replacement': replacement, 'expected_set_hash': expected_set_hash,
        'impact': _task_impact(db, parent, base, replacement)}
    return {**payload, 'preview_hash': digest(payload)}


def correct_truth(db, *, actor, idempotency_key, preview_hash, **values):
    from .automatic_delivery import encode
    if not actor.strip():
        raise HTTPException(422, '纠错必须记录实际操作者')
    request = {**values, 'preview_hash': preview_hash, 'actor': actor}
    fingerprint = digest(request)
    existing = db.query(SinglePromptTruthCorrection).filter_by(project_id=values['project_id'], idempotency_key=idempotency_key).one_or_none()
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, '幂等键已绑定其他纠错')
        return existing, False
    preview = preview_correction(db, **values)
    if preview['preview_hash'] != preview_hash:
        raise HTTPException(409, '影响预览已变化，请重新核对后提交')
    correction_id = f'truth-correction-{uuid4()}'
    version = int(preview['base'].get('truth_correction_version') or 0) + 1
    now = datetime.utcnow()
    output = {**preview['replacement'], 'correction_id': correction_id, 'truth_correction_version': version,
        'truth_source': 'MANUAL_CONFIRMED', 'reviewed_by': actor, 'reviewed_at': now.isoformat(), 'row_updated_at': now.isoformat()}
    row = SinglePromptTruthCorrection(correction_id=correction_id, project_id=values['project_id'], truth_id=values['truth_id'],
        version_number=version, idempotency_key=idempotency_key, request_hash=fingerprint, request_json=encode(request),
        base_hash=digest(preview['base']), base_json=encode(preview['base']), output_hash=digest(output), output_json=encode(output),
        impact_json=encode(preview['impact']), actor=actor, reason=values['reason'].strip(), created_at=now)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, '事实纠错发生并发修改，请重新读取') from error
    return row, True


def _reprojection_input(db, *, parent_task_id, project_id, prompt_id, correction_id):
    from .automatic_delivery import require_task, computation_contracts
    from .source_preparation import validate_completion_for_evidence
    parent = require_task(db, parent_task_id, project_id, prompt_id)
    correction = db.query(SinglePromptTruthCorrection).filter_by(correction_id=correction_id, project_id=project_id).one_or_none()
    if not correction:
        raise HTTPException(404, '纠错版本不存在或不属于当前项目')
    _, updated = _validated(correction)
    impact = loads(correction.impact_json, {})
    if impact['parent_task_id'] != parent_task_id or impact['parent_input_hash'] != parent.input_hash:
        raise HTTPException(409, '纠错影响范围与所选任务不一致')
    fixed = loads(parent.input_json, {})
    if fixed.get('computation_contracts') != computation_contracts():
        raise HTTPException(409, '原任务计算契约已变化，不能扩大局部重算范围')
    objects = loads(parent.progress_json, {}).get('objects') or {}
    source_keys = ('citation_manifest_id', 'citation_manifest_hash', 'completion_manifest_id', 'completion_manifest_hash')
    if not all(objects.get(k) for k in source_keys):
        raise HTTPException(409, '原任务缺少固定来源版本，不能局部重算')
    source = {k: objects[k] for k in source_keys}
    validate_completion_for_evidence(db, analysis_id=parent.analysis_id, context_id=parent.context_id, **source, allow_partial=True)
    if _task_impact(db, parent, loads(correction.base_json, {}),
            _replacement(loads(correction.base_json, {}), **{k: loads(correction.request_json, {})[k]
                for k in ('capability_label', 'product_truth_status', 'source_reference', 'reason')})) != impact:
        raise HTTPException(409, '原任务结果与已保存影响范围不一致')
    fixed['truth_snapshot'] = [updated if t['truth_id'] == correction.truth_id else t for t in fixed['truth_snapshot']]
    fixed['source_fetch_authorized'] = False
    fixed['source_input'] = source
    fixed['truth_correction'] = {'correction_id': correction_id, 'output_hash': correction.output_hash,
        'parent_task_id': parent_task_id, 'parent_input_hash': parent.input_hash, 'impact': impact}
    return parent, correction, fixed


def validate_reprojection(db, task):
    fixed = loads(task.input_json, {})
    ref = fixed.get('truth_correction') or {}
    if not ref.get('parent_task_id') or not ref.get('correction_id'):
        raise HTTPException(409, '局部重算缺少纠错身份')
    _, _, expected = _reprojection_input(db, parent_task_id=ref['parent_task_id'], project_id=task.project_id,
        prompt_id=task.prompt_id, correction_id=ref['correction_id'])
    if fixed != expected or digest(expected) != task.input_hash:
        raise HTTPException(409, '局部重算输入与原任务、纠错或影响范围不一致')
    return ref


def affected_directions(directions, correction):
    impact = correction['impact']
    reasons = set(impact['affected_reason_ids'])
    old_ids = set(impact['affected_direction_ids'])
    # Only consume the existing qualifier's selection. When the entire old
    # selection was affected, its replacement may be another qualified reason.
    return [d for d in directions if d['strategy_id'] in old_ids or reasons.intersection(d.get('reason_ids') or [])
        or (old_ids and not impact['unaffected_direction_ids'])]


def create_reprojection_task(db, *, parent_task_id, project_id, prompt_id, correction_id, idempotency_key):
    from .automatic_delivery import encode
    parent, correction, fixed = _reprojection_input(db, parent_task_id=parent_task_id, project_id=project_id,
        prompt_id=prompt_id, correction_id=correction_id)
    impact = fixed['truth_correction']['impact']
    updated = loads(correction.output_json, {})
    fingerprint = digest(fixed)
    same_key = db.query(SinglePromptOptimizationTask).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if same_key and same_key.input_hash != fingerprint:
        raise HTTPException(409, '幂等键已绑定其他重算输入')
    existing = same_key or db.query(SinglePromptOptimizationTask).filter_by(analysis_id=parent.analysis_id, input_hash=fingerprint).one_or_none()
    if existing:
        return existing, False
    current = next((t for t in project_truths(db, project_id) if t['truth_id'] == correction.truth_id), None)
    if current != updated:
        raise HTTPException(409, '事实已产生后续版本，请先核对，不静默覆盖新纠错')
    if not impact['affected_reason_ids'] and not impact['affected_direction_ids']:
        raise HTTPException(409, '本次纠错未影响所选任务的理由或行动，无需重算；旧稿保持')
    row = SinglePromptOptimizationTask(task_id=f'optimize-{uuid4()}', project_id=project_id, prompt_id=prompt_id,
        analysis_id=parent.analysis_id, context_id=parent.context_id, input_json=encode(fixed), input_hash=fingerprint,
        idempotency_key=idempotency_key,
        authorization_json=encode({'policy': 'CACHE_ONLY', 'max_requests': 0, 'max_tokens': 0, 'max_cost_cny': 0}),
        progress_json=encode({'stage': 'SOURCES', 'objects': {}, 'requests': [], 'limitations': []}))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SinglePromptOptimizationTask).filter_by(analysis_id=parent.analysis_id, input_hash=fingerprint).one_or_none()
        if existing:
            return existing, False
        raise
    return row, True

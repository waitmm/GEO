"""Monitor and Validate share frozen inputs and the existing V2 metric calculator."""
from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (SinglePromptAnalysisContext, SinglePromptDiagnosisExecution,
                        SinglePromptDiagnosisResult, SinglePromptObservationComparison)
from app.services.serialization import loads
from app.services.url_identity import canonicalize_url, CANONICALIZATION_VERSION
from .retest import _hash, _canonical_json, measure_frozen_runs, _measurement_contract


CONTRACT = "single_prompt_observation.v1"


def fixed_scope(db: Session, project_id: int, prompt_id: int, ref: dict) -> dict:
    context = db.query(SinglePromptAnalysisContext).filter_by(context_id=ref['context_id'], project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not context:
        raise HTTPException(404, "分析范围不存在或不属于当前项目/问题")
    raw = loads(context.raw_output_json, {})
    if context.raw_output_hash != ref['raw_output_hash'] or _hash(raw) != ref['raw_output_hash']:
        raise HTTPException(409, "原始范围hash不匹配")
    semantic = None
    semantic_contract = None
    version = ref.get('answer_result_version')
    if version:
        result = db.query(SinglePromptDiagnosisResult).filter_by(result_version=version, output_hash=ref.get('answer_result_hash')).one_or_none()
        if not result:
            raise HTTPException(409, "回答结果版本/hash不匹配")
        execution = db.query(SinglePromptDiagnosisExecution).filter_by(diagnosis_id=result.diagnosis_id).one()
        if execution.context_id != context.context_id or execution.project_id != project_id:
            raise HTTPException(409, "回答结果不属于指定Context")
        output = loads(result.output_json, {})
        if _hash(output) != result.output_hash:
            raise HTTPException(409, "回答结果内容hash不匹配")
        semantic = output.get('answer_diagnosis')
        config = loads(execution.contract_config_json, {})
        semantic_contract = {key: value for key, value in config.items() if 'answer' in key and 'version' in key}
    return {'ref': dict(ref), 'raw': raw, 'semantics': semantic, 'semantic_contract': semantic_contract}


def measure_scope(scope: dict, identity: dict, target_url: str = '') -> dict:
    if not str(identity.get('canonical_brand_name') or '').strip():
        raise HTTPException(422, "必须明确测量的品牌身份")
    frozen_identity = {**identity, 'identity_snapshot_hash': _hash(identity)}
    output = measure_frozen_runs(raw=scope['raw'], identity=frozen_identity,
                                 answer_diagnosis=scope['semantics'], published_url=target_url)
    output['input'] = scope['ref']
    output['failed_run_ids'] = [r['run_id'] for r in scope['raw'].get('runs', []) if r.get('status') not in {'success', 'partial_success'} or not str(r.get('answer_text') or '').strip()]
    output['runs'] = scope['raw'].get('runs', [])
    output['limitations'] = ['语义未计算/未准入不等于没有推荐', '引用不证明生成因果；仅报告观测']
    return output


def _urls(raw: dict) -> tuple[dict, bool]:
    urls = {}
    runs = raw.get('runs', [])
    complete = bool(runs)
    for run in runs:
        if run.get('status') not in {'success', 'partial_success'} or not str(run.get('answer_text') or '').strip():
            complete = False
            continue
        complete = complete and run.get('reference_complete') is True
        for ref in run.get('references', []):
            original = str(ref.get('url') or ref.get('canonical_url') or '')
            canonical = canonicalize_url(original)
            if not canonical:
                complete = False
                continue
            urls.setdefault(canonical, []).append({'run_id': run['run_id'], 'raw_url': original, 'title': ref.get('title', '')})
    return urls, complete


def compare_scopes(before: dict, after: dict, identity: dict, target_url: str = '') -> dict:
    left = measure_scope(before, identity, target_url)
    right = measure_scope(after, identity, target_url)
    conflicts, unknown = [], []
    conditions = {}
    for name, scope in [('baseline', before), ('comparison', after)]:
        rows = scope['raw'].get('runs', [])
        conditions[name] = {}
        for field in ['platform', 'source_type', 'adapter', 'original_query', 'collection_mode']:
            observed = [(r.get('observed_conditions') or {}).get(field, {}).get('value') for r in rows]
            values = sorted({str(value) for value in observed if value})
            conditions[name][field] = values
            if not rows or any(not value for value in observed):
                unknown.append(f'{name}:{field}:UNKNOWN')
        for field in ['model_version', 'sampling_mode', 'search_mode', 'network_region', 'language', 'collector_version']:
            values = sorted({str((r.get('environment') or {}).get(field)) for r in rows if (r.get('environment') or {}).get(field)})
            conditions[name][field] = values
            if not rows or any((r.get('environment') or {}).get(field) in (None, '', 'UNKNOWN', 'UNAVAILABLE') for r in rows):
                unknown.append(f'{name}:{field}:UNVERIFIED')
        if any((r.get('environment') or {}).get('session_verification', {}).get('status') != 'VERIFIED' for r in rows):
            unknown.append(f'{name}:INDEPENDENT_SESSION_UNVERIFIED')
    for field in conditions['baseline']:
        l, r = conditions['baseline'][field], conditions['comparison'][field]
        if l and r and l != r:
            conflicts.append(f'{field}:CONFLICT')
        if len(l) > 1 or len(r) > 1:
            conflicts.append(f'{field}:MIXED_CONDITIONS')
    metrics = {}
    for key, l in left['metrics'].items():
        r = right['metrics'][key]
        semantic_conflict = key in {'brand_option_rate', 'brand_recommendation_rate'} and before.get('semantic_contract') != after.get('semantic_contract')
        critical_unknown = any(':UNKNOWN' in value for value in unknown)
        comparable = not conflicts and not semantic_conflict and not critical_unknown and l['value'] is not None and r['value'] is not None
        metrics[key] = {'baseline': l, 'comparison': r,
                        'delta_percentage_points': round((r['value'] - l['value']) * 100, 4) if comparable else None,
                        'comparability': 'NOT_COMPARABLE' if conflicts or semantic_conflict or critical_unknown else 'DESCRIPTIVE_WITH_LIMITATIONS' if unknown else 'RECORDED_CONDITIONS_MATCH',
                        'semantic_contract_matches': not semantic_conflict,
                        'status': 'OBSERVABLE' if comparable else 'UNAVAILABLE_OR_NOT_COMPARABLE'}
    old, old_complete = _urls(before['raw'])
    new, new_complete = _urls(after['raw'])
    return {'contract_version': CONTRACT, 'measurement_contract': _measurement_contract(),
            'baseline': left, 'comparison': right, 'metrics': metrics, 'conditions': conditions,
            'conflicts': sorted(set(conflicts)), 'limitations': sorted(set(unknown)) + ['不是因果效果结论', '首次/新增仅相对于本次选定范围，不是页面收录时间'],
            'citation_changes': {'identity_version': CANONICALIZATION_VERSION,
                'newly_observed': [{'url': u, 'references': new[u]} for u in sorted(new.keys() - old.keys())] if old_complete else [],
                'continuing': [{'url': u, 'baseline': old[u], 'comparison': new[u]} for u in sorted(new.keys() & old.keys())],
                'not_observed_again': [{'url': u, 'references': old[u]} for u in sorted(old.keys() - new.keys())] if new_complete else [],
                'baseline_complete': old_complete, 'comparison_complete': new_complete,
                'unclassified_baseline': sorted(old.keys() - new.keys()) if not new_complete else [],
                'unclassified_comparison': sorted(new.keys() - old.keys()) if not old_complete else []},
            'publication_required': False, 'causal_conclusion': False}


def create_observation_comparison(db: Session, *, project_id: int, prompt_id: int, baseline: dict, comparison: dict, identity: dict, target_url: str = '') -> tuple[SinglePromptObservationComparison, bool]:
    before, after = (fixed_scope(db, project_id, prompt_id, ref) for ref in (baseline, comparison))
    left_ids = {r['run_id'] for r in before['raw'].get('runs', [])}
    right_ids = {r['run_id'] for r in after['raw'].get('runs', [])}
    if not left_ids or not right_ids or left_ids & right_ids:
        raise HTTPException(422, "比较范围须非空且不重叠，不能把同一回答充当新样本")
    snapshot = {'project_id': project_id, 'prompt_id': prompt_id, 'baseline': baseline, 'comparison': comparison,
                'identity': identity, 'target_url': target_url, 'contract': CONTRACT, 'measurement_contract': _measurement_contract(),
                'baseline_semantic_contract': before.get('semantic_contract'), 'comparison_semantic_contract': after.get('semantic_contract')}
    input_hash = _hash(snapshot)
    existing = db.query(SinglePromptObservationComparison).filter_by(project_id=project_id, prompt_id=prompt_id, input_hash=input_hash).one_or_none()
    if existing:
        return existing, False
    output = compare_scopes(before, after, identity, target_url)
    result = SinglePromptObservationComparison(result_version=f'observation-v1:{uuid4()}', project_id=project_id,
        prompt_id=prompt_id, input_hash=input_hash, input_snapshot_json=_canonical_json(snapshot),
        output_json=_canonical_json(output), output_hash=_hash(output))
    db.add(result)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SinglePromptObservationComparison).filter_by(project_id=project_id, prompt_id=prompt_id, input_hash=input_hash).one_or_none()
        if existing:
            return existing, False
        raise
    return result, True

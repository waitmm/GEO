"""Monitor and Validate share frozen inputs and the existing V2 metric calculator."""
from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (SinglePromptAnalysisContext, SinglePromptDiagnosisExecution,
                        SinglePromptDiagnosisResult, SinglePromptObservationComparison)
from app.services.serialization import loads
from app.services.url_identity import canonicalize_url, CANONICALIZATION_VERSION
from .retest import _hash, _canonical_json, measure_frozen_runs, _measurement_contract


CONTRACT = "single_prompt_observation.v2_admitted_metrics"


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
    days = {}
    unknown_dates = []
    for run in scope['raw'].get('runs') or []:
        try:
            value = run.get('finished_at') or run.get('started_at')
            captured = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            day = captured.replace(tzinfo=timezone.utc).date().isoformat() if captured.tzinfo is None else captured.astimezone(timezone.utc).date().isoformat()
        except (ValueError, TypeError):
            unknown_dates.append(run['run_id'])
            continue
        days.setdefault(day, []).append(run)
    output['trend'] = {'timezone': 'UTC', 'unknown_date_run_ids': unknown_dates, 'points': [
        {'date': day, 'run_ids': [r['run_id'] for r in rows],
         'metrics': measure_frozen_runs(raw={**scope['raw'], 'runs': rows}, identity=frozen_identity,
             answer_diagnosis=scope['semantics'], published_url=target_url)['metrics']}
        for day, rows in sorted(days.items())]}
    return output


def aggregate_prompt_metrics(measurements: list[dict]) -> dict:
    keys = sorted({key for row in measurements for key in row['metrics']})
    result = {}
    for key in keys:
        admitted = [(row['prompt']['id'], row['metrics'][key]) for row in measurements
            if row['metrics'].get(key, {}).get('value') is not None]
        numerator = sum(m['hit_count'] for _, m in admitted)
        denominator = sum(m['evaluable_count'] for _, m in admitted)
        result[key] = {'prompt_macro_average': round(sum(m['hit_count'] / m['evaluable_count'] for _, m in admitted) / len(admitted), 6) if admitted else None,
            'run_weighted_average': round(numerator / denominator, 6) if denominator else None,
            'participating_prompt_ids': [p for p, _ in admitted], 'participating_prompt_count': len(admitted),
            'total_prompt_count': len(measurements), 'hit_count': numerator, 'evaluable_count': denominator,
            'planned_count': sum(row['metrics'].get(key, {}).get('planned_count', 0) for row in measurements)}
    return result


def opportunity_hint(intent: str, metrics: dict) -> dict:
    """A navigation hint, not a Strategy verdict or a calibrated opportunity score."""
    mention = metrics['brand_mention_rate']
    option = metrics['brand_option_rate']
    if not mention['evaluable_count']:
        state, label, reason = 'NEEDS_DATA', '先积累样本', '当前没有有效回答，不能判断品牌缺席。'
    elif intent not in {'supplier_recommendation', 'category_awareness', 'usage_instruction'}:
        state, label, reason = 'UNKNOWN_INTENT', '保留问题目标未知', '本范围没有明确的问题意图，不能按当前配置补写旧范围的优化目标。'
    elif intent != 'supplier_recommendation':
        state, label, reason = 'OBSERVE', '观察内容需求', '概念或操作类问题不以推荐品牌为默认目标；可分析解释、步骤和条件是否充分。'
    elif not option['evaluable_count']:
        state, label, reason = 'NEEDS_ANALYSIS', '先分析候选行为', '已有有效回答，但候选判断尚未计算；不能把正文提及当作推荐。'
    elif option['hit_count'] == 0:
        state, label, reason = 'INVESTIGATE', '建议分析选择缺口', '已评估范围未将品牌列为选项；需要结合理由与来源判断具体行动，不能直接归因。'
    else:
        state, label, reason = 'OBSERVE', '继续观察', '已评估范围中品牌出现为选项，继续检查覆盖和变化，不自动判定优化成功。'
    return {'state': state, 'label': label, 'reason': reason, 'intent_type': intent,
        'evaluated_run_ids': option['evaluable_run_ids'] if intent == 'supplier_recommendation' else mention['evaluable_run_ids'],
        'limitation': '仅针对当前选定范围的导航建议，不是策略结论；主动分析入口始终保留。'}


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

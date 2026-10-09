import copy
import hashlib
import json

import pytest
from fastapi import HTTPException
from release_test_client import TestClient
from sqlalchemy import text

from app.core.release_database import get_release_db
from app.models import BrowserMonitorRun, Prompt, SinglePromptAnalysisContext, SinglePromptObservationComparison, SinglePromptPublicationRecord
from app.modules.single_prompt_v2.context_provider import load_context, save_context, select_context
from app.modules.single_prompt_v2.observation import aggregate_prompt_metrics, compare_scopes, create_observation_comparison, measure_scope, opportunity_hint
from app.modules.single_prompt_v2.service import create_analysis, claim_analysis, finalize_analysis
from app.release_main import create_release_app
from test_release_first_slice import _migrated_session, _seed_frozen_analysis
from app.services.url_identity import canonicalize_url


IDENTITY = {'canonical_brand_name': 'Target', 'accepted_aliases': [], 'official_domains': [], 'official_urls': []}


def test_ambiguous_alias_requires_admitted_grounded_entity_not_literal_occurrence():
    identity = {**IDENTITY, 'accepted_aliases': ['过滤']}
    current = scope(1, answer='使用前请先过滤水中的颗粒。')
    current['raw']['runs'].append(scope(2, answer='普通维护建议。')['raw']['runs'][0])
    measured = measure_scope(current, identity)['metrics']['brand_mention_rate']
    assert measured['hit_count'] == 0 and measured['evaluable_run_ids'] == [2]
    assert measured['value'] == 0 and measured['status'] == 'PARTIAL'
    assert measured['unevaluated'] == [{'run_id': 1, 'reason': 'BRAND_ALIAS_AMBIGUOUS'}]
    current['semantics'] = {'answer_jobs': [{'answer_hash': hashlib.sha256(current['raw']['runs'][0]['answer_text'].encode()).hexdigest(),
        'status': 'FAILED_SCHEMA', 'run_ids': [1]}], 'events': [
            {'run_id': 1, 'entity_text': '过滤', 'fact_consumption_eligible': True, 'effective_speech_act': 'MENTION'}]}
    assert measure_scope(current, identity)['metrics']['brand_mention_rate']['hit_count'] == 0
    current['raw']['runs'][0]['answer_text'] = '过滤工具可用于资料整理。'
    current['semantics']['answer_jobs'][0].update(status='DONE', answer_hash=hashlib.sha256('过滤工具可用于资料整理。'.encode()).hexdigest())
    measured = measure_scope(current, identity)['metrics']['brand_mention_rate']
    assert measured['hit_run_ids'] == [1] and measured['evaluable_count'] == 2
    current['semantics']['events'][0]['fact_consumption_eligible'] = False
    assert measure_scope(current, identity)['metrics']['brand_mention_rate']['unevaluated_count'] == 1


def test_canonical_mention_remains_observable_without_semantics_and_alias_unknown_is_not_zero():
    identity = {**IDENTITY, 'accepted_aliases': ['普通']}
    measured = measure_scope(scope(1, answer='普通维护建议'), identity)['metrics']['brand_mention_rate']
    assert measured['value'] is None and measured['evaluable_count'] == 0
    measured = measure_scope(scope(2, answer='Target 的普通维护建议'), identity)['metrics']['brand_mention_rate']
    assert measured['value'] == 1 and measured['evaluable_run_ids'] == [2]


def test_opportunity_uses_intent_and_does_not_turn_unknown_into_brand_gap():
    sample = scope(1, answer='General explanation with no brand')
    metrics = measure_scope(sample, IDENTITY)['metrics']
    assert opportunity_hint('supplier_recommendation', metrics)['state'] == 'NEEDS_ANALYSIS'
    assert opportunity_hint('category_awareness', metrics)['state'] == 'OBSERVE'
    sample['semantics'] = {'answer_jobs': [{'answer_hash': hashlib.sha256(sample['raw']['runs'][0]['answer_text'].encode()).hexdigest(),
        'status': 'DONE_ZERO_EVENTS'}], 'events': []}
    metrics = measure_scope(sample, IDENTITY)['metrics']
    assert opportunity_hint('supplier_recommendation', metrics)['state'] == 'INVESTIGATE'
    assert opportunity_hint('usage_instruction', metrics)['state'] == 'OBSERVE'
    failed = measure_scope(scope(1, failed=True), IDENTITY)['metrics']
    assert opportunity_hint('supplier_recommendation', failed)['state'] == 'NEEDS_DATA'


def test_nine_run_metrics_use_only_evaluated_denominator_and_recommendation_is_option():
    current = scope(1)
    current['raw']['runs'] = [scope(i, answer=f'Sample {i}: Target is mentioned')['raw']['runs'][0] for i in range(1, 10)]
    current['semantics'] = {'answer_jobs': [
        {'answer_hash': hashlib.sha256(r['answer_text'].encode()).hexdigest(), 'status': 'DONE'}
        for r in current['raw']['runs'][:3]], 'events': [
            {'run_id': 1, 'entity_text': 'Target', 'fact_consumption_eligible': True, 'effective_speech_act': 'RECOMMEND'},
        ]}
    result = measure_scope(current, IDENTITY)
    for key in ['brand_recommendation_rate', 'brand_option_rate']:
        metric = result['metrics'][key]
        assert (metric['hit_count'], metric['evaluable_count'], metric['planned_count']) == (1, 3, 9)
        assert metric['value'] == 0.333333
        assert metric['evaluable_run_ids'] == [1, 2, 3]
        assert len(metric['unevaluated']) == 6
    current['semantics'] = {'answer_jobs': [
        {'answer_hash': hashlib.sha256(r['answer_text'].encode()).hexdigest(), 'status': 'DONE_ZERO_EVENTS'}
        for r in current['raw']['runs']], 'events': []}
    zero = measure_scope(current, IDENTITY)['metrics']['brand_recommendation_rate']
    assert (zero['hit_count'], zero['evaluable_count'], zero['value']) == (0, 9, 0)


def test_failed_answer_cannot_confer_positive_metric_from_stale_event():
    current = scope(1)
    current['semantics'] = {'answer_jobs': [{'answer_hash': hashlib.sha256(current['raw']['runs'][0]['answer_text'].encode()).hexdigest(),
        'status': 'FAILED_SCHEMA', 'run_ids': [1]}], 'events': [
        {'run_id': 1, 'entity_text': 'Target', 'fact_consumption_eligible': True, 'effective_speech_act': 'RECOMMEND'}]}
    result = measure_scope(current, IDENTITY)
    for name in ['brand_option_rate', 'brand_recommendation_rate']:
        assert result['metrics'][name]['value'] is None
        assert result['metrics'][name]['hit_count'] == 0
    assert result['metrics']['brand_mention_rate']['value'] == 1


def test_macro_and_weighted_average_use_independent_expected_counts_and_unknown_is_not_zero():
    rows = []
    for prompt_id, count, hits in [(1, 2, 1), (2, 10, 9), (3, 0, 0)]:
        item = scope(prompt_id)
        item['raw']['runs'] = [scope(100 * prompt_id + i, answer='Target' if i < hits else 'Another tool')['raw']['runs'][0] for i in range(count)]
        measured = measure_scope(item, IDENTITY)
        measured['prompt'] = {'id': prompt_id}
        rows.append(measured)
    result = aggregate_prompt_metrics(rows)
    mention = result['brand_mention_rate']
    assert mention['prompt_macro_average'] == .7
    assert mention['run_weighted_average'] == .833333
    assert mention['participating_prompt_ids'] == [1, 2]
    assert mention['total_prompt_count'] == 3 and mention['evaluable_count'] == 12
    assert result['brand_option_rate']['prompt_macro_average'] is None


def test_daily_trend_retains_unknown_time_and_uses_same_metric_definition():
    first, second, third = [scope(i)['raw']['runs'][0] for i in range(1, 4)]
    first['finished_at'] = '2026-10-09T02:00:00+08:00'
    second['finished_at'] = '2026-10-09T02:00:00'
    third['finished_at'] = 'not-a-date'
    current = scope(1)
    current['raw']['runs'] = [first, second, third]
    result = measure_scope(current, IDENTITY)
    assert [p['date'] for p in result['trend']['points']] == ['2026-10-08', '2026-10-09']
    assert result['trend']['unknown_date_run_ids'] == [3]
    assert result['metrics']['brand_mention_rate']['evaluable_count'] == 3
    assert [p['metrics']['brand_mention_rate']['evaluable_count'] for p in result['trend']['points']] == [1, 1]


def test_url_query_identity_does_not_remove_business_parameters():
    assert canonicalize_url('https://example.com/?from_date=2026&spmodel=a&utm_source=x') == 'https://example.com?from_date=2026&spmodel=a'
    assert canonicalize_url('https://example.com/?id=1') != canonicalize_url('https://example.com/?id=2')


def scope(run_id, answer='Target is an option', *, complete=True, failed=False, url='https://example.com/doc?id=1', platform='wenxin'):
    run = {'run_id': run_id, 'status': 'failed' if failed else 'success', 'answer_text': '' if failed else answer,
           'reference_complete': complete, 'references': [{'url': url}, {'url': url}],
           'observed_conditions': {k: {'value': v} for k, v in {'platform': platform, 'source_type': 'browser_audit',
             'adapter': 'wenxin_web_audit', 'original_query': 'Which tool?', 'collection_mode': 'single_independent'}.items()},
           'environment': {'sampling_mode': 'single_independent'}}
    return {'ref': {'context_id': f'ctx-{run_id}'}, 'raw': {'runs': [run]}, 'semantics': None}


def test_compare_without_publication_uses_independent_denominators_and_url_sets():
    a, b = scope(1), scope(2, answer='No brand', url='https://example.com/doc?id=2')
    output = compare_scopes(a, b, IDENTITY)
    mention = output['metrics']['brand_mention_rate']
    assert (mention['baseline']['hit_count'], mention['baseline']['evaluable_count']) == (1, 1)
    assert mention['comparison']['value'] == 0
    assert mention['delta_percentage_points'] == -100
    assert output['metrics']['brand_option_rate']['baseline']['value'] is None
    assert output['metrics']['brand_recommendation_rate']['baseline']['value'] is None
    assert len(output['citation_changes']['newly_observed']) == 1
    assert len(output['citation_changes']['not_observed_again']) == 1
    assert output['publication_required'] is False and output['causal_conclusion'] is False


def test_failure_and_partial_references_do_not_become_disappearance_or_zero():
    output = compare_scopes(scope(1), scope(2, failed=True), IDENTITY)
    assert output['metrics']['brand_mention_rate']['comparison']['value'] is None
    assert output['citation_changes']['not_observed_again'] == []
    assert output['citation_changes']['unclassified_baseline']
    output = compare_scopes(scope(1, complete=False), scope(2, url='https://other.com/new'), IDENTITY)
    assert output['citation_changes']['newly_observed'] == []


def test_condition_conflict_blocks_delta_not_raw_values():
    output = compare_scopes(scope(1), scope(2, platform='other'), IDENTITY)
    assert output['metrics']['brand_mention_rate']['baseline']['value'] == 1
    assert output['metrics']['brand_mention_rate']['delta_percentage_points'] is None
    assert 'platform:CONFLICT' in output['conflicts']


def test_zero_to_one_of_nine_is_11_points_not_100_percent_or_full_recommendation():
    before, after = scope(1), scope(10)
    before['raw']['runs'] = [scope(i, answer=f'General advice {i}')['raw']['runs'][0] for i in range(1, 10)]
    after['raw']['runs'] = [scope(i, answer=f'Target is listed {i}' if i == 10 else f'General advice {i}')['raw']['runs'][0] for i in range(10, 19)]
    for sample in [before, after]:
        sample['semantics'] = {'answer_jobs': [{'answer_hash': hashlib.sha256(r['answer_text'].encode()).hexdigest(),
            'status': 'DONE_ZERO_EVENTS' if r['run_id'] != 10 else 'DONE'} for r in sample['raw']['runs']], 'events': []}
    after['semantics']['events'] = [{'run_id': 10, 'entity_text': 'Target', 'fact_consumption_eligible': True,
        'effective_speech_act': 'INCLUDE_AS_OPTION'}]
    compared = compare_scopes(before, after, IDENTITY)
    for key in ['brand_mention_rate', 'brand_option_rate']:
        metric = compared['metrics'][key]
        assert (metric['baseline']['hit_count'], metric['baseline']['evaluable_count']) == (0, 9)
        assert (metric['comparison']['hit_count'], metric['comparison']['evaluable_count']) == (1, 9)
        assert metric['delta_percentage_points'] == pytest.approx(11.1111)
        assert metric['comparison'] == measure_scope(after, IDENTITY)['metrics'][key]
    assert compared['metrics']['brand_recommendation_rate']['delta_percentage_points'] == 0
    assert compared['causal_conclusion'] is False


def test_mention_option_and_recommendation_are_three_distinct_counts():
    current = scope(1)
    current['raw']['runs'] = [scope(i, answer=f'Target text {i}')['raw']['runs'][0] for i in range(1, 4)]
    current['semantics'] = {'answer_jobs': [{'status': 'DONE',
        'answer_hash': hashlib.sha256(r['answer_text'].encode()).hexdigest()} for r in current['raw']['runs']],
        'events': [{'run_id': i, 'entity_text': 'Target', 'fact_consumption_eligible': True, 'effective_speech_act': act}
                   for i, act in enumerate(['MENTION', 'INCLUDE_AS_OPTION', 'RECOMMEND'], 1)]}
    metrics = measure_scope(current, IDENTITY)['metrics']
    for name, ids in [('brand_mention_rate', [1, 2, 3]), ('brand_option_rate', [2, 3]), ('brand_recommendation_rate', [3])]:
        assert metrics[name]['hit_run_ids'] == ids
        assert metrics[name]['evaluable_count'] == 3


def test_monitor_handoff_freezes_scope_rejects_stale_and_replays_without_new_runs(tmp_path, monkeypatch):
    from app.models import Project, SinglePromptAnalysis
    from app.services.serialization import loads
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        original = _seed_frozen_analysis(db, reference_urls=[])
        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db
        client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000))
        base = '/api/v2/projects/1/prompts/44'
        selected = client.get(base + '/monitor').json()['analysis_selection']
        before_count = db.query(BrowserMonitorRun).count()
        payload = {'scope_hash': selected['scope_hash']}
        project = db.get(Project, 1); project.brand_name = 'Changed identity'; db.commit()
        assert client.post(base + '/monitor-analysis', json=payload).status_code == 409
        project.brand_name = 'Target'; db.commit()
        response = client.post(base + '/monitor-analysis', json=payload)
        assert response.status_code == 201, response.text
        saved = response.json()
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=saved['analysis']['analysis_id']).one()
        plan = loads(analysis.sampling_plan_json, {})
        assert plan['run_ids'] == selected['selected_run_ids']
        assert plan['run_fingerprints'] == selected['run_fingerprints']
        assert plan['origin_monitor_scope'] == selected
        assert analysis.task_id is None and analysis.analysis_id != original.analysis_id
        assert db.query(BrowserMonitorRun).count() == before_count
        refreshed_click = client.post(base + '/monitor-analysis', json=payload)
        assert refreshed_click.status_code == 200
        assert refreshed_click.json()['analysis']['analysis_id'] == analysis.analysis_id
        project = db.get(Project, 1); project.brand_name = 'Changed identity'; db.commit()
        assert client.post(base + '/monitor-analysis', json=payload).status_code == 200
        assert client.post(base + '/monitor-analysis', json=payload).json()['analysis']['analysis_id'] == analysis.analysis_id
        current = client.get(base + '/monitor').json()['analysis_selection']
        prompt = db.get(Prompt, 44); prompt.prompt_group = 'changed group'; db.commit()
        assert client.post(base + '/monitor-analysis', json={'scope_hash': current['scope_hash']}).status_code == 409
        assert client.post(base.replace('/1/', '/2/') + '/monitor-analysis', json=payload).status_code == 404
        pending, _ = create_analysis(db, project_id=1, prompt_id=44, sample_count=1, idempotency_key='later-pending')
        current = client.get(base + '/monitor').json()['analysis_selection']
        waiting = db.query(BrowserMonitorRun).filter_by(task_id=pending.task_id).one()
        assert current['excluded_run_ids'] == [waiting.id]
        assert current['selected_run_ids'] == selected['selected_run_ids']
        accepted = client.post(base + '/monitor-analysis', json={'scope_hash': current['scope_hash']})
        assert accepted.status_code == 201
        record = db.query(SinglePromptAnalysis).filter_by(analysis_id=accepted.json()['analysis']['analysis_id']).one()
        assert loads(record.sampling_plan_json, {})['origin_monitor_scope']['excluded_run_ids'] == [waiting.id]
    finally:
        db.close(); engine.dispose()


def test_semantic_uncertainty_is_not_negative_and_options_are_separate():
    s = scope(1)
    s['semantics'] = {'answer_jobs': [{'answer_hash': hashlib.sha256(s['raw']['runs'][0]['answer_text'].encode()).hexdigest(), 'status': 'DONE'}],
        'events': [{'run_id': 1, 'entity_text': 'Target', 'fact_consumption_eligible': False, 'effective_speech_act': 'INCLUDE_AS_OPTION'}]}
    output = compare_scopes(s, scope(2), IDENTITY)
    assert output['metrics']['brand_recommendation_rate']['baseline']['value'] is None
    assert output['metrics']['brand_option_rate']['baseline']['value'] is None
    s['semantics']['events'][0]['fact_consumption_eligible'] = True
    output = compare_scopes(s, scope(2), IDENTITY)
    assert output['metrics']['brand_option_rate']['baseline']['value'] == 1
    assert output['metrics']['brand_recommendation_rate']['baseline']['value'] == 0


def test_formal_api_context_and_comparison_persist_without_reviews(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        _seed_frozen_analysis(db, reference_urls=[])
        second, _ = create_analysis(db, project_id=1, prompt_id=44, sample_count=1, idempotency_key='second-test-sample')
        token = claim_analysis(db, second.analysis_id)
        run = db.query(BrowserMonitorRun).filter_by(task_id=second.task_id).one()
        run.status = 'success'; run.answer_text = 'Target is mentioned'; run.reference_complete = True
        db.commit()
        assert finalize_analysis(db, second.analysis_id, token)
        rows = db.query(SinglePromptAnalysisContext).order_by(SinglePromptAnalysisContext.id).all()
        refs = [{'context_id': r.context_id, 'raw_output_hash': r.raw_output_hash} for r in rows]
        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db
        client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000))
        monitor_uri = '/api/v2/projects/1/prompts/44/monitor'
        monitor = client.get(monitor_uri)
        assert monitor.status_code == 200, monitor.text
        assert len(monitor.json()['runs']) == 2
        assert monitor.json()['metrics']['brand_option_rate']['value'] is None
        overview = client.get('/api/v2/projects/1/monitor')
        assert overview.status_code == 200
        assert overview.json()['metrics']['brand_mention_rate']['prompt_macro_average'] == .5
        assert overview.json()['metrics']['brand_option_rate']['prompt_macro_average'] is None
        assert client.get('/api/v2/projects/999/monitor').status_code == 404
        prompt = db.get(Prompt, 44)
        original = prompt.prompt_text
        prompt.prompt_text = 'Changed question, different sampling scope'
        db.commit()
        changed_pool = client.get(monitor_uri).json()
        assert changed_pool['runs'] == []
        assert len(changed_pool['historical_query_runs']) == 2
        assert changed_pool['metrics']['brand_mention_rate']['value'] is None
        assert client.get(monitor_uri.replace('/1/', '/2/')).status_code == 404
        prompt.prompt_text = original
        db.commit()
        uri = '/api/v2/projects/1/prompts/44/observation-comparisons'
        payload = {'baseline': refs[0], 'comparison': refs[1], 'identity': IDENTITY}
        response = client.post(uri, json=payload)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert client.post(uri, json=payload).json()['result_version'] == saved['result_version']
        assert db.query(SinglePromptObservationComparison).count() == 1
        assert db.query(SinglePromptPublicationRecord).count() == 0
        for side, ref in [('baseline', refs[0]), ('comparison', refs[1])]:
            measurement = client.post('/api/v2/projects/1/prompts/44/measurements', json={'scope': ref, 'identity': IDENTITY})
            assert measurement.status_code == 200
            for name, metric in measurement.json()['metrics'].items():
                assert saved['output']['metrics'][name][side] == metric
        negative = client.post(uri, json={'baseline': refs[1], 'comparison': refs[0], 'identity': IDENTITY})
        assert negative.status_code == 201
        assert negative.json()['output']['metrics']['brand_mention_rate']['delta_percentage_points'] == -100
        history = client.get(uri).json()
        assert {r['result_version'] for r in history} == {saved['result_version'], negative.json()['result_version']}
        assert client.get(uri + '/' + negative.json()['result_version']).json()['output'] == negative.json()['output']
        assert client.get(uri + '/' + saved['result_version']).json()['output_hash'] == saved['output_hash']
        assert client.get(uri.replace('/1/', '/2/') + '/' + saved['result_version']).status_code == 404
        altered = copy.deepcopy(payload); altered['baseline']['raw_output_hash'] = '0' * 64
        assert client.post(uri, json=altered).status_code == 409
        assert client.post(uri, json={**payload, 'comparison': refs[0]}).status_code == 422
        context = client.post('/api/v2/projects/1/brand-contexts', json={'expected_version': 0, 'title': 'Brand', 'content': 'User supplied scope.'})
        assert context.status_code == 201
        old = context.json()
        assert client.post('/api/v2/projects/1/brand-contexts', json={'expected_version': 0, 'title': 'Stale', 'content': 'Conflict'}).status_code == 409
        client.post('/api/v2/projects/1/brand-contexts', json={'expected_version': 1, 'title': 'New', 'content': 'New content'})
        assert load_context(db, project_id=1, context_version_id=old['context_version_id'])['content'] == 'User supplied scope.'
        selected = select_context(db, project_id=1, context_version_id=old['context_version_id'], query='supplied scope')
        assert selected['passages'][0]['text'] == 'User supplied scope.'
        assert 'content' not in selected and selected['allowed_use'] == 'INTERNAL_CONTEXT_NOT_PUBLIC_FACT'
        assert select_context(db, project_id=1, context_version_id=old['context_version_id'], query='unrelated filter')['passages'] == []
        assert load_context(db, project_id=1, context_version_id=None)['mode'] == 'EMPTY'
        with pytest.raises(HTTPException):
            load_context(db, project_id=2, context_version_id=old['context_version_id'])
        with pytest.raises(Exception, match='RELEASE_HISTORY_IMMUTABLE'):
            db.execute(text('UPDATE single_prompt_observation_comparisons SET output_json = :value'), {'value': '{}'})
        db.rollback()
    finally:
        db.close(); engine.dispose()

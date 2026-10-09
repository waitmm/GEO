import copy
import hashlib
import json

import pytest
from fastapi import HTTPException
from release_test_client import TestClient
from sqlalchemy import text

from app.core.release_database import get_release_db
from app.models import BrowserMonitorRun, SinglePromptAnalysisContext, SinglePromptObservationComparison, SinglePromptPublicationRecord
from app.modules.single_prompt_v2.context_provider import load_context, save_context, select_context
from app.modules.single_prompt_v2.observation import compare_scopes, create_observation_comparison, measure_scope
from app.modules.single_prompt_v2.service import create_analysis, claim_analysis, finalize_analysis
from app.release_main import create_release_app
from test_release_first_slice import _migrated_session, _seed_frozen_analysis
from app.services.url_identity import canonicalize_url


IDENTITY = {'canonical_brand_name': 'Target', 'accepted_aliases': [], 'official_domains': [], 'official_urls': []}


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
        uri = '/api/v2/projects/1/prompts/44/observation-comparisons'
        payload = {'baseline': refs[0], 'comparison': refs[1], 'identity': IDENTITY}
        response = client.post(uri, json=payload)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert client.post(uri, json=payload).json()['result_version'] == saved['result_version']
        assert db.query(SinglePromptObservationComparison).count() == 1
        assert db.query(SinglePromptPublicationRecord).count() == 0
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

from fastapi import HTTPException
import pytest
from release_test_client import TestClient

from app.core.release_database import get_release_db
from app.models import BrowserMonitorRun, BrowserMonitorTask, Competitor, Prompt
from app.modules.single_prompt_v2.service import (
    create_analysis, create_analysis_from_runs, create_frozen_analysis,
    queue_frozen_analysis, queue_run_retry, retry_analysis, list_prompt_run_pool, get_analysis_status,
    _hash,
)
from app.release_main import create_release_app
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    try:
        with TestClient(app, base_url='http://127.0.0.1') as client:
            yield client, db
    finally:
        db.close(); engine.dispose()


def test_catalog_normalizes_and_rejects_duplicates_without_partial_mutation(catalog):
    client, db = catalog
    project = client.post('/api/projects', json={'name': ' Project ', 'brand_name': ' Brand ',
        'brand_aliases': [' B ', 'B'], 'competitors': [{'name': ' Other '}]}).json()
    project_id = project['id']
    assert project['name'] == 'Project' and project['brand_aliases'] == ['B']
    route = f'/api/projects/{project_id}/prompts'
    first = client.post(route, json={'prompt_text': '  First line\nSecond line  ', 'intent_type': 'unknown'})
    assert first.status_code == 200 and first.json()['prompt_text'] == 'First line\nSecond line'
    assert client.post(route, json={'prompt_text': 'First line\nSecond line'}).status_code == 409
    assert client.post(route, json={'prompt_text': ' First line\nSecond line '}).status_code == 409
    assert db.query(Prompt).count() == 1
    before = client.get('/api/projects').json()
    invalid = client.patch(f'/api/projects/{project_id}', json={'name': 'Changed', 'competitors': [{'name': ' '}]})
    assert invalid.status_code == 422
    assert client.get('/api/projects').json() == before
    assert db.query(Competitor).one().name == 'Other'


@pytest.mark.parametrize('payload', [
    {'name': ' '}, {'brand_name': None}, {'website_url': 'javascript:alert(1)'},
    {'website_url': 'https://user:password@example.com'}, {'website_url': 'https://example.com:wrong'},
    {'brand_aliases': None}, {'brand_aliases': [' ']}, {'competitors': None},
])
def test_project_invalid_update_is_422_and_non_destructive(catalog, payload):
    client, db = catalog
    created = client.post('/api/projects', json={'name': 'Project', 'brand_name': 'Brand'}).json()
    before = client.get('/api/projects').json()
    assert client.patch(f'/api/projects/{created["id"]}', json=payload).status_code == 422
    assert client.get('/api/projects').json() == before


@pytest.mark.parametrize('payload', [{'enabled': None}, {'intent_type': None}, {'importance': None}, {'title': None}, {'prompt_text': ' '}])
def test_prompt_null_update_cannot_reach_database(catalog, payload):
    client, db = catalog
    project = client.post('/api/projects', json={'name': 'Project', 'brand_name': 'Brand'}).json()
    route = f'/api/projects/{project["id"]}/prompts'
    created = client.post(route, json={'prompt_text': 'Question'}).json()
    before = client.get(route).json()
    assert client.patch(f'{route}/{created["id"]}', json=payload).status_code == 422
    assert client.get(route).json() == before


def test_disabled_prompt_blocks_new_attempts_not_history_or_idempotent_read(catalog):
    client, db = catalog
    analysis = _seed_frozen_analysis(db, reference_urls=[])
    original = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    failed, _ = create_analysis(db, project_id=1, prompt_id=44, sample_count=1, idempotency_key='failed-sampling-attempt')
    failed_run = db.query(BrowserMonitorRun).filter_by(task_id=failed.task_id).one()
    failed.status = 'FAILED'; failed_run.status = 'failed'; failed_run.error_type = 'network_error'
    db.commit()
    db.get(Prompt, 44).enabled = False
    db.commit()
    counts = (db.query(BrowserMonitorTask).count(), db.query(BrowserMonitorRun).count())
    for action in [
        lambda: create_analysis(db, project_id=1, prompt_id=44, sample_count=1, idempotency_key='new-attempt'),
        lambda: queue_run_retry(db, project_id=1, prompt_id=44, run_id=failed_run.id, idempotency_key='new-retry'),
        lambda: retry_analysis(db, failed.analysis_id),
    ]:
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 409 and '停用' in error.value.detail
    assert (db.query(BrowserMonitorTask).count(), db.query(BrowserMonitorRun).count()) == counts
    assert failed.status == 'FAILED' and failed_run.status == 'failed'
    previous, created = create_analysis(db, project_id=1, prompt_id=44, sample_count=1, idempotency_key='release-sampling-0001')
    assert not created and previous.analysis_id == analysis.analysis_id
    historical, created = create_analysis_from_runs(db, project_id=1, prompt_id=44,
        run_ids=[original.id], run_fingerprints={row['run_id']: row['input_fingerprint']
            for row in list_prompt_run_pool(db, project_id=1, prompt_id=44, page=1, page_size=20)['items'] if row['run_id'] == original.id},
        base_context_id=None, idempotency_key='disabled-historical-analysis')
    assert created and get_analysis_status(db, historical.analysis_id)['context_id']
    assert client.get('/api/projects/1/prompts').json()[0]['enabled'] is False


def test_disabled_prompt_cannot_queue_or_create_a_frozen_sampling_plan(catalog):
    client, db = catalog
    _seed_frozen_analysis(db, reference_urls=[])
    query = '冻结的采样问题'
    plan = {'project_id': 1, 'prompt_id': 44, 'sample_count': 1, 'platform': 'wenxin',
        'source_type': 'browser_audit', 'adapter': 'wenxin_web_audit',
        'collection_mode': 'single_independent', 'prompt_text_hash': _hash(query)}
    planned, _ = create_frozen_analysis(db, project_id=1, prompt_id=44, prompt_text=query,
        sampling_plan=plan, idempotency_key='planned-before-disable', created_by='offline-test')
    db.commit()
    db.get(Prompt, 44).enabled = False; db.commit()
    with pytest.raises(HTTPException, match='停用'):
        queue_frozen_analysis(db, planned.analysis_id)
    assert planned.status == 'PLANNED'
    with pytest.raises(HTTPException, match='停用'):
        create_frozen_analysis(db, project_id=1, prompt_id=44, prompt_text=query,
            sampling_plan=plan, idempotency_key='planned-after-disable', created_by='offline-test')
    row, created = create_frozen_analysis(db, project_id=1, prompt_id=44, prompt_text=query,
        sampling_plan=plan, idempotency_key='planned-before-disable', created_by='offline-test')
    assert row.analysis_id == planned.analysis_id and not created

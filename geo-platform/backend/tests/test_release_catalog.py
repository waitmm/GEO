import hashlib
import json

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import pytest
from release_test_client import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.release_database import get_release_db
from app.models import (
    BrowserMonitorRun, BrowserMonitorTask, Competitor, Organization, Project, ProjectConfigurationVersion, Prompt,
    PromptVersion,
)
from app.modules.single_prompt_v2.service import (
    create_analysis, create_analysis_from_runs, create_frozen_analysis,
    queue_frozen_analysis, queue_run_retry, retry_analysis, list_prompt_run_pool, get_analysis_status,
    _hash,
)
from app.release_main import create_release_app
from test_release_first_slice import ROOT, _migrated_session, _seed_frozen_analysis


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


def test_prompt_versions_are_append_only_noop_idempotent_and_project_scoped(catalog):
    client, db = catalog
    first_project = client.post('/api/projects', json={'name': 'First', 'brand_name': 'First'}).json()
    second_project = client.post('/api/projects', json={'name': 'Second', 'brand_name': 'Second'}).json()
    route = f"/api/projects/{first_project['id']}/prompts"
    prompt = client.post(route, json={
        'prompt_text': 'Question V1', 'title': 'Title V1', 'intent_type': 'unknown',
        'prompt_group': 'Group V1', 'enabled': True,
    }).json()
    versions_route = f"{route}/{prompt['id']}/versions"
    versions = client.get(versions_route).json()
    assert len(versions) == 1
    v1 = versions[0]
    assert v1['version_number'] == 1 and v1['status'] == 'EFFECTIVE'
    assert {key: v1['snapshot'][key] for key in (
        'project_id', 'prompt_id', 'prompt_text', 'title', 'intent_type', 'prompt_group', 'enabled',
    )} == {
        'project_id': first_project['id'], 'prompt_id': prompt['id'], 'prompt_text': 'Question V1',
        'title': 'Title V1', 'intent_type': 'unknown', 'prompt_group': 'Group V1', 'enabled': True,
    }
    canonical = json.dumps(v1['snapshot'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert hashlib.sha256(canonical.encode()).hexdigest() == v1['snapshot_hash']

    assert client.patch(f"{route}/{prompt['id']}", json={'title': 'Title V1'}).status_code == 200
    assert db.query(PromptVersion).filter_by(prompt_id=prompt['id']).count() == 1
    assert client.patch(f"{route}/{prompt['id']}", json={
        'prompt_text': 'Question V2', 'title': 'Title V2', 'enabled': False,
    }).status_code == 200
    versions = client.get(versions_route).json()
    assert [(row['version_number'], row['status']) for row in versions] == [
        (2, 'EFFECTIVE'), (1, 'SUPERSEDED'),
    ]
    assert versions[0]['snapshot']['prompt_text'] == 'Question V2'
    assert client.get(f"{versions_route}/{v1['prompt_version_id']}").json()['snapshot'] == v1['snapshot']

    row = db.query(PromptVersion).filter_by(prompt_version_id=v1['prompt_version_id']).one()
    original = row.snapshot_json
    row.snapshot_json = '{}'
    with pytest.raises(Exception, match='PROMPT_VERSION_IMMUTABLE'):
        db.commit()
    db.rollback()
    assert db.query(PromptVersion).filter_by(prompt_version_id=v1['prompt_version_id']).one().snapshot_json == original
    db.delete(db.query(PromptVersion).filter_by(prompt_version_id=v1['prompt_version_id']).one())
    with pytest.raises(Exception, match='PROMPT_VERSION_IMMUTABLE'):
        db.commit()
    db.rollback()

    other = client.post(f"/api/projects/{second_project['id']}/prompts", json={'prompt_text': 'Other'}).json()
    assert client.get(
        f"/api/projects/{second_project['id']}/prompts/{other['id']}/versions/{v1['prompt_version_id']}"
    ).status_code == 404
    assert client.get(f"/api/projects/{second_project['id']}/prompts/{prompt['id']}/versions").status_code == 404


def test_prompt_version_migration_backfills_historical_prompts(tmp_path, monkeypatch):
    database_path = tmp_path / 'prompt-version-backfill.db'
    monkeypatch.setenv('GEO_RELEASE_DATABASE_URL', f'sqlite:///{database_path.as_posix()}')
    config = Config(str(ROOT / 'alembic.release.ini'))
    command.upgrade(config, '20261015_01')
    engine = create_engine(f'sqlite:///{database_path.as_posix()}')
    db = sessionmaker(bind=engine)()
    db.add(Organization(id=91, name='Historical Org'))
    db.add(Project(id=92, organization_id=91, name='Historical Project', brand_name='Historical'))
    db.add(Prompt(
        id=93, project_id=92, prompt_text='Historical question', title='Historical title',
        intent_type='usage_instruction', prompt_group='Historical group', enabled=False,
    ))
    db.commit()
    db.close()
    engine.dispose()

    command.upgrade(config, 'head')
    engine = create_engine(f'sqlite:///{database_path.as_posix()}')
    db = sessionmaker(bind=engine)()
    try:
        row = db.query(PromptVersion).filter_by(project_id=92, prompt_id=93).one()
        snapshot = json.loads(row.snapshot_json)
        assert row.version_number == 1
        assert snapshot['prompt_text'] == 'Historical question'
        assert snapshot['title'] == 'Historical title'
        assert snapshot['intent_type'] == 'usage_instruction'
        assert snapshot['prompt_group'] == 'Historical group'
        assert snapshot['enabled'] is False
    finally:
        db.close()
        engine.dispose()


def test_configuration_preview_matches_saved_normalization_without_business_writes(catalog):
    from scripts.release_upgrade_check import business_fingerprint
    client, db = catalog
    before = business_fingerprint(db.get_bind().url.database)
    payload = {'name': ' Preview ', 'brand_name': ' Brand ', 'brand_aliases': [' B ', 'B'],
        'website_url': ' https://EXAMPLE.com/help ', 'region': ' US ', 'language': ' en-US ',
        'competitors': [{'name': ' Other ', 'website_url': 'https://other.example:8443/help'}]}
    response = client.post('/api/projects/configuration-preview', json=payload)
    assert response.status_code == 200
    preview = response.json()
    assert preview['values']['brand_aliases'] == ['B']
    assert preview['configured_official_host'] == 'example.com'
    assert preview['alias_duplicates_removed'] == 1
    assert preview['domain_status'] == 'CONFIGURED_NOT_VERIFIED'
    assert business_fingerprint(db.get_bind().url.database) == before
    saved = client.post('/api/projects', json=payload).json()
    for field in ['name', 'brand_name', 'brand_aliases', 'website_url', 'region', 'language']:
        assert preview['values'][field] == saved[field]
    assert client.get('/api/projects').json()[0] == saved
    assert client.post('/api/projects/configuration-preview', json={
        'name': 'No domain', 'brand_name': 'Brand'}).json()['domain_status'] == 'UNKNOWN'
    before = business_fingerprint(db.get_bind().url.database)
    assert client.post('/api/projects/configuration-preview', json={
        **payload, 'website_url': 'https://user:password@example.com'}).status_code == 422
    assert business_fingerprint(db.get_bind().url.database) == before


def test_project_configuration_versions_are_append_only_and_exactly_readable(catalog):
    client, db = catalog
    created = client.post('/api/projects', json={
        'name': 'Project', 'brand_name': 'Brand V1', 'brand_aliases': ['old'],
        'website_url': 'https://v1.example/path',
        'competitors': [{'name': 'Competitor V1', 'aliases': ['C1']}],
    }).json()
    project_id = created['id']
    versions = client.get(f'/api/projects/{project_id}/configuration-versions').json()
    assert len(versions) == 1 and versions[0]['version_number'] == 1
    v1_id = versions[0]['configuration_version_id']
    assert versions[0]['snapshot']['brand_aliases'] == ['old']

    response = client.patch(f'/api/projects/{project_id}', json={
        'brand_name': 'Brand V2', 'brand_aliases': ['new'],
        'competitors': [{'name': 'Competitor V2', 'aliases': []}],
    })
    assert response.status_code == 200
    versions = client.get(f'/api/projects/{project_id}/configuration-versions').json()
    assert [(row['version_number'], row['status']) for row in versions] == [
        (2, 'EFFECTIVE'), (1, 'SUPERSEDED')]
    frozen = client.get(f'/api/projects/{project_id}/configuration-versions/{v1_id}').json()
    assert frozen['snapshot']['brand_name'] == 'Brand V1'
    assert frozen['snapshot']['brand_aliases'] == ['old']
    assert frozen['snapshot']['competitors'][0]['name'] == 'Competitor V1'
    assert frozen['snapshot']['website_url'] == 'https://v1.example/path'

    # A no-op write does not invent a new semantic version.
    assert client.patch(f'/api/projects/{project_id}', json={'brand_name': 'Brand V2'}).status_code == 200
    assert db.query(ProjectConfigurationVersion).filter_by(project_id=project_id).count() == 2
    row = db.query(ProjectConfigurationVersion).filter_by(configuration_version_id=v1_id).one()
    original = row.snapshot_json
    row.snapshot_json = '{}'
    with pytest.raises(Exception, match='PROJECT_CONFIGURATION_IMMUTABLE'):
        db.commit()
    db.rollback()
    assert db.query(ProjectConfigurationVersion).filter_by(configuration_version_id=v1_id).one().snapshot_json == original
    db.delete(db.query(ProjectConfigurationVersion).filter_by(configuration_version_id=v1_id).one())
    with pytest.raises(Exception, match='PROJECT_CONFIGURATION_IMMUTABLE'):
        db.commit()
    db.rollback()

    other = client.post('/api/projects', json={'name': 'Other', 'brand_name': 'Other'}).json()
    assert client.get(f"/api/projects/{other['id']}/configuration-versions/{v1_id}").status_code == 404


def test_first_edit_freezes_pre_versioned_project_before_mutation(catalog):
    client, db = catalog
    # Simulate a project carried forward from a release before this ledger existed.
    existing = client.post('/api/projects', json={'name': 'Existing', 'brand_name': 'Existing'}).json()
    legacy = Project(organization_id=existing['organization_id'], name='Legacy', brand_name='Before')
    db.add(legacy); db.commit(); db.refresh(legacy)
    assert client.patch(f"/api/projects/{legacy.id}", json={'brand_name': 'After'}).status_code == 200
    versions = client.get(f"/api/projects/{legacy.id}/configuration-versions").json()
    assert [row['snapshot']['brand_name'] for row in versions] == ['After', 'Before']


def test_batch_prompts_preserve_multiline_and_report_each_item_without_sampling(catalog):
    client, db = catalog
    project = client.post('/api/projects', json={'name': 'Project', 'brand_name': 'Brand'}).json()
    route = f'/api/projects/{project["id"]}/prompts'
    payload = {'items': [
        {'prompt_text': '  How to clean?\nUnder which conditions?  ', 'intent_type': 'usage_instruction'},
        {'prompt_text': 'How to clean?\nUnder which conditions?', 'importance': 5},
        {'prompt_text': ' '}, {'prompt_text': 'Other', 'importance': 6},
        {'prompt_text': 'Other', 'topic_id': 999}, {'prompt_text': 'Other', 'daily_tracking_enabled': True},
        {'prompt_text': 'Other', 'unexpected': 'reject'}, {'prompt_text': 'Other'},
    ]}
    response = client.post(f'{route}/batch', json=payload)
    assert response.status_code == 200
    results = response.json()['items']
    assert [item['status'] for item in results] == ['CREATED', 'EXISTING', *['REJECTED'] * 5, 'CREATED']
    assert results[0]['prompt_id'] == results[1]['prompt_id']
    assert [item['index'] for item in results] == list(range(8))
    first = db.get(Prompt, results[0]['prompt_id'])
    assert first.prompt_text == 'How to clean?\nUnder which conditions?' and first.importance == 3
    repeated = client.post(f'{route}/batch', json=payload).json()['items']
    assert [item['status'] for item in repeated] == ['EXISTING', 'EXISTING', *['REJECTED'] * 5, 'EXISTING']
    assert db.query(Prompt).count() == 2
    assert db.query(BrowserMonitorRun).count() == db.query(BrowserMonitorTask).count() == 0


@pytest.mark.parametrize('items', [[], [{'prompt_text': 'Q'}] * 21])
def test_batch_bounds_are_enforced_before_writes(catalog, items):
    client, db = catalog
    project = client.post('/api/projects', json={'name': 'Project', 'brand_name': 'Brand'}).json()
    assert client.post(f'/api/projects/{project["id"]}/prompts/batch', json={'items': items}).status_code == 422
    assert db.query(Prompt).count() == 0


def test_batch_duplicate_does_not_hide_invalid_scope_or_tracking(catalog):
    client, db = catalog
    one = client.post('/api/projects', json={'name': 'One', 'brand_name': 'Brand'}).json()['id']
    two = client.post('/api/projects', json={'name': 'Two', 'brand_name': 'Brand'}).json()['id']
    topic = client.post(f'/api/projects/{two}/topics', json={'name': 'Other topic'}).json()['id']
    client.post(f'/api/projects/{one}/prompts', json={'prompt_text': 'Q'})
    result = client.post(f'/api/projects/{one}/prompts/batch', json={'items': [
        {'prompt_text': 'Q', 'topic_id': topic}, {'prompt_text': 'Q', 'daily_tracking_enabled': True},
    ]}).json()['items']
    assert [item['status'] for item in result] == ['REJECTED', 'REJECTED']
    other = client.post(f'/api/projects/{two}/prompts/batch', json={'items': [{'prompt_text': 'Q'}]})
    assert other.json()['items'][0]['status'] == 'CREATED'
    assert client.post('/api/projects/999/prompts/batch', json={'items': [{'prompt_text': 'Q'}]}).status_code == 404


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
    prompt_version = json.loads(analysis.sampling_plan_json)['prompt_version']
    version_args = {'prompt_version_id': prompt_version['prompt_version_id'],
        'snapshot_hash': prompt_version['snapshot_hash']}
    original = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    failed, _ = create_analysis(db, project_id=1, prompt_id=44, **version_args,
        sample_count=1, idempotency_key='failed-sampling-attempt')
    failed_run = db.query(BrowserMonitorRun).filter_by(task_id=failed.task_id).one()
    failed.status = 'FAILED'; failed_run.status = 'failed'; failed_run.error_type = 'network_error'
    db.commit()
    db.get(Prompt, 44).enabled = False
    db.commit()
    counts = (db.query(BrowserMonitorTask).count(), db.query(BrowserMonitorRun).count())
    for action in [
        lambda: create_analysis(db, project_id=1, prompt_id=44, **version_args,
            sample_count=1, idempotency_key='new-attempt'),
        lambda: queue_run_retry(db, project_id=1, prompt_id=44, run_id=failed_run.id, idempotency_key='new-retry'),
        lambda: retry_analysis(db, failed.analysis_id),
    ]:
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 409 and '停用' in error.value.detail
    assert (db.query(BrowserMonitorTask).count(), db.query(BrowserMonitorRun).count()) == counts
    assert failed.status == 'FAILED' and failed_run.status == 'failed'
    previous, created = create_analysis(db, project_id=1, prompt_id=44, **version_args,
        sample_count=1, idempotency_key='release-sampling-0001')
    assert not created and previous.analysis_id == analysis.analysis_id
    historical, created = create_analysis_from_runs(db, project_id=1, prompt_id=44,
        **version_args,
        run_ids=[original.id], run_fingerprints={row['run_id']: row['input_fingerprint']
            for row in list_prompt_run_pool(db, project_id=1, prompt_id=44, page=1, page_size=20)['items'] if row['run_id'] == original.id},
        base_context_id=None, idempotency_key='disabled-historical-analysis')
    assert created and get_analysis_status(db, historical.analysis_id)['context_id']
    assert client.get('/api/projects/1/prompts').json()[0]['enabled'] is False


def test_disabled_prompt_cannot_queue_or_create_a_frozen_sampling_plan(catalog):
    client, db = catalog
    source = _seed_frozen_analysis(db, reference_urls=[])
    query = source.prompt_text_snapshot
    prompt_version = json.loads(source.sampling_plan_json)['prompt_version']
    plan = {'project_id': 1, 'prompt_id': 44, 'sample_count': 1, 'platform': 'wenxin',
        'source_type': 'browser_audit', 'adapter': 'wenxin_web_audit',
        'collection_mode': 'single_independent', 'prompt_text_hash': _hash(query),
        'prompt_version': prompt_version}
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


def test_delete_only_unused_prompt_and_never_cross_project(catalog):
    client, db = catalog
    project = client.post('/api/projects', json={'name': 'Project', 'brand_name': 'Brand'}).json()
    route = f'/api/projects/{project["id"]}/prompts'
    prompt = client.post(route, json={'prompt_text': 'Unused question'}).json()
    assert client.delete(f'/api/projects/999/prompts/{prompt["id"]}').status_code == 404
    assert db.get(Prompt, prompt['id']) is not None
    result = client.delete(f'{route}/{prompt["id"]}')
    assert result.status_code == 200 and result.json() == {'deleted': True, 'prompt_id': prompt['id']}
    db.expire_all()
    assert db.get(Prompt, prompt['id']) is None
    assert client.get(route).json() == []


def test_delete_rejects_used_prompt_without_modifying_history(catalog):
    client, db = catalog
    analysis = _seed_frozen_analysis(db, reference_urls=[])
    original = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    before = (original.answer_text, original.status, original.task_id, analysis.analysis_id)
    response = client.delete('/api/projects/1/prompts/44')
    assert response.status_code == 409 and '停用' in response.json()['detail']
    db.expire_all()
    assert db.get(Prompt, 44) is not None
    assert (original.answer_text, original.status, original.task_id, analysis.analysis_id) == before


def test_delete_rejects_schedule_even_without_any_run(catalog):
    from app.models import SinglePromptSamplingSchedule
    from datetime import datetime
    client, db = catalog
    project = client.post('/api/projects', json={'name': 'Project', 'brand_name': 'Brand'}).json()
    route = f'/api/projects/{project["id"]}/prompts'
    prompt = client.post(route, json={'prompt_text': 'Scheduled question'}).json()
    schedule = SinglePromptSamplingSchedule(schedule_id='delete-guard', project_id=project['id'],
        prompt_id=prompt['id'], plan_json='{}', plan_hash='fixed', next_due_at=datetime.utcnow(),
        timezone='Asia/Shanghai', local_time='09:00', remaining_attempts=1, authorization_note='offline test')
    db.add(schedule); db.commit()
    assert db.query(BrowserMonitorRun).count() == 0
    assert client.delete(f'{route}/{prompt["id"]}').status_code == 409
    assert db.get(Prompt, prompt['id']) is not None
    assert db.query(SinglePromptSamplingSchedule).filter_by(schedule_id='delete-guard').one()

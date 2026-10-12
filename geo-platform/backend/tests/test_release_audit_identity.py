"""User-entered names cannot replace the authenticated audit identity."""
import ast
from hashlib import sha256
import inspect
import json

import pytest
from fastapi.routing import APIRoute

from release_test_client import TestClient
from test_single_prompt_v2_diagnosis import _session, _seed, _ready_analysis, _compute
from app.core.release_access import authenticated_actor
from app.core.release_database import get_release_db
from app.release_main import create_release_app


@pytest.mark.parametrize('mode', ['LOCAL_ONLY', 'INVITATION'])
@pytest.mark.parametrize('operation', ['revisions', 'reviews'])
def test_saved_operator_is_authenticated_identity(tmp_path, monkeypatch, mode, operation):
    key = 'isolated-operator-audit-not-real-01234567890123456789'
    monkeypatch.delenv('GEO_RELEASE_ACCESS_CONFIG', raising=False)
    expected_actor = 'local-owner'
    if mode == 'INVITATION':
        config = tmp_path / 'access.json'
        config.write_text(json.dumps({'accounts': [{'name': 'actual-operator',
            'key_sha256': sha256(key.encode()).hexdigest(), 'project_ids': [1]}]}))
        config.chmod(0o600)
        monkeypatch.setenv('GEO_RELEASE_ACCESS_CONFIG', str(config))
        expected_actor = 'actual-operator'
    db, engine = _session(tmp_path)
    try:
        _seed(db)
        analysis = _ready_analysis(db)
        execution, result = _compute(db, analysis)
        original = result.output_json
        output = json.loads(original)
        body = {'project_id': 1, 'prompt_id': 44, 'reviewable_set_hash': result.reviewable_set_hash}
        if operation == 'revisions':
            body.update(base_result_version=result.result_version, base_result_hash=result.output_hash,
                editor='forged-administrator', edits=[{'target_type': 'RECOMMENDATION_EVENT',
                    'target_id': output['answer_diagnosis']['events'][1]['event_id'],
                    'value': 'INCLUDE_AS_OPTION', 'reason': 'Isolated correction audit'}])
        else:
            body.update(result_hash=result.output_hash, reviewer='forged-administrator', note='', decisions=[])
        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db
        options = ({'base_url': 'https://geo.example', 'client': ('192.0.2.91', 8000)}
            if mode == 'INVITATION' else {'base_url': 'http://127.0.0.1'})
        with TestClient(app, **options) as client:
            path = (f'/api/v2/single-prompt/analyses/{analysis.analysis_id}/diagnoses/'
                f'{execution.diagnosis_id}/results/{result.result_version}/{operation}')
            if mode == 'INVITATION':
                assert client.post(path, json=body).status_code == 401
                assert client.post('/api/access/session', json={'access_key': key}).status_code == 200
            response = client.post(path, json=body)
            assert response.status_code == 200, response.text
            saved = response.json()
            actor = (saved['result']['output']['revision']['editor'] if operation == 'revisions'
                else saved['review']['reviewer'])
            assert actor == expected_actor
            if operation == 'revisions':
                override = saved['result']['output']['answer_diagnosis']['events'][1]['human_override']
                assert override['editor'] == expected_actor
                assert override['after'] == 'INCLUDE_AS_OPTION'
            db.refresh(result)
            assert result.output_json == original
    finally:
        db.close()
        engine.dispose()


def test_release_audit_routes_bind_server_identity():
    # Route coverage supplements the persisted-record tests, not vice versa.
    names = {'authorize_citation_contribution_execution', 'review_citation_contribution',
        'start_source_preparation', 'reuse_source_completion', 'submit_source_manual_content',
        'waive_prepared_source', 'complete_source_preparation', 'revise_diagnosis', 'review_diagnosis',
        'create_qualification_critic', 'create_qualification_critic_supplemental',
        'create_qualification_critic_phase_b1_review', 'revise_strategy', 'review_strategy',
        'revise_execution', 'confirm_execution', 'record_execution_publication', 'create_target_brand_truth'}
    actor_fields = {'authorized_by', 'reviewer', 'editor', 'created_by', 'reused_by',
        'submitted_by', 'waived_by', 'confirmer', 'recorder', 'reviewed_by'}
    app = create_release_app(validate_on_startup=False)
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.endpoint.__name__ in names]
    assert {r.endpoint.__name__ for r in routes} == names
    for route in routes:
        assert any(d.call is authenticated_actor for d in route.dependant.dependencies), route.path
        code = ast.parse(inspect.getsource(route.endpoint))
        arguments = [node for node in ast.walk(code) if isinstance(node, ast.keyword) and node.arg in actor_fields]
        assert arguments, route.path
        assert all(isinstance(arg.value, ast.Name) and arg.value.id == 'actor' for arg in arguments), route.path

from hashlib import sha256
import json
import re

from fastapi.routing import APIRoute
from release_test_client import TestClient

from app.core.release_access import require_project_access
from app.core.release_database import get_release_db
from app.release_main import create_release_app
from test_automatic_delivery import scene

KEY = 'isolated-route-matrix-invitation-not-real-0123456789'


def configure(tmp_path, monkeypatch):
    path = tmp_path / 'access-matrix.json'
    path.write_text(json.dumps({'accounts': [{
        'name': 'project-two', 'key_sha256': sha256(KEY.encode()).hexdigest(), 'project_ids': [2],
    }]}))
    path.chmod(0o600)
    monkeypatch.setenv('GEO_RELEASE_ACCESS_CONFIG', str(path))


def test_every_release_business_route_requires_project_permission_before_database(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    app = create_release_app(validate_on_startup=False)
    def forbidden_db():
        raise AssertionError('Denied request reached business database')
    app.dependency_overrides[get_release_db] = forbidden_db
    routes = [route for route in app.routes if isinstance(route, APIRoute)
        and route.path.startswith('/api/') and not route.path.startswith('/api/access/')
        and route.path != '/api/health']
    assert {'/api/projects', '/api/v2/single-prompt/optimization-tasks/{task_id}'} <= {r.path for r in routes}
    for route in routes:
        assert any(dep.call is require_project_access for dep in route.dependant.dependencies), route.path
    with TestClient(app, base_url='https://geo.example', client=('192.0.2.90', 8000)) as client:
        for logged_in, expected in [(False, 401), (True, 403)]:
            if logged_in:
                assert client.post('/api/access/session', json={'access_key': KEY}).status_code == 200
            for route in routes:
                if logged_in and route.path in {'/api/projects', '/api/platforms'}:
                    # Authorized catalog lists filter their own rows; checked separately.
                    methods = route.methods - {'GET'}
                else:
                    methods = route.methods
                path = re.sub(r'\{[^}]+\}', '1', route.path)
                for method in methods:
                    response = client.request(method, path, params={'project_id': 1, 'prompt_id': 44},
                        **({'json': {'project_id': 1, 'prompt_id': 44}} if method != 'GET' else {}))
                    assert response.status_code == expected, (method, path, response.status_code, response.text)


def test_foreign_object_ids_cannot_be_disguised_as_authorized_project(scene, monkeypatch):
    from app.models import Project, SinglePromptSourcePreparation
    from app.modules.single_prompt_v2.context_provider import save_context
    from scripts.release_upgrade_check import business_fingerprint
    db, task, _, tmp_path = scene
    db.add(Project(id=2, organization_id=db.get(Project, 1).organization_id,
        name='Authorized other project', brand_name='Other brand'))
    db.commit()
    context = save_context(db, project_id=1, expected_version=0, title='Private original',
        content='PRIVATE_CONTEXT_BODY_NOT_FOR_PROJECT_TWO', source_reference='internal')
    preparation = db.query(SinglePromptSourcePreparation).one()
    configure(tmp_path, monkeypatch)
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    prefix = '/api/v2/single-prompt'
    query = {'project_id': 2, 'prompt_id': 44}
    reads = [
        f'{prefix}/analyses/{task.analysis_id}',
        f'{prefix}/analyses/{task.analysis_id}/optimization-tasks',
        f'{prefix}/analyses/{task.analysis_id}/source-preparation',
        f'{prefix}/analyses/{task.analysis_id}/diagnoses/diagnosis-contribution-fixture',
        f'{prefix}/source-preparations/{preparation.preparation_id}',
        f'{prefix}/optimization-tasks/{task.task_id}',
        f'{prefix}/optimization-tasks/{task.task_id}/deliveries',
        f'/api/v2/projects/2/brand-contexts/{context.context_version_id}',
        '/api/v2/projects/2/prompts/44/monitor',
    ]
    before = business_fingerprint(db.get_bind().url.database)
    with TestClient(app, base_url='https://geo.example', client=('192.0.2.91', 8000)) as client:
        assert client.post('/api/access/session', json={'access_key': KEY}).status_code == 200
        assert [row['id'] for row in client.get('/api/projects').json()] == [2]
        # Scoped collections deliberately return no visible rows, not an object error.
        assert client.get(f'{prefix}/analyses/{task.analysis_id}/citation-contributions', params=query).json() == []
        for path in reads:
            response = client.get(path, params=query)
            assert response.status_code in {404, 409}, (path, response.status_code, response.text)
            assert set(response.json()) == {'detail'}
            assert 'PRIVATE_CONTEXT_BODY_NOT_FOR_PROJECT_TWO' not in response.text
        writes = [
            (f'{prefix}/optimization-tasks/{task.task_id}/{action}', {**query, 'expected_revision': task.revision})
            for action in ['cancel', 'resume']
        ] + [(f'{prefix}/source-preparations/{preparation.preparation_id}/auto-fetch', query)]
        for path, body in writes:
            response = client.post(path, json=body)
            assert response.status_code in {404, 409}, (path, response.status_code, response.text)
        assert client.post(f'{prefix}/analyses/{task.analysis_id}/retry', params=query).status_code == 409
    assert business_fingerprint(db.get_bind().url.database) == before

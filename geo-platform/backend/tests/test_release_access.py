from hashlib import sha256
import json

from fastapi import Depends, FastAPI
from release_test_client import TestClient
import pytest

from app.core.release_access import install_access, require_project_access


KEY = 'isolated-test-invitation-not-a-real-secret-0123456789'


def app():
    instance = FastAPI()
    install_access(instance, ['http://127.0.0.1:5173'])
    @instance.get('/api/projects/{project_id}', dependencies=[Depends(require_project_access)])
    def project(project_id: int):
        return {'id': project_id}
    @instance.post('/api/projects', dependencies=[Depends(require_project_access)])
    def create():
        return {'created': True}
    return instance


@pytest.fixture
def invitation(tmp_path, monkeypatch):
    path = tmp_path / 'access.json'
    data = {'accounts': [{'name': 'operator', 'key_sha256': sha256(KEY.encode()).hexdigest(), 'project_ids': [1]}]}
    path.write_text(json.dumps(data)); path.chmod(0o600)
    monkeypatch.setenv('GEO_RELEASE_ACCESS_CONFIG', str(path))
    return path, data


def test_invitation_scope_revocation_and_logout(invitation):
    path, data = invitation
    client = TestClient(app(), base_url='https://geo.example', client=('192.0.2.10', 8000))
    assert client.get('/api/projects/1').status_code == 401
    login = client.post('/api/access/session', json={'access_key': KEY})
    assert login.status_code == 200
    assert all(x in login.headers['set-cookie'] for x in ['HttpOnly', 'Secure', 'SameSite=strict'])
    assert client.get('/api/projects/1').status_code == 200
    assert client.get('/api/projects/2').status_code == 403
    assert client.get('/api/projects/1?project_id=2').status_code == 403
    assert client.post('/api/projects?project_id=1', json={}).status_code == 403
    data['accounts'][0]['project_ids'] = [2]
    path.write_text(json.dumps(data))
    assert client.get('/api/projects/1').status_code == 403
    assert client.get('/api/projects/2').status_code == 200
    assert client.post('/api/access/session', json={'access_key': KEY}, headers={'Origin': 'https://attacker.example'}).status_code == 403
    client.delete('/api/access/session')
    assert client.get('/api/projects/2').status_code == 401


def test_fail_closed_remote_no_tls_and_rate_limit(invitation):
    instance = app()
    remote = TestClient(instance, base_url='http://geo.example', client=('192.0.2.11', 8000))
    assert remote.get('/api/access/session').status_code == 403
    remote = TestClient(instance, base_url='https://geo.example', client=('192.0.2.11', 8000))
    for _ in range(5):
        assert remote.post('/api/access/session', json={'access_key': 'wrong' * 10}).status_code == 401
    assert remote.post('/api/access/session', json={'access_key': KEY}).status_code == 429


def test_local_only_requires_real_loopback_and_safe_origin(monkeypatch):
    monkeypatch.delenv('GEO_RELEASE_ACCESS_CONFIG', raising=False)
    instance = app()
    local = TestClient(instance, base_url='http://127.0.0.1', client=('127.0.0.1', 8000))
    assert local.get('/api/projects/1').status_code == 200
    assert 'noindex' in local.get('/api/projects/1').headers['x-robots-tag']
    assert local.post('/api/projects', headers={'Origin': 'https://attacker.example'}).status_code == 403
    rebound = TestClient(instance, base_url='http://attacker.example', client=('127.0.0.1', 8000))
    assert rebound.get('/api/projects/1').status_code == 403
    remote = TestClient(instance, base_url='http://127.0.0.1', client=('192.0.2.10', 8000))
    assert remote.get('/api/projects/1').status_code == 403

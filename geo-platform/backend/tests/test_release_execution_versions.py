"""Exact-version reads and mutation scope checks through the release router."""
import json
from hashlib import sha256

import pytest

from release_test_client import TestClient
from app.core.release_database import get_release_db
from app.release_main import create_release_app
from app.modules.single_prompt_v2.execution import create_execution_proposal, revise_execution_proposal
from scripts.release_upgrade_check import business_fingerprint
from test_single_prompt_v2_execution import _session, _create_proposal, _ready_edit, _create_confirmed_publication


def _client(db):
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    return TestClient(app, base_url='http://127.0.0.1')


def _url(strategy, proposal):
    return f'/api/v2/single-prompt/strategies/{strategy.strategy_id}/execution-proposals/{proposal.proposal_id}'


def _revision(original):
    return {'project_id': 1, 'prompt_id': 44, 'base_result_version': original.result_version,
            'base_result_hash': original.output_hash, 'reviewable_set_hash': original.reviewable_set_hash,
            'editor': 'isolated-reviewer', 'edit': _ready_edit(json.loads(original.output_json))}


def test_detail_reads_exact_old_or_current_version_without_writes(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, _, proposal, original = _create_proposal(db)
        revised = revise_execution_proposal(db, proposal_id=proposal.proposal_id,
            base_result_version=original.result_version, base_result_hash=original.output_hash,
            reviewable_set_hash=original.reviewable_set_hash, editor='isolated-reviewer',
            edit=_ready_edit(json.loads(original.output_json)))
        before = business_fingerprint(tmp_path / 'v2-execution.db')
        with _client(db) as client:
            for version in [original.result_version, revised.result_version, None]:
                params = {'project_id': 1, 'prompt_id': 44}
                if version is not None:
                    params['result_version'] = version
                response = client.get(_url(strategy, proposal), params=params)
                assert response.status_code == 200
                value = response.json()
                expected = original if version == original.result_version else revised
                assert value['result']['result_version'] == expected.result_version
                assert value['result']['output_hash'] == expected.output_hash
                assert value['result']['output'] == json.loads(expected.output_json)
                assert value['version_selection'] == {
                    'active_result_version': revised.result_version,
                    'is_active_result': expected is revised,
                }
                if expected is original:
                    assert value['allowed_operations'] == ['VIEW']
                    assert value['delivery_status']['next_action'] == 'VIEW_HISTORY'
                else:
                    assert 'REVISE' in value['allowed_operations']
            stale = client.post(_url(strategy, proposal) + f'/results/{original.result_version}/revisions', json=_revision(original))
            assert stale.status_code == 409
            stale_confirm = client.post(_url(strategy, proposal) + f'/results/{original.result_version}/confirmations', json={
                'project_id': 1, 'prompt_id': 44, 'result_hash': original.output_hash,
                'reviewable_set_hash': original.reviewable_set_hash, 'idempotency_key': 'stale-confirm',
                'confirmer': 'isolated-reviewer', 'note': ''})
            assert stale_confirm.status_code == 409
        assert business_fingerprint(tmp_path / 'v2-execution.db') == before
    finally:
        db.close()
        engine.dispose()


def test_detail_missing_empty_or_foreign_version_never_falls_back(tmp_path):
    db, engine = _session(tmp_path)
    try:
        strategy, _, proposal, original = _create_proposal(db)
        other, foreign, _ = create_execution_proposal(db,
            strategy_id=strategy.strategy_id, strategy_result_version=proposal.strategy_result_version,
            project_id=1, prompt_id=44, direction_id=proposal.direction_id,
            idempotency_key='different-proposal', strategy_result_hash=proposal.strategy_result_hash,
            strategy_review_id=proposal.strategy_review_id,
            strategy_review_snapshot_hash=proposal.strategy_review_snapshot_hash)
        assert other.proposal_id != proposal.proposal_id
        before = business_fingerprint(tmp_path / 'v2-execution.db')
        with _client(db) as client:
            for version in ['', 'missing', foreign.result_version]:
                response = client.get(_url(strategy, proposal), params={
                    'project_id': 1, 'prompt_id': 44, 'result_version': version})
                assert response.status_code == 404
                assert response.json()['detail'] == '指定执行方案结果版本不存在或不属于当前方案'
            assert client.get(_url(strategy, proposal), params={
                'project_id': 2, 'prompt_id': 44, 'result_version': original.result_version}).status_code == 409
        assert business_fingerprint(tmp_path / 'v2-execution.db') == before
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize('operation', ['revisions', 'confirmations', 'publications'])
@pytest.mark.parametrize('wrong_scope', ['project', 'prompt', 'strategy'])
def test_execution_mutation_rejects_wrong_scope_before_any_commit(tmp_path, operation, wrong_scope):
    db, engine = _session(tmp_path)
    try:
        if operation == 'publications':
            from app.models import SinglePromptExecutionProposal
            strategy, _, confirmation, publication = _create_confirmed_publication(db)
            proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=confirmation.proposal_id).one()
            url = _url(strategy, proposal) + f'/confirmations/{confirmation.confirmation_id}/publications'
            body = {**json.loads(publication.report_json), 'project_id': 1, 'prompt_id': 44,
                    'idempotency_key': 'wrong-scope-new-report', 'recorder': 'isolated-reviewer'}
        else:
            strategy, _, proposal, original = _create_proposal(db)
            if operation == 'confirmations':
                original = revise_execution_proposal(db, proposal_id=proposal.proposal_id,
                    base_result_version=original.result_version, base_result_hash=original.output_hash,
                    reviewable_set_hash=original.reviewable_set_hash, editor='isolated-reviewer',
                    edit=_ready_edit(json.loads(original.output_json)))
                body = {'project_id': 1, 'prompt_id': 44, 'result_hash': original.output_hash,
                        'reviewable_set_hash': original.reviewable_set_hash, 'idempotency_key': 'wrong-scope-confirm',
                        'confirmer': 'isolated-reviewer', 'note': ''}
            else:
                body = _revision(original)
            url = _url(strategy, proposal) + f'/results/{original.result_version}/{operation}'
        if wrong_scope == 'strategy':
            url = url.replace(strategy.strategy_id, 'wrong-strategy')
        else:
            body[wrong_scope + '_id'] = 999
        before = business_fingerprint(tmp_path / 'v2-execution.db')
        with _client(db) as client:
            response = client.post(url, json=body)
            assert response.status_code == (404 if wrong_scope == 'strategy' else 409), response.text
        assert business_fingerprint(tmp_path / 'v2-execution.db') == before
        if wrong_scope == 'project':
            with _client(db) as client:
                accepted = client.post(url, json={**body, 'project_id': 1})
                assert accepted.status_code in {200, 201}, accepted.text
            assert business_fingerprint(tmp_path / 'v2-execution.db') != before
    finally:
        db.close()
        engine.dispose()


def test_invited_project_cannot_mutate_foreign_proposal_by_forging_body_scope(tmp_path, monkeypatch):
    key = 'isolated-invitation-version-scope-not-real-secret-012345'
    path = tmp_path / 'access.json'
    path.write_text(json.dumps({'accounts': [{'name': 'project-two',
        'key_sha256': sha256(key.encode()).hexdigest(), 'project_ids': [2]}]}))
    path.chmod(0o600)
    monkeypatch.setenv('GEO_RELEASE_ACCESS_CONFIG', str(path))
    db, engine = _session(tmp_path)
    try:
        strategy, _, proposal, original = _create_proposal(db)
        before = business_fingerprint(tmp_path / 'v2-execution.db')
        with _client(db) as client:
            assert client.post('/api/access/session', json={'access_key': key}).status_code == 200
            body = {**_revision(original), 'project_id': 2}
            assert client.post(_url(strategy, proposal) + f'/results/{original.result_version}/revisions', json=body).status_code == 409
        assert business_fingerprint(tmp_path / 'v2-execution.db') == before
    finally:
        db.close()
        engine.dispose()


def test_historical_confirmation_keeps_exact_publication_recording_identity(tmp_path):
    from app.models import SinglePromptExecutionProposalResult
    db, engine = _session(tmp_path)
    try:
        strategy, proposal, confirmation, publication = _create_confirmed_publication(db)
        old = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=confirmation.result_version).one()
        revised = revise_execution_proposal(db, proposal_id=proposal.proposal_id,
            base_result_version=old.result_version, base_result_hash=old.output_hash,
            reviewable_set_hash=old.reviewable_set_hash, editor='isolated-reviewer',
            edit={**_ready_edit(json.loads(old.output_json)), 'execution_note': 'New version retained separately'})
        old_bytes = old.output_json
        with _client(db) as client:
            response = client.get(_url(strategy, proposal), params={
                'project_id': 1, 'prompt_id': 44, 'result_version': old.result_version})
            assert response.json()['allowed_operations'] == ['VIEW', 'RECORD_PUBLICATION']
            response = client.post(_url(strategy, proposal) + f'/confirmations/{confirmation.confirmation_id}/publications',
                json={**json.loads(publication.report_json), 'project_id': 1, 'prompt_id': 44,
                      'idempotency_key': 'historical-publication', 'recorder': 'isolated-reviewer'})
            assert response.status_code == 201, response.text
            assert response.json()['result']['result_version'] == old.result_version
            assert response.json()['version_selection']['active_result_version'] == revised.result_version
            assert len(response.json()['publications']) == 2
        db.refresh(proposal)
        db.refresh(old)
        assert proposal.active_result_version == revised.result_version
        assert old.output_json == old_bytes
    finally:
        db.close()
        engine.dispose()

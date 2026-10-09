"""Isolated formal API/worker checks; no real model calls or human decisions."""
import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from release_test_client import TestClient
from test_release_first_slice import _migrated_session, _seed_citation_contribution_fixture
from app.core.release_database import get_release_db
from app.models import SinglePromptDiagnosisReview, SinglePromptCitationContributionExecution, SinglePromptCitationContributionResult, SinglePromptPreparedSourceSnapshot
from app.modules.single_prompt_v2.citation_contribution import authorize_citation_contribution, execute_citation_contribution
from app.release_main import create_release_app


def test_partial_source_freeze_is_explicit_immutable_and_not_negative_evidence(tmp_path, monkeypatch):
    from app.models import SinglePromptSourceDisposition, SinglePromptSourceCompletionManifest
    from app.modules.single_prompt_v2.source_preparation import freeze_completion_manifest, validate_completion_for_evidence
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path, reviewed=False)
        source = db.query(SinglePromptSourceDisposition).filter_by(state='READY').one()
        source.state = 'MANUAL_REQUIRED'
        source.active_snapshot_id = None
        db.commit()
        with pytest.raises(HTTPException):
            freeze_completion_manifest(db, preparation_id=source.preparation_id, created_by='test')
        partial = freeze_completion_manifest(db, preparation_id=source.preparation_id, created_by='test', allow_partial=True)
        assert partial.status == 'PARTIAL' and partial.ready_source_count == 0 and partial.waived_source_count == 1
        assert fixture['completion'].status == 'FROZEN'
        assert freeze_completion_manifest(db, preparation_id=source.preparation_id, created_by='test', allow_partial=True).manifest_id == partial.manifest_id
        assert db.query(SinglePromptSourceCompletionManifest).count() == 2
        binding = dict(analysis_id=partial.analysis_id, context_id=partial.context_id,
            citation_manifest_id=partial.citation_manifest_id, citation_manifest_hash=partial.citation_manifest_hash,
            completion_manifest_id=partial.manifest_id, completion_manifest_hash=partial.payload_hash)
        with pytest.raises(HTTPException):
            validate_completion_for_evidence(db, **binding)
        _, snapshots, limits = validate_completion_for_evidence(db, **binding, allow_partial=True)
        assert snapshots == []
        assert {'code': 'SOURCE_NOT_CONSUMABLE', 'source_key': source.source_key,
            'disposition': 'MANUAL_REQUIRED', 'negative_evidence': False} in limits
        assert source.state == 'MANUAL_REQUIRED' and not source.waived_by
    finally:
        db.close(); engine.dispose()


def payload(fixture):
    return dict(project_id=1, prompt_id=44, input_authority='MACHINE_ADMISSION',
        selected_run_id=fixture['run'].id, answer_result_version=fixture['result'].result_version,
        answer_result_hash=fixture['result'].output_hash, citation_manifest_id=fixture['manifest'].manifest_id,
        citation_manifest_hash=fixture['manifest'].payload_hash, completion_manifest_id=fixture['completion'].manifest_id,
        completion_manifest_hash=fixture['completion'].payload_hash, fixed_run_ids=[fixture['run'].id],
        idempotency_key='machine-no-review-plan')


def test_formal_machine_plan_without_review_requires_exact_scope_and_no_implicit_authorization(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path, reviewed=False)
        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db
        client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 55000))
        uri = f"/api/v2/single-prompt/analyses/{fixture['analysis'].analysis_id}/citation-contributions"
        value = payload(fixture)
        response = client.post(uri, json=value)
        assert response.status_code == 201, response.text
        row = db.query(SinglePromptCitationContributionExecution).one()
        frozen = json.loads(row.input_snapshot_json)
        assert frozen['input_authority'] == 'MACHINE_ADMISSION' and frozen['answer_review_id'] is None
        assert row.status == 'AWAITING_EXTERNAL_AUTHORIZATION'
        assert json.loads(row.authorization_json) == {}
        assert client.post(uri, json=value).status_code == 200
        assert client.post(uri, json={**value, 'answer_result_hash': '0'*64}).status_code == 409
        assert client.post(uri, json={**value, 'answer_review_id': 'invented-review'}).status_code == 422
        assert client.post(uri, json={**value, 'selected_run_id': 999}).status_code == 422
        assert client.post(uri, json={**value, 'fixed_run_ids': [fixture['run'].id, 999], 'idempotency_key': 'wrong-full-scope'}).status_code == 409
        assert db.query(SinglePromptDiagnosisReview).count() == 0
        assert db.query(SinglePromptCitationContributionExecution).count() == 1
        assert db.query(SinglePromptCitationContributionResult).count() == 0
    finally:
        db.close(); engine.dispose()


def test_worker_revalidates_machine_plan_before_any_provider_request(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path, reviewed=False)
        from app.modules.single_prompt_v2.citation_contribution import create_citation_contribution_plan
        row, _ = create_citation_contribution_plan(db, analysis_id=fixture['analysis'].analysis_id,
            answer_review_id=None, **payload(fixture))
        plan = json.loads(row.plan_json)['call_plan']
        authorize_citation_contribution(db, contribution_id=row.contribution_id, project_id=1, prompt_id=44,
            plan_hash=row.plan_hash, provider='deepseek', model=plan['model'],
            max_external_requests=plan['max_new_external_requests'], max_total_tokens=plan['conservative_token_ceiling'],
            max_budget_cny=plan['budget_upper_bound_cny'], cost_upper_bound_cny=plan['budget_upper_bound_cny'],
            pricing_basis='ISOLATED_TEST_NO_PROVIDER', authorized_by='isolated-test')
        source = db.query(SinglePromptPreparedSourceSnapshot).one()
        # A missing artifact is a storage failure, not permission to use the cached plan.
        from pathlib import Path
        Path(source.artifact_path).unlink()
        identity = row.contribution_id
        class NeverCalled:
            def judge(self, *args, **kwargs):
                raise AssertionError('Worker must reject before calling provider')
        with pytest.raises(HTTPException):
            execute_citation_contribution(identity, session_factory=Session, judge=NeverCalled())
        db.expire_all()
        failed = db.query(SinglePromptCitationContributionExecution).one()
        assert failed.status == 'FAILED' and failed.external_llm_calls == 0
        assert db.query(SinglePromptCitationContributionResult).count() == 0
        assert db.query(SinglePromptDiagnosisReview).count() == 0
    finally:
        db.close(); engine.dispose()

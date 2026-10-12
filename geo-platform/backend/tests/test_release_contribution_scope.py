"""Release writes must bind the URL analysis before committing any changes."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from release_test_client import TestClient
from test_release_first_slice import _session, _seed_citation_contribution_fixture, _create_contribution_fixture_plan
from app.core.release_database import get_release_db
from app.modules.single_prompt_v2.citation_contribution import execute_citation_contribution
from app.release_main import create_release_app
from scripts.release_upgrade_check import business_fingerprint


class SimulatedJudge:
    def __init__(self):
        self.client = SimpleNamespace(call_count=0, external_call_count=0, external_token_count=0)

    def judge(self, answer_units, passages, candidate_pairs, citation_index=0, db=None):
        self.client.call_count += 1
        self.client.external_call_count += 1
        self.client.external_token_count += 100
        return {"evaluations": [{**pair, "answer_span": None, "source_span": None,
            "correspondence_mode": "NO_CORRESPONDENCE", "evidence_relation": "NO_MATCH",
            "rationale": "Isolated negative fixture"} for pair in candidate_pairs], "no_binding_reason": None}


@pytest.mark.parametrize('operation', ['authorizations', 'reviews'])
def test_wrong_analysis_rejected_before_authorization_or_review_commit(tmp_path, monkeypatch, operation):
    db, engine = _session(tmp_path)
    try:
        fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path, reviewed=False)
        row, _ = _create_contribution_fixture_plan(db, fixture, machine=True)
        analysis_id, contribution_id = row.analysis_id, row.contribution_id
        base = f'/api/v2/single-prompt/analyses/{analysis_id}/citation-contributions/{contribution_id}'
        plan = json.loads(row.plan_json)['call_plan']
        authorization = dict(project_id=row.project_id, prompt_id=row.prompt_id,
            plan_hash=row.plan_hash, provider='deepseek', model=plan['model'],
            max_external_requests=plan['max_new_external_requests'],
            max_total_tokens=plan['conservative_token_ceiling'],
            max_budget_cny=plan['budget_upper_bound_cny'], cost_upper_bound_cny=plan['budget_upper_bound_cny'],
            pricing_basis='ISOLATED_NO_EXTERNAL_CALLS', authorized_by='isolated-test')
        app = create_release_app(validate_on_startup=False)
        app.dependency_overrides[get_release_db] = lambda: db
        with TestClient(app, base_url='http://127.0.0.1') as client:
            if operation == 'authorizations':
                path, body = base + '/authorizations', authorization
            else:
                response = client.post(base + '/authorizations', json=authorization)
                assert response.status_code == 202, response.text
                execute_citation_contribution(contribution_id,
                    session_factory=sessionmaker(bind=engine, expire_on_commit=False), judge=SimulatedJudge())
                db.expire_all()
                response = client.get(base, params={'project_id': row.project_id, 'prompt_id': row.prompt_id})
                assert response.status_code == 200, response.text
                status = response.json()
                result, projection = status['result'], status['human_calibration']
                assert result['output']['evaluations'] and projection['review_targets']
                decisions = [{
                    'target_type': target['target_type'], 'target_id': target['target_id'],
                    'gold_identity': target['gold_identity'], 'human_correspondence_mode': 'NO_CORRESPONDENCE',
                    'human_evidence_relation': 'NO_MATCH', 'span_validity': 'NOT_APPLICABLE',
                    'subject_attribution': 'PRESERVED', 'qualifier_preservation': 'PRESERVED',
                    'decision_role_validity': 'VALID', 'review_comment': 'Isolated fixture gold',
                } for target in projection['review_targets'] if target['requires_human_review']]
                assert all(item['target_type'] == 'EVALUATION' for item in decisions)
                body = dict(project_id=row.project_id, prompt_id=row.prompt_id,
                    result_hash=result['output_hash'], reviewable_set_hash=result['reviewable_set_hash'],
                    calibration_sample_identity=projection['calibration_sample_identity'],
                    binding_census_hash=projection['binding_census_hash'],
                    human_review_set_hash=projection['human_review_set_hash'],
                    reviewer='isolated-test', decisions=decisions, missed_bindings=[], note='Simulated only')
                path = base + f"/results/{result['result_version']}/reviews"
            before = business_fingerprint(tmp_path / 'release-first-slice.db')
            rejected = client.post(path.replace(analysis_id, 'wrong-analysis'), json=body)
            assert rejected.status_code == 404, rejected.text
            assert business_fingerprint(tmp_path / 'release-first-slice.db') == before
            accepted = client.post(path, json=body)
            assert accepted.status_code == (202 if operation == 'authorizations' else 200), accepted.text
            assert business_fingerprint(tmp_path / 'release-first-slice.db') != before
            if operation == 'authorizations':
                assert accepted.json()['execution']['status'] == 'QUEUED'
            else:
                assert accepted.json()['result']['output'] == result['output']
    finally:
        db.close()
        engine.dispose()

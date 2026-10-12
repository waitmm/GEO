"""Explicit asset checks affect publication only, not the checked manuscript."""
import copy
import json

import pytest
from fastapi import HTTPException

from test_automatic_delivery import scene
from test_delivery_revision import delivered
from app.modules.single_prompt_v2.asset_verification import asset_check_errors
from app.modules.single_prompt_v2.execution import revise_execution_proposal, confirm_execution_proposal, _assess_publication_conformance


def _check(selection):
    return dict(asset_type=selection['asset_type'], publication_surface=selection['publication_surface'],
        inventory_scope='Official help center pages checked by the editor', inventory_complete=False,
        no_suitable_existing=False, url='https://example.com/help/guide', title='Existing help page',
        content_version='cms-revision-12', ownership_basis='Assigned editor in brand CMS',
        editable=True, content_fit=True)


@pytest.mark.parametrize('field,value', [('url', 'javascript:alert(1)'), ('url', 'https://user:secret@example.com'),
    ('content_version', ''), ('ownership_basis', ''), ('editable', False), ('content_fit', False),
    ('asset_type', 'OTHER'), ('publication_surface', 'OTHER'), ('editable', 'true')])
def test_update_asset_never_infers_ownership_version_or_permission(field, value):
    selection = {'asset_operation': 'UPDATE_EXISTING', 'asset_type': 'HELP_DOC', 'publication_surface': 'OWNED_HELP_CENTER'}
    selection['asset_verification'] = {**_check(selection), field: value}
    assert asset_check_errors(selection)


def test_empty_inventory_is_not_evidence_for_new_asset():
    selection = {'asset_operation': 'CREATE_NEW', 'asset_type': 'HELP_DOC', 'publication_surface': 'OWNED_HELP_CENTER'}
    assert asset_check_errors(selection) == ['ASSET_VERIFICATION_REQUIRED']
    selection['asset_verification'] = {**_check(selection), 'url': ''}
    assert asset_check_errors(selection) == ['ASSET_INVENTORY_INCOMPLETE']
    selection['asset_verification'].update(inventory_complete=True, no_suitable_existing=True)
    assert asset_check_errors(selection) == []


def test_asset_revision_preserves_text_qa_old_results_and_task_without_calls(delivered):
    db, parent, base, calls, _, _ = delivered
    original, task_input, progress = base.output_json, parent.input_json, parent.progress_json
    output = json.loads(original)
    edit = copy.deepcopy(output['selection'])
    edit.update(asset_operation='UPDATE_EXISTING', asset_verification=_check(edit))
    edit.update(publishing_account='brand-editor', publishing_location='help-center', account_control_status='USER_REPORTED_CONTROL')
    args = dict(proposal_id=base.proposal_id, base_result_version=base.result_version,
        base_result_hash=base.output_hash, reviewable_set_hash=base.reviewable_set_hash, editor='asset-editor')
    forged = copy.deepcopy(edit)
    forged['asset_verification']['system_verified'] = True
    with pytest.raises(HTTPException, match='核查字段不合法'):
        revise_execution_proposal(db, **args, edit=forged)
    revised = revise_execution_proposal(db, **args, edit=edit)
    saved = json.loads(revised.output_json)
    assert saved['asset_operation'] == 'UPDATE_EXISTING'
    assert saved['validation']['validators']['asset_operation_selected'] == 'PASS'
    assert saved['validation']['content_delivery_status'] == 'READY'
    assert saved['validation']['status'] == 'READY_FOR_CONFIRMATION'
    assert saved['asset_verification_receipt']['provenance'] == 'USER_REPORTED'
    assert saved['asset_verification_receipt']['system_verified'] is False
    assert saved['asset_verification_receipt']['editor'] == 'asset-editor'
    for key in ('delivery_input', 'publication_draft', 'generation_receipt', 'automatic_qa'):
        assert saved[key] == output[key]
    db.refresh(base)
    db.refresh(parent)
    assert base.output_json == original and parent.input_json == task_input and parent.progress_json == progress
    assert len(calls) == 4
    confirmation, created = confirm_execution_proposal(db, proposal_id=base.proposal_id,
        result_version=revised.result_version, result_hash=revised.output_hash,
        reviewable_set_hash=revised.reviewable_set_hash, idempotency_key='isolated-asset-confirm',
        confirmer='asset-editor', note='Offline only')
    assert created
    confirmed = json.loads(confirmation.confirmation_snapshot_json)
    report = dict(actual_account='brand-editor', actual_location='help-center',
        actual_content_version=revised.result_version, actual_url=edit['asset_verification']['url'])
    assert _assess_publication_conformance(report, confirmed)['conformance'] == 'MATCHED'
    mismatch = _assess_publication_conformance({**report, 'actual_url': 'https://example.com/other'}, confirmed)
    assert mismatch['conformance'] == 'OUTSIDE_CONFIRMED_SCOPE'
    assert mismatch['mismatches'] == ['ASSET_URL_DIFFERS_FROM_CONFIRMATION']
    with pytest.raises(HTTPException, match='版本已变化'):
        revise_execution_proposal(db, **args, edit=edit)


def test_incomplete_asset_check_saves_draft_but_cannot_grant_publication(delivered):
    db, _, base, calls, _, _ = delivered
    original = json.loads(base.output_json)
    revised = revise_execution_proposal(db, proposal_id=base.proposal_id,
        base_result_version=base.result_version, base_result_hash=base.output_hash,
        reviewable_set_hash=base.reviewable_set_hash, editor='asset-editor', edit={'asset_operation': 'CREATE_NEW'})
    output = json.loads(revised.output_json)
    assert output['validation']['status'] == 'READY_FOR_BUSINESS_INPUT'
    assert output['validation']['content_delivery_status'] == 'READY'
    assert output['validation']['publication_status'] == 'NEEDS_BUSINESS_CONFIRMATION'
    assert 'ASSET_VERIFICATION_REQUIRED' in output['validation']['errors']
    assert output['publication_draft'] == original['publication_draft'] and len(calls) == 4

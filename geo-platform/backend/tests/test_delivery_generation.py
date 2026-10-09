import copy

import pytest
from pydantic import ValidationError

from app.modules.single_prompt_v2.delivery_generation import (
    DraftResponse, TextQAResponse, admit_draft, admit_qa, finish_draft, generate_and_check,
    generation_input, segments_of, revalidate_generated_draft,
)
from app.modules.single_prompt_v2.delivery_text import text_digest
from app.modules.single_prompt_v2.execution import _machine_public_truths


@pytest.fixture
def frozen():
    text = '仅在电源断开时，甲厂过滤器可以拆卸清洗。不支持带电清洗。'
    return {'prompt_text': '空气过滤器如何清洗', 'prompt_configuration': {'intent_type': 'usage_instruction'},
        'brand': {'brand_name': '乙厂'}, 'question_topics': [], 'strategy_direction': {},
        'brand_context': {'context_version_id': 'brand:v1', 'passages': []},
        'selected_evidence': [{'section_id': 'source:1', 'passage_text': text, 'passage_hash': text_digest(text),
            'title': '甲厂维护手册', 'url': 'https://example.com/manual', 'snapshot_id': 'snap:1',
            'passage_id': 'passage:1', 'binding_id': 'binding:1', 'evidence_relation': 'SUPPORTS_PARTIAL'}]}


def draft(text='先核对过滤器的型号与维护说明；断电和晾干条件不清楚时不要开始拆卸。', kind='INSTRUCTION', ids=None):
    return {'sections': [{'heading': '开始清洗前先核对条件',
        'blocks': [{'kind': kind, 'text': text, 'evidence_ids': ids or []}]}]}


def all_pass(value):
    return {'checks': [{'segment_id': s['segment_id'], 'verdict': 'PASS', 'rationale': '建议没有增加能力承诺。'}
        for s in segments_of(value)]}


def test_kernel_uses_frozen_input_and_both_production_admissions(frozen):
    calls = []
    stages = []
    class Client:
        def structured_generate_sync(self, **kwargs):
            calls.append(kwargs)
            assert stages[-1] == ("DRAFT" if len(calls) == 1 else "TEXT_QA")
            value = draft() if len(calls) == 1 else all_pass(draft())
            kwargs['response_schema'].model_validate(value)
            return kwargs['response_validator'](value)
    before = copy.deepcopy(frozen)
    result = generate_and_check(frozen, client=Client(), on_stage=stages.append)
    assert stages == ["DRAFT", "TEXT_QA"]
    assert frozen == before and len(calls) == 2
    assert all(c['structured_output_mode'] == 'JSON_SCHEMA' and c['strict_json'] for c in calls)
    assert '过滤器' in result['body_markdown'] and '抖音' not in result['body_markdown']
    assert result['qa']['status'] == 'READY' and result['qa']['repairs'] == []
    assert result['qa']['checked_content_hash'] == text_digest(result['body_markdown'])


@pytest.mark.parametrize('change', ['number', 'subject', 'condition'])
def test_static_checks_override_model_pass_and_record_real_local_repair(frozen, change):
    text = frozen['selected_evidence'][0]['passage_text']
    text = text + '清洗效率提升99%。' if change == 'number' else text.replace('甲厂', '乙厂') if change == 'subject' else text.replace('仅在电源断开时，', '')
    value = draft(text, 'SOURCE_STATEMENT', ['source:1'])
    result = finish_draft(value, all_pass(value), generation_input(frozen))
    assert result['qa']['findings'] and len(result['qa']['repairs']) == 1
    repair = result['qa']['repairs'][0]
    assert repair['before'] != repair['after'] and repair['recheck'] == 'PASS'
    assert '99%' not in result['body_markdown'] and '乙厂过滤器' not in result['body_markdown']
    assert '仅在电源断开时' in result['body_markdown']


def test_missing_fake_and_cross_brand_evidence_are_rejected(frozen):
    inputs = generation_input(frozen)
    for value in [draft('乙厂支持带电清洗', 'TARGET_STATEMENT', ['source:1']),
                  draft('过滤器可带电清洗', 'SOURCE_STATEMENT'),
                  draft('过滤器可清洗', 'SOURCE_STATEMENT', ['invented'])]:
        with pytest.raises(ValueError):
            admit_draft(value, inputs)


def public_truth():
    return {'truth_id': 7, 'capability_label': '支持离线备份（仅限本地设备）',
        'product_truth_status': 'SUPPORTED', 'truth_source': 'MANUAL_CONFIRMED',
        'source_reference': 'https://example.com/target-manual',
        'statement_eligibility': {'status': 'ELIGIBLE', 'issues': []}}


def qualified_truths(truth):
    return _machine_public_truths({'object_qualifications': [{'object_id': '7',
        'object_type': 'PRODUCT_TRUTH', 'eligibility_by_use': {'public_claim': 'CONSUMABLE'}}]},
        {'truth_ids': [7]}, {'truth_diagnosis': {'truth_snapshot': [truth]}})


def test_qualified_target_fact_is_consumed_with_exact_provenance_and_conditions(frozen):
    frozen['truths'] = qualified_truths(public_truth())
    inputs = generation_input(frozen)
    fact = next(row for row in inputs['public_evidence'] if row['kind'] == 'TARGET_VERIFIED')
    assert fact['truth_id'] == 7 and fact['url'] == public_truth()['source_reference']
    assert fact['text'] == '乙厂：支持离线备份（仅限本地设备）'
    value = draft(fact['text'], 'TARGET_STATEMENT', ['truth:7'])
    assert finish_draft(value, all_pass(value), inputs)['qa']['repairs'] == []
    inflated = draft('乙厂支持离线备份', 'TARGET_STATEMENT', ['truth:7'])
    repaired = finish_draft(inflated, all_pass(inflated), inputs)
    assert repaired['qa']['repairs'][0]['after'] == ''
    assert 'QUALIFIER_NOT_PRESERVED' in repaired['qa']['findings'][0]['issue_codes']


def test_internal_truth_missing_source_or_tampered_snapshot_cannot_become_public(frozen):
    from fastapi import HTTPException
    truth = public_truth()
    truth['source_reference'] = ''
    with pytest.raises(HTTPException):
        qualified_truths(truth)
    frozen['truths'] = qualified_truths(public_truth())
    frozen['truths'][0]['capability_label'] = '支持云端备份'
    with pytest.raises(ValueError, match='TARGET_TRUTH_PROVENANCE_INVALID'):
        generation_input(frozen)
    unqualified = {'object_qualifications': [{'object_id': '7', 'object_type': 'PRODUCT_TRUTH',
        'eligibility_by_use': {'public_claim': 'VERIFY_FIRST'}}]}
    assert _machine_public_truths(unqualified, {'truth_ids': [7]},
        {'truth_diagnosis': {'truth_snapshot': [public_truth()]}}) == []


def test_qa_cannot_skip_or_duplicate_segments_or_return_only_self_summary():
    value = draft()
    rows = segments_of(value)
    with pytest.raises(ValueError):
        admit_qa({'checks': all_pass(value)['checks'][:1]}, rows)
    with pytest.raises(ValueError):
        admit_qa({'checks': all_pass(value)['checks'] + all_pass(value)['checks'][:1]}, rows)
    with pytest.raises(ValidationError):
        TextQAResponse.model_validate({'status': 'READY'})


def test_no_sources_do_not_become_invented_facts_and_rejected_all_is_not_success(frozen):
    frozen['selected_evidence'] = []
    value = draft()
    inputs = generation_input(frozen)
    assert admit_draft(value, inputs) == value
    with pytest.raises(ValueError):
        admit_draft(draft('过滤器可以带电清洗', 'SOURCE_STATEMENT'), inputs)
    qa = all_pass(value)
    qa['checks'][1].update(verdict='UNSUPPORTED', rationale='该操作不适用于已给输入。')
    result = finish_draft(value, qa, inputs)
    assert result['qa']['status'] == 'NO_DELIVERABLE_CONTENT'
    assert result['qa']['repairs'][0]['after'] == ''


def test_private_context_is_not_a_public_claim_source(frozen):
    secret = '这是一段仅用于内部讨论且没有允许对外公开的长段产品资料内容'
    frozen['brand_context']['passages'] = [{'text': secret}]
    value = draft(secret)
    result = finish_draft(value, all_pass(value), generation_input(frozen))
    assert secret not in result['body_markdown']
    assert 'PRIVATE_CONTEXT_LEAK' in result['qa']['findings'][0]['issue_codes']


def test_provider_and_local_schema_share_actual_limits():
    schema = DraftResponse.model_json_schema()
    assert schema['$defs']['DraftBlock']['properties']['text']['maxLength'] == 1200
    assert schema['properties']['sections']['maxItems'] == 8
    with pytest.raises(ValidationError):
        DraftResponse.model_validate(draft('x' * 1201))


def test_saved_qa_flag_and_repairs_are_recomputed_not_trusted(frozen):
    value = draft()
    result = finish_draft(value, all_pass(value), generation_input(frozen))
    assert revalidate_generated_draft(frozen, result)['repairs'] == []
    tampered = copy.deepcopy(result)
    tampered['qa']['repairs'] = [{'result': 'APPLIED'}]
    with pytest.raises(ValueError, match='MUTATED'):
        revalidate_generated_draft(frozen, tampered)
    tampered = copy.deepcopy(result)
    tampered['body_markdown'] += '\n乙厂保证99%提升'
    with pytest.raises(ValueError, match='MUTATED'):
        revalidate_generated_draft(frozen, tampered)


def test_irrelevant_claim_is_removed_not_replaced_with_irrelevant_source_quote(frozen):
    value = draft(frozen['selected_evidence'][0]['passage_text'], 'SOURCE_STATEMENT', ['source:1'])
    qa = all_pass(value)
    qa['checks'][1].update(verdict='IRRELEVANT', rationale='该型号不在本题适用范围。')
    result = finish_draft(value, qa, generation_input(frozen))
    assert result['qa']['status'] == 'NO_DELIVERABLE_CONTENT'
    assert result['qa']['repairs'][0]['after'] == ''

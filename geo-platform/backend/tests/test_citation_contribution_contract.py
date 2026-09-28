from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.single_prompt_v2.citation_contribution import (
    CITATION_CONTRIBUTION_PROMPT_VERSION,
    CITATION_CONTRIBUTION_SCHEMA_VERSION,
    SEMANTIC_LLM_TRANSPORT_VERSION,
    CitationContributionJudge,
    CitationContributionResponse,
    _canary_gate_result,
    build_citation_contribution_system_prompt,
    citation_contribution_response_examples,
    citation_contribution_response_schema,
)
from app.modules.single_prompt_v2.schemas import CitationContributionCalibrationDecision
from app.services.semantic_llm import deepseek


ROOT = Path(__file__).resolve().parent


def _valid_response() -> dict:
    return {
        "evaluations": [{
            "candidate_pair_index": 0,
            "answer_unit_index": 0,
            "citation_index": 0,
            "passage_index": 0,
            "answer_span": "支持批量生成短链",
            "source_span": "支持批量生成短链",
            "correspondence_mode": "DIRECT_REUSE",
            "evidence_relation": "SUPPORTS_FULL",
            "rationale": "两个固定片段直接对应",
        }],
        "no_binding_reason": None,
    }


def test_old_p1_failed_responses_are_permanent_rejection_fixtures():
    fixtures = json.loads(
        (ROOT / "fixtures/citation_contribution_p1_failed_schema_golden.json").read_text()
    )
    assert len(fixtures) == 19
    assert len({item["artifact_hash"] for item in fixtures}) == 19
    for item in fixtures:
        with pytest.raises(ValidationError):
            CitationContributionResponse.model_validate(item["payload"])


def test_typed_schema_is_the_prompt_and_example_source():
    schema = citation_contribution_response_schema()
    examples = citation_contribution_response_examples()
    prompt = build_citation_contribution_system_prompt()

    assert set(schema["required"]) == {"evaluations", "no_binding_reason"}
    assert schema["additionalProperties"] is False
    assert json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")) in prompt
    assert json.dumps(examples, ensure_ascii=False, sort_keys=True, separators=(",", ":")) in prompt
    assert '"results"' not in prompt
    assert '"candidate_pairs"' not in prompt
    assert examples[0]["evaluations"] and examples[0]["no_binding_reason"] is None
    assert examples[1]["evaluations"] == [] and examples[1]["no_binding_reason"]


@pytest.mark.parametrize(
    "payload",
    [
        {"evaluations": [], "no_binding_reason": None},
        {"evaluations": [], "no_binding_reason": "  "},
        {**_valid_response(), "no_binding_reason": "不应同时存在"},
        {**_valid_response(), "unknown": True},
        {"evaluations": "not-a-list", "no_binding_reason": "原因"},
    ],
)
def test_top_level_schema_and_cross_field_contract_reject_invalid_shapes(payload):
    with pytest.raises(ValidationError):
        CitationContributionResponse.model_validate(payload)


def test_dynamic_gate_maps_frozen_indexes_and_rejects_semantic_span_sentinels():
    unit = {
        "answer_unit_id": "au-internal",
        "raw_text": "支持批量生成短链",
        "context_heading": "",
        "primary_type": "FACT",
        "semantic_facets": [],
    }
    passage = {"passage_id": "psg-internal", "text": "支持批量生成短链。"}
    pair = {"answer_unit_id": "au-internal", "passage_id": "psg-internal"}

    class StaticClient:
        def __init__(self, payload):
            self.payload = payload
            self.kwargs = None

        def structured_generate_sync(self, **kwargs):
            self.kwargs = kwargs
            return kwargs["response_validator"](self.payload)

    client = StaticClient(_valid_response())
    admitted = CitationContributionJudge(client).judge([unit], [passage], [pair])
    assert admitted["evaluations"][0]["answer_unit_id"] == "au-internal"
    assert admitted["evaluations"][0]["passage_id"] == "psg-internal"
    assert client.kwargs["structured_output_mode"] == "JSON_SCHEMA"
    assert client.kwargs["transport_version"] == SEMANTIC_LLM_TRANSPORT_VERSION
    assert client.kwargs["prompt_version"] == CITATION_CONTRIBUTION_PROMPT_VERSION
    assert client.kwargs["schema_version"] == CITATION_CONTRIBUTION_SCHEMA_VERSION
    assert client.kwargs["user_payload"]["frozen_candidate_pairs"] == [{
        "candidate_pair_index": 0,
        "answer_unit_index": 0,
        "citation_index": 0,
        "passage_index": 0,
    }]
    assert "answer_unit_id" not in json.dumps(client.kwargs["user_payload"])
    assert "passage_id" not in json.dumps(client.kwargs["user_payload"])

    negative = _valid_response()
    negative["evaluations"][0].update({
        "answer_span": None,
        "source_span": "NO_MATCH",
        "correspondence_mode": "NO_CORRESPONDENCE",
        "evidence_relation": "NO_MATCH",
    })
    with pytest.raises(Exception, match="不得携带"):
        CitationContributionJudge(StaticClient(negative)).judge([unit], [passage], [pair])


def test_deepseek_json_schema_mode_sends_provider_schema_via_responses_api(monkeypatch):
    captured: dict = {}
    raw = _valid_response()

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "status": "completed",
                "model": "deepseek-flash",
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(raw, ensure_ascii=False)}],
                }],
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            }

    class FakeHttpClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, headers, json):
            captured.update({"url": url, "body": json})
            return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = deepseek.DeepSeekClient(thinking_mode="disabled", max_attempts=1)
    client.settings.deepseek_api_key = "test-key"
    result = client.structured_generate_sync(
        system_prompt=build_citation_contribution_system_prompt(),
        user_payload={"untrusted": "data"},
        response_schema=CitationContributionResponse,
        prompt_version=CITATION_CONTRIBUTION_PROMPT_VERSION,
        schema_version=CITATION_CONTRIBUTION_SCHEMA_VERSION,
        strict_json=True,
        response_validator=lambda payload: CitationContributionResponse.model_validate(payload).model_dump(mode="json"),
        structured_output_mode="JSON_SCHEMA",
        transport_version=SEMANTIC_LLM_TRANSPORT_VERSION,
    )

    assert result == raw
    assert captured["url"].endswith("/responses")
    assert "response_format" not in captured["body"]
    assert captured["body"]["model"] == "deepseek-flash"
    assert captured["body"]["reasoning"] == {"effort": "none"}
    assert captured["body"]["text"]["format"] == {
        "type": "json_schema",
        "name": "CitationContributionResponse",
        "schema": citation_contribution_response_schema(),
    }
    assert client.external_call_count == 1
    assert client.external_token_count == 18
    assert client.external_input_token_count == 11
    assert client.external_output_token_count == 7


def test_responses_transport_records_requested_and_effective_model_identity(monkeypatch):
    assert deepseek.resolve_deepseek_request_model(
        "deepseek-v4-flash", "JSON_SCHEMA"
    ) == "deepseek-flash"
    assert deepseek.resolve_deepseek_request_model(
        "deepseek-v4-flash", None
    ) == "deepseek-v4-flash"


def test_json_schema_transport_changes_cache_identity_without_changing_default_identity():
    system = "Return JSON."
    payload = {"value": "x"}
    legacy = deepseek._input_hash(system, payload, "p1", "s1", "disabled")
    structured = deepseek._input_hash(
        system,
        payload,
        "p1",
        "s1",
        "disabled",
        "JSON_SCHEMA",
        "schema-hash",
        SEMANTIC_LLM_TRANSPORT_VERSION,
    )
    assert structured != legacy


def test_two_call_canary_requires_both_fixed_citations_to_pass():
    canary_ids = ["citation-1", "citation-2"]
    assert _canary_gate_result([], canary_ids) is None
    assert _canary_gate_result([
        {"citation_id": "citation-1", "processing_status": "DONE"},
    ], canary_ids) is None
    assert _canary_gate_result([
        {"citation_id": "citation-1", "processing_status": "DONE"},
        {"citation_id": "citation-2", "processing_status": "FAILED"},
    ], canary_ids) is False
    assert _canary_gate_result([
        {"citation_id": "citation-1", "processing_status": "DONE"},
        {"citation_id": "citation-2", "processing_status": "DONE"},
    ], canary_ids) is True


def test_human_gold_contract_rejects_old_accept_reject_shape_and_requires_comment():
    with pytest.raises(ValidationError):
        CitationContributionCalibrationDecision.model_validate({
            "target_type": "EVALUATION",
            "target_id": "evaluation-1",
            "decision": "ACCEPT",
        })
    with pytest.raises(ValidationError):
        CitationContributionCalibrationDecision.model_validate({
            "target_type": "EVALUATION",
            "target_id": "evaluation-1",
            "gold_identity": "a" * 64,
            "human_correspondence_mode": "DIRECT_REUSE",
            "human_evidence_relation": "SUPPORTS_FULL",
            "span_validity": "VALID",
            "subject_attribution": "PRESERVED",
            "qualifier_preservation": "PRESERVED",
            "decision_role_validity": "VALID",
            "review_comment": "",
        })


def test_recall_boundary_gold_stays_independent_from_machine_relation_fields():
    parsed = CitationContributionCalibrationDecision.model_validate({
        "target_type": "RECALL_CONTROL",
        "target_id": "control-1",
        "gold_identity": "b" * 64,
        "boundary_has_correspondence": True,
        "boundary_has_support": False,
        "boundary_has_related": True,
        "boundary_should_enter_candidate": True,
        "boundary_miss_reason": "RANKING_BOUNDARY",
        "review_comment": "主题相关，应该进入正式候选",
    })
    assert parsed.human_evidence_relation is None
    assert parsed.boundary_has_related is True

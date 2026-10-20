import hashlib
import json
from pathlib import Path

import pytest

from app.services.semantic_llm import deepseek
from app.services.semantic_llm.base import SemanticLLMError
from app.modules.agent_experiment.contracts import AgentDecision
from app.modules.agent_experiment.runner import (
    AGENT_DECISION_PROMPT_VERSION,
    AGENT_DECISION_SCHEMA_VERSION,
    AGENT_DECISION_TRANSPORT_VERSION,
    DeepSeekDecisionClient,
    _model_payload,
    _recover_agent_dsml_tool_call,
    _system_prompt,
)
from app.modules.agent_experiment.service import _execution_profile


def test_explicit_thinking_mode_changes_cache_identity_without_changing_legacy_identity():
    system = "Return JSON."
    payload = {"value": "x"}
    legacy_payload = {
        "system": system,
        "payload": payload,
        "pv": "p1",
        "sv": "s1",
    }
    expected_legacy = hashlib.sha256(
        json.dumps(legacy_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    assert deepseek._input_hash(system, payload, "p1", "s1") == expected_legacy
    assert deepseek._input_hash(system, payload, "p1", "s1", "disabled") != expected_legacy


def test_disabled_thinking_is_sent_and_failed_http_attempts_are_counted(monkeypatch):
    bodies = []

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "deepseek-v4-flash",
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning_content": "reasoning"},
                }],
                "usage": {"total_tokens": 11},
            }

    class FakeHttpClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, headers, json):
            bodies.append(json)
            return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    client = deepseek.DeepSeekClient(thinking_mode="disabled")
    monkeypatch.setattr(client.settings, 'deepseek_api_key', 'test-key')

    with pytest.raises(SemanticLLMError, match="finish_reason=length"):
        client.structured_generate_sync(
            system_prompt="Return JSON.",
            user_payload={"value": "x"},
            response_schema=dict,
            prompt_version="p1",
            schema_version="s1",
        )

    assert len(bodies) == 3
    assert all(body["thinking"] == {"type": "disabled"} for body in bodies)
    assert client.external_call_count == 3
    assert client.external_token_count == 33


def test_cache_only_miss_never_reads_api_key_or_starts_http(monkeypatch):
    def fail_http(*_args, **_kwargs):
        raise AssertionError("CACHE_ONLY must not construct an HTTP client")

    monkeypatch.setattr(deepseek.httpx, "Client", fail_http)
    client = deepseek.DeepSeekClient(thinking_mode="disabled", max_attempts=1, cache_only=True)
    monkeypatch.setattr(client.settings, 'deepseek_api_key', '')

    with pytest.raises(SemanticLLMError) as rejected:
        client.structured_generate_sync(
            system_prompt="Return JSON.",
            user_payload={"value": "cache miss"},
            response_schema=dict,
            prompt_version="cache-only-v1",
            schema_version="cache-only-v1",
        )

    assert getattr(rejected.value, "code", "") == "CACHE_MISS"
    assert client.external_call_count == 0
    assert client.external_token_count == 0


def test_responses_plain_text_transport_has_no_json_format_or_retry(monkeypatch):
    bodies = []
    reservations = []
    audits = []

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "deepseek-flash", "status": "completed",
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": "## GEO 诊断与依据\n完整 Markdown"},
                ]}],
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            }

    class FakeHttpClient:
        def __init__(self, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json):
            assert url.endswith("/responses")
            bodies.append(json)
            return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = deepseek.DeepSeekClient(
        max_attempts=1, request_guard=reservations.append,
        response_audit_sink=audits.append,
    )
    monkeypatch.setattr(client.settings, "deepseek_api_key", "test-key")
    output = client.text_generate_sync(
        system_prompt="Return one Markdown artifact.",
        user_payload={"contract_version": "geo.evidence-pack.v1"},
        model="deepseek-flash", prompt_version="geo-evidence-pack-synthesis.v1",
        schema_version="geo.evidence-pack.markdown-result.v1", max_tokens=4096,
    )
    assert output.endswith("完整 Markdown")
    assert len(bodies) == len(reservations) == 1
    assert "text" not in bodies[0] and "tools" not in bodies[0]
    assert reservations[0]["transport_kind"] == "RESPONSES_TEXT"
    assert reservations[0]["attempt"] == 1
    assert audits[-1]["validation_status"] == "ACCEPTED"
    assert client.external_call_count == 1 and client.external_token_count == 120


def test_provider_http_error_audit_retains_status_category_and_no_usage(monkeypatch):
    audits = []

    class FakeResponse:
        status_code = 400
        text = '{"error":{"type":"invalid_request_error","message":"unsupported field"}}'

        @staticmethod
        def json():
            return {"error": {"type": "invalid_request_error", "message": "unsupported field"}}

    class FakeHttpClient:
        def __init__(self, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json): return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = deepseek.DeepSeekClient(max_attempts=1, response_audit_sink=audits.append)
    monkeypatch.setattr(client.settings, "deepseek_api_key", "test-key")
    with pytest.raises(SemanticLLMError) as rejected:
        client.text_generate_sync(
            system_prompt="Return Markdown.", user_payload={"scope": "frozen"},
            model="deepseek-flash", prompt_version="evidence-pack-http-error-v1",
        )
    assert getattr(rejected.value, "code", "") == "PROVIDER_HTTP_ERROR"
    assert audits[-1]["http_status"] == 400
    assert audits[-1]["provider_error_category"] == "invalid_request_error"
    assert audits[-1]["token_usage"] == {}
    assert audits[-1]["raw_http_response"] == FakeResponse.text


def test_structured_provider_http_error_is_audited_before_parse(monkeypatch):
    audits = []

    class FakeResponse:
        status_code = 422
        text = '{"error":{"code":"schema_unsupported","message":"bad format"}}'

        @staticmethod
        def json():
            return {"error": {"code": "schema_unsupported", "message": "bad format"}}

    class FakeHttpClient:
        def __init__(self, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json): return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = deepseek.DeepSeekClient(max_attempts=1, response_audit_sink=audits.append)
    monkeypatch.setattr(client.settings, "deepseek_api_key", "test-key")
    with pytest.raises(SemanticLLMError) as rejected:
        client.structured_generate_sync(
            system_prompt="Return one decision.", user_payload={"scope": "frozen"},
            response_schema=AgentDecision, model="deepseek-flash",
            prompt_version="structured-http-error-v1", schema_version="decision-v1",
            strict_json=True, structured_output_mode="JSON_SCHEMA",
            provider_schema_strict=True,
        )
    assert getattr(rejected.value, "code", "") == "PROVIDER_HTTP_ERROR"
    assert audits[-1]["validation_status"] == "REJECTED"
    assert audits[-1]["http_status"] == 422
    assert audits[-1]["provider_error_category"] == "schema_unsupported"
    assert audits[-1]["token_usage"] == {}
    assert audits[-1]["raw_http_response"] == FakeResponse.text


def test_request_guard_denial_precedes_network_and_retry(monkeypatch):
    reservations = []
    def guard(identity):
        reservations.append(identity)
        raise ValueError('AUTHORIZED_BUDGET_EXHAUSTED')
    def fail_http(*args, **kwargs):
        raise AssertionError('Denied request must not start HTTP')
    monkeypatch.setattr(deepseek.httpx, 'Client', fail_http)
    client = deepseek.DeepSeekClient(max_attempts=3, request_guard=guard)
    monkeypatch.setattr(client.settings, 'deepseek_api_key', 'isolated-secret')
    with pytest.raises(ValueError, match='AUTHORIZED_BUDGET_EXHAUSTED'):
        client.structured_generate_sync(system_prompt='Return JSON.', user_payload={'value': 'x'},
            response_schema=dict, prompt_version='guard:1', schema_version='guard:1')
    assert len(reservations) == 1 and client.external_call_count == 0
    assert reservations[0]['input_token_upper_bound'] > len('Return JSON.')
    assert reservations[0]['max_output_tokens'] == 4096
    assert 'isolated-secret' not in json.dumps(reservations)


def test_responses_request_serializes_agent_history_and_observation_catalog(monkeypatch):
    bodies = []
    decision = {
        "action_type": "STOP", "reasoning": "offline transport assertion",
        "tool_name": None, "arguments": None, "artifact": None,
        "stop_reason": "offline transport assertion complete",
    }

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "deepseek-flash", "status": "completed",
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": json.dumps(decision, ensure_ascii=False)},
                ]}],
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            }

    class FakeHttpClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, headers, json):
            bodies.append(json)
            return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = deepseek.DeepSeekClient(max_attempts=1)
    monkeypatch.setattr(client.settings, "deepseek_api_key", "test-key")
    payload = {
        "contract_version": "geo.agent.loop-input.v2",
        "tool_history": [{"turn": 1, "tool_result": {"observation_id": "obs-1",
                            "data": {"valid_answer_count": 1}}}],
        "observation_catalog": [{"observation_id": "obs-1", "status": "AVAILABLE"}],
    }
    output = client.structured_generate_sync(
        system_prompt="Return one AgentDecision.", user_payload=payload,
        response_schema=AgentDecision, model="deepseek-flash",
        prompt_version="geo-agent-loop.v2", schema_version="geo.agent.decision.v1",
        max_tokens=2048, strict_json=True, structured_output_mode="JSON_SCHEMA",
    )
    assert output == decision
    assert len(bodies) == 1
    assert json.loads(bodies[0]["input"]) == payload
    assert bodies[0]["max_output_tokens"] == 2048
    assert bodies[0]["text"]["format"]["type"] == "json_schema"
    assert bodies[0]["text"]["format"]["name"] == "AgentDecision"
    assert "strict" not in bodies[0]["text"]["format"]


def test_agent_request_uses_strict_single_decision_protocol_without_parallel_flags(monkeypatch):
    bodies = []
    reservations = []
    decision = {
        "action_type": "STOP", "reasoning": "当前证据不足，安全停止",
        "tool_name": None, "arguments": None, "artifact": None,
        "stop_reason": "需要先取得一项真实工具观察",
    }

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "deepseek-flash", "status": "completed",
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": json.dumps(decision, ensure_ascii=False)},
                ]}],
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            }

    class FakeHttpClient:
        def __init__(self, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json):
            assert url.endswith("/responses")
            bodies.append(json)
            return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = DeepSeekDecisionClient(cache_only=False, request_guard=reservations.append)
    monkeypatch.setattr(client.client.settings, "deepseek_api_key", "test-key")
    scope = {
        "identity": {"project_id": 1, "prompt_id": 1, "run_ids": ["1"]},
        "prompt": {"text": "抖音跳转链接"}, "monitor_metrics": {"valid_answer_count": 1},
        "source_snapshots": [], "product_truth": {"set_hash": "truth"},
        "brand_context": {"mode": "EMPTY"},
    }
    payload = _model_payload(
        scope, [], [], 1, max_model_calls=10, finalization=False,
        consecutive_no_progress=0, execution_identity="execution-hash",
    )
    output, usage = client.decide(
        db=None, system_prompt=_system_prompt(_execution_profile()),
        user_payload=payload, max_tokens=2048,
    )

    assert output == decision and usage["input_tokens"] == 100
    assert len(bodies) == len(reservations) == 1
    body = bodies[0]
    assert body["instructions"].startswith("# 当前调用协议（高于下方长期业务目标）")
    assert "当前这一次模型调用只负责选择**现在最有价值的一个动作**" in body["instructions"]
    assert "developer" not in body and "messages" not in body
    assert "parallel_tool_calls" not in body and "max_tool_calls" not in body
    assert body["text"]["format"]["strict"] is True
    schema = body["text"]["format"]["schema"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "action_type", "reasoning", "tool_name", "arguments", "artifact", "stop_reason",
    }
    assert schema["properties"]["action_type"]["enum"] == ["TOOL_CALL", "FINAL_ARTIFACT", "STOP"]
    assert "run_shell" not in json.dumps(schema)
    sent_payload = json.loads(body["input"])
    assert sent_payload["contract_version"] == "geo.agent.loop-input.v3"
    assert sent_payload["current_call_contract"] == {
        "decision_count": 1,
        "allowed_action_types": ["TOOL_CALL", "FINAL_ARTIFACT", "STOP"],
        "future_action_list_allowed": False,
        "unexecuted_tool_results_must_not_be_assumed": True,
    }
    identity = reservations[0]
    assert identity["prompt_version"] == AGENT_DECISION_PROMPT_VERSION
    assert identity["schema_version"] == AGENT_DECISION_SCHEMA_VERSION
    assert identity["transport_version"] == AGENT_DECISION_TRANSPORT_VERSION
    assert identity["generation_parameters"]["provider_schema_strict"] is True


def test_single_decision_prompt_rejects_legacy_execution_identity_before_transport():
    legacy = _execution_profile()
    legacy["contract_version"] = "geo.agent.execution.v2"
    legacy["model_profile"].pop("single_decision_prompt_contract")
    with pytest.raises(RuntimeError, match="AGENT_SINGLE_DECISION_PROMPT_CONTRACT_MISMATCH"):
        _system_prompt(legacy)


def test_fifth_real_batched_decision_response_is_rejected_whole(monkeypatch):
    output_text = (
        Path(__file__).parent / "fixtures" / "deepseek_agent_validation_5_output.txt"
    ).read_text(encoding="utf-8").rstrip("\n")
    assert hashlib.sha256(output_text.encode()).hexdigest() == (
        "f9083dad8a57d7d75684bbd854b7c16557e82ac63440128078b1fbcfcf3ebe62"
    )
    assert len(output_text.splitlines()) == 8

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "deepseek-flash", "status": "completed",
                "output": [{"type": "message", "status": "completed", "content": [
                    {"type": "output_text", "text": output_text},
                ]}],
                "usage": {"input_tokens": 5307, "output_tokens": 752, "total_tokens": 6059},
            }

    class FakeHttpClient:
        def __init__(self, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json): return FakeResponse()

    audit = []
    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = deepseek.DeepSeekClient(max_attempts=1, response_audit_sink=audit.append)
    monkeypatch.setattr(client.settings, "deepseek_api_key", "test-key")
    with pytest.raises(SemanticLLMError) as rejected:
        client.structured_generate_sync(
            system_prompt="Return exactly one AgentDecision.", user_payload={"turn": 1},
            response_schema=AgentDecision, model="deepseek-flash",
            prompt_version=AGENT_DECISION_PROMPT_VERSION,
            schema_version=AGENT_DECISION_SCHEMA_VERSION,
            max_tokens=8192, strict_json=True, structured_output_mode="JSON_SCHEMA",
            transport_version=AGENT_DECISION_TRANSPORT_VERSION,
            provider_schema_strict=True, allow_json_wrapper_recovery=False,
            non_json_response_recovery=_recover_agent_dsml_tool_call,
            response_validator=lambda value: AgentDecision.model_validate(value).model_dump(mode="json"),
        )
    assert getattr(rejected.value, "code", "") == "FAILED_PARSE"
    assert audit[-1]["validation_status"] == "REJECTED"
    assert audit[-1]["raw_response_hash"] == hashlib.sha256(output_text.encode()).hexdigest()


def test_responses_native_function_call_yields_one_complete_decision():
    decision = {
        "action_type": "TOOL_CALL", "reasoning": "读取冻结回答",
        "tool_name": "read_answer", "arguments": {"run_id": "1"},
        "artifact": None, "stop_reason": None,
    }
    content, candidate, output_kind = deepseek._responses_output_candidate({
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "function_call", "name": "AgentDecision",
             "arguments": json.dumps(decision, ensure_ascii=False)},
        ],
    }, expected_function_name="AgentDecision")
    assert output_kind == "FUNCTION_CALL"
    assert json.loads(content) == decision
    assert AgentDecision.model_validate(candidate).model_dump(mode="json") == decision


@pytest.mark.parametrize("output", [
    [
        {"type": "message", "content": [{"type": "output_text", "text": "{}"}]},
        {"type": "function_call", "name": "AgentDecision", "arguments": "{}"},
    ],
    [
        {"type": "function_call", "name": "AgentDecision", "arguments": "{}"},
        {"type": "function_call", "name": "AgentDecision", "arguments": "{}"},
    ],
    [{"type": "custom_tool_call", "name": "AgentDecision", "input": "{}"}],
])
def test_responses_rejects_ambiguous_or_unsupported_decision_outputs(output):
    with pytest.raises(SemanticLLMError):
        deepseek._responses_output_candidate(
            {"output": output}, expected_function_name="AgentDecision",
        )


def test_responses_function_call_rejects_wrong_name_and_incomplete_arguments():
    with pytest.raises(SemanticLLMError):
        deepseek._responses_output_candidate({
            "output": [{"type": "function_call", "name": "read_answer",
                        "arguments": '{"run_id":"1"}'}],
        }, expected_function_name="AgentDecision")
    with pytest.raises(SemanticLLMError):
        deepseek._responses_output_candidate({
            "output": [{"type": "function_call", "name": "AgentDecision",
                        "arguments": '{"action_type":"TOOL_CALL"'}],
        }, expected_function_name="AgentDecision")


def test_agent_pipeline_recovers_complete_dsml_without_extracting_nested_arguments(monkeypatch):
    wrapped = (
        '<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="AgentDecision"> '
        '<｜｜DSML｜｜ parameter name="action_type">TOOL_CALL</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="reasoning">读取冻结回答</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="tool_name">read_answer</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="arguments">{"run_id":"1"}</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="artifact">null</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="stop_reason">null</｜｜DSML｜｜ parameter> '
        '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>'
    )

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "deepseek-flash", "status": "completed",
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": wrapped},
                ]}],
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            }

    class FakeHttpClient:
        def __init__(self, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def post(self, url, headers, json): return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    client = deepseek.DeepSeekClient(max_attempts=1)
    monkeypatch.setattr(client.settings, "deepseek_api_key", "test-key")
    output = client.structured_generate_sync(
        system_prompt="Return one AgentDecision.", user_payload={"scope": "frozen"},
        response_schema=AgentDecision, model="deepseek-flash",
        prompt_version="geo-agent-loop.v2", schema_version="geo.agent.decision.v1",
        max_tokens=2048, strict_json=True, structured_output_mode="JSON_SCHEMA",
        allow_json_wrapper_recovery=False,
        non_json_response_recovery=_recover_agent_dsml_tool_call,
        recovery_contract_version="geo.agent.deepseek-dsml-agent-decision.v2",
        response_validator=lambda value: AgentDecision.model_validate(value).model_dump(mode="json"),
    )
    assert output["action_type"] == "TOOL_CALL"
    assert output["tool_name"] == "read_answer"
    assert output["arguments"] == {"run_id": "1"}

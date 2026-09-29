from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict

from app.services.semantic_llm import model_b, siliconflow
from app.services.semantic_llm.base import SemanticLLMError


class CriticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: str
    object_ids: list[str]


def _valid_payload() -> dict:
    return {"decision": "KEEP", "object_ids": ["direction-1"]}


def test_siliconflow_qwen_uses_official_chat_json_schema_transport(monkeypatch):
    captured: dict = {}
    audits: list[dict] = []
    cache_writes: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""
        headers = {"x-siliconcloud-trace-id": "trace-1"}

        @staticmethod
        def json():
            return {
                "model": "Qwen/Qwen3.6-35B-A3B",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(_valid_payload())},
                }],
                "usage": {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20},
            }

    class FakeHttpClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, headers, json):
            captured.update({"url": url, "headers": headers, "body": json})
            return FakeResponse()

    monkeypatch.setattr(siliconflow.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr(siliconflow.LLMCallCache, "get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        siliconflow.LLMCallCache,
        "put",
        lambda *_args, **kwargs: cache_writes.append(kwargs),
    )
    client = siliconflow.SiliconFlowClient(
        max_attempts=1,
        response_audit_sink=audits.append,
    )
    client.settings.siliconflow_api_key = "test-key"

    result = client.structured_generate_sync(
        system_prompt="Return the bounded critic decision.",
        user_payload={"allowed_object_ids": ["direction-1"]},
        response_schema=CriticResponse,
        prompt_version="model-b-critic.v1",
        schema_version="model-b-critic.strict.v1",
        db=object(),
    )

    assert result == _valid_payload()
    assert captured["url"] == "https://api.siliconflow.cn/v1/chat/completions"
    assert captured["body"]["model"] == "Qwen/Qwen3.6-35B-A3B"
    assert captured["body"]["enable_thinking"] is False
    assert captured["body"]["temperature"] == 0.0
    assert captured["body"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "CriticResponse",
            "strict": True,
            "schema": CriticResponse.model_json_schema(mode="validation"),
        },
    }
    assert client.external_call_count == 1
    assert client.external_input_token_count == 13
    assert client.external_output_token_count == 7
    assert audits[0]["provider_trace_id"] == "trace-1"
    assert audits[0]["request_identity"]["provider"] == "siliconflow"
    assert audits[0]["request_identity"]["effective_request_model"] == "Qwen/Qwen3.6-35B-A3B"
    assert cache_writes[0]["provider"] == "siliconflow"
    assert cache_writes[0]["model"] == "Qwen/Qwen3.6-35B-A3B"
    assert cache_writes[0]["parsed_payload"] == _valid_payload()


def test_siliconflow_rejects_unknown_fields_without_retry(monkeypatch):
    audits: list[dict] = []
    cache_writes: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""
        headers = {}

        @staticmethod
        def json():
            payload = {**_valid_payload(), "new_fact": "hallucinated"}
            return {
                "model": "Qwen/Qwen3.6-35B-A3B",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(payload)},
                }],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            }

    class FakeHttpClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr(siliconflow.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr(siliconflow.LLMCallCache, "get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        siliconflow.LLMCallCache,
        "put",
        lambda *_args, **kwargs: cache_writes.append(kwargs),
    )
    client = siliconflow.SiliconFlowClient(max_attempts=1, response_audit_sink=audits.append)
    client.settings.siliconflow_api_key = "test-key"

    with pytest.raises(SemanticLLMError, match="准入校验"):
        client.structured_generate_sync(
            system_prompt="Return JSON.",
            user_payload={"allowed_object_ids": ["direction-1"]},
            response_schema=CriticResponse,
            prompt_version="model-b-critic.v1",
            schema_version="model-b-critic.strict.v1",
            db=object(),
        )

    assert client.external_call_count == 1
    assert client.call_count == 0
    assert audits[-1]["validation_status"] == "REJECTED"
    assert cache_writes == []


def test_model_b_is_disabled_for_external_calls_by_default(monkeypatch):
    settings = model_b.get_settings()
    monkeypatch.setattr(settings, "model_b_enabled", False)
    monkeypatch.setattr(settings, "model_b_provider", "siliconflow")

    with pytest.raises(SemanticLLMError) as rejected:
        model_b.create_model_b_client(cache_only=False)

    assert getattr(rejected.value, "code", "") == "MODEL_B_DISABLED"


def test_model_b_cache_only_miss_never_reads_key_or_starts_http(monkeypatch):
    def fail_http(*_args, **_kwargs):
        raise AssertionError("CACHE_ONLY must not start an external request")

    monkeypatch.setattr(siliconflow.httpx, "Client", fail_http)
    client = model_b.create_model_b_client(cache_only=True)
    client.settings.siliconflow_api_key = ""

    with pytest.raises(SemanticLLMError) as rejected:
        client.structured_generate_sync(
            system_prompt="Return JSON.",
            user_payload={"allowed_object_ids": ["direction-1"]},
            response_schema=CriticResponse,
            prompt_version="model-b-critic.v1",
            schema_version="model-b-critic.strict.v1",
        )

    assert getattr(rejected.value, "code", "") == "CACHE_MISS"
    assert client.external_call_count == 0


def test_siliconflow_schema_and_model_change_cache_identity():
    base = siliconflow.structured_input_hash(
        "system",
        {"value": "x"},
        "p1",
        "s1",
        "disabled",
        "JSON_SCHEMA",
        "schema-a",
        siliconflow.SILICONFLOW_JSON_SCHEMA_TRANSPORT_VERSION,
        "Qwen/Qwen3.6-35B-A3B",
        "Qwen/Qwen3.6-35B-A3B",
    )
    changed_model = siliconflow.structured_input_hash(
        "system",
        {"value": "x"},
        "p1",
        "s1",
        "disabled",
        "JSON_SCHEMA",
        "schema-a",
        siliconflow.SILICONFLOW_JSON_SCHEMA_TRANSPORT_VERSION,
        "Qwen/Qwen3.5-4B",
        "Qwen/Qwen3.5-4B",
    )
    assert base != changed_model

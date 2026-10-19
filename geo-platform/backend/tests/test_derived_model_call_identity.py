from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict

from app.modules.single_prompt_v2.diagnosis import (
    _contract_config,
    _require_derived_model_call_contracts,
)
from app.services.semantic_llm import deepseek
from app.services.semantic_llm.base import SemanticLLMError


class TinyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: str


def _contract(client: deepseek.DeepSeekClient, **overrides):
    values = {
        "system_prompt": "Return the frozen object.",
        "response_schema": TinyResponse,
        "prompt_version": "identity-test.p1",
        "schema_version": "identity-test.s1",
        "requested_model_alias": client.settings.deepseek_model,
        "thinking_mode": "disabled",
        "max_tokens": 2048,
        "structured_output_mode": "JSON_SCHEMA",
        "transport_version": deepseek.DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION,
        "endpoint_base_url": client.settings.deepseek_base_url,
    }
    values.update(overrides)
    return deepseek.derive_deepseek_call_contract(**values)


def test_call_contract_is_complete_and_each_technical_dimension_is_versioned():
    client = deepseek.DeepSeekClient(thinking_mode="disabled", max_attempts=1)
    frozen = _contract(client)
    assert frozen["contract_version"] == deepseek.DERIVED_MODEL_CALL_IDENTITY_VERSION
    assert frozen["endpoint_path"] == "/responses"
    assert frozen["transport_kind"] == "RESPONSES_JSON_SCHEMA"
    assert frozen["cache_identity_version"] == deepseek.DERIVED_MODEL_CACHE_IDENTITY_VERSION
    assert len(frozen["prompt_hash"]) == len(frozen["provider_schema_hash"]) == 64
    assert len(frozen["call_identity_hash"]) == 64

    variants = (
        {"system_prompt": "Different prompt."},
        {"max_tokens": 4096},
        {"transport_version": "semantic_llm.deepseek.responses_json_schema.v999"},
        {"endpoint_base_url": "https://identity.invalid/v1"},
        {"requested_model_alias": "deepseek-v4-pro"},
    )
    assert all(_contract(client, **variant)["call_identity_hash"] != frozen["call_identity_hash"]
               for variant in variants)


def test_frozen_identity_allows_exact_response_and_rejects_provider_model_or_transport_drift(monkeypatch):
    client = deepseek.DeepSeekClient(thinking_mode="disabled", max_attempts=1)
    contract = _contract(client)
    client.frozen_call_contracts = {contract["prompt_version"]: contract}
    monkeypatch.setattr(client.settings, "deepseek_api_key", "test-key")
    reservations = []
    client.request_guard = reservations.append

    response_body = {
        "model": contract["effective_request_model"],
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"value":"ok"}'}]}],
        "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
    }

    class FakeResponse:
        status_code = 200
        text = json.dumps(response_body)

        @staticmethod
        def json():
            return response_body

    class FakeHttpClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, headers, json):
            assert url == contract["endpoint"]
            return FakeResponse()

    monkeypatch.setattr(deepseek.httpx, "Client", FakeHttpClient)
    args = dict(system_prompt="Return the frozen object.", user_payload={"scope": "fixed"},
        response_schema=TinyResponse, prompt_version="identity-test.p1", schema_version="identity-test.s1",
        max_tokens=2048, strict_json=True, structured_output_mode="JSON_SCHEMA",
        transport_version=deepseek.DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION)
    assert client.structured_generate_sync(**args) == {"value": "ok"}
    assert reservations[0]["call_identity_hash"] == contract["call_identity_hash"]
    assert reservations[0]["input_scope_hash"]

    response_body["model"] = "deepseek-unknown"
    with pytest.raises(SemanticLLMError) as model_error:
        client.structured_generate_sync(**args)
    assert model_error.value.code == "PROVIDER_MODEL_IDENTITY_MISMATCH"

    response_body["model"] = contract["effective_request_model"]
    response_body["choices"] = []
    with pytest.raises(SemanticLLMError) as transport_error:
        client.structured_generate_sync(**args)
    assert transport_error.value.code == "PROVIDER_TRANSPORT_IDENTITY_MISMATCH"


def test_cache_key_cannot_cross_call_identity_and_legacy_config_is_fail_closed(monkeypatch):
    observed = []

    def no_cache(_db, **identity):
        observed.append(identity)
        return None

    monkeypatch.setattr(deepseek.LLMCallCache, "get", no_cache)
    common = dict(system_prompt="Return the frozen object.", user_payload={"scope": "fixed"},
        response_schema=TinyResponse, prompt_version="identity-test.p1", schema_version="identity-test.s1",
        strict_json=True, structured_output_mode="JSON_SCHEMA",
        transport_version=deepseek.DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION, db=object())
    for max_tokens in (2048, 4096):
        client = deepseek.DeepSeekClient(thinking_mode="disabled", max_attempts=1, cache_only=True)
        contract = _contract(client, max_tokens=max_tokens)
        client.frozen_call_contracts = {contract["prompt_version"]: contract}
        with pytest.raises(SemanticLLMError) as miss:
            client.structured_generate_sync(max_tokens=max_tokens, **common)
        assert miss.value.code == "CACHE_MISS"
    assert observed[0]["input_hash"] != observed[1]["input_hash"]

    with pytest.raises(SemanticLLMError) as legacy:
        _require_derived_model_call_contracts({})
    assert legacy.value.code == "DERIVED_MODEL_CALL_IDENTITY_LEGACY_UNBOUND"
    frozen_config = _contract_config()
    first = next(iter(frozen_config["derived_model_call_contracts"].values()))
    first["transport_version"] = "drift"
    with pytest.raises(SemanticLLMError) as drift:
        _require_derived_model_call_contracts(frozen_config)
    assert drift.value.code == "DERIVED_MODEL_CALL_IDENTITY_DRIFT"


def test_request_is_rejected_before_network_when_frozen_call_identity_drifts(monkeypatch):
    client = deepseek.DeepSeekClient(thinking_mode="disabled", max_attempts=1)
    contract = _contract(client)
    contract["endpoint"] = "https://drift.invalid/responses"
    client.frozen_call_contracts = {contract["prompt_version"]: contract}
    monkeypatch.setattr(deepseek.httpx, "Client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network must not start")))
    with pytest.raises(SemanticLLMError) as rejected:
        client.structured_generate_sync(system_prompt="Return the frozen object.", user_payload={"scope": "fixed"},
            response_schema=TinyResponse, prompt_version="identity-test.p1", schema_version="identity-test.s1",
            max_tokens=2048, structured_output_mode="JSON_SCHEMA",
            transport_version=deepseek.DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION)
    assert rejected.value.code == "DERIVED_MODEL_CALL_IDENTITY_DRIFT"

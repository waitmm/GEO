import hashlib
import json

import pytest

from app.services.semantic_llm import deepseek
from app.services.semantic_llm.base import SemanticLLMError


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

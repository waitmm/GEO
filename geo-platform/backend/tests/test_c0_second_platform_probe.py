"""C0 only: synthetic field mapping and explicit, non-production gap probes.

No consumer HTTP, browser, model, database, credential or artifact writes.
The two strict xfails are C1 blockers, not accepted production behavior.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.monitoring.collectors.base import CollectorResult
from app.modules.monitoring.collectors.registry import get_collector
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.single_prompt_v2.manual_import import _text_sha, _validate_citations
from app.modules.single_prompt_v2.observation_api import ManualObservationImportCreate


FIXTURE = Path(__file__).parent / "fixtures" / "c0_second_platform_observations.json"
DATA = json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("row", DATA["observations"], ids=lambda row: row["platform"])
def test_synthetic_collector_envelope_preserves_occurrences_and_candidate_separation(row):
    assert DATA["provenance"] == "SYNTHETIC_CONTRACT_PROBE"
    assert DATA["actual_platform_capture"] is DATA["production_admission"] is False
    result = CollectorResult(
        answer_text=row["answer_text"], references=deepcopy(row["references"]),
        retrieval_candidates=deepcopy(row["retrieval_candidates"]), metrics=dict(row["metrics"]),
        environment={"platform": row["platform"], "adapter": row["proposed_adapter"],
                     "sampling_mode": "UNKNOWN", "model_version": "UNKNOWN"},
    )
    replay = CollectorResult(**json.loads(json.dumps(asdict(result), ensure_ascii=False)))
    assert asdict(replay) == asdict(result)
    assert _text_sha(result.answer_text) == hashlib.sha256(result.answer_text.encode()).hexdigest()
    assert len(replay.references) == row["metrics"]["parsed_reference_count"]
    assert [ref["reference_index"] for ref in replay.references] == list(range(1, len(replay.references) + 1))
    assert not ({ref["url"] for ref in replay.references} & {ref["url"] for ref in replay.retrieval_candidates})
    # This is a storage-envelope probe, not a fabricated DOM parser or a live adapter.
    assert replay.environment["sampling_mode"] == "UNKNOWN"


@pytest.mark.parametrize("row", DATA["observations"], ids=lambda row: row["platform"])
def test_candidate_collector_is_not_enabled_by_c0(row):
    with pytest.raises(ValueError, match="Unsupported browser collector"):
        get_collector(row["proposed_adapter"])


@pytest.mark.parametrize("row", DATA["observations"], ids=lambda row: row["platform"])
def test_current_manual_admission_rejects_second_platform_without_wenxin_impersonation(row):
    payload = {
        "prompt_version_id": "synthetic-prompt-version", "prompt_snapshot_hash": "a" * 64,
        "configuration_version_id": "synthetic-config-version", "configuration_snapshot_hash": "b" * 64,
        "observed_at": "2026-10-30T00:00:00Z", "source_platform": row["platform"],
        "answer_text": row["answer_text"], "citations": [],
        "citation_observation_status": "UNKNOWN", "citation_note": "合成 C0，不是人工真实观测",
        "idempotency_key": "c0-synthetic-only-" + row["platform"],
    }
    with pytest.raises(ValidationError) as error:
        ManualObservationImportCreate.model_validate(payload)
    assert any(item["loc"] == ("source_platform",) for item in error.value.errors())


@pytest.mark.parametrize("state, citations, note", [
    ("COMPLETE", [{"title": "合成引用", "url": "https://example.invalid/a"}], ""),
    ("CONFIRMED_NONE", [], "人工已检查引用区域"),
    ("UNKNOWN", [], "尚未检查引用区域"),
    ("PARSE_FAILED", [], "引用区域存在但无法完整读取"),
])
def test_existing_manual_citation_state_contract_is_reusable_without_external_calls(state, citations, note):
    assert _validate_citations(state, citations, note) == citations


@pytest.mark.xfail(strict=True, reason="C1-GAP-01: missing reference metadata becomes a false complete zero")
def test_missing_reference_metadata_must_not_become_confirmed_zero(monkeypatch):
    executor = object.__new__(MonitoringTaskExecutor)
    for method in ("_stage", "_clear_run_outputs", "_save_references", "_save_candidates", "_save_result_artifacts"):
        monkeypatch.setattr(executor, method, lambda *args, **kwargs: None)
    captured = []
    db = SimpleNamespace(add=captured.append)
    run = SimpleNamespace(id=1)
    project = SimpleNamespace(brand_name="合成品牌", brand_aliases_json="[]")
    result = CollectorResult(answer_text="合成离线回答，正文足够长，但没有任何可确认的引用区域观测或计数信息。")
    executor.apply_result(db, run, project, result)
    assert run.reference_complete is False


@pytest.mark.xfail(strict=True, reason="C1-GAP-02: shared reference persistence hardcodes 文心助手")
def test_second_platform_reference_must_not_be_relabelled_wenxin():
    executor = object.__new__(MonitoringTaskExecutor)
    captured = []
    db = SimpleNamespace(add=captured.append)
    executor._save_references(db, 1, [{
        "reference_index": 1, "display_title": "合成引用", "url": "https://example.invalid/a",
        "platform_name": "腾讯元宝", "resolution_method": "synthetic_observed_link",
    }])
    assert captured[0].platform_name == "腾讯元宝"

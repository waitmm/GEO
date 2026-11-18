"""Offline-only Tencent Yuanbao projection through the existing GEO chain.

The fixture is synthetic and cannot enable the production collector registry.
No browser, login, HTTP, model, source fetch or paid call is used here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import pytest

from release_test_client import TestClient

from app.core.release_database import get_release_db
from app.models import (
    AgentExperimentRun,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Project,
    ReferenceSource,
    RetrievalCandidate,
    SinglePromptAnalysis,
)
from app.modules.agent_experiment.evidence_pack import build_evidence_pack
from app.modules.agent_experiment.service import create_agent_run
from app.modules.monitoring.collectors.base import CollectorResult
from app.modules.monitoring.collectors.registry import get_collector
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.release_main import create_release_app
from app.modules.single_prompt_v2.service import _hash
from app.services.serialization import dumps, loads
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


FIXTURE = Path(__file__).parent / "fixtures" / "c1_yuanbao_offline_replay.json"
DATA = json.loads(FIXTURE.read_text())


def _result(case: dict) -> CollectorResult:
    return CollectorResult(
        answer_text=case["answer_text"],
        references=deepcopy(case["references"]),
        retrieval_candidates=deepcopy(case["retrieval_candidates"]),
        metrics=dict(case["metrics"]),
        environment={
            "sampling_mode": "SYNTHETIC_OFFLINE_REPLAY",
            "collector_version": "yuanbao-offline-contract-probe.v1",
            "parser_version": "yuanbao-offline-contract-probe.v1",
        },
        reference_observation_status=case["reference_observation_status"],
    )


def _client(db):
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


@pytest.mark.parametrize(
    "case_name, expected_status, complete, error_type",
    [
        ("confirmed_none", "success", True, ""),
        ("unknown", "partial_success", False, "reference_observation_unknown"),
        ("parse_failed", "partial_success", False, "reference_parse_failed"),
        ("complete_unresolved_target", "partial_success", False, "reference_incomplete"),
    ],
)
def test_reference_observation_states_do_not_collapse_unknown_to_zero(
    case_name, expected_status, complete, error_type, monkeypatch,
):
    case = next(item for item in DATA["cases"] if item["name"] == case_name)
    executor = object.__new__(MonitoringTaskExecutor)
    monkeypatch.setattr(executor, "_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_clear_run_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_references", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_candidates", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_result_artifacts", lambda *args, **kwargs: None)

    class DB:
        def add(self, value):
            pass

    class Row:
        id = 1
        platform = "yuanbao"

    class Project:
        brand_name = "合成品牌"
        brand_aliases_json = "[]"

    run = Row()
    executor.apply_result(DB(), run, Project(), _result(case))
    assert run.status == expected_status
    assert run.reference_complete is complete
    assert run.error_type == error_type
    if case_name in {"unknown", "parse_failed"}:
        assert run.expected_reference_count == case["metrics"].get("ui_declared_count", 0)
        assert run.reference_complete is False


def test_collector_environment_cannot_override_run_identity_or_qualification(monkeypatch):
    executor = object.__new__(MonitoringTaskExecutor)
    monkeypatch.setattr(executor, "_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_clear_run_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_references", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_candidates", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_result_artifacts", lambda *args, **kwargs: None)

    class DB:
        def add(self, value):
            pass

    class Row:
        id = 1
        project_id = 1
        prompt_id = 44
        platform = "yuanbao"
        adapter = "yuanbao_web_audit"
        reference_complete = True
        sampling_mode = "ORIGINAL"

    class Project:
        brand_name = "合成品牌"
        brand_aliases_json = "[]"

    result = CollectorResult(
        answer_text="这是一段足够长的离线合成回答，用来验证采集环境不能覆盖服务端冻结身份或引用资格。",
        references=[],
        metrics={},
        environment={
            "project_id": 99,
            "prompt_id": 999,
            "platform": "wenxin",
            "adapter": "wenxin_web_audit",
            "reference_complete": True,
            "status": "success",
            "sampling_mode": "SYNTHETIC_OFFLINE_REPLAY",
        },
        reference_observation_status="UNKNOWN",
    )
    run = Row()
    executor.apply_result(DB(), run, Project(), result)

    assert (run.project_id, run.prompt_id) == (1, 44)
    assert (run.platform, run.adapter) == ("yuanbao", "yuanbao_web_audit")
    assert run.reference_complete is False
    assert run.status == "partial_success"
    assert run.error_type == "reference_observation_unknown"
    assert run.sampling_mode == "SYNTHETIC_OFFLINE_REPLAY"


def test_complete_counts_without_reference_records_fail_closed(monkeypatch):
    executor = object.__new__(MonitoringTaskExecutor)
    monkeypatch.setattr(executor, "_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_clear_run_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_references", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_candidates", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_result_artifacts", lambda *args, **kwargs: None)

    class DB:
        def add(self, value):
            pass

    class Row:
        id = 1
        platform = "yuanbao"

    class Project:
        brand_name = "合成品牌"
        brand_aliases_json = "[]"

    result = CollectorResult(
        answer_text="这是一段足够长的离线合成回答，用来验证引用计数不能代替实际引用记录。",
        references=[],
        metrics={
            "ui_declared_count": 1,
            "dom_reference_count": 1,
            "parsed_reference_count": 1,
            "resolved_url_count": 1,
        },
        reference_observation_status="COMPLETE",
    )
    run = Row()
    executor.apply_result(DB(), run, Project(), result)

    assert run.reference_complete is False
    assert run.status == "partial_success"
    assert run.error_type == "reference_incomplete"


def test_complete_resolved_count_must_match_actual_urls(monkeypatch):
    executor = object.__new__(MonitoringTaskExecutor)
    monkeypatch.setattr(executor, "_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_clear_run_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_references", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_candidates", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_result_artifacts", lambda *args, **kwargs: None)

    class DB:
        def add(self, value):
            pass

    class Row:
        id = 1
        platform = "yuanbao"

    class Project:
        brand_name = "合成品牌"
        brand_aliases_json = "[]"

    result = CollectorResult(
        answer_text="这是一段足够长的离线合成回答，用来验证已解析计数必须对应实际非空引用 URL。",
        references=[{
            "display_title": "合成未解析引用",
            "url": "",
            "resolution_method": "unresolved",
        }],
        metrics={
            "ui_declared_count": 1,
            "dom_reference_count": 1,
            "parsed_reference_count": 1,
            "resolved_url_count": 1,
        },
        reference_observation_status="COMPLETE",
    )
    run = Row()
    executor.apply_result(DB(), run, Project(), result)

    assert run.reference_complete is False
    assert run.status == "partial_success"
    assert run.error_type == "reference_incomplete"


def test_negative_counts_cannot_qualify_confirmed_none(monkeypatch):
    executor = object.__new__(MonitoringTaskExecutor)
    monkeypatch.setattr(executor, "_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_clear_run_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_references", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_candidates", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_save_result_artifacts", lambda *args, **kwargs: None)

    class DB:
        def add(self, value):
            pass

    class Row:
        id = 1
        platform = "yuanbao"

    class Project:
        brand_name = "合成品牌"
        brand_aliases_json = "[]"

    result = CollectorResult(
        answer_text="这是一段足够长的离线合成回答，用来验证负数计数不能成为已确认零引用。",
        references=[],
        metrics={
            "ui_declared_count": -1,
            "dom_reference_count": 0,
            "parsed_reference_count": 0,
            "resolved_url_count": 0,
        },
        reference_observation_status="CONFIRMED_NONE",
    )
    run = Row()
    executor.apply_result(DB(), run, Project(), result)

    assert run.reference_complete is False
    assert run.status == "partial_success"
    assert run.error_type == "reference_incomplete"


def test_yuanbao_offline_result_persists_freezes_and_enters_optimize_without_admission(
    tmp_path, monkeypatch,
):
    assert DATA["provenance"] == "SYNTHETIC_CONTRACT_PROBE"
    assert DATA["actual_platform_capture"] is DATA["production_admission"] is False
    with pytest.raises(ValueError, match="Unsupported browser collector"):
        get_collector(DATA["adapter"])

    db, engine = _migrated_session(tmp_path, monkeypatch)
    executor = MonitoringTaskExecutor()
    try:
        source = _seed_frozen_analysis(db, reference_urls=[])
        task = db.get(BrowserMonitorTask, source.task_id)
        run = db.query(BrowserMonitorRun).filter_by(task_id=task.id).one()
        source_plan = loads(source.sampling_plan_json, {})
        source_plan["platform"] = DATA["platform"]
        source_plan["adapter"] = DATA["adapter"]
        source.sampling_plan_json = dumps(source_plan)
        source.sampling_plan_hash = _hash(source_plan)
        task.platform = DATA["platform"]
        task.adapter = DATA["adapter"]
        run.platform = DATA["platform"]
        run.adapter = DATA["adapter"]
        run.source_type = "browser_audit"
        run.started_at = datetime(2026, 11, 18, 1, 0, 0)
        db.commit()

        case = next(item for item in DATA["cases"] if item["name"] == "complete_unresolved_target")
        executor.apply_result(db, run, db.get(Project, 1), _result(case))
        run.finished_at = datetime(2026, 11, 18, 1, 1, 0)
        task.status = "partial_success"
        db.commit()

        assert run.status == "partial_success"
        assert run.reference_complete is False
        assert run.error_type == "reference_incomplete"
        references = db.query(ReferenceSource).filter_by(run_id=run.id).order_by(ReferenceSource.reference_index).all()
        assert [row.platform_name for row in references] == ["腾讯元宝", "腾讯元宝"]
        assert references[0].canonical_url_hash == references[1].canonical_url_hash
        assert [row.reference_index for row in references] == [1, 2]
        candidates = db.query(RetrievalCandidate).filter_by(run_id=run.id).all()
        assert len(candidates) == 1
        assert candidates[0].url != references[0].url

        client = _client(db)
        range_base = "/api/v2/projects/1/prompts/44/analysis-ranges"
        preview = client.post(range_base + "/preview", json={"mode": "RUN_IDS", "run_ids": [run.id]})
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["valid_count"] == 1 and len(body["groups"]) == 1
        group = body["groups"][0]
        assert group["identity"]["platform"] == "yuanbao"
        assert group["identity"]["adapter"] == "yuanbao_web_audit"
        assert group["selected_run_ids"] == [run.id]

        frozen = client.post(range_base + "/freeze", json={
            "selector": body["selector"],
            "preview_hash": body["preview_hash"],
            "group_hash": group["group_hash"],
            "selected_run_ids": [run.id],
        })
        assert frozen.status_code == 201, frozen.text
        analysis_id = frozen.json()["analysis"]["analysis_id"]
        context_id = frozen.json()["context_id"]
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one()
        plan = json.loads(analysis.sampling_plan_json)
        assert plan["run_ids"] == [run.id]
        assert plan["origin_monitor_scope"]["group_hash"] == group["group_hash"]

        agent, created = create_agent_run(
            db,
            project_id=1,
            prompt_id=44,
            analysis_id=analysis_id,
            context_id=context_id,
            idempotency_key="c1-yuanbao-offline-optimize",
            requested_by="offline-contract-test",
            execution_mode="EVIDENCE_PACK",
        )
        assert created is True and agent.status == "QUEUED"
        scope = json.loads(agent.input_scope_json)
        assert scope["run_scope"]["run_ids"] == [run.id]
        assert scope["runs"][0]["observed_conditions"]["platform"] == {
            "value": "yuanbao",
            "source": "RUN_CAPTURE",
        }
        assert scope["runs"][0]["observed_conditions"]["adapter"] == {
            "value": "yuanbao_web_audit",
            "source": "RUN_CAPTURE",
        }
        assert len(scope["runs"][0]["references"]) == 2
        assert len(scope["runs"][0]["retrieval_candidates"]) == 1
        # References inherit the immutable platform identity of their containing
        # Run; the database-specific display label is intentionally not copied
        # into the frozen reference projection.
        assert scope["runs"][0]["reference_complete"] is False
        assert db.query(AgentExperimentRun).filter_by(run_id=agent.run_id).count() == 1
        pack = build_evidence_pack(scope)
        assert pack["runs"][0]["run_id"] == run.id
        assert pack["runs"][0]["reference_count"] == 2
        assert pack["runs"][0]["reference_complete"] is False
        assert pack["coverage"]["valid_answer_count"] == 1
    finally:
        executor.close()
        db.close()
        engine.dispose()

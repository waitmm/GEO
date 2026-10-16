from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.models import (BrowserMonitorRun, BrowserMonitorTask, Project, RunArtifact, SinglePromptAnalysisContext,
                        SinglePromptObservationComparison,
                        SinglePromptPreparedSourceSnapshot)
from app.modules.monitoring.collectors.base import CollectorResult
from app.modules.monitoring.executor import MonitoringTaskExecutor
from app.modules.monitoring.services import update_task_status_from_runs
from app.modules.single_prompt_v2.service import claim_analysis, finalize_analysis
from scripts.joint_real_acceptance import _sessions
from test_release_first_slice import _migrated_session, _seed_frozen_analysis


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "joint_real_acceptance.py"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _run(*args: object) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_imported_run_and_url_enter_frozen_monitor_validate_and_source_chains(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    baseline = _seed_frozen_analysis(db, reference_urls=["https://example.com/baseline"])
    database = Path(db.get_bind().url.database)
    prompt_text = baseline.prompt_text_snapshot
    baseline_id = baseline.analysis_id
    db.close()
    engine.dispose()

    artifacts = tmp_path / "joint-artifacts"
    manifest_path = tmp_path / "prepare.json"
    second_prompt_path = tmp_path / "second-prompt.txt"
    second_prompt_path.write_text("请列出短链接服务的两个常见选择维度。", encoding="utf-8")
    prepared = _run(
        "--artifact-root", artifacts,
        "prepare",
        "--database", database,
        "--baseline-analysis-id", baseline_id,
        "--idempotency-key", "joint-real-run-0001",
        "--second-prompt-text-file", second_prompt_path,
        "--brand-name", "腾讯云",
        "--website-url", "https://cloud.tencent.com",
        "--manifest", manifest_path,
    )
    analysis_id = prepared["prepared"]["analysis_id"]
    query_path = tmp_path / "observed-query.txt"
    query_path.write_text(prompt_text, encoding="utf-8")

    source_url = "https://example.com/real-source"
    collector_result = {
        "answer_text": "真实隔离回答指出 Target 可作为候选，并提供一个可公开验证的来源用于本地导入验收。",
        "answer_html": "<p>真实隔离回答指出 Target 可作为候选。</p>",
        "platform_reported_search": {"status": "MODEL_REPORTED", "consumption_policy": "OBSERVATION_ONLY"},
        "answer_content_boundary": {"contract_version": "wenxin-final-answer-boundary-v1", "status": "FINAL_ANSWER_ONLY", "source": "WENXIN_FINAL_MARKDOWN_DOM"},
        "references": [{"reference_index": 1, "display_title": "Real source", "matched_title": "Real source", "url": source_url, "canonical_url": source_url, "domain": "example.com", "resolution_method": "dom-direct-url", "match_confidence": 1.0}],
        "retrieval_candidates": [],
        "artifacts": [],
        "metrics": {"ui_declared_count": 1, "dom_reference_count": 1, "parsed_reference_count": 1, "resolved_url_count": 1},
        "environment": {"collector_id": "isolated-controller", "collection_mode": "single_independent", "sampling_mode": "single_independent", "browser": "Chromium", "browser_version": "test", "os": "test", "profile_identifier": "isolated", "conversation_id": "fresh-conversation", "network_region": "unknown", "collector_version": "fixture-real-shape-v1", "parser_version": "fixture-parser-v1"},
    }
    Session, execution_engine = _sessions(database)
    execution_db = Session()
    executor = MonitoringTaskExecutor()
    try:
        for analysis_row in prepared["prepared"]["analyses"]:
            token = claim_analysis(execution_db, analysis_row["analysis_id"])
            run = execution_db.get(BrowserMonitorRun, analysis_row["run_ids"][0])
            executor.apply_result(execution_db, run, execution_db.get(Project, prepared["prepared"]["project_id"]), CollectorResult(**collector_result))
            executor.artifacts.save_json(execution_db, run.id, "raw_result", "result.json", collector_result)
            run.finished_at = datetime.utcnow()
            execution_db.commit()
            update_task_status_from_runs(execution_db, execution_db.get(BrowserMonitorTask, run.task_id))
            assert finalize_analysis(execution_db, analysis_row["analysis_id"], token)
    finally:
        executor.close()
        execution_db.close()
        execution_engine.dispose()

    clean_text = "这是主控已在外部步骤取得的页面正文，本测试只验证本地持久化，不执行任何网络请求。" * 3
    acquired_at = datetime(2026, 10, 16, 8, 0).isoformat()
    source_path = tmp_path / "source-results.json"
    _write(source_path, {
        "contract_version": "joint-real-source-results.v1",
        "analysis_id": analysis_id,
        "budget": {
            "distinct_url_limit": 20,
            "top_level_attempt_limit": 20,
            "automatic_retries": 0,
            "attempts": [{
                "requested_url": source_url,
                "attempt_no": 1,
                "redirect_events": [],
            }],
        },
        "results": [{
            "requested_url": source_url,
            "result": {
                "fetch_status": "SUCCESS",
                "title": "真实来源",
                "clean_text": clean_text,
                "canonical_url": source_url,
                "fetch_time": acquired_at,
                "acquisition_receipt": {
                    "contract_version": "source-acquisition.v1",
                    "requested_url": source_url,
                    "final_url": source_url,
                    "acquired_at": acquired_at,
                    "method": "PLAYWRIGHT",
                    "network_policy": "PUBLIC_DNS_PINNED_TLS_VERIFIED_V1",
                    "documents": [{
                        "url": source_url,
                        "status": 200,
                        "tls_verified": True,
                        "public_address_pinned": True,
                        "response_body_hash": "a" * 64,
                        "content_type": "text/html",
                        "last_modified": "",
                    }],
                    "content_hash": hashlib.sha256(clean_text.encode()).hexdigest(),
                    "scope": "TRANSPORT_AND_EXTRACTED_CONTENT_ONLY",
                },
            },
        }],
    })
    report_path = tmp_path / "report.json"
    report = _run(
        "--artifact-root", artifacts,
        "accept",
        "--database", database,
        "--manifest", manifest_path,
        "--source-results", source_path,
        "--official-url", source_url,
        "--report", report_path,
    )

    assert report["external_requests_by_importer"] == 0
    assert len(report["comparison"]["run_ids"]) == 1
    assert report["comparison"]["run_ids"][0] in report["t07"]["run_ids"]
    assert len(report["t07"]["project_prompt_ids"]) == 2
    assert report["t21"]["monitor_validate_same_counts"] is True
    assert report["t21"]["result_version"].startswith("observation-v1:")
    assert report["t09"]["fetch_summary"]["ready"] == 1
    assert report["t09"]["snapshots"][0]["acquisition_method"] == "AUTO_FETCH"
    assert report["t09"]["supplemental"]["source_role"] == "SUPPLEMENTAL_PUBLIC_SOURCE"
    assert report["t09"]["supplemental"]["original_citation_count_before"] == report["t09"]["supplemental"]["original_citation_count_after"]

    Session, verification_engine = _sessions(database)
    verification = Session()
    try:
        assert verification.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).count() == 1
        assert verification.query(SinglePromptObservationComparison).count() == 1
        snapshot = verification.query(SinglePromptPreparedSourceSnapshot).one()
        assert snapshot.content_hash == hashlib.sha256(clean_text.encode()).hexdigest()
        assert verification.query(RunArtifact).filter(
            RunArtifact.run_id.in_([row["run_id"] for row in prepared["prepared"]["runs"]]),
            RunArtifact.artifact_type == "raw_result",
        ).count() == 2
    finally:
        verification.close()
        verification_engine.dispose()

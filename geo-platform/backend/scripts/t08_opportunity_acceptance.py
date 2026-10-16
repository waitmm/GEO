"""T08 acceptance on an isolated copy of a joint release SQLite database.

The gate starts the real release ASGI application on loopback, uses HTTP for the
Monitor -> Analysis handoff, persists only to the copied database, and never
starts a worker or an external model call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _http(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_ready(base_url: str, process: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"release server exited early with {process.returncode}")
        try:
            status, body = _http("GET", base_url + "/api/health")
            if status == 200 and body.get("status") == "ok":
                return
        except (URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise RuntimeError("release server did not become ready")


def run_gate(*, source: Path, project_id: int, prompt_id: int, output: Path) -> dict:
    from app.api.release_catalog import _record_project_configuration
    from app.models import (
        BrowserMonitorRun,
        Project,
        SinglePromptAnalysis,
        SinglePromptAnalysisContext,
        SinglePromptOptimizationTask,
    )
    from app.modules.single_prompt_v2.observation import opportunity_hint
    from app.services.serialization import loads

    if not source.is_file():
        raise ValueError(f"joint database does not exist: {source}")
    source_hash_before = _hash_file(source)
    runtime = output / "runtime-release.db"
    _copy_database(source, runtime)

    engine = create_engine(f"sqlite:///{runtime.resolve()}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    try:
        if not db.get(Project, project_id):
            raise ValueError("project does not exist in the isolated joint database")
        before = {
            "analyses": db.query(SinglePromptAnalysis).count(),
            "selected_prompt_analyses": db.query(SinglePromptAnalysis).filter_by(prompt_id=prompt_id).count(),
            "runs": db.query(BrowserMonitorRun).count(),
            "optimization_tasks": db.query(SinglePromptOptimizationTask).count(),
        }
    finally:
        db.close()

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "GEO_RELEASE_DATABASE_URL": f"sqlite:///{runtime.resolve()}",
        "MONITORING_WORKER": "0",
        "DEEPSEEK_API_KEY": "",
        "SILICONFLOW_API_KEY": "",
        "WENXIN_API_KEY": "",
        "WENXIN_SECRET_KEY": "",
    }
    log_path = output / "api.log"
    log = log_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.release_main:app", "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_ready(base_url, process)
        endpoint = f"/api/v2/projects/{project_id}/prompts/{prompt_id}"
        monitor_status, monitor = _http("GET", base_url + endpoint + "/monitor")
        if monitor_status != 200:
            raise AssertionError((monitor_status, monitor))
        stale_selection = monitor["analysis_selection"]
        if not stale_selection["selected_run_ids"]:
            raise AssertionError("joint prompt has no eligible frozen run for T08")

        db = Session()
        try:
            project = db.get(Project, project_id)
            project.industry = f"{project.industry}|t08-isolated-stale-check"
            _record_project_configuration(db, project)
            db.commit()
        finally:
            db.close()

        stale_status, stale_body = _http("POST", base_url + endpoint + "/monitor-analysis", {"scope_hash": stale_selection["scope_hash"]})
        if stale_status != 409:
            raise AssertionError(("stale scope was accepted", stale_status, stale_body))

        refreshed_status, refreshed = _http("GET", base_url + endpoint + "/monitor")
        if refreshed_status != 200:
            raise AssertionError((refreshed_status, refreshed))
        selected = refreshed["analysis_selection"]
        if selected["scope_hash"] == stale_selection["scope_hash"]:
            raise AssertionError("project configuration change did not alter scope identity")

        created_status, created = _http("POST", base_url + endpoint + "/monitor-analysis", {"scope_hash": selected["scope_hash"]})
        repeated_status, repeated = _http("POST", base_url + endpoint + "/monitor-analysis", {"scope_hash": selected["scope_hash"]})
        if created_status != 201 or repeated_status != 200:
            raise AssertionError((created_status, repeated_status, created, repeated))
        if created["analysis"]["analysis_id"] != repeated["analysis"]["analysis_id"]:
            raise AssertionError("same scope did not reuse the same Analysis")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()

    db = Session()
    try:
        after = {
            "analyses": db.query(SinglePromptAnalysis).count(),
            "selected_prompt_analyses": db.query(SinglePromptAnalysis).filter_by(prompt_id=prompt_id).count(),
            "runs": db.query(BrowserMonitorRun).count(),
            "optimization_tasks": db.query(SinglePromptOptimizationTask).count(),
        }
        if after["analyses"] != before["analyses"] + 1 or after["selected_prompt_analyses"] != before["selected_prompt_analyses"] + 1:
            raise AssertionError(("unexpected Analysis creation", before, after))
        if after["runs"] != before["runs"] or after["optimization_tasks"] != before["optimization_tasks"]:
            raise AssertionError(("handoff started sampling or Optimize", before, after))

        analysis_id = created["analysis"]["analysis_id"]
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one()
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).one()
        plan = loads(analysis.sampling_plan_json, {})
        scope = loads(context.run_scope_json, {})
        raw = loads(context.raw_output_json, {})
        identity_checks = {
            "project": plan.get("project_id") == selected.get("project_id") == project_id,
            "prompt": plan.get("prompt_id") == selected.get("prompt_id") == prompt_id,
            "prompt_version": plan.get("prompt_version") == selected.get("prompt_version"),
            "project_configuration": plan.get("project_configuration") == selected.get("project_configuration"),
            "monitor_raw_hash": plan.get("origin_monitor_scope", {}).get("raw_output_hash") == selected.get("raw_output_hash"),
            "monitor_scope_hash": plan.get("origin_monitor_scope", {}).get("scope_hash") == selected.get("scope_hash"),
            "context": created.get("context_id") == context.context_id,
            "context_raw_hash": created.get("raw_output_hash") == context.raw_output_hash,
            "run_scope": scope.get("run_ids") == selected.get("selected_run_ids"),
            "raw_plan": raw.get("sampling_plan") == plan,
        }
        if not all(identity_checks.values()):
            raise AssertionError(identity_checks)
    finally:
        db.close()
        engine.dispose()

    zero_metrics = {
        "brand_mention_rate": {"evaluable_count": 2, "hit_count": 0, "evaluable_run_ids": [1, 2]},
        "brand_option_rate": {"evaluable_count": 2, "hit_count": 0, "evaluable_run_ids": [1, 2]},
        "brand_recommendation_rate": {"evaluable_count": 2, "hit_count": 0, "evaluable_run_ids": [1, 2]},
    }
    intent_checks = {
        intent: opportunity_hint(intent, zero_metrics)
        for intent in ("category_awareness", "usage_instruction")
    }
    if any(value["state"] != "OBSERVE" or value["score"] is not None for value in intent_checks.values()):
        raise AssertionError(intent_checks)

    source_hash_after = _hash_file(source)
    if source_hash_after != source_hash_before:
        raise AssertionError("source database changed")
    report = {
        "contract_version": "t08-opportunity-http-acceptance.v1",
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_database": str(source.resolve()),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "runtime_database": str(runtime.resolve()),
        "project_id": project_id,
        "prompt_id": prompt_id,
        "stale_scope_status": stale_status,
        "created_status": created_status,
        "idempotent_status": repeated_status,
        "analysis_id": created["analysis"]["analysis_id"],
        "context_id": created["context_id"],
        "raw_output_hash": created["raw_output_hash"],
        "run_scope_hash": context.run_scope_hash,
        "scope_hash": selected["scope_hash"],
        "identity_checks": identity_checks,
        "row_counts_before": before,
        "row_counts_after": after,
        "intent_checks": intent_checks,
        "external_model_calls": 0,
    }
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(log_path, output / "api-preserved.log")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--prompt-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_gate(source=args.database, project_id=args.project_id, prompt_id=args.prompt_id, output=args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

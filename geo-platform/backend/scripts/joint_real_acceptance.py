from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PREPARE_CONTRACT = "joint-real-acceptance-prepare.v1"
SOURCE_RESULTS_CONTRACT = "joint-real-source-results.v1"
SAMPLE_REQUEST_BUDGET = 6
SAMPLE_REQUEST_PLAN = 2
SOURCE_DISTINCT_URL_LIMIT = 20
SOURCE_TOP_LEVEL_ATTEMPT_LIMIT = 20


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _budget_connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("CREATE TABLE IF NOT EXISTS sample_attempts (attempt_id TEXT PRIMARY KEY, run_id INTEGER UNIQUE NOT NULL, analysis_id TEXT NOT NULL, ordinal INTEGER UNIQUE NOT NULL, status TEXT NOT NULL, reserved_at TEXT NOT NULL, finished_at TEXT, outcome_json TEXT NOT NULL DEFAULT '{}')")
    connection.execute("CREATE TABLE IF NOT EXISTS budget_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return connection


def reserve_sample_attempt(path: Path, *, analysis_id: str, run_id: int, attempt_id: str) -> int:
    connection = _budget_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute("SELECT value FROM budget_meta WHERE key='active_attempt'").fetchone()
        if active:
            raise RuntimeError(f"已有未闭合真实尝试 {active[0]}；拒绝继续")
        used = int(connection.execute("SELECT COUNT(*) FROM sample_attempts").fetchone()[0])
        if used >= SAMPLE_REQUEST_BUDGET:
            raise RuntimeError(f"真实采样预算已用尽：{used}/{SAMPLE_REQUEST_BUDGET}")
        ordinal = used + 1
        connection.execute("INSERT INTO sample_attempts(attempt_id,run_id,analysis_id,ordinal,status,reserved_at) VALUES(?,?,?,?,?,?)", (attempt_id, run_id, analysis_id, ordinal, "RESERVED", _utc_now()))
        connection.execute("INSERT INTO budget_meta(key,value) VALUES('active_attempt',?)", (attempt_id,))
        connection.execute("COMMIT")
        return ordinal
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def finish_sample_attempt(path: Path, *, attempt_id: str, outcome: dict) -> None:
    connection = _budget_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute("SELECT value FROM budget_meta WHERE key='active_attempt'").fetchone()
        if not active or active[0] != attempt_id:
            raise RuntimeError("active attempt lock 与当前 attempt 不一致")
        connection.execute("UPDATE sample_attempts SET status='FINISHED',finished_at=?,outcome_json=? WHERE attempt_id=?", (_utc_now(), _canonical_json(outcome), attempt_id))
        connection.execute("DELETE FROM budget_meta WHERE key='active_attempt'")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _url_budget_connection(path: Path) -> sqlite3.Connection:
    connection = _budget_connection(path)
    connection.execute("CREATE TABLE IF NOT EXISTS url_attempts (attempt_key TEXT PRIMARY KEY, requested_url TEXT UNIQUE NOT NULL, ordinal INTEGER UNIQUE NOT NULL, status TEXT NOT NULL, reserved_at TEXT NOT NULL, finished_at TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS url_visits (url TEXT PRIMARY KEY, attempt_key TEXT NOT NULL, kind TEXT NOT NULL, visited_ordinal INTEGER UNIQUE NOT NULL, reserved_at TEXT NOT NULL)")
    return connection


def _begin_url_attempt(path: Path, requested_url: str) -> str:
    key = hashlib.sha256(f"{requested_url}\0{_utc_now()}".encode()).hexdigest()
    connection = _url_budget_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute("SELECT value FROM budget_meta WHERE key='active_url_attempt'").fetchone()
        if active:
            raise RuntimeError(f"已有未闭合 URL attempt {active[0]}")
        used = int(connection.execute("SELECT COUNT(*) FROM url_attempts").fetchone()[0])
        if used >= SOURCE_TOP_LEVEL_ATTEMPT_LIMIT:
            raise RuntimeError("URL top-level attempt 预算已用尽")
        connection.execute("INSERT INTO url_attempts VALUES(?,?,?,?,?,NULL)", (key, requested_url, used + 1, "RESERVED", _utc_now()))
        connection.execute("INSERT INTO budget_meta(key,value) VALUES('active_url_attempt',?)", (key,))
        connection.execute("COMMIT")
        return key
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _reserve_url_visit(path: Path, *, attempt_key: str, url: str, is_redirect: bool) -> None:
    connection = _url_budget_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute("SELECT value FROM budget_meta WHERE key='active_url_attempt'").fetchone()
        if not active or active[0] != attempt_key:
            raise RuntimeError("URL active lock 不匹配")
        used = int(connection.execute("SELECT COUNT(*) FROM url_visits").fetchone()[0])
        known = connection.execute("SELECT 1 FROM url_visits WHERE url=?", (url,)).fetchone()
        if not known and used >= SOURCE_DISTINCT_URL_LIMIT:
            raise RuntimeError("distinct URL 预算已用尽")
        if not known:
            connection.execute("INSERT INTO url_visits VALUES(?,?,?,?,?)", (url, attempt_key, "REDIRECT" if is_redirect else "TOP_LEVEL", used + 1, _utc_now()))
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _finish_url_attempt(path: Path, attempt_key: str) -> None:
    connection = _url_budget_connection(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute("SELECT value FROM budget_meta WHERE key='active_url_attempt'").fetchone()
        if not active or active[0] != attempt_key:
            raise RuntimeError("URL active lock 不匹配")
        connection.execute("UPDATE url_attempts SET status='FINISHED',finished_at=? WHERE attempt_key=?", (_utc_now(), attempt_key))
        connection.execute("DELETE FROM budget_meta WHERE key='active_url_attempt'")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _sessions(database: Path):
    engine = create_engine(f"sqlite:///{database.resolve()}", connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine, expire_on_commit=False), engine


def prepare(*, database: Path, baseline_analysis_id: str, idempotency_key: str,
            second_prompt_text: str, brand_name: str, website_url: str,
            manifest_path: Path) -> dict:
    from app.api.release_catalog import _record_project_configuration, _record_prompt_version
    from app.models import BrowserMonitorRun, Project, Prompt, SinglePromptAnalysis, SinglePromptAnalysisContext
    from app.modules.single_prompt_v2.service import create_analysis
    from app.services.serialization import loads

    if not database.is_file():
        raise ValueError(f"数据库不存在：{database}")
    Session, engine = _sessions(database)
    db = Session()
    try:
        baseline = db.query(SinglePromptAnalysis).filter_by(analysis_id=baseline_analysis_id).one_or_none()
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=baseline_analysis_id).one_or_none()
        if not baseline or not context or baseline.status not in {"READY", "READY_WITH_FAILURES"}:
            raise ValueError("baseline Analysis/Context 不存在或尚未冻结")
        plan = loads(baseline.sampling_plan_json, {})
        prompt_version = plan.get("prompt_version") or {}
        if prompt_version.get("binding_status") != "BOUND":
            raise ValueError("baseline 没有可复用的冻结 PromptVersion")
        if not brand_name.strip() or not website_url.strip():
            raise ValueError("joint fixture 的 brand-name/website-url 必须非空")
        project = db.get(Project, baseline.project_id)
        project.brand_name = brand_name.strip()
        project.website_url = website_url.strip()
        configuration = _record_project_configuration(db, project)
        db.commit()
        primary, primary_created = create_analysis(
            db,
            project_id=baseline.project_id,
            prompt_id=baseline.prompt_id,
            prompt_version_id=prompt_version["prompt_version_id"],
            snapshot_hash=prompt_version["snapshot_hash"],
            sample_count=1,
            idempotency_key=f"{idempotency_key}:primary",
        )
        second_prompt = Prompt(
            project_id=baseline.project_id,
            title="联合真实验收第二固定 Prompt",
            prompt_text=second_prompt_text,
            prompt_group="joint-live-acceptance",
            intent_type="category_awareness",
            importance=3,
            sample_count=1,
            enabled=True,
        )
        db.add(second_prompt)
        db.flush()
        second_version = _record_prompt_version(db, second_prompt)
        db.commit()
        secondary, secondary_created = create_analysis(
            db,
            project_id=baseline.project_id,
            prompt_id=second_prompt.id,
            prompt_version_id=second_version.prompt_version_id,
            snapshot_hash=second_version.snapshot_hash,
            sample_count=1,
            idempotency_key=f"{idempotency_key}:secondary",
        )
        analyses = [(primary, primary_created), (secondary, secondary_created)]
        runs = []
        analysis_rows = []
        for analysis, created in analyses:
            analysis_runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
            if analysis.status != "QUEUED" or len(analysis_runs) != 1 or any(run.status != "queued" for run in analysis_runs):
                raise ValueError("预留 Analysis/Run 已被消费，拒绝替换为新样本")
            runs.extend(analysis_runs)
            analysis_rows.append({
                "analysis_id": analysis.analysis_id,
                "task_id": analysis.task_id,
                "prompt_id": analysis.prompt_id,
                "sampling_plan_hash": analysis.sampling_plan_hash,
                "created": created,
                "run_ids": [run.id for run in analysis_runs],
            })
        if len(runs) != SAMPLE_REQUEST_PLAN:
            raise ValueError("预留 Analysis/Run 已被消费，拒绝替换为新样本")
        manifest = {
            "contract_version": PREPARE_CONTRACT,
            "baseline": {
                "analysis_id": baseline.analysis_id,
                "context_id": context.context_id,
                "raw_output_hash": context.raw_output_hash,
            },
            "prepared": {
                "analysis_id": primary.analysis_id,
                "task_id": primary.task_id,
                "project_id": primary.project_id,
                "prompt_id": primary.prompt_id,
                "original_query": runs[0].original_query,
                "original_query_sha256": hashlib.sha256(runs[0].original_query.encode()).hexdigest(),
                "prompt_version_id": prompt_version["prompt_version_id"],
                "prompt_snapshot_hash": prompt_version["snapshot_hash"],
                "sample_request_budget": SAMPLE_REQUEST_BUDGET,
                "planned_new_requests": SAMPLE_REQUEST_PLAN,
                "project_configuration": {
                    "configuration_version_id": configuration.configuration_version_id,
                    "snapshot_hash": configuration.snapshot_hash,
                    "brand_name": brand_name.strip(),
                    "website_url": website_url.strip(),
                },
                "analyses": analysis_rows,
                "runs": [{
                    "run_id": run.id,
                    "analysis_id": next(row["analysis_id"] for row in analysis_rows if run.id in row["run_ids"]),
                    "logical_run_id": run.logical_run_id,
                    "attempt_id": run.attempt_id,
                    "attempt_no": run.attempt_no,
                    "original_query": run.original_query,
                    "original_query_sha256": hashlib.sha256(run.original_query.encode()).hexdigest(),
                } for run in runs],
                "second_prompt": {
                    "prompt_id": second_prompt.id,
                    "prompt_version_id": second_version.prompt_version_id,
                    "snapshot_hash": second_version.snapshot_hash,
                },
            },
        }
    finally:
        db.close()
        engine.dispose()
    manifest["prepared_database_sha256"] = _file_hash(database)
    manifest["manifest_payload_hash"] = _hash(manifest)
    _write_json(manifest_path, manifest)
    return manifest


def _source_fetcher(source_payload: dict):
    if source_payload.get("contract_version") != SOURCE_RESULTS_CONTRACT:
        raise ValueError("URL 结果契约版本不匹配")
    rows = source_payload.get("results") or []
    budget = source_payload.get("budget") or {}
    attempts = budget.get("attempts") or []
    if budget.get("distinct_url_limit") != SOURCE_DISTINCT_URL_LIMIT or budget.get("top_level_attempt_limit") != SOURCE_TOP_LEVEL_ATTEMPT_LIMIT:
        raise ValueError("URL 双预算上限必须固定为 distinct=20、top-level attempts=20")
    if budget.get("automatic_retries") != 0 or len(attempts) > SOURCE_TOP_LEVEL_ATTEMPT_LIMIT:
        raise ValueError("URL 获取禁止自动重试，且 top-level attempts 不得超过 20")
    attempt_urls = [str(row.get("requested_url") or "") for row in attempts]
    redirect_urls = []
    for attempt in attempts:
        for event in attempt.get("redirect_events") or []:
            if not event.get("from_url") or not event.get("target_url") or event.get("counted_before_follow") is not True:
                raise ValueError("redirect 必须含 from/target 且在继续前原子计入凭据")
            redirect_urls.append(str(event["target_url"]))
    if len(set(attempt_urls + redirect_urls)) > SOURCE_DISTINCT_URL_LIMIT or len(set(attempt_urls)) != len(attempt_urls):
        raise ValueError("URL 尝试必须 distinct 且不得超过 20")
    if any(row.get("attempt_no") != 1 for row in attempts):
        raise ValueError("每个 URL 只允许一次 top-level attempt")
    result_urls = [str(row.get("requested_url") or "") for row in rows]
    if result_urls != attempt_urls:
        raise ValueError("每次 top-level attempt 必须且只能对应一个持久化结果")
    indexed = {}
    for row in rows:
        requested_url = str(row.get("requested_url") or "")
        result = row.get("result") or {}
        if not requested_url or requested_url in indexed:
            raise ValueError("URL 结果缺少唯一 requested_url")
        if str(result.get("fetch_status") or "").upper() == "SUCCESS" and not result.get("acquisition_receipt"):
            raise ValueError("成功 URL 结果必须携带真实 acquisition_receipt")
        if isinstance(result.get("fetch_time"), str):
            result = {**result, "fetch_time": datetime.fromisoformat(result["fetch_time"])}
        indexed[requested_url] = result

    def fetch(urls: list[str]) -> list[dict]:
        return [indexed.get(url, {"fetch_status": "FETCH_FAILED", "failure_reason": "本次验收未提供该 URL 的真实结果"}) for url in urls]

    return fetch


def accept(*, database: Path, manifest_path: Path, official_url: str,
           source_results_path: Path, report_path: Path) -> dict:
    from app.models import (BrowserMonitorRun, ReferenceSource, RunArtifact, SinglePromptAnalysis, SinglePromptAnalysisContext,
                            SinglePromptPreparedSourceSnapshot)
    from app.modules.single_prompt_v2.observation import (
        create_observation_comparison,
        fixed_scope,
        measure_scope,
    )
    from app.modules.single_prompt_v2.observation_api import current_monitor, project_monitor
    from app.modules.single_prompt_v2.source_preparation import (create_source_preparation,
        execute_auto_fetch, freeze_completion_manifest, queue_auto_fetch)
    from app.modules.single_prompt_v2.supplemental_sources import execute_source, frozen_sources, queue_source
    from app.services.serialization import loads

    manifest = _read_json(manifest_path)
    payload_hash = manifest.pop("manifest_payload_hash", None)
    if manifest.get("contract_version") != PREPARE_CONTRACT or payload_hash != _hash(manifest):
        raise ValueError("prepare manifest 契约或 hash 不匹配")
    prepared = manifest["prepared"]
    source_payload = _read_json(source_results_path)
    if source_payload.get("analysis_id") != prepared["analysis_id"]:
        raise ValueError("URL 结果没有绑定本次 Analysis")

    Session, engine = _sessions(database)
    db = Session()
    try:
        analyses = [db.query(SinglePromptAnalysis).filter_by(analysis_id=row["analysis_id"]).one() for row in prepared["analyses"]]
        analysis = analyses[0]
        run_rows = [db.get(BrowserMonitorRun, row["run_id"]) for row in prepared["runs"]]
        analysis_by_id = {row.analysis_id: row for row in analyses}
        expected_analysis_hashes = {row["analysis_id"]: row["sampling_plan_hash"] for row in prepared["analyses"]}
        if any(row.sampling_plan_hash != expected_analysis_hashes[row.analysis_id] for row in analyses) or any(
            run is None
            or run.task_id != analysis_by_id[expected["analysis_id"]].task_id
            or run.logical_run_id != expected["logical_run_id"]
            or run.attempt_id != expected["attempt_id"]
            or run.attempt_no != expected["attempt_no"]
            or hashlib.sha256(run.original_query.encode()).hexdigest() != expected["original_query_sha256"]
            for run, expected in zip(run_rows, prepared["runs"])
        ):
            raise ValueError("预留 Runs/Analysis 身份漂移")
        existing_contexts = [db.query(SinglePromptAnalysisContext).filter_by(analysis_id=row.analysis_id).one_or_none() for row in analyses]
        if not all(existing_contexts) or any(row.status not in {"READY", "READY_WITH_FAILURES"} for row in analyses):
            raise ValueError("两个正式 execute-one Analysis 尚未全部冻结")
        raw_artifacts = [db.query(RunArtifact).filter_by(run_id=run.id, artifact_type="raw_result").one_or_none() for run in run_rows]
        if any(not row or not Path(row.storage_path).is_file() for row in raw_artifacts):
            raise ValueError("正式 Run 缺少 raw_result artifact，拒绝验收")
        raw_result_hashes = {str(run.id): _file_hash(Path(artifact.storage_path)) for run, artifact in zip(run_rows, raw_artifacts)}
        context = existing_contexts[0]

        baseline_ref = manifest["baseline"]
        comparison_ref = {"context_id": context.context_id, "raw_output_hash": context.raw_output_hash}
        baseline_scope = fixed_scope(db, prepared["project_id"], prepared["prompt_id"], baseline_ref)
        comparison_scope = fixed_scope(db, prepared["project_id"], prepared["prompt_id"], comparison_ref)
        baseline_plan = baseline_scope["raw"].get("sampling_plan") or {}
        brand = (baseline_plan.get("project_configuration") or {}).get("brand") or {}
        website = str(brand.get("website_url") or "")
        domain = urlsplit(website).hostname
        identity = {
            "canonical_brand_name": brand.get("brand_name"),
            "accepted_aliases": brand.get("brand_aliases") or [],
            "official_domains": [domain] if domain else [],
            "official_urls": [website] if website else [],
        }
        comparison, _ = create_observation_comparison(
            db,
            project_id=prepared["project_id"],
            prompt_id=prepared["prompt_id"],
            baseline=baseline_ref,
            comparison=comparison_ref,
            identity=identity,
        )
        baseline_measurement = measure_scope(baseline_scope, identity)
        comparison_measurement = measure_scope(comparison_scope, identity)
        monitor = current_monitor(prepared["project_id"], prepared["prompt_id"], db)
        project_view = project_monitor(prepared["project_id"], db)

        preparation, _ = create_source_preparation(
            db,
            analysis_id=analysis.analysis_id,
            project_id=prepared["project_id"],
            prompt_id=prepared["prompt_id"],
            idempotency_key=f"joint-real-source:{analysis.analysis_id}",
            created_by="joint-real-acceptance",
        )
        queue_auto_fetch(db, preparation_id=preparation.preparation_id,
                         project_id=prepared["project_id"], prompt_id=prepared["prompt_id"])
        fetch_summary = execute_auto_fetch(
            preparation.preparation_id,
            session_factory=Session,
            fetcher=_source_fetcher(source_payload),
        )
        if fetch_summary["ready"] < 1:
            raise ValueError("没有任何真实 URL 结果通过 T09 正文与获取凭据 Gate")
        source_manifest = freeze_completion_manifest(
            db,
            preparation_id=preparation.preparation_id,
            created_by="joint-real-acceptance",
            allow_partial=True,
        )
        snapshots = db.query(SinglePromptPreparedSourceSnapshot).filter_by(
            preparation_id=preparation.preparation_id
        ).order_by(SinglePromptPreparedSourceSnapshot.id).all()
        official_row = next((row for row in source_payload.get("results") or [] if row.get("requested_url") == official_url), None)
        if not official_row:
            raise ValueError("source-results 未包含显式官网 URL 结果")
        original_citation_count = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_([run.id for run in run_rows])).count()
        supplemental, _ = queue_source(
            db,
            project_id=prepared["project_id"],
            url=official_url,
            idempotency_key=f"joint-real-official:{analysis.analysis_id}",
            fetch_authorized=True,
        )
        execute_source(
            supplemental.source_id,
            session_factory=Session,
            fetcher=lambda urls: [{
                **official_row["result"],
                "url": official_url,
                "fetch_time": datetime.fromisoformat(official_row["result"]["fetch_time"]),
            }],
        )
        db.expire_all()
        supplemental_snapshot = frozen_sources(
            db,
            project_id=prepared["project_id"],
            source_ids=[supplemental.source_id],
        )[0]
        db.refresh(supplemental)
        citation_count_after = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_([run.id for run in run_rows])).count()
        if citation_count_after != original_citation_count:
            raise ValueError("supplemental source 改写了原始 citation 集合")
        comparison_output = loads(comparison.output_json, {})
        report = {
            "contract_version": "joint-real-acceptance-report.v1",
            "external_requests_by_importer": 0,
            "project_id": prepared["project_id"],
            "prompt_id": prepared["prompt_id"],
            "prompt_version_id": prepared["prompt_version_id"],
            "baseline": baseline_ref,
            "comparison": {
                **comparison_ref,
                "analysis_id": analysis.analysis_id,
                "run_ids": [run.id for run, expected in zip(run_rows, prepared["runs"]) if expected["analysis_id"] == analysis.analysis_id],
            },
            "t07": {
                "run_ids": [row["run_id"] for row in monitor["runs"]],
                "metrics": monitor["metrics"],
                "scope_hash": monitor["analysis_selection"]["scope_hash"],
                "project_prompt_ids": [row["prompt"]["id"] for row in project_view["prompts"]],
                "project_metrics": project_view["metrics"],
            },
            "t21": {
                "result_version": comparison.result_version,
                "output_hash": comparison.output_hash,
                "metrics": comparison_output["metrics"],
                "conflicts": comparison_output["conflicts"],
                "limitations": comparison_output["limitations"],
                "monitor_validate_same_counts": (
                    baseline_measurement["metrics"] == comparison_output["baseline"]["metrics"]
                    and comparison_measurement["metrics"] == comparison_output["comparison"]["metrics"]
                ),
            },
            "t09": {
                "preparation_id": preparation.preparation_id,
                "fetch_summary": fetch_summary,
                "completion_manifest_id": source_manifest.manifest_id,
                "completion_manifest_hash": source_manifest.payload_hash,
                "completion_status": source_manifest.status,
                "snapshots": [{
                    "snapshot_id": row.snapshot_id,
                    "canonical_url": row.canonical_url,
                    "content_hash": row.content_hash,
                    "acquisition_method": row.acquisition_method,
                } for row in snapshots],
                "supplemental": {
                    "source_id": supplemental.source_id,
                    "source_role": supplemental_snapshot["source_role"],
                    "snapshot_hash": supplemental.snapshot_hash,
                    "content_hash": supplemental_snapshot["content_hash"],
                    "acquisition_receipt": supplemental_snapshot["acquisition_receipt"],
                    "original_citation_count_before": original_citation_count,
                    "original_citation_count_after": citation_count_after,
                },
            },
            "raw_result_artifact_sha256": raw_result_hashes,
        }
    finally:
        db.close()
        engine.dispose()
    report["report_payload_hash"] = _hash(report)
    _write_json(report_path, report)
    return report


def execute_one(*, database: Path, manifest_path: Path, analysis_id: str, budget_database: Path) -> dict:
    """Execute one predeclared one-Run Analysis; this is the only command that may sample externally."""
    from app.models import BrowserMonitorRun, RunArtifact, SinglePromptAnalysis, SinglePromptAnalysisContext
    from app.modules.single_prompt_v2.service import execute_analysis

    manifest = _read_json(manifest_path)
    payload_hash = manifest.pop("manifest_payload_hash", None)
    if manifest.get("contract_version") != PREPARE_CONTRACT or payload_hash != _hash(manifest):
        raise ValueError("prepare manifest 契约或 hash 不匹配")
    declared = next((row for row in manifest["prepared"]["analyses"] if row["analysis_id"] == analysis_id), None)
    if not declared:
        raise ValueError("Analysis 未在冻结 manifest 中声明")
    Session, engine = _sessions(database)
    db = Session()
    try:
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one()
        runs = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).order_by(BrowserMonitorRun.id).all()
        if analysis.status != "QUEUED" or len(runs) != 1 or runs[0].status != "queued":
            raise ValueError("execute-one 仅接受尚未消费的单 Run Analysis")
        run = runs[0]
        expected = next(row for row in manifest["prepared"]["runs"] if row["run_id"] == run.id)
        if run.attempt_id != expected["attempt_id"] or run.attempt_no != 1 or run.retry_of_run_id is not None:
            raise ValueError("冻结 Run 身份漂移")
    finally:
        db.close()
    ordinal = reserve_sample_attempt(
        budget_database,
        analysis_id=analysis_id,
        run_id=run.id,
        attempt_id=run.attempt_id,
    )
    # No loop and no retry: formal execution is invoked exactly once after durable reservation.
    execute_analysis(analysis_id, freeze_with_failures=True, session_factory=Session)
    db = Session()
    try:
        run = db.get(BrowserMonitorRun, run.id)
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one()
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).one_or_none()
        raw_artifact = db.query(RunArtifact).filter_by(run_id=run.id, artifact_type="raw_result").one_or_none()
        raw_result_hash = _file_hash(Path(raw_artifact.storage_path)) if raw_artifact and Path(raw_artifact.storage_path).is_file() else ""
        if run.status == "success" and not raw_result_hash:
            raise RuntimeError("成功 Run 缺少 raw_result artifact；保留 active lock 等待人工核对")
        outcome = {
            "ordinal": ordinal,
            "request_budget_limit": SAMPLE_REQUEST_BUDGET,
            "automatic_retries": 0,
            "analysis_id": analysis_id,
            "analysis_status": analysis.status,
            "run_id": run.id,
            "attempt_id": run.attempt_id,
            "run_status": run.status,
            "error_type": run.error_type,
            "error_message": run.error_message,
            "context_id": context.context_id if context else None,
            "raw_output_hash": context.raw_output_hash if context else None,
            "raw_result_artifact_sha256": raw_result_hash,
        }
    finally:
        db.close()
        engine.dispose()
    finish_sample_attempt(budget_database, attempt_id=run.attempt_id, outcome=outcome)
    return outcome


def fetch_urls(*, analysis_id: str, urls_path: Path, budget_database: Path,
               output_path: Path, fetcher=None) -> dict:
    """Fetch each explicit URL once; the durable callback accounts every connection first."""
    if fetcher is None:
        from app.modules.optimization.passage_service import fetch_page
        fetcher = fetch_page
    urls_value = json.loads(urls_path.read_text(encoding="utf-8"))
    if not isinstance(urls_value, list) or not urls_value or any(not isinstance(url, str) or not url for url in urls_value):
        raise ValueError("urls JSON 必须是非空字符串数组")
    if len(urls_value) > SOURCE_TOP_LEVEL_ATTEMPT_LIMIT or len(set(urls_value)) != len(urls_value):
        raise ValueError("top-level URL 必须 distinct 且不超过 20")
    attempts = []
    results = []
    for requested_url in urls_value:
        attempt_key = _begin_url_attempt(budget_database, requested_url)
        redirect_events = []
        prior_url = None

        def before_request(url: str, metadata: dict) -> None:
            nonlocal prior_url
            _reserve_url_visit(
                budget_database,
                attempt_key=attempt_key,
                url=url,
                is_redirect=bool(metadata.get("is_redirect")),
            )
            if metadata.get("is_redirect"):
                redirect_events.append({
                    "from_url": prior_url,
                    "target_url": url,
                    "counted_before_follow": True,
                })
            prior_url = url

        try:
            result = fetcher(requested_url, before_request=before_request)
        except BaseException:
            # Preserve active lock: after an unclassified crash the command must not guess whether delivery occurred.
            raise
        _finish_url_attempt(budget_database, attempt_key)
        attempts.append({
            "requested_url": requested_url,
            "attempt_no": 1,
            "redirect_events": redirect_events,
        })
        results.append({"requested_url": requested_url, "result": result})
    output = {
        "contract_version": SOURCE_RESULTS_CONTRACT,
        "analysis_id": analysis_id,
        "budget": {
            "distinct_url_limit": SOURCE_DISTINCT_URL_LIMIT,
            "top_level_attempt_limit": SOURCE_TOP_LEVEL_ATTEMPT_LIMIT,
            "automatic_retries": 0,
            "attempts": attempts,
        },
        "results": results,
    }
    _write_json(output_path, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Joint isolated acceptance. Only execute-one may invoke the configured collector.")
    parser.add_argument("--artifact-root", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--database", type=Path, required=True)
    prepare_parser.add_argument("--baseline-analysis-id", required=True)
    prepare_parser.add_argument("--idempotency-key", required=True)
    prepare_parser.add_argument("--second-prompt-text-file", type=Path, required=True)
    prepare_parser.add_argument("--brand-name", required=True)
    prepare_parser.add_argument("--website-url", required=True)
    prepare_parser.add_argument("--manifest", type=Path, required=True)
    accept_parser = subparsers.add_parser("accept")
    accept_parser.add_argument("--database", type=Path, required=True)
    accept_parser.add_argument("--manifest", type=Path, required=True)
    accept_parser.add_argument("--source-results", type=Path, required=True)
    accept_parser.add_argument("--official-url", required=True)
    accept_parser.add_argument("--report", type=Path, required=True)
    execute_parser = subparsers.add_parser("execute-one")
    execute_parser.add_argument("--database", type=Path, required=True)
    execute_parser.add_argument("--manifest", type=Path, required=True)
    execute_parser.add_argument("--analysis-id", required=True)
    execute_parser.add_argument("--budget-database", type=Path, required=True)
    fetch_parser = subparsers.add_parser("fetch-urls")
    fetch_parser.add_argument("--analysis-id", required=True)
    fetch_parser.add_argument("--urls", type=Path, required=True)
    fetch_parser.add_argument("--budget-database", type=Path, required=True)
    fetch_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["MONITORING_ARTIFACT_DIR"] = str(args.artifact_root / "monitoring")
    os.environ["EVIDENCE_ARTIFACT_DIR"] = str(args.artifact_root / "evidence")
    if args.command == "prepare":
        output = prepare(database=args.database, baseline_analysis_id=args.baseline_analysis_id,
                         idempotency_key=args.idempotency_key,
                         second_prompt_text=args.second_prompt_text_file.read_text(encoding="utf-8"),
                         brand_name=args.brand_name, website_url=args.website_url,
                         manifest_path=args.manifest)
    elif args.command == "accept":
        output = accept(database=args.database, manifest_path=args.manifest,
                        official_url=args.official_url, source_results_path=args.source_results,
                        report_path=args.report)
    elif args.command == "execute-one":
        output = execute_one(database=args.database, manifest_path=args.manifest,
                             analysis_id=args.analysis_id, budget_database=args.budget_database)
    else:
        output = fetch_urls(analysis_id=args.analysis_id, urls_path=args.urls,
                            budget_database=args.budget_database, output_path=args.output)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

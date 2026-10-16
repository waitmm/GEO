from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import SinglePromptAnalysisContext, SinglePromptDiagnosisExecution
from app.modules.single_prompt_v2.diagnosis import recover_interrupted_diagnoses
from app.modules.single_prompt_v2.observation import fixed_scope, measure_scope
from app.modules.single_prompt_v2.retest import _canonical_json, _hash


DB_ENV = "GEO_T05_ACCEPTANCE_DB"
MANIFEST_ENV = "GEO_T05_ACCEPTANCE_MANIFEST"
DB_SHA_ENV = "GEO_T05_ACCEPTANCE_DB_SHA256"


def _required_saved_evidence() -> tuple[str, str, str]:
    values = tuple(os.environ.get(key, "") for key in (DB_ENV, MANIFEST_ENV, DB_SHA_ENV))
    if not all(values):
        pytest.skip(f"真实 T05 隔离证据未绑定；需设置 {DB_ENV}/{MANIFEST_ENV}/{DB_SHA_ENV}")
    return values


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _saved_rows(database: str, manifest: dict) -> tuple[dict, dict, dict]:
    connection = sqlite3.connect(f"file:{database}?immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        context = dict(connection.execute(
            "SELECT * FROM single_prompt_analysis_contexts WHERE analysis_id = ?",
            (manifest["analysis_id"],),
        ).fetchone())
        config = dict(connection.execute(
            "SELECT * FROM project_configuration_versions WHERE project_id = ?",
            (manifest["project_id"],),
        ).fetchone())
        prompt = dict(connection.execute(
            "SELECT * FROM prompt_versions WHERE prompt_id = ?",
            (manifest["prompt_id"],),
        ).fetchone())
        return context, config, prompt
    finally:
        connection.close()


def test_real_t05_sample_survives_restart_and_replays_frozen_metrics(tmp_path):
    database, manifest_path, expected_database_sha = _required_saved_evidence()
    with open(manifest_path, encoding="utf-8") as stream:
        manifest = json.load(stream)
    assert manifest["isolated_test_data"] is True
    assert _sha256(database) == expected_database_sha

    context_row, config_row, prompt_row = _saved_rows(database, manifest)
    raw = json.loads(context_row["raw_output_json"])
    config_snapshot = json.loads(config_row["snapshot_json"])
    prompt_snapshot = json.loads(prompt_row["snapshot_json"])
    plan = raw["sampling_plan"]

    assert context_row["raw_output_hash"] == _hash(raw)
    assert context_row["raw_output_hash"] == "e38266eb78aa67fa08f644c22066cf5b5e79f8327b2490a9f92e391782624fbd"
    assert config_row["configuration_version_id"] == manifest["project_configuration_version_id"]
    assert config_row["snapshot_hash"] == manifest["project_configuration_snapshot_hash"] == _hash(config_snapshot)
    assert prompt_row["prompt_version_id"] == manifest["prompt_version_id"]
    assert prompt_row["snapshot_hash"] == manifest["snapshot_hash"] == _hash(prompt_snapshot)
    assert hashlib.sha256(prompt_snapshot["prompt_text"].encode()).hexdigest() == manifest["prompt_text_hash"]
    assert plan["project_configuration"]["configuration_version_id"] == config_row["configuration_version_id"]
    assert plan["project_configuration"]["snapshot_hash"] == config_row["snapshot_hash"]
    assert plan["prompt_version"]["prompt_version_id"] == prompt_row["prompt_version_id"]
    assert plan["prompt_version"]["snapshot_hash"] == prompt_row["snapshot_hash"]

    frozen_database = tmp_path / "t05-restart.sqlite3"
    shutil.copy2(database, frozen_database)
    engine = create_engine(f"sqlite:///{frozen_database}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        contract_config = {"measurement_contract_version": "single_prompt_measurement.v4_alias_evidence"}
        brand_snapshot = plan["project_configuration"]["brand"]
        db.add(SinglePromptDiagnosisExecution(
            diagnosis_id="t06-t05-crash-injection",
            analysis_id=context_row["analysis_id"],
            context_id=context_row["context_id"],
            project_id=context_row["project_id"],
            prompt_id=context_row["prompt_id"],
            idempotency_key="t06-t05-crash-injection",
            input_fingerprint=_hash({"context_id": context_row["context_id"], "purpose": "T06_RECOVERY_GATE"}),
            raw_output_hash=context_row["raw_output_hash"],
            brand_snapshot_json=_canonical_json(brand_snapshot),
            brand_snapshot_hash=_hash(brand_snapshot),
            truth_snapshot_json="[]",
            truth_set_hash=_hash([]),
            contract_config_json=_canonical_json(contract_config),
            contract_config_hash=_hash(contract_config),
            status="RUNNING",
            progress_json='{"stage":"METRIC_PROJECTION"}',
            active_attempt_token="simulated-crashed-process",
            attempt_count=1,
        ))
        db.commit()
    finally:
        db.close()
        engine.dispose()

    restarted_engine = create_engine(f"sqlite:///{frozen_database}", connect_args={"check_same_thread": False})
    RestartedSession = sessionmaker(bind=restarted_engine)
    restarted = RestartedSession()
    try:
        assert recover_interrupted_diagnoses(restarted) == 1
        recovered = restarted.query(SinglePromptDiagnosisExecution).filter_by(
            diagnosis_id="t06-t05-crash-injection"
        ).one()
        assert recovered.status == "INTERRUPTED"
        assert recovered.blocker_code == "SERVICE_RESTART_INTERRUPTED"
        assert recovered.active_attempt_token == ""
        assert recovered.raw_output_hash == context_row["raw_output_hash"]
        assert recovered.attempt_count == 1

        ref = {
            "context_id": context_row["context_id"],
            "raw_output_hash": context_row["raw_output_hash"],
        }
        scope = fixed_scope(restarted, manifest["project_id"], manifest["prompt_id"], ref)
        identity = {
            "canonical_brand_name": config_snapshot["brand_name"],
            "accepted_aliases": config_snapshot["brand_aliases"],
            "official_domains": [],
            "official_urls": [],
        }
        first = measure_scope(scope, identity)
        replay = measure_scope(scope, identity)
        assert replay == first
        assert first["raw_output_hash"] == context_row["raw_output_hash"]
        assert first["metric_version"] == "single_prompt_measurement.v4_alias_evidence"
        assert first["brand_config_version"] == {
            "configuration_version_id": config_row["configuration_version_id"],
            "version_number": config_row["version_number"],
            "snapshot_hash": config_row["snapshot_hash"],
        }
        assert first["runs"][0]["answer_text"] == raw["runs"][0]["answer_text"]
        mention = first["metrics"]["brand_mention_rate"]
        assert (mention["hit_count"], mention["evaluable_count"], mention["value"]) == (0, 1, 0)
        for key in ("brand_option_rate", "brand_recommendation_rate"):
            metric = first["metrics"][key]
            assert metric["planned_count"] == 1
            assert metric["evaluable_count"] == 0
            assert metric["value"] is None
            assert metric["status"] == "NOT_COMPUTABLE"
            assert metric["unevaluated"] == [
                {"run_id": manifest["run_id"], "reason": "ANSWER_SEMANTIC_NOT_EVALUATED"}
            ]
        persisted_context = restarted.query(SinglePromptAnalysisContext).filter_by(
            context_id=context_row["context_id"]
        ).one()
        assert persisted_context.raw_output_json == context_row["raw_output_json"]
        assert persisted_context.raw_output_hash == context_row["raw_output_hash"]
    finally:
        restarted.close()
        restarted_engine.dispose()

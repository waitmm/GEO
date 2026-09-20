from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, EvidenceAlignmentMaterialization, SourceClaimMaterialization
from app.modules.optimization.materialization_executor import (
    FAILED_FINAL,
    HIT,
    OWNED_BY_OTHER,
    batch_count,
    claim_materialization,
    execute_with_limited_concurrency,
    mark_materialization_failed,
    release_materialization_owner,
    wait_for_materialization,
)


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'executor.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _create_values(model_cls):
    if model_cls is SourceClaimMaterialization:
        return {
            "passage_id": "doc1:b1",
            "passage_content_hash": "passage",
            "source_document_id": 1,
            "source_document_content_hash": "doc",
            "contract_version": "SOURCE_CLAIM_V1",
            "compatibility_status": "UNKNOWN",
            "extractor_impl_version": "impl",
            "prompt_version": "source_claim.v1",
            "schema_version": "v1",
            "provider": "deepseek",
            "model": "test",
        }
    return {
        "answer_unit_semantic_hash": "answer",
        "source_claim_semantic_hash": "claim",
        "contract_version": "ALIGNMENT_V1",
        "compatibility_status": "UNKNOWN",
        "judge_impl_version": "impl",
        "prompt_version": "evidence_alignment.v1",
        "schema_version": "v1",
        "provider": "deepseek",
        "model": "test",
    }


@pytest.mark.parametrize("model_cls", [SourceClaimMaterialization, EvidenceAlignmentMaterialization])
def test_same_materialization_key_single_flight_across_workers(tmp_path, model_cls):
    Session = _session_factory(tmp_path)
    calls = 0
    lock = Lock()

    def worker(index: int):
        nonlocal calls
        db = Session()
        try:
            claim = claim_materialization(
                db,
                model_cls,
                materialization_key="same-key",
                create_values=_create_values(model_cls),
                owner_id=f"worker-{index}",
                lease_seconds=30,
                max_attempts=3,
            )
            if claim.outcome == OWNED_BY_OTHER:
                waited = wait_for_materialization(
                    db,
                    model_cls,
                    materialization_key="same-key",
                    timeout_seconds=2,
                    poll_interval_seconds=0.01,
                )
                return waited.outcome
            if claim.outcome == HIT:
                return HIT
            with lock:
                calls += 1
            time.sleep(0.05)
            claim.row.status = "DONE"
            claim.row.compatibility_status = "COMPATIBLE"
            release_materialization_owner(claim.row)
            db.commit()
            return claim.outcome
        finally:
            db.close()

    outcomes = execute_with_limited_concurrency(list(range(10)), worker, max_concurrency=10)
    db = Session()
    try:
        rows = db.query(model_cls).all()
        assert len(rows) == 1
        assert rows[0].status == "DONE"
        assert calls == 1
        assert outcomes.count("OWNER") == 1
        assert all(outcome in {HIT, "OWNER"} for outcome in outcomes)
    finally:
        db.close()


def test_duplicate_work_items_dedupe_to_one_unique_job():
    work_items = ["same-key"] * 100
    unique_jobs = {key: [] for key in work_items}

    assert len(work_items) == 100
    assert len(unique_jobs) == 1
    assert batch_count(len(unique_jobs), 10) == 1


def test_limited_concurrency_caps_active_external_calls():
    active = 0
    max_observed = 0
    lock = Lock()

    def worker(item: int):
        nonlocal active, max_observed
        with lock:
            active += 1
            max_observed = max(max_observed, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return item

    result = execute_with_limited_concurrency(list(range(10)), worker, max_concurrency=2)

    assert sorted(result) == list(range(10))
    assert max_observed <= 2


def test_valid_lease_blocks_duplicate_llm_and_expired_lease_reclaims_same_row(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        active = EvidenceAlignmentMaterialization(
            materialization_key="lease-key",
            answer_unit_semantic_hash="answer",
            source_claim_semantic_hash="claim",
            contract_version="ALIGNMENT_V1",
            status="IN_PROGRESS",
            owner_id="worker-a",
            lease_expires_at=datetime.utcnow() + timedelta(seconds=60),
            attempt_count=1,
        )
        db.add(active)
        db.commit()

        blocked = claim_materialization(
            db,
            EvidenceAlignmentMaterialization,
            materialization_key="lease-key",
            create_values=_create_values(EvidenceAlignmentMaterialization),
            owner_id="worker-b",
            lease_seconds=30,
            max_attempts=3,
        )
        assert blocked.outcome == OWNED_BY_OTHER
        assert db.query(EvidenceAlignmentMaterialization).count() == 1

        active.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        reclaimed = claim_materialization(
            db,
            EvidenceAlignmentMaterialization,
            materialization_key="lease-key",
            create_values=_create_values(EvidenceAlignmentMaterialization),
            owner_id="worker-b",
            lease_seconds=30,
            max_attempts=3,
        )

        assert reclaimed.outcome == "OWNER"
        assert reclaimed.lease_reclaimed is True
        assert reclaimed.row.owner_id == "worker-b"
        assert reclaimed.row.attempt_count == 2
        assert db.query(EvidenceAlignmentMaterialization).count() == 1
    finally:
        db.close()


def test_crash_resume_uses_done_hits_and_reclaims_expired_job(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        for index in range(6):
            db.add(EvidenceAlignmentMaterialization(
                materialization_key=f"done-{index}",
                answer_unit_semantic_hash=f"a{index}",
                source_claim_semantic_hash=f"c{index}",
                contract_version="ALIGNMENT_V1",
                status="DONE",
                attempt_count=1,
            ))
        db.add(EvidenceAlignmentMaterialization(
            materialization_key="crashed",
            answer_unit_semantic_hash="a",
            source_claim_semantic_hash="c",
            contract_version="ALIGNMENT_V1",
            status="IN_PROGRESS",
            owner_id="dead-worker",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
            attempt_count=1,
        ))
        db.commit()

        keys = [f"done-{index}" for index in range(6)] + ["crashed"] + [f"new-{index}" for index in range(3)]
        outcomes = []
        reclaims = 0
        for key in keys:
            claim = claim_materialization(
                db,
                EvidenceAlignmentMaterialization,
                materialization_key=key,
                create_values={**_create_values(EvidenceAlignmentMaterialization), "answer_unit_semantic_hash": key},
                owner_id="resume-worker",
                lease_seconds=30,
                max_attempts=3,
            )
            outcomes.append(claim.outcome)
            if claim.lease_reclaimed:
                reclaims += 1

        assert outcomes.count(HIT) == 6
        assert outcomes.count("OWNER") == 4
        assert reclaims == 1
        assert db.query(EvidenceAlignmentMaterialization).count() == 10
    finally:
        db.close()


def test_retryable_failure_reuses_same_row_then_done(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        first = claim_materialization(
            db,
            EvidenceAlignmentMaterialization,
            materialization_key="retry-key",
            create_values=_create_values(EvidenceAlignmentMaterialization),
            owner_id="worker-a",
            lease_seconds=30,
            max_attempts=3,
        )
        assert first.outcome == "OWNER"
        assert mark_materialization_failed(
            db,
            first.row,
            error_message="timeout",
            retryable=True,
            max_attempts=3,
        ) == "FAILED_RETRYABLE"

        second = claim_materialization(
            db,
            EvidenceAlignmentMaterialization,
            materialization_key="retry-key",
            create_values=_create_values(EvidenceAlignmentMaterialization),
            owner_id="worker-b",
            lease_seconds=30,
            max_attempts=3,
        )
        assert second.outcome == "OWNER"
        assert second.retry is True
        assert second.row.attempt_count == 2
        second.row.status = "DONE"
        release_materialization_owner(second.row)
        db.commit()

        assert db.query(EvidenceAlignmentMaterialization).count() == 1
        assert db.query(EvidenceAlignmentMaterialization).one().status == "DONE"
    finally:
        db.close()


def test_failed_final_does_not_retry_or_call_external(tmp_path):
    Session = _session_factory(tmp_path)
    db = Session()
    try:
        first = claim_materialization(
            db,
            EvidenceAlignmentMaterialization,
            materialization_key="final-key",
            create_values=_create_values(EvidenceAlignmentMaterialization),
            owner_id="worker-a",
            lease_seconds=30,
            max_attempts=3,
        )
        assert mark_materialization_failed(
            db,
            first.row,
            error_message="invalid input",
            retryable=False,
            max_attempts=3,
        ) == "FAILED_FINAL"

        second = claim_materialization(
            db,
            EvidenceAlignmentMaterialization,
            materialization_key="final-key",
            create_values=_create_values(EvidenceAlignmentMaterialization),
            owner_id="worker-b",
            lease_seconds=30,
            max_attempts=3,
        )

        assert second.outcome == FAILED_FINAL
        assert second.row.attempt_count == 1
        assert db.query(EvidenceAlignmentMaterialization).count() == 1
    finally:
        db.close()

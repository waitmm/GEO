#!/usr/bin/env python3
"""Reconcile one legacy append-only retry pair into one business Run.

Dry-run is the default. ``--apply`` is allowed only for an explicitly audited pair
covered by SC-RUN-RETRY-001; it never starts collection or analysis work.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.release_database import ReleaseSessionLocal
from app.models import (
    BrandMention,
    BrowserMonitorRun,
    BrowserMonitorRunAttempt,
    ReferenceSource,
    RetrievalCandidate,
    RunArtifact,
    SinglePromptAnalysisContext,
    SinglePromptCitationContributionExecution,
    SinglePromptManualImport,
)
from app.services.serialization import loads


MOVABLE_OUTPUTS = (BrandMention, ReferenceSource, RetrievalCandidate, RunArtifact)
IMMUTABLE_DIRECT_DEPENDENCIES = (
    (SinglePromptCitationContributionExecution, SinglePromptCitationContributionExecution.selected_run_id),
    (SinglePromptManualImport, SinglePromptManualImport.run_id),
)
PRESERVED_SOURCE_COLUMNS = {
    "id", "task_id", "project_id", "prompt_id", "logical_run_id", "created_at", "retry_of_run_id",
}


def _context_memberships(db: Session, run_ids: set[int]) -> dict[int, list[str]]:
    memberships = {run_id: [] for run_id in run_ids}
    for context in db.query(SinglePromptAnalysisContext).all():
        scope = loads(context.run_scope_json, {})
        for raw_run_id in scope.get("run_ids") or []:
            run_id = int(raw_run_id)
            if run_id in memberships:
                memberships[run_id].append(context.analysis_id)
    return memberships


def audit_pair(db: Session, *, source_run_id: int, result_run_id: int) -> dict:
    source = db.get(BrowserMonitorRun, source_run_id)
    result = db.get(BrowserMonitorRun, result_run_id)
    if not source or not result:
        raise RuntimeError("RUN_NOT_FOUND")
    if source.id == result.id:
        raise RuntimeError("RUN_PAIR_MUST_DIFFER")
    if (source.project_id, source.prompt_id) != (result.project_id, result.prompt_id):
        raise RuntimeError("RUN_SCOPE_MISMATCH")
    if result.retry_of_run_id != source.id or result.logical_run_id != source.logical_run_id:
        raise RuntimeError("LEGACY_RETRY_LINEAGE_MISMATCH")
    if source.status not in {"failed", "blocked"} or (source.answer_text or "").strip():
        raise RuntimeError("SOURCE_IS_NOT_EMPTY_FAILED_RUN")
    if result.status not in {"success", "partial_success"} or not (result.answer_text or "").strip():
        raise RuntimeError("RESULT_IS_NOT_USABLE_SUCCESS")

    memberships = _context_memberships(db, {source.id, result.id})
    if any(memberships.values()):
        raise RuntimeError(f"RUN_ALREADY_CONSUMED:{json.dumps(memberships, sort_keys=True)}")
    if db.query(BrowserMonitorRun).filter(BrowserMonitorRun.retry_of_run_id == result.id).count():
        raise RuntimeError("RESULT_RUN_HAS_RETRY_CHILDREN")
    if db.query(BrowserMonitorRunAttempt).filter(BrowserMonitorRunAttempt.run_id == result.id).count():
        raise RuntimeError("RESULT_RUN_HAS_ATTEMPT_AUDIT")

    direct_dependencies: dict[str, dict[int, int]] = {}
    for model, run_column in IMMUTABLE_DIRECT_DEPENDENCIES:
        counts = {
            run_id: db.query(model).filter(run_column == run_id).count()
            for run_id in (source.id, result.id)
        }
        direct_dependencies[model.__tablename__] = counts
        if any(counts.values()):
            raise RuntimeError(f"IMMUTABLE_RUN_DEPENDENCY:{model.__tablename__}:{counts}")

    # Catch new FK consumers that this one-time reconciler does not know how to move.
    allowed_tables = {model.__tablename__ for model in MOVABLE_OUTPUTS} | {
        "browser_monitor_runs", "browser_monitor_run_attempts",
        *(model.__tablename__ for model, _ in IMMUTABLE_DIRECT_DEPENDENCIES),
    }
    unknown_dependencies: dict[str, int] = {}
    connection = db.connection()
    schema = inspect(connection)
    for table_name in schema.get_table_names():
        for foreign_key in schema.get_foreign_keys(table_name):
            if foreign_key.get("referred_table") != "browser_monitor_runs":
                continue
            columns = foreign_key.get("constrained_columns") or []
            if len(columns) != 1 or table_name in allowed_tables:
                continue
            column = columns[0]
            count = connection.exec_driver_sql(
                f'SELECT COUNT(*) FROM "{table_name}" WHERE "{column}" IN (?, ?)',
                (source.id, result.id),
            ).scalar_one()
            if count:
                unknown_dependencies[f"{table_name}.{column}"] = int(count)
    if unknown_dependencies:
        raise RuntimeError(f"UNKNOWN_RUN_DEPENDENCY:{json.dumps(unknown_dependencies, sort_keys=True)}")

    movable_counts = {
        model.__tablename__: {
            "source": db.query(model).filter(model.run_id == source.id).count(),
            "result": db.query(model).filter(model.run_id == result.id).count(),
        }
        for model in MOVABLE_OUTPUTS
    }
    return {
        "status": "SAFE_TO_RECONCILE",
        "source_run_id": source.id,
        "result_run_id": result.id,
        "project_id": source.project_id,
        "prompt_id": source.prompt_id,
        "logical_run_id": source.logical_run_id,
        "source_status": source.status,
        "result_status": result.status,
        "result_answer_char_count": result.answer_char_count,
        "result_reference_count": result.resolved_reference_count,
        "analysis_memberships": memberships,
        "direct_dependencies": direct_dependencies,
        "movable_outputs": movable_counts,
    }


def reconcile_pair(db: Session, *, source_run_id: int, result_run_id: int) -> dict:
    audit = audit_pair(db, source_run_id=source_run_id, result_run_id=result_run_id)
    source = db.get(BrowserMonitorRun, source_run_id)
    result = db.get(BrowserMonitorRun, result_run_id)
    assert source and result

    attempt = BrowserMonitorRunAttempt(
        attempt_id=result.attempt_id,
        run_id=source.id,
        task_id=result.task_id,
        attempt_no=max(2, result.attempt_no),
        idempotency_key=result.retry_idempotency_key or f"legacy-retry-run-{result.id}",
        status=result.status.upper(),
        previous_status=source.status,
        previous_error_stage=source.error_stage,
        previous_error_type=source.error_type,
        previous_error_message=source.error_message,
        result_status=result.status,
        result_error_stage=result.error_stage,
        result_error_type=result.error_type,
        result_error_message=result.error_message,
        answer_char_count=result.answer_char_count,
        reference_count=result.resolved_reference_count,
        started_at=result.started_at,
        finished_at=result.finished_at,
    )
    db.add(attempt)
    db.flush()

    # The failed source has no admissible answer. Remove its derived collection rows,
    # then move the successful retry outputs to the stable business Run identity.
    for model in MOVABLE_OUTPUTS:
        db.query(model).filter(model.run_id == source.id).delete(synchronize_session=False)
        db.query(model).filter(model.run_id == result.id).update(
            {model.run_id: source.id}, synchronize_session=False,
        )

    result_values = {
        column.name: getattr(result, column.name)
        for column in BrowserMonitorRun.__table__.columns
        if column.name not in PRESERVED_SOURCE_COLUMNS
    }
    db.delete(result)
    db.flush()
    for name, value in result_values.items():
        setattr(source, name, value)
    source.retry_of_run_id = None
    source.retry_count = max(1, source.attempt_no - 1)
    source.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(source)
    return {
        **audit,
        "status": "RECONCILED",
        "business_run_id": source.id,
        "removed_legacy_retry_run_id": result_run_id,
        "attempt_id": attempt.attempt_id,
        "attempt_no": attempt.attempt_no,
        "final_status": source.status,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--result-run-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = ReleaseSessionLocal()
    try:
        result = (
            reconcile_pair(db, source_run_id=args.source_run_id, result_run_id=args.result_run_id)
            if args.apply
            else audit_pair(db, source_run_id=args.source_run_id, result_run_id=args.result_run_id)
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()

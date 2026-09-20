"""Execution guardrails for V1.1 materialization ledgers.

This helper owns only execution state: claim, lease, wait, retry, and metrics.
Business materialization identity and payloads remain in their own ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import math
import time
import uuid
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


OWNER = "OWNER"
HIT = "HIT"
OWNED_BY_OTHER = "OWNED_BY_OTHER"
FAILED_FINAL = "FAILED_FINAL"
WAIT_TIMEOUT = "WAIT_TIMEOUT"

ACTIVE_STATUSES = {"IN_PROGRESS"}
CLAIMABLE_STATUSES = {"MISSING", "FAILED_RETRYABLE"}
STALE_COMPATIBILITY = {
    "STALE_SCHEMA",
    "STALE_CONTENT",
    "STALE_MODEL",
    "STALE_PROMPT",
    "STALE_SOURCE_SNAPSHOT",
    "INCOMPATIBLE",
}


@dataclass
class MaterializationClaim:
    outcome: str
    row: Any | None = None
    previous_status: str = ""
    lease_reclaimed: bool = False
    retry: bool = False
    created: bool = False


@dataclass
class MaterializationWait:
    outcome: str
    row: Any | None = None
    waited_ms: int = 0


def new_executor_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def batch_count(unique_jobs: int, batch_size: int) -> int:
    if unique_jobs <= 0:
        return 0
    return int(math.ceil(unique_jobs / max(1, int(batch_size or 1))))


def execute_with_limited_concurrency(items: list[Any], worker, *, max_concurrency: int) -> list[Any]:
    max_workers = max(1, int(max_concurrency or 1))
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(worker, items))


def claim_materialization(
    db: Session,
    model_cls: type,
    *,
    materialization_key: str,
    create_values: dict,
    owner_id: str,
    lease_seconds: int,
    max_attempts: int,
    force_reclaim: bool = False,
) -> MaterializationClaim:
    """Atomically claim a materialization row for expensive execution.

    SQLite does not provide row-level locks, so the implementation relies on a
    unique key for first insert and a conditional UPDATE for existing rows.
    """
    now = datetime.utcnow()
    lease_expires_at = now + timedelta(seconds=max(1, int(lease_seconds or 1)))
    row = (
        db.query(model_cls)
        .filter(model_cls.materialization_key == materialization_key)
        .first()
    )
    if row is None:
        values = dict(create_values)
        values.update({
            "materialization_key": materialization_key,
            "status": "IN_PROGRESS",
            "owner_id": owner_id,
            "lease_expires_at": lease_expires_at,
            "attempt_count": 1,
            "started_at": now,
            "error_message": "",
        })
        row = model_cls(**values)
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return MaterializationClaim(OWNER, row=row, previous_status="MISSING", created=True)
        except IntegrityError:
            db.rollback()
            return claim_materialization(
                db,
                model_cls,
                materialization_key=materialization_key,
                create_values=create_values,
                owner_id=owner_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
                force_reclaim=force_reclaim,
            )

    previous_status = row.status or "MISSING"
    previous_owner = row.owner_id or ""
    previous_lease = row.lease_expires_at
    if previous_status == "DONE" and not force_reclaim:
        return MaterializationClaim(HIT, row=row, previous_status=previous_status)
    if previous_status == "FAILED_FINAL" and not force_reclaim:
        return MaterializationClaim(FAILED_FINAL, row=row, previous_status=previous_status)
    if (
        previous_status == "IN_PROGRESS"
        and previous_lease is not None
        and previous_lease > now
        and previous_owner != owner_id
        and not force_reclaim
    ):
        return MaterializationClaim(OWNED_BY_OTHER, row=row, previous_status=previous_status)
    if previous_status == "FAILED_RETRYABLE" and int(row.attempt_count or 0) >= max(1, int(max_attempts or 1)):
        row.status = "FAILED_FINAL"
        row.error_message = row.error_message or "materialization_max_attempts_exceeded"
        db.commit()
        return MaterializationClaim(FAILED_FINAL, row=row, previous_status=previous_status)

    claimable = or_(
        model_cls.status.in_(list(CLAIMABLE_STATUSES)),
        and_(
            model_cls.status == "IN_PROGRESS",
            or_(
                model_cls.lease_expires_at.is_(None),
                model_cls.lease_expires_at <= now,
            ),
        ),
    )
    if force_reclaim:
        claimable = or_(claimable, model_cls.status == "DONE")

    updated = (
        db.query(model_cls)
        .filter(model_cls.materialization_key == materialization_key)
        .filter(claimable)
        .update(
            {
                "status": "IN_PROGRESS",
                "owner_id": owner_id,
                "lease_expires_at": lease_expires_at,
                "attempt_count": func.coalesce(model_cls.attempt_count, 0) + 1,
                "started_at": now,
                "error_message": "",
            },
            synchronize_session=False,
        )
    )
    db.commit()
    row = (
        db.query(model_cls)
        .filter(model_cls.materialization_key == materialization_key)
        .first()
    )
    if updated == 1:
        return MaterializationClaim(
            OWNER,
            row=row,
            previous_status=previous_status,
            lease_reclaimed=previous_status == "IN_PROGRESS",
            retry=previous_status == "FAILED_RETRYABLE",
        )
    if row is not None and row.status == "DONE":
        return MaterializationClaim(HIT, row=row, previous_status=row.status or "")
    if row is not None and row.status == "FAILED_FINAL":
        return MaterializationClaim(FAILED_FINAL, row=row, previous_status=row.status or "")
    return MaterializationClaim(OWNED_BY_OTHER, row=row, previous_status=row.status if row else previous_status)


def wait_for_materialization(
    db: Session,
    model_cls: type,
    *,
    materialization_key: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> MaterializationWait:
    started = time.monotonic()
    timeout = max(0.0, float(timeout_seconds or 0.0))
    poll_interval = max(0.01, float(poll_interval_seconds or 0.01))
    while True:
        row = (
            db.query(model_cls)
            .filter(model_cls.materialization_key == materialization_key)
            .first()
        )
        if row is not None and row.status == "DONE":
            waited_ms = int((time.monotonic() - started) * 1000)
            return MaterializationWait(HIT, row=row, waited_ms=waited_ms)
        if row is not None and row.status in {"FAILED_RETRYABLE", "FAILED_FINAL"}:
            waited_ms = int((time.monotonic() - started) * 1000)
            return MaterializationWait(row.status, row=row, waited_ms=waited_ms)
        if time.monotonic() - started >= timeout:
            waited_ms = int((time.monotonic() - started) * 1000)
            return MaterializationWait(WAIT_TIMEOUT, row=row, waited_ms=waited_ms)
        time.sleep(poll_interval)
        db.expire_all()


def mark_materialization_failed(
    db: Session,
    row: Any,
    *,
    error_message: str,
    retryable: bool,
    max_attempts: int,
) -> str:
    attempts = int(row.attempt_count or 0)
    final = (not retryable) or attempts >= max(1, int(max_attempts or 1))
    row.status = "FAILED_FINAL" if final else "FAILED_RETRYABLE"
    row.compatibility_status = "UNKNOWN"
    row.error_message = (error_message or "")[:2000]
    row.lease_expires_at = None
    row.owner_id = ""
    db.commit()
    return row.status


def release_materialization_owner(row: Any) -> None:
    row.owner_id = ""
    row.lease_expires_at = None

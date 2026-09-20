from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.runtime_projection.canonical import (
    CANONICALIZATION_VERSION,
    FieldState,
    manifest_bytes,
    sha256_bytes,
    semantic_hash,
)
from app.modules.runtime_projection.projector import (
    RUNTIME_PROFILE_VERSION,
    STAGE_CONTRACTS,
    STAGE_DEPENDENCIES,
)

from .models import (
    RuntimeAnalysisContext,
    RuntimeContextStageSelection,
    RuntimeContextStageSelectionEvent,
    RuntimeCurrentContextPointer,
    RuntimeCurrentContextPointerEvent,
    RuntimeManifest,
    RuntimeReviewTarget,
    RuntimeStageAttempt,
    RuntimeStageAttemptResult,
    RuntimeStageExecution,
    RuntimeStageInputEdge,
    RuntimeStageReviewDecision,
    RuntimeValidityEvent,
    RuntimeValidityState,
)


TRACKS = frozenset({"PRODUCTION", "SHADOW", "GOLDEN_REPLAY", "LEGACY"})
INPUT_ROLES = frozenset(
    {
        "ROOT_MANIFEST",
        "UPSTREAM_STAGE_OUTPUT",
        "REUSABLE_INPUT",
        "AUTHORITATIVE_REVIEW",
        "CONFIGURATION",
    }
)
REVIEW_TARGET_TYPES = frozenset({"STAGE_OUTPUT", "STAGE_PARTITION", "REUSABLE_FACT_VERSION"})
REVIEW_DECISIONS = frozenset({"CONFIRM", "REJECT", "REOPEN", "DEFER", "SHELVE"})


class RuntimePersistenceError(RuntimeError):
    code = "RUNTIME_PERSISTENCE_ERROR"


class ImmutableObjectError(RuntimePersistenceError):
    code = "IMMUTABLE_OBJECT"


class ConcurrencyConflict(RuntimePersistenceError):
    code = "CONCURRENCY_CONFLICT"


class ReviewConflict(ConcurrencyConflict):
    code = "REVIEW_CONFLICT"


class FencingConflict(ConcurrencyConflict):
    code = "FENCING_CONFLICT"


class InvalidTransition(RuntimePersistenceError):
    code = "INVALID_TRANSITION"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_runtime_id(prefix: str) -> str:
    return f"{prefix}:{uuid4()}"


def _json_audit_value(value: Any) -> Any:
    if isinstance(value, FieldState):
        states = ("FIELD_ABSENT", "FIELD_PRESENT_NULL", "EMPTY_COLLECTION", "VALUE")
        payload = {"field_state": states[value.code]}
        if value.code == 3:
            payload["value"] = _json_audit_value(value.value)
        return payload
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"timestamp": value.isoformat()}
    if isinstance(value, Mapping):
        return {str(key): _json_audit_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_audit_value(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_json_audit_value(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _is_sha256(value: str | None) -> bool:
    if value is None or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


class RuntimePersistence:
    """Transactional persistence primitives for RFC-RUNTIME-001 Phase 1A.

    The caller owns the outer transaction. Methods flush their own writes and
    use CAS updates where the frozen contract requires optimistic concurrency.
    """

    def __init__(self, session: Session):
        self.session = session

    def _manifest(self, manifest_id: str) -> RuntimeManifest:
        manifest = self.session.get(RuntimeManifest, manifest_id)
        if manifest is None:
            raise InvalidTransition(f"unknown manifest: {manifest_id}")
        return manifest

    def create_manifest(
        self,
        *,
        manifest_id: str,
        manifest_type: str,
        manifest_contract_version: str,
        payload: Any,
        member_refs: Sequence[Mapping[str, Any]],
        created_by: str,
        created_at: datetime | None = None,
    ) -> RuntimeManifest:
        member_count = len(member_refs)
        canonical = manifest_bytes(manifest_type, manifest_contract_version, payload)
        digest = sha256_bytes(canonical)
        candidate = RuntimeManifest(
            manifest_id=manifest_id,
            manifest_type=manifest_type,
            manifest_contract_version=manifest_contract_version,
            canonicalization_version=CANONICALIZATION_VERSION,
            member_count=member_count,
            member_refs_json=_json(member_refs),
            payload_json=_json(payload),
            canonical_bytes=canonical,
            canonical_hash=digest,
            created_by=created_by,
            created_at=created_at or utcnow(),
        )
        existing = self.session.get(RuntimeManifest, manifest_id)
        if existing is not None:
            same = all(
                getattr(existing, field) == getattr(candidate, field)
                for field in (
                    "manifest_type",
                    "manifest_contract_version",
                    "canonicalization_version",
                    "member_count",
                    "member_refs_json",
                    "payload_json",
                    "canonical_bytes",
                    "canonical_hash",
                )
            )
            if not same:
                raise ImmutableObjectError(f"manifest identity collision: {manifest_id}")
            return existing
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def create_context(
        self,
        *,
        context_id: str,
        project_id: int,
        prompt_id: int,
        workflow_track: str,
        context_fingerprint: str,
        root_manifest_id: str,
        root_runtime_contract_profile_version: str,
        context_manifest_hash: str,
        evidence_package_ref: str,
        creation_actor: str,
        creation_reason: str,
        created_at: datetime | None = None,
    ) -> RuntimeAnalysisContext:
        if workflow_track not in TRACKS:
            raise InvalidTransition(f"unknown workflow track: {workflow_track}")
        if not _is_sha256(context_fingerprint) or not _is_sha256(context_manifest_hash):
            raise InvalidTransition("context hashes must be lowercase SHA-256")
        if self.session.get(RuntimeAnalysisContext, context_id) is not None:
            raise ImmutableObjectError(f"context already exists: {context_id}")
        root = self._manifest(root_manifest_id)
        context = RuntimeAnalysisContext(
            context_id=context_id,
            project_id=project_id,
            prompt_id=prompt_id,
            workflow_track=workflow_track,
            context_fingerprint=context_fingerprint,
            fingerprint_contract_version="runtime_context_fingerprint.v1",
            root_manifest_id=root.manifest_id,
            root_manifest_hash=root.canonical_hash,
            root_runtime_contract_profile_version=root_runtime_contract_profile_version,
            context_manifest_hash=context_manifest_hash,
            evidence_package_ref=evidence_package_ref,
            creation_actor=creation_actor,
            creation_reason=creation_reason,
            created_at=created_at or utcnow(),
        )
        self.session.add(context)
        self._add_validity_state(
            target_type="CONTEXT",
            context_id=context_id,
            stage_execution_id=None,
            target_ref=context_id,
            target_hash=context_manifest_hash,
        )
        self.session.flush()
        return context

    def create_stage_execution(
        self,
        *,
        stage_execution_id: str,
        context_id: str,
        stage_type: str,
        input_manifest_id: str,
        configuration_manifest_id: str,
        input_edges: Sequence[Mapping[str, Any]],
        created_by: str,
        creation_reason: str,
        semantic_execution_fingerprint: str | None = None,
        supersedes_stage_execution_id: str | None = None,
        created_at: datetime | None = None,
    ) -> RuntimeStageExecution:
        if stage_type not in STAGE_CONTRACTS:
            raise InvalidTransition(f"stage is not in frozen profile: {stage_type}")
        if self.session.get(RuntimeAnalysisContext, context_id) is None:
            raise InvalidTransition(f"unknown context: {context_id}")
        if self.session.get(RuntimeStageExecution, stage_execution_id) is not None:
            raise ImmutableObjectError(f"stage execution already exists: {stage_execution_id}")
        input_manifest = self._manifest(input_manifest_id)
        configuration_manifest = self._manifest(configuration_manifest_id)
        expected_input_type = f"StageInputManifest/{stage_type}"
        expected_contract = STAGE_CONTRACTS[stage_type]
        if (
            input_manifest.manifest_type != expected_input_type
            or input_manifest.manifest_contract_version != f"{expected_contract}/input"
        ):
            raise InvalidTransition("input manifest does not match frozen Stage contract")
        if (
            configuration_manifest.manifest_type != f"StageConfigurationManifest/{stage_type}"
            or configuration_manifest.manifest_contract_version != f"{expected_contract}/configuration"
        ):
            raise InvalidTransition("configuration manifest does not match frozen Stage contract")
        if input_manifest.member_count != len(input_edges):
            raise InvalidTransition("persisted input edge count does not match input manifest")
        configuration_edges = [
            edge
            for edge in input_edges
            if edge.get("input_role") == "CONFIGURATION"
            and edge.get("source_identity_ref") == configuration_manifest_id
            and edge.get("consumed_semantic_hash") == configuration_manifest.canonical_hash
        ]
        if len(configuration_edges) != 1:
            raise InvalidTransition("Stage input must contain its one exact configuration edge")
        if semantic_execution_fingerprint is not None and not _is_sha256(semantic_execution_fingerprint):
            raise InvalidTransition("semantic execution fingerprint must be lowercase SHA-256")
        if supersedes_stage_execution_id is not None:
            prior = self.session.get(RuntimeStageExecution, supersedes_stage_execution_id)
            if prior is None or prior.context_id != context_id or prior.stage_type != stage_type:
                raise InvalidTransition("RECOMPUTE may supersede only the same Context and Stage type")

        execution = RuntimeStageExecution(
            stage_execution_id=stage_execution_id,
            context_id=context_id,
            runtime_stage_profile_version=RUNTIME_PROFILE_VERSION,
            stage_type=stage_type,
            stage_scope_key="WHOLE_CONTEXT",
            stage_contract_version=expected_contract,
            input_manifest_id=input_manifest.manifest_id,
            input_set_hash=input_manifest.canonical_hash,
            configuration_manifest_id=configuration_manifest.manifest_id,
            semantic_config_signature=configuration_manifest.canonical_hash,
            semantic_execution_fingerprint=semantic_execution_fingerprint,
            supersedes_stage_execution_id=supersedes_stage_execution_id,
            compute_outcome="NOT_STARTED",
            current_active_authority_generation=0,
            output_manifest_id=None,
            output_set_hash=None,
            output_count=None,
            completion_attempt_id=None,
            created_by=created_by,
            creation_reason=creation_reason,
            created_at=created_at or utcnow(),
            completed_at=None,
        )
        self.session.add(execution)
        self._add_validity_state(
            target_type="STAGE_EXECUTION",
            context_id=context_id,
            stage_execution_id=stage_execution_id,
            target_ref=stage_execution_id,
            target_hash=None,
        )
        self.session.flush()

        for position, raw_edge in enumerate(input_edges):
            role = str(raw_edge["input_role"])
            if role not in INPUT_ROLES:
                raise InvalidTransition(f"unknown StageInputRole: {role}")
            consumed_hash = str(raw_edge["consumed_semantic_hash"])
            if not _is_sha256(consumed_hash):
                raise InvalidTransition("input edge hash must be lowercase SHA-256")
            upstream_id = raw_edge.get("upstream_stage_execution_id")
            if role == "UPSTREAM_STAGE_OUTPUT":
                if not upstream_id:
                    raise InvalidTransition("UPSTREAM_STAGE_OUTPUT requires an execution id")
                upstream = self.session.get(RuntimeStageExecution, str(upstream_id))
                if upstream is None or upstream.context_id != context_id:
                    raise InvalidTransition("upstream execution must belong to the same Context")
                if upstream.stage_type not in STAGE_DEPENDENCIES[stage_type]:
                    raise InvalidTransition("upstream Stage is not a frozen dependency")
                if upstream.output_set_hash != consumed_hash:
                    raise InvalidTransition("input edge hash does not match upstream output")
            edge = RuntimeStageInputEdge(
                edge_id=str(raw_edge.get("edge_id") or f"{stage_execution_id}:input:{position}"),
                stage_execution_id=stage_execution_id,
                input_role=role,
                source_manifest_type=str(raw_edge["source_manifest_type"]),
                source_identity_ref=str(raw_edge["source_identity_ref"]),
                source_contract_version=str(raw_edge["source_contract_version"]),
                consumed_semantic_hash=consumed_hash,
                source_partition_ref=(
                    str(raw_edge["source_partition_ref"])
                    if raw_edge.get("source_partition_ref") is not None
                    else None
                ),
                upstream_stage_execution_id=str(upstream_id) if upstream_id else None,
                created_at=created_at or utcnow(),
            )
            self.session.add(edge)
        self.session.flush()
        return execution

    def recompute_stage_execution(self, **kwargs: Any) -> RuntimeStageExecution:
        if not kwargs.get("supersedes_stage_execution_id"):
            raise InvalidTransition("RECOMPUTE requires supersedes_stage_execution_id")
        return self.create_stage_execution(**kwargs)

    def claim_attempt(
        self,
        *,
        attempt_id: str,
        stage_execution_id: str,
        trigger_actor: str,
        trigger_reason: str,
        executor_identity: str,
        owner_id: str,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> RuntimeStageAttempt:
        now = now or utcnow()
        execution = self.session.get(RuntimeStageExecution, stage_execution_id)
        if execution is None:
            raise InvalidTransition(f"unknown StageExecution: {stage_execution_id}")
        if execution.compute_outcome in {"SUCCEEDED", "TERMINAL_FAILED", "SKIPPED"}:
            raise InvalidTransition(f"StageExecution is terminal: {execution.compute_outcome}")
        if execution.compute_outcome == "ACTIVE":
            active_attempt = self.session.scalar(
                select(RuntimeStageAttempt).where(
                    RuntimeStageAttempt.stage_execution_id == stage_execution_id,
                    RuntimeStageAttempt.authority_generation
                    == execution.current_active_authority_generation,
                )
            )
            if active_attempt is not None and active_attempt.lease_expires_at > now:
                raise FencingConflict("current Attempt lease has not expired")
        attempt_no = int(
            self.session.scalar(
                select(func.coalesce(func.max(RuntimeStageAttempt.attempt_no), 0)).where(
                    RuntimeStageAttempt.stage_execution_id == stage_execution_id
                )
            )
            or 0
        ) + 1
        old_generation = execution.current_active_authority_generation
        generation = old_generation + 1
        result = self.session.execute(
            update(RuntimeStageExecution)
            .where(
                RuntimeStageExecution.stage_execution_id == stage_execution_id,
                RuntimeStageExecution.current_active_authority_generation == old_generation,
                RuntimeStageExecution.compute_outcome.in_(("NOT_STARTED", "ACTIVE")),
            )
            .values(compute_outcome="ACTIVE", current_active_authority_generation=generation)
        )
        if result.rowcount != 1:
            raise FencingConflict("Attempt authority generation changed concurrently")
        attempt = RuntimeStageAttempt(
            attempt_id=attempt_id,
            stage_execution_id=stage_execution_id,
            attempt_no=attempt_no,
            authority_generation=generation,
            trigger_actor=trigger_actor,
            trigger_reason=trigger_reason,
            executor_identity=executor_identity,
            owner_id=owner_id,
            lease_acquired_at=now,
            lease_expires_at=lease_expires_at,
            started_at=now,
        )
        self.session.add(attempt)
        self.session.flush()
        self.session.expire(execution)
        return attempt

    def record_attempt_failure(
        self,
        *,
        attempt_id: str,
        retryable: bool,
        error_code: str,
        error_detail: str,
        runtime_metrics: Mapping[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> RuntimeStageAttemptResult:
        attempt = self.session.get(RuntimeStageAttempt, attempt_id)
        if attempt is None:
            raise InvalidTransition(f"unknown Attempt: {attempt_id}")
        if self.session.get(RuntimeStageAttemptResult, attempt_id) is not None:
            raise ImmutableObjectError(f"Attempt already has a result: {attempt_id}")
        execution = self.session.get(RuntimeStageExecution, attempt.stage_execution_id)
        authoritative = (
            execution is not None
            and execution.compute_outcome == "ACTIVE"
            and execution.current_active_authority_generation == attempt.authority_generation
        )
        if authoritative:
            new_outcome = "NOT_STARTED" if retryable else "TERMINAL_FAILED"
            self.session.execute(
                update(RuntimeStageExecution)
                .where(
                    RuntimeStageExecution.stage_execution_id == attempt.stage_execution_id,
                    RuntimeStageExecution.current_active_authority_generation == attempt.authority_generation,
                    RuntimeStageExecution.compute_outcome == "ACTIVE",
                )
                .values(compute_outcome=new_outcome)
            )
            attempt_outcome = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
        else:
            attempt_outcome = "LATE_OR_SUPERSEDED_ATTEMPT"
        result = RuntimeStageAttemptResult(
            attempt_id=attempt_id,
            attempt_outcome=attempt_outcome,
            finished_at=finished_at or utcnow(),
            error_code=error_code,
            error_detail=error_detail,
            retryable=retryable if authoritative else False,
            runtime_metrics_json=_json(runtime_metrics or {}),
            audit_output_manifest_id=None,
            audit_output_hash=None,
        )
        self.session.add(result)
        self.session.flush()
        return result

    def publish_success(
        self,
        *,
        attempt_id: str,
        output_manifest_id: str,
        runtime_metrics: Mapping[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> bool:
        attempt = self.session.get(RuntimeStageAttempt, attempt_id)
        if attempt is None:
            raise InvalidTransition(f"unknown Attempt: {attempt_id}")
        if self.session.get(RuntimeStageAttemptResult, attempt_id) is not None:
            raise ImmutableObjectError(f"Attempt already has a result: {attempt_id}")
        output = self._manifest(output_manifest_id)
        execution = self.session.get(RuntimeStageExecution, attempt.stage_execution_id)
        if execution is None:
            raise InvalidTransition("Attempt has no StageExecution")
        expected_type = f"StageOutputManifest/{execution.stage_type}"
        expected_contract = f"{execution.stage_contract_version}/output"
        if output.manifest_type != expected_type or output.manifest_contract_version != expected_contract:
            raise InvalidTransition("output manifest does not match Stage contract")
        finished_at = finished_at or utcnow()
        result = self.session.execute(
            update(RuntimeStageExecution)
            .where(
                RuntimeStageExecution.stage_execution_id == execution.stage_execution_id,
                RuntimeStageExecution.compute_outcome == "ACTIVE",
                RuntimeStageExecution.current_active_authority_generation == attempt.authority_generation,
                RuntimeStageExecution.output_manifest_id.is_(None),
            )
            .values(
                compute_outcome="SUCCEEDED",
                output_manifest_id=output.manifest_id,
                output_set_hash=output.canonical_hash,
                output_count=output.member_count,
                completion_attempt_id=attempt.attempt_id,
                completed_at=finished_at,
            )
        )
        published = result.rowcount == 1
        attempt_result = RuntimeStageAttemptResult(
            attempt_id=attempt_id,
            attempt_outcome="SUCCEEDED" if published else "LATE_OR_SUPERSEDED_ATTEMPT",
            finished_at=finished_at,
            error_code="" if published else "FENCING_GENERATION_SUPERSEDED",
            error_detail="" if published else "Attempt output retained for audit only",
            retryable=False,
            runtime_metrics_json=_json(runtime_metrics or {}),
            audit_output_manifest_id=None if published else output.manifest_id,
            audit_output_hash=None if published else output.canonical_hash,
        )
        self.session.add(attempt_result)
        self.session.flush()
        self.session.expire(execution)
        return published

    def create_review_target(
        self,
        *,
        review_target_id: str,
        target_type: str,
        target_identity_ref: str,
        target_version: str,
        reviewed_manifest_id: str,
        review_contract_version: str,
        context_id: str | None = None,
        stage_execution_id: str | None = None,
        output_partition_id: str | None = None,
        created_at: datetime | None = None,
    ) -> RuntimeReviewTarget:
        if target_type not in REVIEW_TARGET_TYPES:
            raise InvalidTransition(f"unknown review target type: {target_type}")
        manifest = self._manifest(reviewed_manifest_id)
        if target_type in {"STAGE_OUTPUT", "STAGE_PARTITION"}:
            if not context_id or not stage_execution_id:
                raise InvalidTransition("Stage review target requires Context and StageExecution")
            execution = self.session.get(RuntimeStageExecution, stage_execution_id)
            if execution is None or execution.context_id != context_id:
                raise InvalidTransition("review target StageExecution does not match Context")
            if target_type == "STAGE_OUTPUT":
                if execution.compute_outcome != "SUCCEEDED":
                    raise InvalidTransition("full Stage output is not immutable and complete")
                if execution.output_manifest_id != reviewed_manifest_id:
                    raise InvalidTransition("review manifest is not the Stage output")
            elif output_partition_id is None:
                raise InvalidTransition("partition review requires output_partition_id")
        elif any((context_id, stage_execution_id, output_partition_id)):
            raise InvalidTransition("reusable fact review cannot inherit Stage target identity")

        scope_payload = {
            "context_id": context_id,
            "stage_execution_id": stage_execution_id,
            "target_type": target_type,
            "target_identity_ref": target_identity_ref,
            "target_version": target_version,
            "output_partition_id": output_partition_id,
            "reviewed_manifest_id": reviewed_manifest_id,
            "reviewed_output_hash": manifest.canonical_hash,
            "review_contract_version": review_contract_version,
        }
        target = RuntimeReviewTarget(
            review_target_id=review_target_id,
            authority_scope_key=semantic_hash(scope_payload),
            target_type=target_type,
            context_id=context_id,
            stage_execution_id=stage_execution_id,
            target_identity_ref=target_identity_ref,
            target_version=target_version,
            output_partition_id=output_partition_id,
            reviewed_manifest_id=manifest.manifest_id,
            reviewed_output_hash=manifest.canonical_hash,
            member_count=manifest.member_count,
            member_refs_json=manifest.member_refs_json,
            review_contract_version=review_contract_version,
            current_review_id=None,
            state_version=0,
            created_at=created_at or utcnow(),
        )
        self.session.add(target)
        self.session.flush()
        return target

    def append_review_decision(
        self,
        *,
        review_id: str,
        review_target_id: str,
        decision: str,
        actor: str,
        review_note: str,
        expected_state_version: int,
        supersedes_review_id: str | None,
        reviewed_at: datetime | None = None,
    ) -> RuntimeStageReviewDecision:
        if decision not in REVIEW_DECISIONS:
            raise InvalidTransition(f"unknown review decision: {decision}")
        target = self.session.get(RuntimeReviewTarget, review_target_id)
        if target is None:
            raise InvalidTransition(f"unknown review target: {review_target_id}")
        if target.state_version != expected_state_version:
            raise ReviewConflict("stale review state version")
        if target.current_review_id != supersedes_review_id:
            raise ReviewConflict("review predecessor is not the current authoritative leaf")
        if expected_state_version == 0 and supersedes_review_id is not None:
            raise ReviewConflict("first review cannot supersede another decision")
        if expected_state_version > 0 and supersedes_review_id is None:
            raise ReviewConflict("later review must supersede the current leaf")
        if supersedes_review_id is not None:
            predecessor = self.session.get(RuntimeStageReviewDecision, supersedes_review_id)
            if predecessor is None or predecessor.review_target_id != review_target_id:
                raise ReviewConflict("cross-target or missing predecessor")

        review = RuntimeStageReviewDecision(
            review_id=review_id,
            review_target_id=review_target_id,
            decision=decision,
            actor=actor,
            reviewed_at=reviewed_at or utcnow(),
            review_note=review_note,
            supersedes_review_id=supersedes_review_id,
            submitted_state_version=expected_state_version,
        )
        try:
            with self.session.begin_nested():
                self.session.add(review)
                self.session.flush()
                result = self.session.execute(
                    update(RuntimeReviewTarget)
                    .where(
                        RuntimeReviewTarget.review_target_id == review_target_id,
                        RuntimeReviewTarget.state_version == expected_state_version,
                        RuntimeReviewTarget.current_review_id.is_(None)
                        if supersedes_review_id is None
                        else RuntimeReviewTarget.current_review_id == supersedes_review_id,
                    )
                    .values(current_review_id=review_id, state_version=expected_state_version + 1)
                )
                if result.rowcount != 1:
                    raise ReviewConflict("review branch conflict")
                self.session.flush()
        except IntegrityError as exc:
            raise ReviewConflict("review branch conflict") from exc
        self.session.expire(target)
        return review

    def transition_current_context(
        self,
        *,
        project_id: int,
        prompt_id: int,
        workflow_track: str,
        new_context_id: str | None,
        expected_state_version: int,
        actor: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> RuntimeCurrentContextPointer:
        if workflow_track not in TRACKS:
            raise InvalidTransition(f"unknown workflow track: {workflow_track}")
        if new_context_id is not None:
            context = self.session.get(RuntimeAnalysisContext, new_context_id)
            if context is None or (context.project_id, context.prompt_id, context.workflow_track) != (
                project_id,
                prompt_id,
                workflow_track,
            ):
                raise InvalidTransition("Context does not match pointer scope")
            if self.context_eligibility(new_context_id) != "ELIGIBLE":
                raise InvalidTransition("ineligible Context cannot become current")
        pointer = self.session.scalar(
            select(RuntimeCurrentContextPointer).where(
                RuntimeCurrentContextPointer.project_id == project_id,
                RuntimeCurrentContextPointer.prompt_id == prompt_id,
                RuntimeCurrentContextPointer.workflow_track == workflow_track,
            )
        )
        occurred_at = occurred_at or utcnow()
        if pointer is None:
            if expected_state_version != 0:
                raise ConcurrencyConflict("pointer does not exist at expected version")
            pointer = RuntimeCurrentContextPointer(
                pointer_id=new_runtime_id("current-context-pointer"),
                project_id=project_id,
                prompt_id=prompt_id,
                workflow_track=workflow_track,
                current_context_id=new_context_id,
                state_version=1,
                updated_at=occurred_at,
            )
            self.session.add(pointer)
            self.session.flush()
            old_context_id = None
        else:
            old_context_id = pointer.current_context_id
            result = self.session.execute(
                update(RuntimeCurrentContextPointer)
                .where(
                    RuntimeCurrentContextPointer.pointer_id == pointer.pointer_id,
                    RuntimeCurrentContextPointer.state_version == expected_state_version,
                )
                .values(
                    current_context_id=new_context_id,
                    state_version=expected_state_version + 1,
                    updated_at=occurred_at,
                )
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict("stale CurrentContextPointer state version")
        self.session.add(
            RuntimeCurrentContextPointerEvent(
                event_id=new_runtime_id("current-context-event"),
                pointer_id=pointer.pointer_id,
                previous_context_id=old_context_id,
                new_context_id=new_context_id,
                actor=actor,
                reason=reason,
                occurred_at=occurred_at,
                prior_state_version=expected_state_version,
                new_state_version=expected_state_version + 1,
            )
        )
        self.session.flush()
        self.session.expire(pointer)
        return pointer

    def transition_stage_selection(
        self,
        *,
        context_id: str,
        stage_type: str,
        new_stage_execution_id: str | None,
        expected_state_version: int,
        actor: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> RuntimeContextStageSelection:
        context = self.session.get(RuntimeAnalysisContext, context_id)
        if context is None:
            raise InvalidTransition(f"unknown Context: {context_id}")
        output_manifest_id = None
        output_hash = None
        if new_stage_execution_id is not None:
            execution = self.session.get(RuntimeStageExecution, new_stage_execution_id)
            if (
                execution is None
                or execution.context_id != context_id
                or execution.stage_type != stage_type
                or execution.runtime_stage_profile_version != RUNTIME_PROFILE_VERSION
                or execution.stage_scope_key != "WHOLE_CONTEXT"
            ):
                raise InvalidTransition("StageExecution does not match selection scope")
            if execution.compute_outcome != "SUCCEEDED" or self.stage_eligibility(execution.stage_execution_id) != "ELIGIBLE":
                raise InvalidTransition("only a successful eligible StageExecution may be selected")
            output_manifest_id = execution.output_manifest_id
            output_hash = execution.output_set_hash
        selection = self.session.scalar(
            select(RuntimeContextStageSelection).where(
                RuntimeContextStageSelection.context_id == context_id,
                RuntimeContextStageSelection.runtime_stage_profile_version == RUNTIME_PROFILE_VERSION,
                RuntimeContextStageSelection.stage_type == stage_type,
                RuntimeContextStageSelection.stage_scope_key == "WHOLE_CONTEXT",
            )
        )
        occurred_at = occurred_at or utcnow()
        if selection is None:
            if expected_state_version != 0:
                raise ConcurrencyConflict("selection does not exist at expected version")
            selection = RuntimeContextStageSelection(
                selection_id=new_runtime_id("stage-selection"),
                context_id=context_id,
                runtime_stage_profile_version=RUNTIME_PROFILE_VERSION,
                stage_type=stage_type,
                stage_scope_key="WHOLE_CONTEXT",
                selected_stage_execution_id=new_stage_execution_id,
                selected_output_manifest_id=output_manifest_id,
                selected_output_hash=output_hash,
                selection_state_version=1,
                updated_at=occurred_at,
            )
            self.session.add(selection)
            self.session.flush()
            old_execution_id = None
        else:
            old_execution_id = selection.selected_stage_execution_id
            result = self.session.execute(
                update(RuntimeContextStageSelection)
                .where(
                    RuntimeContextStageSelection.selection_id == selection.selection_id,
                    RuntimeContextStageSelection.selection_state_version == expected_state_version,
                )
                .values(
                    selected_stage_execution_id=new_stage_execution_id,
                    selected_output_manifest_id=output_manifest_id,
                    selected_output_hash=output_hash,
                    selection_state_version=expected_state_version + 1,
                    updated_at=occurred_at,
                )
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict("stale ContextStageSelection state version")
        self.session.add(
            RuntimeContextStageSelectionEvent(
                event_id=new_runtime_id("stage-selection-event"),
                selection_id=selection.selection_id,
                previous_stage_execution_id=old_execution_id,
                new_stage_execution_id=new_stage_execution_id,
                actor=actor,
                reason=reason,
                occurred_at=occurred_at,
                prior_state_version=expected_state_version,
                new_state_version=expected_state_version + 1,
            )
        )
        self.session.flush()
        self.session.expire(selection)
        return selection

    def _add_validity_state(
        self,
        *,
        target_type: str,
        context_id: str | None,
        stage_execution_id: str | None,
        target_ref: str,
        target_hash: str | None,
    ) -> RuntimeValidityState:
        target_key = f"{target_type}:{target_ref}:{target_hash or ''}"
        state = RuntimeValidityState(
            validity_state_id=new_runtime_id("validity-state"),
            target_key=target_key,
            target_type=target_type,
            context_id=context_id,
            stage_execution_id=stage_execution_id,
            target_ref=target_ref,
            target_hash=target_hash,
            direct_eligibility="ELIGIBLE",
            state_version=0,
            updated_at=utcnow(),
        )
        self.session.add(state)
        return state

    def register_output_validity_target(
        self,
        *,
        target_type: str,
        context_id: str,
        stage_execution_id: str,
        manifest_id: str,
        manifest_hash: str,
    ) -> RuntimeValidityState:
        if target_type not in {"STAGE_OUTPUT", "STAGE_PARTITION"}:
            raise InvalidTransition("output validity target must be STAGE_OUTPUT or STAGE_PARTITION")
        execution = self.session.get(RuntimeStageExecution, stage_execution_id)
        manifest = self._manifest(manifest_id)
        if execution is None or execution.context_id != context_id:
            raise InvalidTransition("validity target StageExecution does not match Context")
        if manifest.canonical_hash != manifest_hash:
            raise InvalidTransition("validity target hash does not match immutable manifest")
        if target_type == "STAGE_OUTPUT" and (
            execution.compute_outcome != "SUCCEEDED"
            or execution.output_manifest_id != manifest_id
            or execution.output_set_hash != manifest_hash
        ):
            raise InvalidTransition("STAGE_OUTPUT validity target is not the completed Stage output")
        target_key = f"{target_type}:{manifest_id}:{manifest_hash}"
        existing = self.session.scalar(
            select(RuntimeValidityState).where(RuntimeValidityState.target_key == target_key)
        )
        if existing is not None:
            return existing
        state = self._add_validity_state(
            target_type=target_type,
            context_id=context_id,
            stage_execution_id=stage_execution_id,
            target_ref=manifest_id,
            target_hash=manifest_hash,
        )
        self.session.flush()
        return state

    def _validity_for(
        self,
        target_type: str,
        target_ref: str,
        target_hash: str | None = None,
    ) -> RuntimeValidityState:
        conditions = [
            RuntimeValidityState.target_type == target_type,
            RuntimeValidityState.target_ref == target_ref,
        ]
        if target_hash is not None:
            conditions.append(RuntimeValidityState.target_hash == target_hash)
        state = self.session.scalar(select(RuntimeValidityState).where(*conditions))
        if state is None:
            raise InvalidTransition(f"missing validity state for {target_type}:{target_ref}")
        return state

    def transition_validity(
        self,
        *,
        target_type: str,
        target_ref: str,
        target_hash: str | None = None,
        decision: str,
        expected_state_version: int,
        reason_code: str,
        reason_note: str,
        actor: str,
        source: str,
        authorization_evidence: Mapping[str, Any],
        compatibility_validation: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> RuntimeValidityEvent:
        state = self._validity_for(target_type, target_ref, target_hash)
        if state.state_version != expected_state_version:
            raise ConcurrencyConflict("stale validity state version")
        if decision == "INVALIDATE":
            if state.direct_eligibility == "INVALIDATED":
                raise InvalidTransition("target is already invalidated")
            new_eligibility = "INVALIDATED"
        elif decision == "REACTIVATE":
            if state.direct_eligibility != "INVALIDATED":
                raise InvalidTransition("only a directly invalidated target may be reactivated")
            if not compatibility_validation:
                raise InvalidTransition("reactivation requires compatibility validation evidence")
            if target_type == "STAGE_EXECUTION":
                eligibility = self.stage_eligibility(target_ref, ignore_direct=True)
                if eligibility != "ELIGIBLE":
                    raise InvalidTransition(f"Stage dependency lineage is not restorable: {eligibility}")
            new_eligibility = "ELIGIBLE"
        else:
            raise InvalidTransition(f"unsupported validity decision: {decision}")
        occurred_at = occurred_at or utcnow()
        previous_eligibility = state.direct_eligibility
        result = self.session.execute(
            update(RuntimeValidityState)
            .where(
                RuntimeValidityState.validity_state_id == state.validity_state_id,
                RuntimeValidityState.state_version == expected_state_version,
            )
            .values(
                direct_eligibility=new_eligibility,
                state_version=expected_state_version + 1,
                updated_at=occurred_at,
            )
        )
        if result.rowcount != 1:
            raise ConcurrencyConflict("validity state changed concurrently")
        event = RuntimeValidityEvent(
            event_id=new_runtime_id("validity-event"),
            validity_state_id=state.validity_state_id,
            decision=decision,
            previous_eligibility=previous_eligibility,
            new_eligibility=new_eligibility,
            reason_code=reason_code,
            reason_note=reason_note,
            actor=actor,
            source=source,
            authorization_evidence_json=_json(authorization_evidence),
            compatibility_validation_json=_json(compatibility_validation or {}),
            occurred_at=occurred_at,
            expected_state_version=expected_state_version,
            new_state_version=expected_state_version + 1,
        )
        self.session.add(event)
        self.session.flush()
        self.session.expire(state)
        return event

    def context_eligibility(self, context_id: str) -> str:
        return self._validity_for("CONTEXT", context_id).direct_eligibility

    def stage_eligibility(
        self,
        stage_execution_id: str,
        *,
        ignore_direct: bool = False,
        _seen: set[str] | None = None,
    ) -> str:
        execution = self.session.get(RuntimeStageExecution, stage_execution_id)
        if execution is None:
            raise InvalidTransition(f"unknown StageExecution: {stage_execution_id}")
        seen = set() if _seen is None else set(_seen)
        if stage_execution_id in seen:
            raise InvalidTransition("Stage dependency cycle")
        seen.add(stage_execution_id)
        state = self._validity_for("STAGE_EXECUTION", stage_execution_id)
        if not ignore_direct and state.direct_eligibility != "ELIGIBLE":
            return state.direct_eligibility
        if self.context_eligibility(execution.context_id) != "ELIGIBLE":
            return "BLOCKED"
        if execution.output_manifest_id and execution.output_set_hash:
            output_state = self.session.scalar(
                select(RuntimeValidityState).where(
                    RuntimeValidityState.target_type == "STAGE_OUTPUT",
                    RuntimeValidityState.target_ref == execution.output_manifest_id,
                    RuntimeValidityState.target_hash == execution.output_set_hash,
                )
            )
            if output_state is not None and output_state.direct_eligibility != "ELIGIBLE":
                return output_state.direct_eligibility
        edges = self.session.scalars(
            select(RuntimeStageInputEdge).where(
                RuntimeStageInputEdge.stage_execution_id == stage_execution_id,
                RuntimeStageInputEdge.input_role == "UPSTREAM_STAGE_OUTPUT",
            )
        ).all()
        for edge in edges:
            consumed_state = self.session.scalar(
                select(RuntimeValidityState).where(
                    RuntimeValidityState.target_ref == edge.source_identity_ref,
                    RuntimeValidityState.target_hash == edge.consumed_semantic_hash,
                )
            )
            if consumed_state is not None and consumed_state.direct_eligibility != "ELIGIBLE":
                return "STALE"
            upstream = self.session.get(RuntimeStageExecution, edge.upstream_stage_execution_id)
            if upstream is None or upstream.output_set_hash != edge.consumed_semantic_hash:
                return "STALE"
            selection = self.session.scalar(
                select(RuntimeContextStageSelection).where(
                    RuntimeContextStageSelection.context_id == execution.context_id,
                    RuntimeContextStageSelection.runtime_stage_profile_version == RUNTIME_PROFILE_VERSION,
                    RuntimeContextStageSelection.stage_type == upstream.stage_type,
                    RuntimeContextStageSelection.stage_scope_key == "WHOLE_CONTEXT",
                )
            )
            if selection is None or selection.selected_stage_execution_id != upstream.stage_execution_id:
                return "STALE"
            if self.stage_eligibility(upstream.stage_execution_id, _seen=seen) != "ELIGIBLE":
                return "STALE"
        return "ELIGIBLE"

    def attempts_for_execution(self, stage_execution_id: str) -> list[RuntimeStageAttempt]:
        return list(
            self.session.scalars(
                select(RuntimeStageAttempt)
                .where(RuntimeStageAttempt.stage_execution_id == stage_execution_id)
                .order_by(RuntimeStageAttempt.attempt_no)
            )
        )

    def validity_history(self, target_type: str, target_ref: str) -> list[RuntimeValidityEvent]:
        state = self._validity_for(target_type, target_ref)
        return list(
            self.session.scalars(
                select(RuntimeValidityEvent)
                .where(RuntimeValidityEvent.validity_state_id == state.validity_state_id)
                .order_by(RuntimeValidityEvent.new_state_version)
            )
        )

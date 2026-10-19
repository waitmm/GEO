"""Read-only T09 hand-off check for an exact old/new source-manifest pair.

This command never imports a provider client, reserves budget, or writes the
database.  It explains whether the immutable downstream base required by
``plan_source_reanalysis`` already exists.  In particular, it does not create
or infer a human Review when the exact reviewed Answer result is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _one(connection: sqlite3.Connection, query: str, values: tuple[Any, ...]) -> sqlite3.Row | None:
    return connection.execute(query, values).fetchone()


def _manifest(
    connection: sqlite3.Connection,
    manifest_id: str,
    payload_hash: str,
    preparation_id: str,
) -> sqlite3.Row:
    row = _one(
        connection,
        """SELECT * FROM single_prompt_source_completion_manifests
           WHERE manifest_id = ? AND payload_hash = ? AND preparation_id = ?""",
        (manifest_id, payload_hash, preparation_id),
    )
    if row is None:
        raise ValueError(f"SOURCE_COMPLETION_MANIFEST_INPUT_MISMATCH:{manifest_id}")
    payload = json.loads(row["payload_json"])
    if _hash(payload) != row["payload_hash"]:
        raise ValueError(f"SOURCE_COMPLETION_MANIFEST_CONTENT_HASH_MISMATCH:{manifest_id}")
    return row


def _source_rows(row: sqlite3.Row) -> dict[str, dict[str, Any]]:
    payload = json.loads(row["payload_json"])
    return {str(item.get("source_key")): item for item in payload.get("sources") or []}


def assess_readiness(
    connection: sqlite3.Connection,
    *,
    preparation_id: str,
    project_id: int,
    prompt_id: int,
    prior_manifest_id: str,
    prior_manifest_hash: str,
    new_manifest_id: str,
    new_manifest_hash: str,
) -> dict[str, Any]:
    """Return a deterministic, read-only readiness/hand-off report."""
    connection.row_factory = sqlite3.Row
    prior = _manifest(connection, prior_manifest_id, prior_manifest_hash, preparation_id)
    current = _manifest(connection, new_manifest_id, new_manifest_hash, preparation_id)
    lineage_fields = (
        "preparation_id",
        "analysis_id",
        "context_id",
        "citation_manifest_id",
        "citation_manifest_hash",
    )
    if any(prior[field] != current[field] for field in lineage_fields) or (
        current["version_number"] <= prior["version_number"]
    ):
        raise ValueError("SOURCE_REANALYSIS_LINEAGE_MISMATCH")
    citation = _one(
        connection,
        "SELECT * FROM single_prompt_citation_manifests WHERE manifest_id = ?",
        (current["citation_manifest_id"],),
    )
    if (
        citation is None
        or citation["analysis_id"] != current["analysis_id"]
        or citation["context_id"] != current["context_id"]
        or citation["payload_hash"] != current["citation_manifest_hash"]
    ):
        raise ValueError("CITATION_MANIFEST_INPUT_MISMATCH")
    if _hash(json.loads(citation["payload_json"])) != citation["payload_hash"]:
        raise ValueError("SOURCE_MANIFEST_CONTENT_HASH_MISMATCH")
    context = _one(
        connection,
        """SELECT * FROM single_prompt_analysis_contexts
           WHERE context_id = ? AND analysis_id = ? AND project_id = ? AND prompt_id = ?""",
        (current["context_id"], current["analysis_id"], project_id, prompt_id),
    )
    if context is None:
        raise ValueError("SOURCE_REANALYSIS_PROJECT_PROMPT_MISMATCH")

    old_rows, new_rows = _source_rows(prior), _source_rows(current)
    if set(old_rows) != set(new_rows):
        raise ValueError("SOURCE_REANALYSIS_SCOPE_CHANGED")
    changed_keys = sorted(key for key in old_rows if old_rows[key] != new_rows[key])
    if not changed_keys:
        raise ValueError("SOURCE_REANALYSIS_NO_CONTENT_CHANGE")
    old_snapshot_ids = {
        str(old_rows[key].get("snapshot_id"))
        for key in changed_keys
        if old_rows[key].get("snapshot_id")
    }

    executions = connection.execute(
        """SELECT * FROM single_prompt_diagnosis_executions
           WHERE analysis_id = ? AND context_id = ? AND project_id = ?
             AND prompt_id = ? AND raw_output_hash = ?
           ORDER BY diagnosis_id""",
        (
            current["analysis_id"],
            current["context_id"],
            project_id,
            prompt_id,
            context["raw_output_hash"],
        ),
    ).fetchall()
    exact_execution_ids = {str(row["diagnosis_id"]) for row in executions}
    results = []
    if exact_execution_ids:
        placeholders = ",".join("?" for _ in exact_execution_ids)
        results = connection.execute(
            f"""SELECT * FROM single_prompt_diagnosis_results
                 WHERE diagnosis_id IN ({placeholders}) ORDER BY result_version""",
            tuple(sorted(exact_execution_ids)),
        ).fetchall()

    affected: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for result in results:
        output = json.loads(result["output_json"])
        inputs = output.get("input") or {}
        if inputs.get("completion_manifest_id") != prior_manifest_id:
            continue
        bound_snapshots = {str(item) for item in inputs.get("source_snapshot_ids") or []}
        if old_snapshot_ids and not bound_snapshots.intersection(old_snapshot_ids):
            continue
        answer_version = str(inputs.get("answer_result_version") or "")
        answer_hash = str(inputs.get("answer_result_hash") or "")
        review_id = str(inputs.get("answer_review_id") or "")
        answer = _one(
            connection,
            "SELECT * FROM single_prompt_diagnosis_results WHERE result_version = ?",
            (answer_version,),
        )
        answer_execution = (
            _one(
                connection,
                "SELECT * FROM single_prompt_diagnosis_executions WHERE diagnosis_id = ?",
                (answer["diagnosis_id"],),
            )
            if answer is not None
            else None
        )
        review = (
            _one(
                connection,
                """SELECT * FROM single_prompt_diagnosis_reviews
                   WHERE diagnosis_id = ? AND review_id = ? AND result_version = ?""",
                (answer["diagnosis_id"], review_id, answer_version),
            )
            if answer is not None
            else None
        )
        exact_answer_scope = bool(
            answer_execution
            and answer_execution["analysis_id"] == current["analysis_id"]
            and answer_execution["context_id"] == current["context_id"]
            and answer_execution["project_id"] == project_id
            and answer_execution["prompt_id"] == prompt_id
            and answer_execution["raw_output_hash"] == context["raw_output_hash"]
        )
        valid = bool(
            answer
            and answer["output_hash"] == answer_hash
            and exact_answer_scope
            and review
            and review["result_hash"] == answer_hash
            and review["reviewable_set_hash"] == answer["reviewable_set_hash"]
            and review["decision"] == "REVIEW_COMPLETED"
        )
        detail = {
            "base_diagnosis_id": str(result["diagnosis_id"]),
            "base_result_version": str(result["result_version"]),
            "answer_result_version": answer_version,
            "answer_review_id": review_id,
        }
        if valid:
            affected.append(detail)
        else:
            if answer is None:
                reason = "ANSWER_RESULT_NOT_FOUND"
            elif not exact_answer_scope:
                reason = "ANSWER_RESULT_SCOPE_MISMATCH"
            elif answer["output_hash"] != answer_hash:
                reason = "ANSWER_RESULT_HASH_MISMATCH"
            elif review is None:
                reason = "EXACT_ANSWER_REVIEW_NOT_FOUND"
            elif review["result_hash"] != answer_hash or review["reviewable_set_hash"] != answer["reviewable_set_hash"]:
                reason = "ANSWER_REVIEW_IDENTITY_MISMATCH"
            else:
                reason = "ANSWER_REVIEW_NOT_COMPLETED"
            rejected.append({**detail, "reason": reason})

    missing_objects: list[dict[str, Any]] = []
    if not executions:
        missing_objects.extend([
            {"object": "SinglePromptDiagnosisExecution", "required_scope": "exact analysis/context/project/prompt/raw_output_hash"},
            {"object": "SinglePromptDiagnosisResult", "required_scope": "completed Answer result in the exact Diagnosis scope"},
            {"object": "SinglePromptDiagnosisReview", "required_scope": "REVIEW_COMPLETED for the exact Answer result/hash/reviewable-set"},
        ])
    if not affected:
        missing_objects.append({
            "object": "SinglePromptDiagnosisResult",
            "required_scope": "Evidence result bound to the prior Completion Manifest and changed prior Snapshot",
        })

    ready = bool(affected)
    if ready:
        root_cause = "ELIGIBLE_REVIEWED_DOWNSTREAM_BASE_EXISTS"
    elif not executions:
        root_cause = "MISSING_FORMAL_OBJECTS_NOT_SELECTOR_DEFECT"
    elif rejected:
        root_cause = "EXISTING_BASE_FAILED_EXACT_IDENTITY_OR_REVIEW_GATE"
    else:
        root_cause = "NO_PRIOR_EVIDENCE_RESULT_BOUND_TO_CHANGED_SOURCE"
    return {
        "status": "READY" if ready else "BLOCKED",
        "t09_status": "READY_FOR_REANALYSIS_PLANNING" if ready else "BLOCKED",
        "gate_code": "T09_REANALYSIS_BASE_READY" if ready else "T09_REVIEWED_DOWNSTREAM_BASE_REQUIRED",
        "root_cause_classification": root_cause,
        "external_model_calls": 0,
        "safety": {
            "database_writes": 0,
            "reviews_created": 0,
            "provider_client_loaded": False,
        },
        "scope": {
            "preparation_id": preparation_id,
            "project_id": project_id,
            "prompt_id": prompt_id,
            "analysis_id": current["analysis_id"],
            "context_id": current["context_id"],
            "raw_output_hash": context["raw_output_hash"],
            "citation_manifest_id": current["citation_manifest_id"],
            "citation_manifest_hash": current["citation_manifest_hash"],
        },
        "source_lineage": {
            "prior_completion_manifest_id": prior_manifest_id,
            "prior_completion_manifest_hash": prior_manifest_hash,
            "new_completion_manifest_id": new_manifest_id,
            "new_completion_manifest_hash": new_manifest_hash,
            "changed_source_keys": changed_keys,
            "changed_prior_snapshot_ids": sorted(old_snapshot_ids),
        },
        "observed_counts": {
            "exact_scope_diagnosis_executions": len(executions),
            "exact_scope_diagnosis_results": len(results),
            "eligible_reviewed_downstream_bases": len(affected),
        },
        "eligible_bases": affected,
        "rejected_bases": rejected,
        "missing_objects": missing_objects,
        "required_actions": [] if ready else [
            {
                "actor": "SYSTEM",
                "action": "在上述固定范围创建并完成 Answer Diagnosis Result；不得复用其他 Prompt/Context 的结果。",
            },
            {
                "actor": "AUTHORIZED_HUMAN_REVIEWER",
                "action": "通过正式审核入口审核该精确 Answer Result/Hash/Reviewable Set；检查器不得代签或创建 Review。",
            },
            {
                "actor": "SYSTEM",
                "action": "使用该精确 Review 和 prior Completion Manifest 完成 Evidence Result，再重新运行本检查。",
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--preparation-id", required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--prompt-id", type=int, required=True)
    parser.add_argument("--prior-manifest-id", required=True)
    parser.add_argument("--prior-manifest-hash", required=True)
    parser.add_argument("--new-manifest-id", required=True)
    parser.add_argument("--new-manifest-hash", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit("REFUSED: database does not exist")
    uri = f"file:{args.database.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        report = assess_readiness(
            connection,
            preparation_id=args.preparation_id,
            project_id=args.project_id,
            prompt_id=args.prompt_id,
            prior_manifest_id=args.prior_manifest_id,
            prior_manifest_hash=args.prior_manifest_hash,
            new_manifest_id=args.new_manifest_id,
            new_manifest_hash=args.new_manifest_hash,
        )
    finally:
        connection.close()
    report["inspection"] = {
        "database": str(args.database.resolve()),
        "database_mode": "READ_ONLY",
        "database_sha256": _file_hash(args.database),
    }
    rendered = _canonical(report) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

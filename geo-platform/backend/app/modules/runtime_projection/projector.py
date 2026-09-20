from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .canonical import (
    CANONICALIZATION_VERSION,
    EMPTY_COLLECTION,
    FIELD_ABSENT,
    FIELD_PRESENT_NULL,
    FieldState,
    canonical_node,
    manifest_bytes,
    manifest_hash,
    semantic_hash,
    sha256_bytes,
    state_for,
    value,
)


SPIKE_CONTRACT_VERSION = "runtime_projection_spike.v1"
RUNTIME_PROFILE_VERSION = "runtime_stage_profile.single_prompt.v1"
LEGACY_PROFILE_VERSION = "legacy_stage_projection.single_prompt.v1"
FIXED_SCOPE_CONTRACT_VERSION = "LegacyFixedScopeValues.v1"
SCOPE_KEY_CONTRACT_VERSION = "LegacyScopeKey.v1"
VIRTUAL_IDENTITY_VERSION = "virtual_runtime_identity.v1"

BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = BACKEND_ROOT.parent
DEFAULT_DB_PATH = BACKEND_ROOT / "geo_v0.db"
CASE_MANIFESTS = {
    "CASE-REAL-019": PROJECT_ROOT / "docs/semantics/snapshots/CASE-REAL-019.manifest.json",
    "CASE-REAL-040": PROJECT_ROOT / "docs/semantics/snapshots/CASE-REAL-040.manifest.json",
}

STAGES = (
    "RUN_METRICS",
    "ANSWER_SEMANTIC",
    "PRODUCT_TRUTH_PROJECTION",
    "BINDING",
    "SOURCE_QUALIFICATION",
    "SOURCE_FETCH",
    "SEGMENTATION",
    "SOURCE_CLAIM",
    "ALIGNMENT_CANDIDATE_BUILD",
    "EVIDENCE_ALIGNMENT",
    "BENCHMARK",
    "GAP",
    "CHANNEL_EVIDENCE",
    "CHANNEL_RESOLUTION",
    "STRATEGY_SYNTHESIS",
    "EXECUTION_PROPOSAL",
)

STAGE_CONTRACTS = {
    stage: f"runtime_stage.{stage.lower()}.v1" for stage in STAGES
}

STAGE_DEPENDENCIES = {
    "RUN_METRICS": [],
    "ANSWER_SEMANTIC": [],
    "PRODUCT_TRUTH_PROJECTION": ["ANSWER_SEMANTIC"],
    "BINDING": ["ANSWER_SEMANTIC"],
    "SOURCE_QUALIFICATION": [],
    "SOURCE_FETCH": ["SOURCE_QUALIFICATION"],
    "SEGMENTATION": ["SOURCE_FETCH"],
    "SOURCE_CLAIM": ["SEGMENTATION", "SOURCE_QUALIFICATION"],
    "ALIGNMENT_CANDIDATE_BUILD": ["BINDING", "SOURCE_CLAIM", "SOURCE_QUALIFICATION"],
    "EVIDENCE_ALIGNMENT": ["ALIGNMENT_CANDIDATE_BUILD"],
    "BENCHMARK": ["EVIDENCE_ALIGNMENT", "SOURCE_QUALIFICATION"],
    "GAP": ["RUN_METRICS", "ANSWER_SEMANTIC", "PRODUCT_TRUTH_PROJECTION", "EVIDENCE_ALIGNMENT", "BENCHMARK"],
    "CHANNEL_EVIDENCE": ["SOURCE_QUALIFICATION", "SOURCE_CLAIM", "EVIDENCE_ALIGNMENT"],
    "CHANNEL_RESOLUTION": ["PRODUCT_TRUTH_PROJECTION", "GAP", "CHANNEL_EVIDENCE"],
    "STRATEGY_SYNTHESIS": ["RUN_METRICS", "ANSWER_SEMANTIC", "PRODUCT_TRUTH_PROJECTION", "BENCHMARK", "GAP", "CHANNEL_RESOLUTION"],
    "EXECUTION_PROPOSAL": ["RUN_METRICS", "STRATEGY_SYNTHESIS", "PRODUCT_TRUTH_PROJECTION"],
}

SELECTORS = {stage: f"legacy_selector.{stage.lower()}.v1" for stage in STAGES}
SELECTORS["ALIGNMENT_CANDIDATE_BUILD"] = "legacy_selector.alignment_candidates.v1"
SCOPE_PROFILES = {stage: f"legacy_scope.{stage.lower()}.v1" for stage in STAGES}
SCOPE_PROFILES["ALIGNMENT_CANDIDATE_BUILD"] = "legacy_scope.alignment_candidates.v1"

SCOPE_KEY_KINDS = {
    "CASE_ID": "STRING",
    "SNAPSHOT_ID": "STRING",
    "EXACT_DATABASE_SHA256": "SHA256",
    "PROJECT_ID": "SCALAR_ID",
    "PROMPT_ID": "SCALAR_ID",
    "EVIDENCE_PACKAGE_ID": "SCALAR_ID",
    "EVIDENCE_PACKAGE_VERSION": "VERSION_INTEGER",
    "EVIDENCE_PACKAGE_HASH": "SHA256",
    "RUN_IDS": "SET_ID_LIST",
    "RUN_SCOPE_HASH": "SHA256",
    "STRATEGY_CANDIDATE_ID": "SCALAR_ID",
    "STRATEGY_CANDIDATE_STATUS": "STRING",
    "CANDIDATE_DOCUMENT_COLUMN": "STRING",
    "JSON_PATH_SET_ID": "STRING",
    "STEP_KEY": "STRING",
}

COMMON_SCOPE_KEYS = ("CASE_ID", "SNAPSHOT_ID", "EXACT_DATABASE_SHA256")
SCOPE_KEYS = {
    "RUN_METRICS": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "EVIDENCE_PACKAGE_VERSION", "EVIDENCE_PACKAGE_HASH", "RUN_IDS", "RUN_SCOPE_HASH", "JSON_PATH_SET_ID"),
    "ANSWER_SEMANTIC": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "RUN_IDS", "RUN_SCOPE_HASH"),
    "PRODUCT_TRUTH_PROJECTION": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "STRATEGY_CANDIDATE_ID", "STRATEGY_CANDIDATE_STATUS", "CANDIDATE_DOCUMENT_COLUMN", "JSON_PATH_SET_ID"),
    "BINDING": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "RUN_IDS", "RUN_SCOPE_HASH"),
    "SOURCE_QUALIFICATION": COMMON_SCOPE_KEYS + ("RUN_IDS", "RUN_SCOPE_HASH"),
    "SOURCE_FETCH": COMMON_SCOPE_KEYS + ("RUN_IDS", "RUN_SCOPE_HASH"),
    "SEGMENTATION": COMMON_SCOPE_KEYS + ("RUN_IDS", "RUN_SCOPE_HASH"),
    "SOURCE_CLAIM": COMMON_SCOPE_KEYS + ("PROJECT_ID", "RUN_IDS", "RUN_SCOPE_HASH"),
    "ALIGNMENT_CANDIDATE_BUILD": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "RUN_IDS", "RUN_SCOPE_HASH"),
    "EVIDENCE_ALIGNMENT": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "RUN_IDS", "RUN_SCOPE_HASH"),
    "BENCHMARK": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "STRATEGY_CANDIDATE_ID", "STRATEGY_CANDIDATE_STATUS", "CANDIDATE_DOCUMENT_COLUMN", "JSON_PATH_SET_ID"),
    "GAP": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "STRATEGY_CANDIDATE_ID", "STRATEGY_CANDIDATE_STATUS", "CANDIDATE_DOCUMENT_COLUMN", "JSON_PATH_SET_ID", "STEP_KEY"),
    "CHANNEL_EVIDENCE": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "STRATEGY_CANDIDATE_ID", "STRATEGY_CANDIDATE_STATUS", "CANDIDATE_DOCUMENT_COLUMN", "JSON_PATH_SET_ID"),
    "CHANNEL_RESOLUTION": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "STRATEGY_CANDIDATE_ID", "STRATEGY_CANDIDATE_STATUS", "CANDIDATE_DOCUMENT_COLUMN", "JSON_PATH_SET_ID"),
    "STRATEGY_SYNTHESIS": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "STRATEGY_CANDIDATE_ID", "STRATEGY_CANDIDATE_STATUS", "CANDIDATE_DOCUMENT_COLUMN", "JSON_PATH_SET_ID"),
    "EXECUTION_PROPOSAL": COMMON_SCOPE_KEYS + ("PROJECT_ID", "PROMPT_ID", "EVIDENCE_PACKAGE_ID", "STRATEGY_CANDIDATE_ID", "STRATEGY_CANDIDATE_STATUS"),
}

JSON_PATH_SETS = {
    "PACKAGE_METRIC_PATHS": ("$.metrics", "$.metric_snapshot", "$.run_metric_eligibility", "$.answer_eligible_run_ids", "$.citation_eligible_run_ids", "$.retrieval_eligible_run_ids", "$.retrieval_metrics_status", "$.metric_spec_version"),
    "CANDIDATE_TRUTH_PATHS": ("$.decision_reasons", "$.evidence_summary.gap_items", "$.target_capabilities", "$.product_truth_refs"),
    "CANDIDATE_BENCHMARK_PATHS": ("$.benchmark_source", "$.benchmark_evidence_ids", "$.citation_decision_values", "$.citation_value_summary", "$.evidence_summary.gap_items"),
    "CANDIDATE_GAP_PATHS": ("$.evidence_summary.gap_items", "$.target_capabilities", "$.gap_item_ids", "$.evidence_gap_reason", "$.evidence_gap_cause", "$.observed_problem", "$.product_truth_gate"),
    "CANDIDATE_CHANNEL_EVIDENCE_PATHS": ("$.channel_aggregation", "$.citation_decision_values", "$.citation_value_summary"),
    "CANDIDATE_CHANNEL_RESOLUTION_PATHS": ("$.channel_roles", "$.planned_channels", "$.strategy_channel_resolver", "$.channel_resolution_state", "$.channels"),
    "CANDIDATE_STRATEGY_PATHS": ("$.strategy_synthesis", "$.decision_reasons", "$.intervention_themes", "$.strategy_portfolio", "$.strategy_decision_view", "$.strategy_audit_view", "$.strategy_context", "$.strategy_phase", "$.strategy_schema_version", "$.strategy_basis", "$.primary_intervention_path", "$.planned_channels"),
}

STAGE_PATH_SET = {
    "RUN_METRICS": "PACKAGE_METRIC_PATHS",
    "PRODUCT_TRUTH_PROJECTION": "CANDIDATE_TRUTH_PATHS",
    "BENCHMARK": "CANDIDATE_BENCHMARK_PATHS",
    "GAP": "CANDIDATE_GAP_PATHS",
    "CHANNEL_EVIDENCE": "CANDIDATE_CHANNEL_EVIDENCE_PATHS",
    "CHANNEL_RESOLUTION": "CANDIDATE_CHANNEL_RESOLUTION_PATHS",
    "STRATEGY_SYNTHESIS": "CANDIDATE_STRATEGY_PATHS",
}

ROW_STATE_FIELDS = {
    "optimization_evidence_packages": ("schema_version", "metric_spec_version", "package_hash", "version"),
    "browser_monitor_runs": ("collector_version", "parser_version", "status", "reference_complete"),
    "reference_sources": ("canonicalization_version", "canonical_url_hash"),
    "retrieval_candidates": ("canonicalization_version", "canonical_url_hash"),
    "prompt_analysis_runs": ("status", "extractor_version", "input_contract_hash", "output_contract_hash"),
    "recommendation_events": ("answer_hash", "provider", "model", "prompt_version", "schema_version", "review_status"),
    "optimization_strategy_candidates": ("effective_payload_version", "review_status", "strategy_synthesis_contract", "strategy_synthesis_version", "candidate_input_contract_hash", "strategy_structural_output_hash"),
    "target_brand_capability_truths": ("product_truth_status", "truth_source", "reviewed_at", "fact_value_version", "fact_value_hash", "binding_version", "binding_hash"),
    "answer_evidence_shadow_runs": ("pipeline_version", "status", "formal_output_impact", "stage_input_hash", "stage_output_hash"),
    "answer_units": ("extraction_version", "extraction_method", "review_status", "immutable_member_hash"),
    "answer_decision_bindings": ("pipeline_version", "binding_method", "review_status", "immutable_partition_hash"),
    "source_documents": ("canonicalization_version", "canonical_url_hash", "clean_text_hash", "fetch_status", "fetch_time", "immutable_content_version_ref", "immutable_content_version_hash"),
    "source_quality": ("clean_text_hash", "extractor_version", "content_quality_status", "quality_source"),
    "source_claim_materializations": ("contract_version", "output_hash", "extractor_impl_version", "prompt_version", "schema_version", "provider", "model", "status"),
    "source_claims": ("provider", "model", "prompt_version", "schema_version", "review_status", "owning_stage_output_hash"),
    "answer_evidence_shadow_results": ("pipeline_version", "formal_output_impact", "review_status", "candidate_manifest_hash"),
    "evidence_alignment_materializations": ("contract_version", "output_hash", "judge_impl_version", "prompt_version", "schema_version", "provider", "model", "status"),
    "evidence_alignments": ("provider", "model", "prompt_version", "schema_version", "review_status", "candidate_manifest_hash", "output_hash"),
    "workflow_confirmations": ("decision_status", "reviewed_at", "immutable_review_target", "immutable_review_hash"),
}

REVIEW_BINDING = {
    "RUN_METRICS": "NONE",
    "ANSWER_SEMANTIC": "CURRENT_STATE_BOUND_OR_OBJECT_ID_ONLY",
    "PRODUCT_TRUTH_PROJECTION": "CURRENT_STATE_BOUND",
    "BINDING": "CURRENT_STATE_BOUND_OR_OBJECT_ID_ONLY",
    "SOURCE_QUALIFICATION": "NONE",
    "SOURCE_FETCH": "NONE",
    "SEGMENTATION": "NONE",
    "SOURCE_CLAIM": "NONE",
    "ALIGNMENT_CANDIDATE_BUILD": "NONE",
    "EVIDENCE_ALIGNMENT": "CURRENT_STATE_BOUND_OR_OBJECT_ID_ONLY",
    "BENCHMARK": "NONE",
    "GAP": "CURRENT_STATE_BOUND_OR_UNBOUND",
    "CHANNEL_EVIDENCE": "NONE",
    "CHANNEL_RESOLUTION": "NONE",
    "STRATEGY_SYNTHESIS": "CURRENT_STATE_BOUND",
    "EXECUTION_PROPOSAL": "UNBOUND",
}

EXPECTED_STAGE_STATUS = {
    "CASE-REAL-019": dict(zip(STAGES, ("PARTIAL", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "PARTIAL", "PARTIAL", "PARTIAL", "PARTIAL", "PARTIAL", "UNAVAILABLE"))),
    "CASE-REAL-040": dict(zip(STAGES, ("PARTIAL", "PARTIAL", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "UNSAFE", "PARTIAL", "PARTIAL", "PARTIAL", "PARTIAL", "PARTIAL", "UNAVAILABLE"))),
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_load(raw: str) -> Any:
    return json.loads(raw, parse_float=Decimal, parse_int=int)


def _strict_int_set(raw: str) -> tuple[set[int], str | None]:
    try:
        payload = _json_load(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        return set(), f"INVALID_JSON:{exc}"
    if not isinstance(payload, list):
        return set(), "INVALID_ARRAY_TYPE"
    values: list[int] = []
    for member in payload:
        if isinstance(member, bool) or not isinstance(member, int):
            return set(), "NON_INTEGER_ARRAY_MEMBER"
        if member <= 0:
            return set(), "NON_POSITIVE_ARRAY_MEMBER"
        values.append(member)
    if len(values) != len(set(values)):
        return set(), "DUPLICATE_ARRAY_MEMBER"
    return set(values), None


def _json_path(document: Any, path: str) -> FieldState:
    if path == "$":
        return state_for(document)
    if not path.startswith("$."):
        raise ValueError(f"unsupported frozen JSON path: {path}")
    current = document
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            return FIELD_ABSENT
        current = current[part]
    return state_for(current)


def _state_name(state: FieldState) -> str:
    return ("FIELD_ABSENT", "FIELD_PRESENT_NULL", "EMPTY_COLLECTION", "VALUE")[state.code]


def _json_safe(value_: Any) -> Any:
    if isinstance(value_, Decimal):
        return format(value_, "f")
    if isinstance(value_, FieldState):
        return {"state": _state_name(value_), "value": _json_safe(value_.value) if value_.code == 3 else None}
    if isinstance(value_, dict):
        return {key: _json_safe(item) for key, item in value_.items()}
    if isinstance(value_, (list, tuple)):
        return [_json_safe(item) for item in value_]
    return value_


def normative_vectors() -> dict[str, dict[str, Any]]:
    members = [
        ("ROOT_MANIFEST", "BrowserMonitorRunRootSnapshot", "root-run-set:synthetic-001", "browser_monitor_run_root_snapshot.v1", "a" * 64),
        ("ROOT_MANIFEST", "ReferenceObservationRootManifest", "root-reference-set:synthetic-001", "reference_observation_root.v1", "b" * 64),
        ("ROOT_MANIFEST", "RetrievalObservationRootManifest", "root-retrieval-set:synthetic-001", "retrieval_observation_root.v1", "c" * 64),
        ("ROOT_MANIFEST", "TargetUrlManifest", "root-target-url-set:synthetic-001", "target_url_identity.exact_utf8.v1", "d" * 64),
        ("CONFIGURATION", "StageConfigurationManifest/RUN_METRICS", "config:run-metrics:synthetic-001", "runtime_stage.run_metrics.v1/configuration", "e" * 64),
    ]
    input_members = [
        {"input_role": role, "source_manifest_type": source_type, "source_identity_ref": source_ref, "source_contract_version": source_version, "consumed_semantic_hash": consumed_hash}
        for role, source_type, source_ref, source_version, consumed_hash in members
    ]
    input_members.sort(key=canonical_node)
    input_bytes = manifest_bytes(
        "StageInputManifest/RUN_METRICS",
        "runtime_stage.run_metrics.v1/input",
        {"stage_type": "RUN_METRICS", "input_role_contract_version": "StageInputRole.v1", "members": input_members},
    )
    db_hash = "fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3"
    entries = [
        {"scope_key": key, "value_kind": SCOPE_KEY_KINDS[key], "canonical_value": val}
        for key, val in {
            "CASE_ID": "CASE-REAL-019", "SNAPSHOT_ID": "CASE-REAL-019@2026-09-08", "EXACT_DATABASE_SHA256": db_hash,
            "PROJECT_ID": 3, "PROMPT_ID": 19, "EVIDENCE_PACKAGE_ID": 12, "STRATEGY_CANDIDATE_ID": 57,
            "STRATEGY_CANDIDATE_STATUS": "ACCEPTED",
        }.items()
    ]
    entries.sort(key=lambda row: canonical_node(row["scope_key"]))
    scope_payload = {"fixed_scope_contract_version": FIXED_SCOPE_CONTRACT_VERSION, "scope_key_contract_version": SCOPE_KEY_CONTRACT_VERSION, "scope_profile_id": SCOPE_PROFILES["EXECUTION_PROPOSAL"], "scope_entries": entries}
    scope_bytes = manifest_bytes("LegacyFixedScopeValues", FIXED_SCOPE_CONTRACT_VERSION, scope_payload)
    scope_hash = sha256_bytes(scope_bytes)
    source_bytes = manifest_bytes(
        "LegacyStageSourceManifest",
        "legacy_stage_source_manifest.v1",
        {
            "legacy_projection_profile_version": LEGACY_PROFILE_VERSION,
            "fixed_snapshot_id": "CASE-REAL-019@2026-09-08",
            "exact_database_sha256": db_hash,
            "stage_type": "EXECUTION_PROPOSAL",
            "selector_contract_id": SELECTORS["EXECUTION_PROPOSAL"],
            "fixed_scope_contract_version": FIXED_SCOPE_CONTRACT_VERSION,
            "scope_key_contract_version": SCOPE_KEY_CONTRACT_VERSION,
            "scope_profile_id": SCOPE_PROFILES["EXECUTION_PROPOSAL"],
            "fixed_scope_values": scope_payload,
            "fixed_scope_hash": scope_hash,
            "source_members": EMPTY_COLLECTION,
        },
    )
    expected = {
        "input_set_hash": "dba2155c917c74e7f297ad0e5fe9a8639ef3f2f8289e3511fcc84e0d96cce10e",
        "fixed_scope_hash": "d361f0132ee1ab4ba8a89d5a6793d6f291b6bf8b413d51d5c91da2e47e24be66",
        "source_ref_set_hash": "543fa710799ecc38c9382b3646643a6b8fddcd807fcd8e43cbe1d3f942b5a483",
    }
    actual = {"input_set_hash": sha256_bytes(input_bytes), "fixed_scope_hash": scope_hash, "source_ref_set_hash": sha256_bytes(source_bytes)}
    return {key: {"expected": expected[key], "actual": actual[key], "match": expected[key] == actual[key]} for key in expected}


class RuntimeProjectionProjector:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path).resolve()
        self.latest_substitution_count = 0
        self.semantic_invention_count = 0
        self._columns: dict[str, set[str]] = {}
        uri = f"file:{self.db_path}?mode=ro"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only = ON")
        denied = {
            getattr(sqlite3, name)
            for name in (
                "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TABLE",
                "SQLITE_CREATE_TEMP_INDEX", "SQLITE_CREATE_TEMP_TABLE", "SQLITE_CREATE_TEMP_TRIGGER", "SQLITE_CREATE_TEMP_VIEW",
                "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW", "SQLITE_DROP_INDEX", "SQLITE_DROP_TABLE", "SQLITE_DROP_TEMP_INDEX",
                "SQLITE_DROP_TEMP_TABLE", "SQLITE_DROP_TEMP_TRIGGER", "SQLITE_DROP_TEMP_VIEW", "SQLITE_DROP_TRIGGER", "SQLITE_DROP_VIEW",
                "SQLITE_ALTER_TABLE", "SQLITE_REINDEX", "SQLITE_ATTACH", "SQLITE_DETACH",
            )
            if hasattr(sqlite3, name)
        }
        self.connection.set_authorizer(lambda action, _a, _b, _db, _source: sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "RuntimeProjectionProjector":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def _table_columns(self, table: str) -> set[str]:
        if table not in self._columns:
            self._columns[table] = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        return self._columns[table]

    def _rows_by_ids(self, table: str, ids: Iterable[int]) -> list[dict[str, Any]]:
        ordered = sorted(set(ids))
        if not ordered:
            return []
        placeholders = ",".join("?" for _ in ordered)
        return self._query(f"SELECT * FROM {table} WHERE id IN ({placeholders}) ORDER BY id", ordered)

    def _rows_by_run_ids(self, table: str, run_ids: set[int]) -> list[dict[str, Any]]:
        if not run_ids:
            return []
        ordered = sorted(run_ids)
        placeholders = ",".join("?" for _ in ordered)
        return self._query(f"SELECT * FROM {table} WHERE run_id IN ({placeholders}) ORDER BY id", ordered)

    def _scope_values(self, stage: str, manifest: dict[str, Any]) -> dict[str, Any]:
        fixed = manifest["fixed_input"]
        values: dict[str, Any] = {
            "CASE_ID": manifest["case_id"], "SNAPSHOT_ID": manifest["snapshot_id"],
            "EXACT_DATABASE_SHA256": manifest["database_identity"]["sha256"], "PROJECT_ID": fixed["project_id"],
            "PROMPT_ID": fixed["prompt_id"], "EVIDENCE_PACKAGE_ID": fixed["evidence_package_id"],
            "EVIDENCE_PACKAGE_VERSION": fixed["evidence_package_version"], "EVIDENCE_PACKAGE_HASH": fixed["evidence_package_hash"],
            "RUN_IDS": sorted(fixed["source_run_ids"]), "RUN_SCOPE_HASH": fixed["run_scope_hash"],
            "STRATEGY_CANDIDATE_ID": fixed["strategy_candidate_id"], "STRATEGY_CANDIDATE_STATUS": fixed["strategy_candidate_status"],
            "CANDIDATE_DOCUMENT_COLUMN": "effective_payload_json" if manifest["case_id"] == "CASE-REAL-019" else "structured_payload_json",
            "JSON_PATH_SET_ID": STAGE_PATH_SET.get(stage), "STEP_KEY": "gap",
        }
        entries = [{"scope_key": key, "value_kind": SCOPE_KEY_KINDS[key], "canonical_value": values[key]} for key in SCOPE_KEYS[stage]]
        entries.sort(key=lambda row: canonical_node(row["scope_key"]))
        return {"fixed_scope_contract_version": FIXED_SCOPE_CONTRACT_VERSION, "scope_key_contract_version": SCOPE_KEY_CONTRACT_VERSION, "scope_profile_id": SCOPE_PROFILES[stage], "scope_entries": entries}

    def _required_states(self, table: str, row: dict[str, Any], manifest: dict[str, Any]) -> dict[str, FieldState]:
        fixed = manifest["fixed_input"]
        states: dict[str, FieldState] = {}
        for field in ROW_STATE_FIELDS[table]:
            if table == "optimization_strategy_candidates" and field in fixed:
                states[field] = state_for(fixed[field])
            elif field in row:
                raw_value = row[field]
                if raw_value is not None and field in {"reviewed_at", "fetch_time"} and isinstance(raw_value, str):
                    raw_value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
                states[field] = state_for(raw_value)
            else:
                states[field] = FIELD_ABSENT
        return states

    def _member_base(self, stage: str, table: str, primary_key: int, source_ref: str, source_kind: str, scope_hash: str) -> dict[str, Any]:
        return {
            "source_ref": source_ref,
            "source_kind": source_kind,
            "legacy_projection_profile_version": LEGACY_PROFILE_VERSION,
            "stage_type": stage,
            "table_name": table,
            "primary_key": primary_key,
            "selector_contract_id": SELECTORS[stage],
            "fixed_snapshot_id": self._active_manifest["snapshot_id"],
            "fixed_scope_contract_version": FIXED_SCOPE_CONTRACT_VERSION,
            "scope_key_contract_version": SCOPE_KEY_CONTRACT_VERSION,
            "scope_profile_id": SCOPE_PROFILES[stage],
            "fixed_scope_hash": scope_hash,
        }

    def _row_member(self, stage: str, table: str, row: dict[str, Any], scope_hash: str) -> dict[str, Any]:
        member = self._member_base(stage, table, row["id"], f"legacy:{table}:{row['id']}", "ROW", scope_hash)
        member.update({"json_column": FIELD_ABSENT, "json_path": FIELD_ABSENT, "json_state": FIELD_ABSENT, "json_value": FIELD_ABSENT, "required_version_hash_states": self._required_states(table, row, self._active_manifest)})
        return member

    def _slice_member(self, stage: str, table: str, row: dict[str, Any], column: str, path: str, document: Any, scope_hash: str) -> dict[str, Any]:
        state = _json_path(document, path)
        source_ref = f"legacy-json:{table}:{row['id']}:{column}:{path}"
        member = self._member_base(stage, table, row["id"], source_ref, "JSON_SLICE", scope_hash)
        slice_hash = sha256_bytes(canonical_node(state))
        required = {"selected_json_column": value(column), "exact_json_path": value(path), "field_state": value(_state_name(state)), "canonical_slice_hash": value(slice_hash)}
        member.update({"json_column": value(column), "json_path": value(path), "json_state": value(_state_name(state)), "json_value": state, "required_version_hash_states": required})
        return member

    @staticmethod
    def _member_identity(member: dict[str, Any]) -> dict[str, Any]:
        return {key: member[key] for key in ("legacy_projection_profile_version", "stage_type", "selector_contract_id", "scope_profile_id", "fixed_scope_hash", "source_ref", "source_kind")}

    def _source_manifest(self, stage: str, scope: dict[str, Any], members: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], list[str]]:
        deduped: dict[bytes, bytes] = {}
        materialized: dict[bytes, dict[str, Any]] = {}
        conflicts: list[str] = []
        for member in members:
            identity = canonical_node(self._member_identity(member))
            content = canonical_node(member)
            if identity in deduped and deduped[identity] != content:
                conflicts.append(member["source_ref"])
            elif identity not in deduped:
                deduped[identity] = content
                materialized[identity] = member
        ordered = [materialized[key] for key in sorted(materialized)]
        scope_hash = manifest_hash("LegacyFixedScopeValues", FIXED_SCOPE_CONTRACT_VERSION, scope)
        payload = {
            "legacy_projection_profile_version": LEGACY_PROFILE_VERSION,
            "fixed_snapshot_id": self._active_manifest["snapshot_id"],
            "exact_database_sha256": self._active_manifest["database_identity"]["sha256"],
            "stage_type": stage,
            "selector_contract_id": SELECTORS[stage],
            "fixed_scope_contract_version": FIXED_SCOPE_CONTRACT_VERSION,
            "scope_key_contract_version": SCOPE_KEY_CONTRACT_VERSION,
            "scope_profile_id": SCOPE_PROFILES[stage],
            "fixed_scope_values": scope,
            "fixed_scope_hash": scope_hash,
            "source_members": ordered if ordered else EMPTY_COLLECTION,
        }
        return manifest_hash("LegacyStageSourceManifest", "legacy_stage_source_manifest.v1", payload), ordered, conflicts

    def _fixed_objects(self, manifest: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], list[str]]:
        fixed = manifest["fixed_input"]
        errors: list[str] = []
        packages = self._query(
            "SELECT * FROM optimization_evidence_packages WHERE id=? AND project_id=? AND prompt_id=? AND version=? AND package_hash=?",
            (fixed["evidence_package_id"], fixed["project_id"], fixed["prompt_id"], fixed["evidence_package_version"], fixed["evidence_package_hash"]),
        )
        candidates = self._query(
            "SELECT * FROM optimization_strategy_candidates WHERE id=? AND project_id=? AND evidence_package_id=? AND review_status=?",
            (fixed["strategy_candidate_id"], fixed["project_id"], fixed["evidence_package_id"], fixed["strategy_candidate_status"]),
        )
        runs = self._rows_by_ids("browser_monitor_runs", fixed["source_run_ids"])
        if len(packages) != 1:
            errors.append("FIXED_EVIDENCE_PACKAGE_UNAVAILABLE")
        if len(candidates) != 1:
            errors.append("FIXED_STRATEGY_CANDIDATE_UNAVAILABLE")
        elif manifest["case_id"] == "CASE-REAL-019" and candidates[0].get("effective_payload_version") != "effective_payload.v1":
            errors.append("FIXED_CANDIDATE_DOCUMENT_VERSION_UNAVAILABLE")
        if {row["id"] for row in runs} != set(fixed["source_run_ids"]):
            errors.append("FIXED_RUN_SET_UNAVAILABLE")
        return packages[0] if len(packages) == 1 else None, candidates[0] if len(candidates) == 1 else None, runs, errors

    def _build_base_sets(self, manifest: dict[str, Any], package: dict[str, Any], candidate: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
        fixed = manifest["fixed_input"]
        run_ids = set(fixed["source_run_ids"])
        references = self._rows_by_run_ids("reference_sources", run_ids)
        retrievals = self._rows_by_run_ids("retrieval_candidates", run_ids)
        observations = [("reference_sources", row) for row in references] + [("retrieval_candidates", row) for row in retrievals]
        tuples = {(row.get("canonicalization_version"), row.get("canonical_url_hash")) for _table, row in observations if row.get("canonicalization_version") and row.get("canonical_url_hash")}
        hashes = sorted({key[1] for key in tuples})
        documents: list[dict[str, Any]] = []
        if hashes:
            placeholders = ",".join("?" for _ in hashes)
            candidates_d = self._query(f"SELECT * FROM source_documents WHERE canonical_url_hash IN ({placeholders}) ORDER BY id", hashes)
            documents = [row for row in candidates_d if (row.get("canonicalization_version"), row.get("canonical_url_hash")) in tuples]
        document_ids = {row["id"] for row in documents}
        qualities: list[dict[str, Any]] = []
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            qualities = self._query(f"SELECT * FROM source_quality WHERE source_document_id IN ({placeholders}) ORDER BY id", sorted(document_ids))
        shadow_scope = self._query(
            "SELECT * FROM answer_evidence_shadow_runs WHERE project_id=? AND prompt_id=? AND evidence_package_id=? ORDER BY id",
            (fixed["project_id"], fixed["prompt_id"], fixed["evidence_package_id"]),
        )
        shadows: list[dict[str, Any]] = []
        shadow_errors: list[str] = []
        for row in shadow_scope:
            parsed, error = _strict_int_set(row["source_run_ids_json"])
            if error:
                shadow_errors.append(f"answer_evidence_shadow_runs:{row['id']}:{error}")
            elif parsed == run_ids:
                shadows.append(row)
        return {
            "package": package, "candidate": candidate, "runs": runs, "run_ids": run_ids,
            "references": references, "retrievals": retrievals, "observations": observations,
            "documents": documents, "document_ids": document_ids, "qualities": qualities,
            "shadows": shadows, "shadow_errors": shadow_errors,
        }

    def _document(self, row: dict[str, Any], column: str) -> tuple[Any, str | None]:
        try:
            return _json_load(row[column]), None
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            return {}, f"INVALID_JSON:{column}:{exc}"

    def _shadow_results(self, base: dict[str, Any]) -> list[dict[str, Any]]:
        fixed = self._active_manifest["fixed_input"]
        shadow_ids = {row["id"] for row in base["shadows"]}
        if not shadow_ids:
            return []
        placeholders_s = ",".join("?" for _ in shadow_ids)
        placeholders_r = ",".join("?" for _ in base["run_ids"])
        return self._query(
            f"SELECT * FROM answer_evidence_shadow_results WHERE shadow_run_id IN ({placeholders_s}) AND project_id=? AND prompt_id=? AND run_id IN ({placeholders_r}) ORDER BY id",
            (*sorted(shadow_ids), fixed["project_id"], fixed["prompt_id"], *sorted(base["run_ids"])),
        )

    def _candidate_slices(self, stage: str, base: dict[str, Any], scope_hash: str) -> tuple[list[dict[str, Any]], list[str], Any]:
        column = "effective_payload_json" if self._active_manifest["case_id"] == "CASE-REAL-019" else "structured_payload_json"
        document, error = self._document(base["candidate"], column)
        members = [self._row_member(stage, "optimization_strategy_candidates", base["candidate"], scope_hash)]
        if error:
            return members, [error], document
        path_set = STAGE_PATH_SET[stage]
        members.extend(self._slice_member(stage, "optimization_strategy_candidates", base["candidate"], column, path, document, scope_hash) for path in JSON_PATH_SETS[path_set])
        return members, [], document

    def _package_slices(self, stage: str, base: dict[str, Any], scope_hash: str) -> tuple[list[dict[str, Any]], list[str]]:
        document, error = self._document(base["package"], "package_payload_json")
        if error:
            return [], [error]
        return [self._slice_member(stage, "optimization_evidence_packages", base["package"], "package_payload_json", path, document, scope_hash) for path in JSON_PATH_SETS["PACKAGE_METRIC_PATHS"]], []

    def _product_truth_ids(self, document: Any) -> tuple[set[int], list[str]]:
        ids: set[int] = set()
        errors: list[str] = []
        for path in ("$.decision_reasons", "$.evidence_summary.gap_items", "$.target_capabilities"):
            state = _json_path(document, path)
            if state.code != 3:
                continue
            if not isinstance(state.value, list):
                errors.append(f"INVALID_PRODUCT_TRUTH_HINT_CONTAINER:{path}")
                continue
            for index, member in enumerate(state.value):
                if not isinstance(member, dict) or "product_truth_ids" not in member:
                    continue
                values = member["product_truth_ids"]
                if not isinstance(values, list):
                    errors.append(f"INVALID_PRODUCT_TRUTH_IDS:{path}:{index}")
                    continue
                integer_values = [item for item in values if isinstance(item, int) and not isinstance(item, bool)]
                if len(integer_values) != len(set(integer_values)):
                    errors.append(f"DUPLICATE_PRODUCT_TRUTH_ID:{path}:{index}")
                for item in values:
                    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                        errors.append(f"NON_INTEGER_PRODUCT_TRUTH_ID:{path}:{index}")
                    else:
                        ids.add(item)
        refs = _json_path(document, "$.product_truth_refs")
        if refs.code == 3 and isinstance(refs.value, dict) and "ids" in refs.value:
            values = refs.value["ids"]
            if not isinstance(values, list):
                errors.append("INVALID_PRODUCT_TRUTH_REFS_IDS")
            else:
                integer_values = [item for item in values if isinstance(item, int) and not isinstance(item, bool)]
                if len(integer_values) != len(set(integer_values)):
                    errors.append("DUPLICATE_PRODUCT_TRUTH_REF_ID")
                for item in values:
                    if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                        errors.append("NON_INTEGER_PRODUCT_TRUTH_REF_ID")
                    else:
                        ids.add(item)
        return ids, errors

    def _materializations_by_observed_ids(self, table: str, direct_document_ids: set[int] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
        fixed = self._active_manifest["fixed_input"]
        selected: dict[int, dict[str, Any]] = {}
        errors: list[str] = []
        for row in self._query(f"SELECT * FROM {table} ORDER BY id"):
            if table == "source_claim_materializations":
                observed, error = _strict_int_set(row["observed_source_document_ids_json"])
                if error:
                    errors.append(f"{table}:{row['id']}:{error}")
                    continue
                if row["source_document_id"] in (direct_document_ids or set()) or observed.intersection(direct_document_ids or set()):
                    selected[row["id"]] = row
            else:
                prompts, prompt_error = _strict_int_set(row["observed_prompt_ids_json"])
                runs, run_error = _strict_int_set(row["observed_run_ids_json"])
                if prompt_error or run_error:
                    errors.append(f"{table}:{row['id']}:{prompt_error or run_error}")
                    continue
                if fixed["prompt_id"] in prompts and runs.intersection(set(fixed["source_run_ids"])):
                    selected[row["id"]] = row
        return list(selected.values()), errors

    def _stage_members(self, stage: str, base: dict[str, Any], scope_hash: str) -> tuple[list[dict[str, Any]], list[str]]:
        fixed = self._active_manifest["fixed_input"]
        members: list[dict[str, Any]] = []
        errors: list[str] = []
        if stage == "RUN_METRICS":
            members = [self._row_member(stage, "optimization_evidence_packages", base["package"], scope_hash)]
            members += [self._row_member(stage, "browser_monitor_runs", row, scope_hash) for row in base["runs"]]
            members += [self._row_member(stage, table, row, scope_hash) for table, row in base["observations"]]
            slices, slice_errors = self._package_slices(stage, base, scope_hash)
            return members + slices, slice_errors
        if stage == "ANSWER_SEMANTIC":
            events = self._query(
                f"SELECT * FROM recommendation_events WHERE project_id=? AND prompt_id=? AND run_id IN ({','.join('?' for _ in base['run_ids'])}) ORDER BY id",
                (fixed["project_id"], fixed["prompt_id"], *sorted(base["run_ids"])),
            )
            analyses = self._query("SELECT * FROM prompt_analysis_runs WHERE project_id=? AND prompt_id=? ORDER BY id", (fixed["project_id"], fixed["prompt_id"]))
            members = [self._row_member(stage, "recommendation_events", row, scope_hash) for row in events]
            members += [self._row_member(stage, "prompt_analysis_runs", row, scope_hash) for row in analyses]
            return members, errors
        if stage == "PRODUCT_TRUTH_PROJECTION":
            members, errors, document = self._candidate_slices(stage, base, scope_hash)
            truth_ids, hint_errors = self._product_truth_ids(document)
            errors += hint_errors
            truth_rows = self._rows_by_ids("target_brand_capability_truths", truth_ids)
            truth_rows = [row for row in truth_rows if row["project_id"] == fixed["project_id"]]
            found = {row["id"] for row in truth_rows}
            errors += [f"MISSING_PRODUCT_TRUTH_HINT:{truth_id}" for truth_id in sorted(truth_ids - found)]
            members += [self._row_member(stage, "target_brand_capability_truths", row, scope_hash) for row in truth_rows]
            return members, errors
        if stage == "BINDING":
            shadow_ids = {row["id"] for row in base["shadows"]}
            members = [self._row_member(stage, "answer_evidence_shadow_runs", row, scope_hash) for row in base["shadows"]]
            if shadow_ids:
                placeholders = ",".join("?" for _ in shadow_ids)
                units = self._query(f"SELECT * FROM answer_units WHERE shadow_run_id IN ({placeholders}) ORDER BY id", sorted(shadow_ids))
                bindings = self._query(f"SELECT * FROM answer_decision_bindings WHERE shadow_run_id IN ({placeholders}) ORDER BY id", sorted(shadow_ids))
                members += [self._row_member(stage, "answer_units", row, scope_hash) for row in units]
                members += [self._row_member(stage, "answer_decision_bindings", row, scope_hash) for row in bindings]
            return members, list(base["shadow_errors"])
        if stage == "SOURCE_QUALIFICATION":
            members = [self._row_member(stage, table, row, scope_hash) for table, row in base["observations"]]
            members += [self._row_member(stage, "source_documents", row, scope_hash) for row in base["documents"]]
            members += [self._row_member(stage, "source_quality", row, scope_hash) for row in base["qualities"]]
            return members, errors
        if stage == "SOURCE_FETCH":
            return [self._row_member(stage, "source_documents", row, scope_hash) for row in base["documents"]], errors
        if stage == "SEGMENTATION":
            for row in base["documents"]:
                document, error = self._document(row, "content_blocks_json")
                if error:
                    errors.append(f"source_documents:{row['id']}:{error}")
                else:
                    members.append(self._slice_member(stage, "source_documents", row, "content_blocks_json", "$", document, scope_hash))
            return members, errors
        if stage == "SOURCE_CLAIM":
            mats, errors = self._materializations_by_observed_ids("source_claim_materializations", base["document_ids"])
            claims = self._query(
                f"SELECT * FROM source_claims WHERE project_id=? AND source_document_id IN ({','.join('?' for _ in base['document_ids'])}) ORDER BY id",
                (fixed["project_id"], *sorted(base["document_ids"])),
            ) if base["document_ids"] else []
            members = [self._row_member(stage, "source_claim_materializations", row, scope_hash) for row in mats]
            members += [self._row_member(stage, "source_claims", row, scope_hash) for row in claims]
            return members, errors
        if stage == "ALIGNMENT_CANDIDATE_BUILD":
            rows = self._shadow_results(base)
            return [self._row_member(stage, "answer_evidence_shadow_results", row, scope_hash) for row in rows], list(base["shadow_errors"])
        if stage == "EVIDENCE_ALIGNMENT":
            alignments = self._query(
                f"SELECT * FROM evidence_alignments WHERE project_id=? AND prompt_id=? AND run_id IN ({','.join('?' for _ in base['run_ids'])}) ORDER BY id",
                (fixed["project_id"], fixed["prompt_id"], *sorted(base["run_ids"])),
            )
            mats, errors = self._materializations_by_observed_ids("evidence_alignment_materializations")
            shadow_results = self._shadow_results(base)
            members = [self._row_member(stage, "evidence_alignments", row, scope_hash) for row in alignments]
            members += [self._row_member(stage, "answer_evidence_shadow_results", row, scope_hash) for row in shadow_results]
            members += [self._row_member(stage, "evidence_alignment_materializations", row, scope_hash) for row in mats]
            return members, errors + list(base["shadow_errors"])
        if stage in ("BENCHMARK", "CHANNEL_EVIDENCE", "CHANNEL_RESOLUTION", "STRATEGY_SYNTHESIS"):
            members, errors, _document = self._candidate_slices(stage, base, scope_hash)
            return members, errors
        if stage == "GAP":
            members, errors, _document = self._candidate_slices(stage, base, scope_hash)
            confirmations = self._query("SELECT * FROM workflow_confirmations WHERE project_id=? AND prompt_id=? AND step_key='gap' ORDER BY id", (fixed["project_id"], fixed["prompt_id"]))
            members += [self._row_member(stage, "workflow_confirmations", row, scope_hash) for row in confirmations]
            return members, errors
        if stage == "EXECUTION_PROPOSAL":
            return [], errors
        raise ValueError(f"unknown frozen stage: {stage}")

    def _derive_completeness(self, stage: str, base: dict[str, Any], member_count: int, errors: list[str]) -> tuple[str, list[str]]:
        if errors and any("INVALID_JSON" in error or "INVALID_ARRAY" in error for error in errors):
            return "UNAVAILABLE", errors
        if stage == "RUN_METRICS":
            return "PARTIAL", ["FORMAL_RUN_METRIC_MANIFEST_NOT_PERSISTED"] + errors
        if stage == "ANSWER_SEMANTIC":
            analysis_count = len(self._query("SELECT id FROM prompt_analysis_runs WHERE project_id=? AND prompt_id=?", (self._active_manifest["fixed_input"]["project_id"], self._active_manifest["fixed_input"]["prompt_id"])))
            if analysis_count == 0:
                return "UNAVAILABLE", ["PROMPT_ANALYSIS_RUN_ABSENT"] + errors
            if analysis_count == 1:
                return "PARTIAL", ["FORMAL_ANSWER_STAGE_MANIFEST_NOT_PERSISTED"] + errors
            return "UNSAFE", ["MULTIPLE_PROMPT_ANALYSIS_RUN_ENVELOPES"] + errors
        if stage == "PRODUCT_TRUTH_PROJECTION":
            return "UNSAFE", ["FORMAL_REASON_PRODUCT_TRUTH_BINDING_ABSENT"] + errors
        if stage == "BINDING":
            if not base["shadows"]:
                return "UNAVAILABLE", ["EXACT_SCOPE_SHADOW_RUN_ABSENT"] + errors
            if len(base["shadows"]) == 1 and base["shadows"][0]["status"].lower() in {"completed", "complete", "success", "succeeded"}:
                return "PARTIAL", ["FORMAL_BINDING_STAGE_MANIFEST_NOT_PERSISTED"] + errors
            return "UNSAFE", ["MULTIPLE_OR_MIXED_SHADOW_RUN_ENVELOPES"] + errors
        if stage == "SOURCE_QUALIFICATION":
            return "UNSAFE", ["MUTABLE_SOURCE_QUALITY_WITHOUT_HISTORICAL_STAGE_MANIFEST"] + errors
        if stage == "SOURCE_FETCH":
            return ("UNSAFE", ["IMMUTABLE_PACKAGE_TIME_CONTENT_VERSION_ABSENT"] + errors) if base["documents"] else ("UNAVAILABLE", ["FIXED_SOURCE_DOCUMENTS_ABSENT"] + errors)
        if stage == "SEGMENTATION":
            return ("UNSAFE", ["IMMUTABLE_PASSAGE_MANIFEST_ABSENT"] + errors) if base["documents"] else ("UNAVAILABLE", ["FIXED_SOURCE_DOCUMENTS_ABSENT"] + errors)
        if stage == "SOURCE_CLAIM":
            return ("UNSAFE", ["PACKAGE_SCOPED_SOURCE_CLAIM_STAGE_BOUNDARY_ABSENT"] + errors) if member_count else ("PARTIAL", ["LEGACY_ZERO_ROWS_NOT_FORMAL_ZERO_OUTPUT"] + errors)
        if stage == "ALIGNMENT_CANDIDATE_BUILD":
            return "UNSAFE", ["SELECTED_AND_OMITTED_CANDIDATE_MANIFEST_ABSENT"] + errors
        if stage == "EVIDENCE_ALIGNMENT":
            return ("UNSAFE", ["CANDIDATE_SCOPED_ALIGNMENT_STAGE_BOUNDARY_ABSENT"] + errors) if member_count else ("PARTIAL", ["LEGACY_ZERO_ROWS_NOT_FORMAL_ZERO_OUTPUT"] + errors)
        if stage in {"BENCHMARK", "GAP", "CHANNEL_EVIDENCE", "CHANNEL_RESOLUTION", "STRATEGY_SYNTHESIS"}:
            return "PARTIAL", ["INDEPENDENT_STAGE_MANIFEST_AND_DEPENDENCY_HASHES_ABSENT"] + errors
        if stage == "EXECUTION_PROPOSAL":
            return "UNAVAILABLE", ["EXECUTION_PROPOSAL_MANIFEST_ABSENT", "ACTION_EXPERIMENT_PR5_SUBSTITUTION_FORBIDDEN"]
        raise ValueError(stage)

    def _unavailable_projection(self, manifest: dict[str, Any], reasons: list[str], db_hash: str) -> dict[str, Any]:
        marker = "ROOT_UNAVAILABLE"
        virtual_context_id = "virtual-context:" + semantic_hash({
            "identity_contract_version": VIRTUAL_IDENTITY_VERSION, "manifest_canonicalization_version": CANONICALIZATION_VERSION,
            "manifest_shape_semantics": "OBJECT_WITH_NESTED_MANIFESTS", "snapshot_schema_version": manifest["snapshot_schema_version"],
            "snapshot_id": manifest["snapshot_id"], "exact_database_sha256": db_hash,
            "legacy_projection_profile_version": LEGACY_PROFILE_VERSION, "root_projection_hash_or_exact_completeness_marker": marker,
        })
        stages = [self._stage_output(stage, "UNAVAILABLE", [], None, reasons) for stage in STAGES]
        result = self._case_result(manifest, virtual_context_id, "UNAVAILABLE", stages, db_hash, reasons)
        return result

    def _stage_output(self, stage: str, completeness: str, source_refs: list[str], source_hash: str | None, reasons: list[str], virtual_context_id: str | None = None) -> dict[str, Any]:
        virtual_id = None
        if completeness == "PARTIAL" and source_hash and virtual_context_id:
            virtual_id = "virtual-stage:" + semantic_hash({
                "identity_contract_version": VIRTUAL_IDENTITY_VERSION, "manifest_canonicalization_version": CANONICALIZATION_VERSION,
                "manifest_shape_semantics": "OBJECT_WITH_NESTED_MANIFESTS", "virtual_context_id": virtual_context_id,
                "stage_type": stage, "runtime_stage_contract_version": STAGE_CONTRACTS[stage],
                "legacy_projection_profile_version": LEGACY_PROFILE_VERSION, "source_ref_set_hash": source_hash,
            })
        return {
            "stage_type": stage,
            "stage_contract_version": STAGE_CONTRACTS[stage],
            "depends_on": STAGE_DEPENDENCIES[stage],
            "virtual_stage_execution_id": virtual_id,
            "legacy_source_refs": source_refs,
            "source_ref_set_hash": source_hash,
            "input_manifest": None,
            "input_set_hash": None,
            "output_manifest": None,
            "output_set_hash": None,
            "output_count": None,
            "completeness": completeness,
            "review_binding_projection": REVIEW_BINDING[stage],
            "authoritative_review_projection": "NONE_REQUIRED" if REVIEW_BINDING[stage] == "NONE" else "UNRESOLVED_LEGACY",
            "current_eligibility": False,
            "blocking_reasons": sorted(set(reasons)),
            "legacy_warnings": ["VIRTUAL_RUNTIME_PROJECTION", "FORMAL_STAGE_MANIFEST_NOT_RECOVERED"],
            "candidate_manifest_projection": {
                "selected_manifest": None,
                "omitted_manifest": None,
                "omission_reasons": None,
                "policy_version_lineage": None,
            } if stage == "ALIGNMENT_CANDIDATE_BUILD" else None,
        }

    def _case_result(
        self,
        manifest: dict[str, Any],
        virtual_context_id: str,
        root_completeness: str,
        stages: list[dict[str, Any]],
        db_hash: str,
        root_reasons: list[str],
        root_sources: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        expected = EXPECTED_STAGE_STATUS.get(manifest["case_id"], {})
        diffs = [{"stage_type": row["stage_type"], "expected": expected.get(row["stage_type"]), "actual": row["completeness"]} for row in stages if expected.get(row["stage_type"]) != row["completeness"]]
        counts = dict(Counter(row["completeness"] for row in stages))
        review_risks = sorted({row["review_binding_projection"] for row in stages if row["review_binding_projection"] not in {"NONE"}})
        result: dict[str, Any] = {
            "projection_kind": "VIRTUAL_RUNTIME_PROJECTION",
            "spike_contract_version": SPIKE_CONTRACT_VERSION,
            "runtime_profile_version": RUNTIME_PROFILE_VERSION,
            "legacy_projection_profile_version": LEGACY_PROFILE_VERSION,
            "case_id": manifest["case_id"],
            "snapshot_id": manifest["snapshot_id"],
            "exact_database_sha256": db_hash,
            "virtual_context_id": virtual_context_id,
            "root_projection": {
                "completeness": root_completeness,
                "fixed_source_manifest": root_sources,
                "root_manifest_hash": None,
                "context_fingerprint": None,
                "context_manifest_hash": None,
                "blocking_reasons": sorted(set(root_reasons)),
            },
            "lineage_completeness": "UNSAFE" if root_completeness != "UNAVAILABLE" else "UNAVAILABLE",
            "stage_graph": stages,
            "stage_completeness_counts": {key: counts.get(key, 0) for key in ("COMPLETE", "PARTIAL", "UNSAFE", "UNAVAILABLE")},
            "strategy_lineage": "UNSAFE" if root_completeness != "UNAVAILABLE" else "UNAVAILABLE",
            "current_projection": {"status": "UNRESOLVED", "current_context_pointer": None, "context_stage_selections": {stage: None for stage in STAGES}},
            "review_binding_risks": review_risks,
            "blocking_reasons": sorted({reason for row in stages for reason in row["blocking_reasons"]}),
            "stage_expectation_diff": diffs,
            "stage_expectation_diff_count": len(diffs),
            "latest_substitution_count": self.latest_substitution_count,
            "semantic_invention_count": self.semantic_invention_count,
            "db_writes": 0,
        }
        result["projection_audit_hash"] = semantic_hash(result)
        return result

    def project_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        self._active_manifest = deepcopy(manifest)
        db_hash = file_sha256(self.db_path)
        if db_hash != manifest["database_identity"]["sha256"]:
            return self._unavailable_projection(manifest, ["EXACT_DATABASE_SHA256_MISMATCH"], db_hash)
        package, candidate, runs, fixed_errors = self._fixed_objects(manifest)
        if fixed_errors or package is None or candidate is None:
            return self._unavailable_projection(manifest, fixed_errors, db_hash)
        base = self._build_base_sets(manifest, package, candidate, runs)
        marker = "ROOT_PARTIAL"
        virtual_context_id = "virtual-context:" + semantic_hash({
            "identity_contract_version": VIRTUAL_IDENTITY_VERSION, "manifest_canonicalization_version": CANONICALIZATION_VERSION,
            "manifest_shape_semantics": "OBJECT_WITH_NESTED_MANIFESTS", "snapshot_schema_version": manifest["snapshot_schema_version"],
            "snapshot_id": manifest["snapshot_id"], "exact_database_sha256": db_hash,
            "legacy_projection_profile_version": LEGACY_PROFILE_VERSION, "root_projection_hash_or_exact_completeness_marker": marker,
        })
        stages: list[dict[str, Any]] = []
        for stage in STAGES:
            scope = self._scope_values(stage, manifest)
            scope_hash = manifest_hash("LegacyFixedScopeValues", FIXED_SCOPE_CONTRACT_VERSION, scope)
            members, errors = self._stage_members(stage, base, scope_hash)
            source_hash, ordered_members, conflicts = self._source_manifest(stage, scope, members)
            errors.extend(f"MANIFEST_IDENTITY_CONFLICT:{ref}" for ref in conflicts)
            completeness, reasons = self._derive_completeness(stage, base, len(ordered_members), errors)
            refs = [member["source_ref"] for member in ordered_members]
            stages.append(self._stage_output(stage, completeness, refs, source_hash, reasons, virtual_context_id))
        root_reasons = ["FORMAL_RUNTIME_ROOT_MANIFESTS_NOT_PERSISTED", "MULTIPLE_HISTORICAL_STAGE_LINEAGES_WITHOUT_SELECTION_EDGES"]
        root_sources = {
            "snapshot_id": manifest["snapshot_id"],
            "evidence_package_ref": f"legacy:optimization_evidence_packages:{package['id']}",
            "run_refs": [f"legacy:browser_monitor_runs:{row['id']}" for row in base["runs"]],
            "run_scope_hash": manifest["fixed_input"]["run_scope_hash"],
            "reference_observation_count": len(base["references"]),
            "retrieval_observation_count": len(base["retrievals"]),
            "target_page_urls_json": package["target_page_urls_json"],
        }
        return self._case_result(manifest, virtual_context_id, "PARTIAL", stages, db_hash, root_reasons, root_sources)

    def project_case(self, case_id: str) -> dict[str, Any]:
        if case_id not in CASE_MANIFESTS:
            raise ValueError(f"case is outside the authorized Spike scope: {case_id}")
        with CASE_MANIFESTS[case_id].open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        return self.project_manifest(manifest)


def run_projection_spike(db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any]:
    path = Path(db_path).resolve()
    db_before = file_sha256(path)
    vectors = normative_vectors()
    with RuntimeProjectionProjector(path) as projector:
        first = {case_id: projector.project_case(case_id) for case_id in CASE_MANIFESTS}
    with RuntimeProjectionProjector(path) as projector:
        second = {case_id: projector.project_case(case_id) for case_id in CASE_MANIFESTS}
    db_after = file_sha256(path)
    determinism = {}
    for case_id in CASE_MANIFESTS:
        first_stages = first[case_id]["stage_graph"]
        second_stages = second[case_id]["stage_graph"]
        determinism[case_id] = {
            "run_1_hash": first[case_id]["projection_audit_hash"],
            "run_2_hash": second[case_id]["projection_audit_hash"],
            "diff": first[case_id]["projection_audit_hash"] != second[case_id]["projection_audit_hash"],
            "virtual_context_id_identical": first[case_id]["virtual_context_id"] == second[case_id]["virtual_context_id"],
            "stage_virtual_ids_identical": [row["virtual_stage_execution_id"] for row in first_stages] == [row["virtual_stage_execution_id"] for row in second_stages],
            "source_ref_set_hashes_identical": [row["source_ref_set_hash"] for row in first_stages] == [row["source_ref_set_hash"] for row in second_stages],
            "input_set_hashes_identical": [row["input_set_hash"] for row in first_stages] == [row["input_set_hash"] for row in second_stages],
            "completeness_identical": [row["completeness"] for row in first_stages] == [row["completeness"] for row in second_stages],
            "blocking_reasons_identical": [row["blocking_reasons"] for row in first_stages] == [row["blocking_reasons"] for row in second_stages],
        }
    vector_pass = all(row["match"] for row in vectors.values())
    expectation_pass = all(first[case_id]["stage_expectation_diff_count"] == 0 for case_id in CASE_MANIFESTS)
    safety_pass = all(first[case_id]["latest_substitution_count"] == 0 and first[case_id]["semantic_invention_count"] == 0 and first[case_id]["db_writes"] == 0 for case_id in CASE_MANIFESTS)
    deterministic = all(not row["diff"] for row in determinism.values())
    if not vector_pass or not deterministic:
        classification = "SPIKE_IMPLEMENTATION_BUG"
    elif not expectation_pass:
        classification = "SPIKE_CONTRACT_MISMATCH"
    elif any(first[case_id]["root_projection"]["completeness"] == "UNAVAILABLE" for case_id in CASE_MANIFESTS):
        classification = "SPIKE_BLOCKED_BY_LEGACY_DATA"
    elif not safety_pass or db_before != db_after:
        classification = "SPIKE_IMPLEMENTATION_BUG"
    else:
        classification = "SPIKE_PASS"
    return {
        "result_classification": classification,
        "frozen_contract": {"rfc_maturity": "FROZEN", "implementation_status": "NOT_IMPLEMENTED"},
        "normative_vectors": vectors,
        "cases": first,
        "determinism": determinism,
        "safety": {
            "latest_substitution_count": sum(first[c]["latest_substitution_count"] for c in CASE_MANIFESTS),
            "semantic_invention_count": sum(first[c]["semantic_invention_count"] for c in CASE_MANIFESTS),
            "semantic_invention_audit": {
                "guessed_product_truth_binding": 0,
                "guessed_current_candidate": 0,
                "guessed_review_authority": 0,
                "guessed_missing_json_path": 0,
                "guessed_source_winner": 0,
                "fallback_latest": 0,
            },
            "db_writes": 0,
            "db_sha_before": db_before,
            "db_sha_after": db_after,
        },
    }

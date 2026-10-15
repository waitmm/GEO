"""Frozen first-slice release schema contract."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text


RELEASE_SCHEMA_REVISION = "20261015_02"

RELEASE_TABLE_ORDER = (
    "organizations",
    "projects",
    "project_configuration_versions",
    "competitors",
    "topics",
    "prompt_clusters",
    "prompts",
    "prompt_versions",
    "monitoring_batches",
    "browser_monitor_tasks",
    "browser_monitor_runs",
    "brand_mentions",
    "reference_sources",
    "retrieval_candidates",
    "run_artifacts",
    "recommendation_entities",
    "target_brand_capability_truths",
    "llm_call_cache",
    "single_prompt_analyses",
    "single_prompt_analysis_contexts",
    "single_prompt_citation_manifests",
    "single_prompt_source_preparations",
    "single_prompt_source_dispositions",
    "single_prompt_prepared_source_snapshots",
    "single_prompt_source_completion_manifests",
    "single_prompt_diagnosis_executions",
    "single_prompt_diagnosis_results",
    "single_prompt_diagnosis_reviews",
    "single_prompt_citation_contribution_executions",
    "single_prompt_citation_contribution_results",
    "single_prompt_citation_contribution_reviews",
    "single_prompt_qualification_critic_executions",
    "single_prompt_qualification_critic_results",
    "single_prompt_qualification_critic_gold_reviews",
    "single_prompt_strategy_executions",
    "single_prompt_strategy_results",
    "single_prompt_strategy_reviews",
    "single_prompt_execution_proposals",
    "single_prompt_execution_proposal_results",
    "single_prompt_execution_confirmations",
    "single_prompt_publication_records",
    "single_prompt_retest_executions",
    "single_prompt_comparison_results",
    "brand_context_versions",
    "single_prompt_observation_comparisons",
    "single_prompt_sampling_schedules",
    "single_prompt_optimization_tasks",
    "supplemental_source_acquisitions",
    "single_prompt_truth_corrections",
)
RELEASE_TABLE_ALLOWLIST = frozenset(RELEASE_TABLE_ORDER)


def sqlite_has_wal_reset_fix(version: str) -> bool:
    try:
        parts = tuple(int(part) for part in version.split(".")[:3])
    except (TypeError, ValueError):
        return False
    if parts >= (3, 51, 3):
        return True
    if parts[:2] == (3, 50) and parts >= (3, 50, 7):
        return True
    return parts[:2] == (3, 44) and parts >= (3, 44, 6)


def inspect_release_database(engine: Engine) -> dict:
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        revision = None
        if "alembic_version" in tables:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        sqlite_version = connection.execute(text("SELECT sqlite_version()")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        foreign_keys = int(connection.execute(text("PRAGMA foreign_keys")).scalar_one())
    business_tables = tables - {"alembic_version"}
    return {
        "revision": revision,
        "sqlite_version": str(sqlite_version),
        "journal_mode": str(journal_mode).lower(),
        "foreign_keys": foreign_keys,
        "tables": sorted(business_tables),
        "missing_tables": sorted(RELEASE_TABLE_ALLOWLIST - business_tables),
        "unexpected_tables": sorted(business_tables - RELEASE_TABLE_ALLOWLIST),
    }


def validate_release_database(engine: Engine) -> dict:
    status = inspect_release_database(engine)
    errors: list[str] = []
    if status["revision"] != RELEASE_SCHEMA_REVISION:
        errors.append(f"RELEASE_SCHEMA_REVISION_MISMATCH:{status['revision'] or 'UNMIGRATED'}")
    if status["missing_tables"]:
        errors.append(f"RELEASE_SCHEMA_TABLES_MISSING:{','.join(status['missing_tables'])}")
    if status["unexpected_tables"]:
        errors.append(f"RELEASE_SCHEMA_TABLES_UNEXPECTED:{','.join(status['unexpected_tables'])}")
    if status["journal_mode"] != "wal":
        errors.append(f"RELEASE_SQLITE_WAL_REQUIRED:{status['journal_mode']}")
    if status["foreign_keys"] != 1:
        errors.append("RELEASE_SQLITE_FOREIGN_KEYS_DISABLED")
    if not sqlite_has_wal_reset_fix(status["sqlite_version"]):
        errors.append(f"RELEASE_SQLITE_VERSION_UNSAFE:{status['sqlite_version']}")
    if errors:
        raise RuntimeError(";".join(errors))
    return {**status, "status": "READY"}

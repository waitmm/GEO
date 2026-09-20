from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base


settings = get_settings()
connect_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_columns()
        _ensure_sqlite_shadow_result_nullable_columns()
        _ensure_sqlite_indexes()
        _ensure_sqlite_v2_context_immutability()
        _ensure_sqlite_v2_diagnosis_immutability()
        _ensure_sqlite_v2_strategy_immutability()
        _ensure_sqlite_v2_execution_immutability()
        _ensure_sqlite_v2_retest_immutability()


def _ensure_sqlite_columns() -> None:
    type_map = {
        "INTEGER": "INTEGER",
        "VARCHAR": "VARCHAR",
        "TEXT": "TEXT",
        "DATETIME": "DATETIME",
        "BOOLEAN": "BOOLEAN",
        "FLOAT": "FLOAT",
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                column_type = type_map.get(column.type.__class__.__name__.upper(), "TEXT")
                nullable = "" if column.nullable or column.default is not None else " NOT NULL"
                default = ""
                if column.default is not None and getattr(column.default, "is_scalar", False):
                    value = column.default.arg
                    if isinstance(value, str):
                        default = f" DEFAULT '{value}'"
                    elif isinstance(value, bool):
                        default = f" DEFAULT {1 if value else 0}"
                    elif isinstance(value, (int, float)):
                        default = f" DEFAULT {value}"
                connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}{default}{nullable}"))


def _ensure_sqlite_shadow_result_nullable_columns() -> None:
    """Relax legacy Shadow-only result columns so unbound AnswerUnit evidence can be audited."""

    table_name = "answer_evidence_shadow_results"
    nullable_columns = {"recommendation_event_id", "decision_binding_id"}
    with engine.begin() as connection:
        inspector = inspect(connection)
        if table_name not in set(inspector.get_table_names()):
            return
        columns = inspector.get_columns(table_name)
        needs_rebuild = any(
            column["name"] in nullable_columns and not column.get("nullable", True)
            for column in columns
        )
        if not needs_rebuild:
            return

        temp_table = f"__tmp_{table_name}_nullable"
        for index in inspector.get_indexes(table_name):
            index_name = index.get("name")
            if index_name:
                connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        connection.execute(text(f"DROP TABLE IF EXISTS {temp_table}"))
        connection.execute(text(f"ALTER TABLE {table_name} RENAME TO {temp_table}"))

        metadata_table = Base.metadata.tables[table_name]
        metadata_table.create(bind=connection, checkfirst=False)
        new_columns = {column.name for column in metadata_table.columns}
        old_columns = {column["name"] for column in columns}
        common_columns = [column.name for column in metadata_table.columns if column.name in old_columns and column.name in new_columns]
        column_sql = ", ".join(common_columns)
        connection.execute(text(f"INSERT INTO {table_name} ({column_sql}) SELECT {column_sql} FROM {temp_table}"))
        connection.execute(text(f"DROP TABLE {temp_table}"))


def _ensure_sqlite_indexes() -> None:
    statements = [
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_evidence_package_project_hash ON optimization_evidence_packages (project_id, package_hash)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_evidence_package_project_prompt_version ON optimization_evidence_packages (project_id, prompt_id, version)",
        "CREATE INDEX IF NOT EXISTS ix_evidence_package_project_prompt_status ON optimization_evidence_packages (project_id, prompt_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_page_snapshots_project_url_type ON page_snapshots (project_id, url, snapshot_type)",
        "CREATE INDEX IF NOT EXISTS ix_page_snapshots_experiment_type ON page_snapshots (experiment_id, snapshot_type)",
        "CREATE INDEX IF NOT EXISTS ix_optimization_hypotheses_experiment_status ON optimization_hypotheses (experiment_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_strategy_candidates_project_status ON optimization_strategy_candidates (project_id, review_status)",
        "CREATE INDEX IF NOT EXISTS ix_strategy_candidates_experiment_status ON optimization_strategy_candidates (experiment_id, review_status)",
        "CREATE INDEX IF NOT EXISTS ix_release_audit_records_experiment_status ON release_audit_records (experiment_id, online_verification_status)",
        "CREATE INDEX IF NOT EXISTS ix_reference_sources_canonical_url_hash ON reference_sources (canonical_url_hash)",
        "CREATE INDEX IF NOT EXISTS ix_retrieval_candidates_canonical_url_hash ON retrieval_candidates (canonical_url_hash)",
        "CREATE INDEX IF NOT EXISTS ix_source_documents_canonical_url_hash ON source_documents (canonical_url_hash)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            try:
                connection.execute(text(statement))
            except Exception:
                # SQLite development databases may contain legacy duplicate rows; formal migrations surface this.
                continue


def _ensure_sqlite_v2_context_immutability() -> None:
    table_name = "single_prompt_analysis_contexts"
    with engine.begin() as connection:
        if table_name not in set(inspect(connection).get_table_names()):
            return
        connection.execute(text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_context_no_update
            BEFORE UPDATE ON single_prompt_analysis_contexts
            BEGIN
              SELECT RAISE(ABORT, 'ANALYSIS_CONTEXT_IMMUTABLE');
            END
            """
        ))
        connection.execute(text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_context_no_delete
            BEFORE DELETE ON single_prompt_analysis_contexts
            BEGIN
              SELECT RAISE(ABORT, 'ANALYSIS_CONTEXT_IMMUTABLE');
            END
            """
        ))


def _ensure_sqlite_v2_diagnosis_immutability() -> None:
    immutable_tables = (
        "single_prompt_source_snapshots",
        "single_prompt_diagnosis_results",
        "single_prompt_diagnosis_reviews",
    )
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        for table_name in immutable_tables:
            if table_name not in tables:
                continue
            connection.execute(text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_DIAGNOSIS_HISTORY_IMMUTABLE');
                END
                """
            ))
            connection.execute(text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_DIAGNOSIS_HISTORY_IMMUTABLE');
                END
                """
            ))


def _ensure_sqlite_v2_strategy_immutability() -> None:
    immutable_tables = (
        "single_prompt_strategy_results",
        "single_prompt_strategy_reviews",
    )
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        for table_name in immutable_tables:
            if table_name not in tables:
                continue
            connection.execute(text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_STRATEGY_HISTORY_IMMUTABLE');
                END
                """
            ))
            connection.execute(text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_STRATEGY_HISTORY_IMMUTABLE');
                END
                """
            ))


def _ensure_sqlite_v2_execution_immutability() -> None:
    immutable_tables = (
        "single_prompt_execution_proposal_results",
        "single_prompt_execution_confirmations",
        "single_prompt_publication_records",
    )
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        for table_name in immutable_tables:
            if table_name not in tables:
                continue
            connection.execute(text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_EXECUTION_HISTORY_IMMUTABLE');
                END
                """
            ))
            connection.execute(text(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, 'V2_EXECUTION_HISTORY_IMMUTABLE');
                END
                """
            ))


def _ensure_sqlite_v2_retest_immutability() -> None:
    table_name = "single_prompt_comparison_results"
    with engine.begin() as connection:
        if table_name not in set(inspect(connection).get_table_names()):
            return
        connection.execute(text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_comparison_results_no_update
            BEFORE UPDATE ON single_prompt_comparison_results
            BEGIN
              SELECT RAISE(ABORT, 'V2_COMPARISON_HISTORY_IMMUTABLE');
            END
            """
        ))
        connection.execute(text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_single_prompt_comparison_results_no_delete
            BEFORE DELETE ON single_prompt_comparison_results
            BEGIN
              SELECT RAISE(ABORT, 'V2_COMPARISON_HISTORY_IMMUTABLE');
            END
            """
        ))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

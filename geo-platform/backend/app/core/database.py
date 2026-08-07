from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_columns()
        _ensure_sqlite_indexes()


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
    ]
    with engine.begin() as connection:
        for statement in statements:
            try:
                connection.execute(text(statement))
            except Exception:
                # SQLite development databases may contain legacy duplicate rows; formal migrations surface this.
                continue


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

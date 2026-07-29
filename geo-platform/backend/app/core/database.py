from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        _ensure_sqlite_columns()


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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

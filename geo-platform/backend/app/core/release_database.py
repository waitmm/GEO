"""Dedicated database connection for the GEO 1.0 release control plane."""

from collections.abc import Generator
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.release_sqlite import get_release_sqlite_dbapi


settings = get_settings()
release_database_url = os.environ.get("GEO_RELEASE_DATABASE_URL") or settings.release_database_url
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if release_database_url.startswith("sqlite")
    else {}
)
engine_options = {"connect_args": connect_args}
if release_database_url.startswith("sqlite"):
    engine_options["module"] = get_release_sqlite_dbapi()
release_engine = create_engine(release_database_url, **engine_options)

if release_database_url.startswith("sqlite"):
    @event.listens_for(release_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


ReleaseSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=release_engine,
)


def get_release_db() -> Generator[Session, None, None]:
    db = ReleaseSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

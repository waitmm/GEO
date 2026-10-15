"""Dedicated database connection for the GEO 1.0 release control plane."""

from collections.abc import Generator
from contextlib import contextmanager
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


class ReadOnlyBusinessQueryError(RuntimeError):
    """A release GET path attempted to mutate durable business state."""


@contextmanager
def read_only_release_session(db: Session) -> Generator[Session, None, None]:
    """Reject ORM writes while a release query is being served."""

    def reject_flush(session, flush_context, instances) -> None:
        if session.new or session.dirty or session.deleted:
            raise ReadOnlyBusinessQueryError("release query attempted a business write")

    def reject_orm_write(execute_state) -> None:
        if execute_state.is_insert or execute_state.is_update or execute_state.is_delete:
            raise ReadOnlyBusinessQueryError("release query attempted a business write")

    event.listen(db, "before_flush", reject_flush)
    event.listen(db, "do_orm_execute", reject_orm_write)
    try:
        yield db
        if db.new or db.dirty or db.deleted:
            raise ReadOnlyBusinessQueryError("release query left pending business writes")
    except ReadOnlyBusinessQueryError:
        db.rollback()
        raise
    finally:
        event.remove(db, "do_orm_execute", reject_orm_write)
        event.remove(db, "before_flush", reject_flush)


def get_release_db() -> Generator[Session, None, None]:
    db = ReleaseSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

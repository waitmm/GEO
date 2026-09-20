from __future__ import annotations

from logging.config import fileConfig
import os
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.release_sqlite import get_release_sqlite_dbapi

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_url() -> str:
    return os.environ.get("GEO_RELEASE_DATABASE_URL") or config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    context.configure(url=get_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"check_same_thread": False, "timeout": 30},
        module=get_release_sqlite_dbapi(),
    )
    with connectable.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("PRAGMA busy_timeout=30000")
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.commit()
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

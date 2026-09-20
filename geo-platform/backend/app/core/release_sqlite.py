"""Select the SQLite DB-API used by release migrations and the release API."""

from __future__ import annotations

import sqlite3
from types import ModuleType


def get_release_sqlite_dbapi() -> ModuleType:
    try:
        from pysqlite3 import dbapi2 as dbapi
    except ImportError:
        dbapi = sqlite3.dbapi2
    return dbapi

"""Build pysqlite3 against the pinned, WAL-reset-safe SQLite amalgamation."""

from __future__ import annotations

import hashlib
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import certifi


PYSQLITE_URL = "https://files.pythonhosted.org/packages/source/p/pysqlite3/pysqlite3-0.6.0.tar.gz"
PYSQLITE_SHA256 = "ecf5112b62a4e6c04438957e343fe9672707bd3191f789ecae6c95b226aa6bb6"
SQLITE_URL = "https://sqlite.org/2026/sqlite-amalgamation-3510300.zip"
SQLITE_SHA256 = "acb1e6f5d832484bf6d32b681e858c38add8b2acdfd42ac5df24b8afb46552b4"


def _download(url: str, destination: Path, expected_hash: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "GEO-Release-Bootstrap/1.0"})
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=120, context=context) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError(f"DOWNLOAD_HASH_MISMATCH:{destination.name}:{actual_hash}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="geo-release-sqlite-") as temp_value:
        root = Path(temp_value)
        pysqlite_archive = root / "pysqlite3-0.6.0.tar.gz"
        sqlite_archive = root / "sqlite-amalgamation-3510300.zip"
        _download(PYSQLITE_URL, pysqlite_archive, PYSQLITE_SHA256)
        _download(SQLITE_URL, sqlite_archive, SQLITE_SHA256)

        with tarfile.open(pysqlite_archive) as archive:
            archive.extractall(root, filter="data")
        with zipfile.ZipFile(sqlite_archive) as archive:
            archive.extractall(root)

        source = root / "pysqlite3-0.6.0"
        amalgamation = root / "sqlite-amalgamation-3510300"
        shutil.copy2(amalgamation / "sqlite3.c", source / "sqlite3.c")
        shutil.copy2(amalgamation / "sqlite3.h", source / "sqlite3.h")

        wheels = root / "wheels"
        wheels.mkdir()
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-build-isolation", str(source), "-w", str(wheels)],
            check=True,
        )
        wheel = next(wheels.glob("pysqlite3-0.6.0-*.whl"))
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", str(wheel)],
            check=True,
        )

    from pysqlite3 import dbapi2

    if dbapi2.sqlite_version != "3.51.3":
        raise RuntimeError(f"UNEXPECTED_RELEASE_SQLITE_VERSION:{dbapi2.sqlite_version}")
    print({"release_sqlite_version": dbapi2.sqlite_version, "dbapi": "pysqlite3"})


if __name__ == "__main__":
    main()

"""Restore a backup into a new directory and exercise the release migration there."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_backup import verify
from app.core.release_sqlite import get_release_sqlite_dbapi


def business_fingerprint(database):
    sqlite = get_release_sqlite_dbapi()
    result = {}
    with sqlite.connect(f'file:{database}?mode=ro', uri=True) as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'")]
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(json.dumps(list(row), ensure_ascii=False, default=str) for row in db.execute(f'SELECT * FROM {quoted}'))
            result[name] = {'count': len(rows), 'hash': sha256('\n'.join(rows).encode()).hexdigest()}
    return result


def check(backup, output):
    backup, output = Path(backup).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Refusing to replace an existing recovery directory')
    original = verify(backup)
    shutil.copytree(backup, output)
    restored = verify(output)  # Reads only the restored files, not original artifact paths.
    database = output / 'database.db'
    before = business_fingerprint(database)
    env = {**os.environ, 'GEO_RELEASE_DATABASE_URL': f'sqlite:///{database}'}
    proc = subprocess.run([sys.executable, '-m', 'alembic', '-c', 'alembic.release.ini', 'upgrade', 'head'],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True)
    (output / 'migration.log').write_text(proc.stdout + proc.stderr)
    proc.check_returncode()
    after = business_fingerprint(database)
    changed = [name for name in before if before[name] != after.get(name)]
    if changed:
        raise ValueError('Migration changed historical business tables: ' + ','.join(changed))
    from sqlalchemy import create_engine, event
    from app.core.release_database import _set_sqlite_pragma
    from app.release_schema import validate_release_database
    engine = create_engine(f'sqlite:///{database}', module=get_release_sqlite_dbapi())
    event.listen(engine, 'connect', _set_sqlite_pragma)
    try:
        status = validate_release_database(engine)
    finally:
        engine.dispose()
    report = {'status': 'PASS_ISOLATED_RESTORE_AND_UPGRADE', 'backup_revision': original['revision'],
              'restored_files': restored, 'database': status, 'historical_tables_unchanged': len(before),
              'added_tables': sorted(set(after) - set(before)), 'fingerprints': before,
              'scope': 'Database and listed artifact roots restored; production paths and business data not rewritten',
              'external_calls': 0}
    (output / 'upgrade-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return {key: value for key, value in report.items() if key != 'fingerprints'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.backup, args.output), ensure_ascii=False))

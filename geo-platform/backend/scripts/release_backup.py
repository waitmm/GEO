"""SQLite Online Backup plus immutable source files; never restore over live data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.release_sqlite import get_release_sqlite_dbapi


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    db_path = directory / 'database.db'
    if file_hash(db_path) != manifest['database_hash']:
        raise ValueError('BACKUP_DATABASE_HASH_MISMATCH')
    sqlite = get_release_sqlite_dbapi()
    supplemental_count = 0
    with sqlite.connect(f'file:{db_path}?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('BACKUP_DATABASE_INTEGRITY_FAILED')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('BACKUP_FOREIGN_KEY_FAILED')
        for row in manifest['sources']:
            path = (directory / row['backup_path']).resolve()
            if not path.is_relative_to(directory) or file_hash(path) != row['artifact_hash']:
                raise ValueError(f"BACKUP_SOURCE_HASH_FAILED:{row['snapshot_id']}")
            record = db.execute('SELECT clean_text, artifact_hash FROM single_prompt_prepared_source_snapshots WHERE snapshot_id=?', (row['snapshot_id'],)).fetchone()
            if not record or hashlib.sha256(record[0].encode()).hexdigest() != row['artifact_hash'] or record[1] != row['artifact_hash']:
                raise ValueError(f"BACKUP_SOURCE_BINDING_FAILED:{row['snapshot_id']}")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='supplemental_source_acquisitions'").fetchone():
            from app.modules.single_prompt_v2.delivery_text import digest, text_digest
            for identity, project, raw, expected in db.execute("SELECT source_id, project_id, snapshot_json, snapshot_hash FROM supplemental_source_acquisitions WHERE status IN ('READY','PARTIAL')"):
                snapshot = json.loads(raw)
                if (digest(snapshot) != expected or snapshot.get('snapshot_id') != identity
                        or snapshot.get('project_id') != project
                        or text_digest(snapshot.get('text', '')) != snapshot.get('content_hash')):
                    raise ValueError('BACKUP_SUPPLEMENTAL_SOURCE_BINDING_FAILED')
                supplemental_count += 1
    for row in manifest.get('artifacts', []):
        path = (directory / row['backup_path']).resolve()
        if not path.is_relative_to(directory) or file_hash(path) != row['hash']:
            raise ValueError('BACKUP_RUNTIME_ARTIFACT_HASH_FAILED')
    return {'database': 'PASS', 'source_bindings': len(manifest['sources']), 'revision': manifest['revision'],
            'supplemental_source_bindings': supplemental_count,
            'archived_artifact_files': len(manifest.get('artifacts', [])),
            'archived_roots': manifest.get('artifact_roots', []), 'full_runtime_artifact_archive': bool(manifest.get('artifact_roots'))}


def backup(database, output, artifact_roots=()):
    database, output = Path(database).resolve(), Path(output).resolve()
    if not database.is_file() or output.exists():
        raise ValueError('Backup requires an existing database and a new destination')
    output.mkdir(parents=True, mode=0o700)
    sqlite = get_release_sqlite_dbapi()
    dest = output / 'database.db'
    with sqlite.connect(f'file:{database}?mode=ro', uri=True) as source, sqlite.connect(dest) as target:
        source.backup(target)
    with sqlite.connect(f'file:{dest}?mode=ro', uri=True) as db:
        revision = db.execute('SELECT version_num FROM alembic_version').fetchone()[0]
        rows = db.execute('SELECT snapshot_id, artifact_path, artifact_hash FROM single_prompt_prepared_source_snapshots').fetchall()
    saved = []
    (output / 'sources').mkdir(mode=0o700)
    for index, (snapshot_id, path, expected) in enumerate(rows):
        original = Path(path)
        if not original.is_absolute():
            original = database.parent / original
        if not original.is_file() or file_hash(original) != expected:
            raise ValueError(f'SOURCE_ARTIFACT_NOT_RESTORABLE:{snapshot_id}')
        relative = f'sources/{index:06d}.txt'
        shutil.copyfile(original, output / relative)
        saved.append({'snapshot_id': snapshot_id, 'original_path': str(original), 'backup_path': relative, 'artifact_hash': expected})
    archived = []
    roots = [Path(root).resolve() for root in artifact_roots]
    for index, root in enumerate(roots):
        if not root.is_dir() or output.is_relative_to(root):
            raise ValueError('Invalid artifact archive root')
        for original in sorted(root.rglob('*')):
            if original.is_symlink():
                raise ValueError('Artifact archives do not follow symlinks')
            if not original.is_file():
                continue
            relative = Path('artifacts') / str(index) / original.relative_to(root)
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            before = file_hash(original)
            shutil.copyfile(original, destination)
            if file_hash(destination) != before or file_hash(original) != before:
                raise ValueError('Artifact changed during backup; quiesce writers and retry')
            archived.append({'backup_path': str(relative), 'original_path': str(original), 'hash': before})
    manifest = {'database_hash': file_hash(dest), 'revision': revision, 'sqlite_version': sqlite.sqlite_version,
                'sources': saved, 'artifacts': archived, 'artifact_roots': [str(root) for root in roots],
                'scope': 'DATABASE_AND_EXPLICIT_ARTIFACT_ROOTS' if roots else 'DATABASE_AND_PREPARED_SOURCE_FILES',
                'limitation': 'Only listed roots are archived. Credentials/browser login profiles are intentionally excluded.'}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return verify(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database')
    parser.add_argument('--output', required=True)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--artifact-root', action='append', default=[])
    args = parser.parse_args()
    result = verify(args.output) if args.verify else backup(args.database, args.output, args.artifact_root)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

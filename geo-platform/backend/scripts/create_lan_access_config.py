"""Create owner-only invitation credentials for one GEO LAN deployment.

Plain invitation keys are written only to the separate recovery file.  The
runtime access configuration contains SHA-256 digests and explicit project
scope.  Existing files are never overwritten.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets


def _exclusive_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def create(config: Path, recovery: Path, admin_name: str, operators: list[str], project_id: int) -> None:
    names = [admin_name, *operators]
    if any(not name.strip() for name in names) or len(set(names)) != len(names):
        raise ValueError("ACCOUNT_NAMES_MUST_BE_NONEMPTY_AND_UNIQUE")
    if project_id < 1:
        raise ValueError("PROJECT_ID_MUST_BE_POSITIVE")
    keys = {name: secrets.token_urlsafe(32) for name in names}
    accounts = [{
        "name": admin_name,
        "key_sha256": sha256(keys[admin_name].encode()).hexdigest(),
        "project_ids": [],
        "admin": True,
        "enabled": True,
    }]
    accounts.extend({
        "name": name,
        "key_sha256": sha256(keys[name].encode()).hexdigest(),
        "project_ids": [project_id],
        "admin": False,
        "enabled": True,
    } for name in operators)
    payload = json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2) + "\n"
    recovery_text = (
        "GEO M1 LAN 一次性邀请凭证（请通过安全渠道分别发放）\n"
        f"Project scope: {project_id}\n\n"
        + "\n".join(f"{name}: {keys[name]}" for name in names)
        + "\n"
    )
    _exclusive_write(config, payload)
    try:
        _exclusive_write(recovery, recovery_text)
    except Exception:
        config.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--recovery", required=True, type=Path)
    parser.add_argument("--admin-name", default="local-admin")
    parser.add_argument("--operator", action="append", default=[])
    parser.add_argument("--project-id", required=True, type=int)
    args = parser.parse_args()
    create(args.config, args.recovery, args.admin_name, args.operator, args.project_id)


if __name__ == "__main__":
    main()

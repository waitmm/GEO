"""Create or rotate the scoped shared-password configuration for an M1.1 pilot.

The password is read from stdin so it is not exposed in the process list or
shell history. Only an scrypt verifier and a random salt are persisted.
"""
from __future__ import annotations

import argparse
from hashlib import scrypt
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile


SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def create(path: Path, password: str, project_id: int, *, name: str = "爱短链内部试用", replace: bool = False) -> dict:
    if len(password) < 12 or len(password) > 512:
        raise ValueError("PASSWORD_LENGTH_MUST_BE_12_TO_512")
    if project_id < 1:
        raise ValueError("PROJECT_ID_MUST_BE_POSITIVE")
    if not name.strip() or len(name) > 100:
        raise ValueError("NAME_MUST_BE_1_TO_100")
    if path.exists() and not replace:
        raise FileExistsError(path)
    salt = secrets.token_bytes(16)
    verifier = scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    value = {
        "mode": "SHARED_PASSWORD",
        "shared_password": {
            "name": name.strip(),
            "salt_hex": salt.hex(),
            "password_scrypt": verifier.hex(),
            "project_ids": [project_id],
            "admin": False,
            "enabled": True,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--project-id", required=True, type=int)
    parser.add_argument("--name", default="爱短链内部试用")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--password-stdin", action="store_true", required=True)
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n")
    create(args.config, password, args.project_id, name=args.name, replace=args.replace)
    print(json.dumps({"status": "CREATED", "config": str(args.config), "project_id": args.project_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()

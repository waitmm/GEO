"""Offline official-sandbox probes. Never invokes exec, model/list, or a model turn."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

from delivery_codex_relay import (
    ROOT, isolated_environment, permission_profile, preflight, run_process,
    sandbox_command, save_json,
)


def probe(binary, directory):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    worktree = directory / "worktree"
    worktree.mkdir()
    (worktree / "backend").mkdir()
    (worktree / ".git").mkdir()
    (worktree / ".git/config").write_text("[core]\nrepositoryformatversion = 0\n")
    (worktree / "allowed.txt").write_text("offline fixture")
    private = directory / "mock-production"
    private.mkdir()
    key = private / "production.key"
    key.write_text("MOCK_SECRET_NOT_A_REAL_CREDENTIAL")
    with sqlite3.connect(private / "production.db") as connection:
        connection.execute("create table private_data(value text)")
    (worktree / ".env").write_text("MOCK_CREDENTIAL=not-real")
    (worktree / "secret-alias").symlink_to(key)
    (worktree / "db-alias").symlink_to(private / "production.db")
    environment = isolated_environment(directory)
    permissions = permission_profile(ROOT, worktree, directory)
    save_json(directory / "permissions.json", permissions)
    report = {"status": "RUNNING", "kind": "REAL_SANDBOX_OFFLINE_FIXTURES",
              "model_calls": 0, "exec_calls": 0, "checks": [], "permissions": permissions}
    listener = socket.socket()
    try:
        report["cli_version"] = subprocess.check_output([binary, "--version"], text=True).strip()
        # A reachable host listener makes refusal meaningful, not merely a closed-port error.
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            peer, _ = listener.accept()
            peer.close()
        report["host_network_control"] = "CONNECTED"
        report["effective_config"] = preflight(binary, worktree, directory, environment, check_catalog=False)
        checks = [
            ("authorized_read_write", "from pathlib import Path; "
             "assert Path('../allowed.txt').read_text() == 'offline fixture'; "
             "Path('../result.txt').write_text('ok'); assert Path('../result.txt').read_text() == 'ok'"),
            ("scratch_database", "import os,sqlite3; "
             "c=sqlite3.connect(os.environ['TMPDIR']+'/test.db'); "
             "c.execute('create table probe(value text)'); c.close()"),
        ]
        for name, path in [("mock_key_denied", key), ("mock_database_file_denied", private / "production.db"),
                           ("workspace_env_denied", worktree / ".env"),
                           ("secret_symlink_denied", worktree / "secret-alias"),
                           ("database_symlink_denied", worktree / "db-alias")]:
            checks.append((name, f"from pathlib import Path\ntry: Path({str(path)!r}).read_bytes()\n"
                           "except PermissionError: pass\nelse: raise AssertionError('unauthorized read succeeded')"))
        checks += [
            ("mock_sqlite_denied", "import sqlite3\ntry: "
             f"sqlite3.connect('file:{private / 'production.db'}?mode=ro', uri=True)\n"
             "except sqlite3.OperationalError: pass\nelse: raise AssertionError('database opened')"),
            ("git_metadata_readonly", "from pathlib import Path\n"
             "assert Path('../.git/config').read_text()\n"
             "try: Path('../.git/config').write_text('changed')\n"
             "except PermissionError: pass\nelse: raise AssertionError('git metadata changed')"),
            ("late_secret_denied", "from pathlib import Path\ntry: Path('../late.env').write_text('secret')\n"
             "except PermissionError: pass\nelse: raise AssertionError('new env file writable')"),
            ("network_denied", "import socket,errno\ntry: "
             f"socket.create_connection(('127.0.0.1',{port}), timeout=1)\n"
             "except OSError as e: assert e.errno in (errno.EPERM,errno.EACCES), repr(e)\n"
             "else: raise AssertionError('unauthorized network connected')"),
        ]
        for name, script in checks:
            command = sandbox_command(binary, worktree / "backend", permissions, [sys.executable, "-c", script])
            log = directory / (name + ".log")
            rc = run_process(command, worktree / "backend", log, 20, env=environment)
            report["checks"].append({"name": name, "exit_code": rc, "log": str(log)})
            save_json(directory / "report.json", report)
        if any(row["exit_code"] for row in report["checks"]):
            raise ValueError("Sandbox security probe failed; no model execution is authorized")
        report["status"] = "PASS"
    except Exception as exc:
        report.update(status="FAIL_CLOSED", reason=f"{type(exc).__name__}: {exc}")
    finally:
        listener.close()
        save_json(directory / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; never overwrites a run")
    options = parser.parse_args()
    result = probe(options.codex, options.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)

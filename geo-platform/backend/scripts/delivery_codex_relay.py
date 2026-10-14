"""Bounded developer sessions. Dry-run by default; never a product acceptance gate."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import socket
import subprocess
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[3]
LEDGER = Path("geo-platform/docs/geo-v1.0/tasks.json")
MODEL = "gpt-5.6-sol"
INTEGRATION = "codex/geo-integration"
PERMISSION_PROFILE = "geo-relay"
EXPECTED = {"model": MODEL, "model_reasoning_effort": "medium", "service_tier": "default",
            "approval_policy": "never", "default_permissions": PERMISSION_PROFILE}
OVERRIDES = {**EXPECTED, "features.multi_agent": False, "features.goals": False,
             "features.apps": False, "features.plugins": False,
             "web_search": "disabled"}


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def stop_group(child):
    # The group may still have descendants after the leader exits.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def detached_integration(root):
    if f"branch refs/heads/{INTEGRATION}" in git(root, "worktree", "list", "--porcelain").splitlines():
        raise ValueError("Integration branch is checked out; refuse to change its working baseline")


def relative_path(value):
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("Paths must be explicit repository-relative paths")
    return path


def protected(value):
    path = relative_path(value)
    return (path.name == "AGENTS.md" or path.name.startswith(".env")
            or path.suffix in {".db", ".sqlite", ".sqlite3"}
            or any(p in {".git", ".codex", ".agents", "artifacts", "backups"} for p in path.parts)
            or str(path) == str(LEDGER)
            or "docs/semantics/" in str(path)
            or path.name in {"acceptance_cases.json", "delivery_codex_relay.py"})


def select_units(ledger, limit):
    if not 1 <= limit <= 3:
        raise ValueError("Batch size must be 1..3")
    tasks = {t["id"]: t for t in ledger["tasks"]}
    units = ledger.get("codex_relay", {}).get("units", [])
    ids = [u["id"] for u in units]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate relay unit identity")
    remaining = {u["id"]: set(u.get("depends_on", [])) for u in units}
    if any(not dependencies <= set(ids) for dependencies in remaining.values()):
        raise ValueError("Unknown relay dependency")
    while remaining:
        ready = {name for name, dependencies in remaining.items() if not dependencies}
        if not ready:
            raise ValueError("Cyclic relay dependencies")
        remaining = {name: dependencies - ready for name, dependencies in remaining.items() if name not in ready}
    selected, completed = [], {u["id"] for u in units if u["status"] == "ACCEPTED"}
    pending = list(units)
    # Stable topological order, not accidental ledger ordering.
    while pending:
        unit = next((u for u in pending if set(u.get("depends_on", [])) <= completed), None)
        if unit is None:
            break
        pending.remove(unit)
        if unit["status"] != "READY":
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", unit["id"]):
            raise ValueError("Invalid unit ID")
        task = tasks.get(unit["task_id"])
        if not task or not set(unit["requirements"]) <= set(task["requirements"]):
            raise ValueError("Unit must bind existing task requirements")
        if not unit["requirements"] or not unit["objective"].strip():
            raise ValueError("Empty task scope")
        if not set(unit.get("depends_on", [])) <= completed:
            continue
        if not unit["allowed_files"] or any(protected(p) for p in unit["allowed_files"]):
            raise ValueError("Protected or empty file scope")
        if not unit["gates"]:
            raise ValueError("Independent gates are required")
        for gate in unit["gates"]:
            relative_path(gate["cwd"])
            if not gate["argv"] or not all(isinstance(a, str) and a for a in gate["argv"]):
                raise ValueError("Gate must be argv, never a shell string")
            if not gate["protected_files"]:
                raise ValueError("Gate must bind independent oracle files")
            for p in gate["protected_files"]:
                relative_path(p)
                if p in unit["allowed_files"]:
                    raise ValueError("Agent may not rewrite its acceptance oracle")
        selected.append(unit)
        completed.add(unit["id"])
        if len(selected) == limit:
            break
    return selected


def read_usage(path):
    totals = dict(input_tokens=0, cached_input_tokens=0, output_tokens=0)
    turns, failed = 0, False
    for line in path.read_text().splitlines():
        event = json.loads(line)
        failed |= event.get("type") in {"error", "turn.failed"}
        if event.get("type") != "turn.completed":
            continue
        usage = event["usage"]
        for key in totals:
            if type(usage.get(key)) is not int or usage[key] < 0:
                raise ValueError("Missing/invalid usage; stop instead of assuming zero")
        if usage["cached_input_tokens"] > usage["input_tokens"]:
            raise ValueError("Cached input is a subset of input")
        for key in totals:
            totals[key] += usage[key]
        turns += 1
    if not turns or failed:
        raise ValueError("Incomplete or failed session; usage cannot authorize continuation")
    totals["activity_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    totals["turns"] = turns
    return totals


def resolve_codex_binary(binary):
    """Resolve file and directory symlinks before Codex records its self-exec path."""
    candidate = shutil.which(str(Path(binary).expanduser()))
    if not candidate:
        raise ValueError("Codex executable not found or not executable")
    try:
        resolved = Path(candidate).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Codex executable has an invalid symlink chain") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("Codex executable must be a regular executable file")
    return str(resolved)


def codex_command(binary, worktree, permissions):
    # Codex itself enforces the profile on tools. Never wrap this process in Seatbelt.
    return [binary, "exec", "--model", MODEL, "--json",
            "--cd", str(worktree), *config_arguments(permissions), "-"]


def config_arguments(permissions):
    # CLI dotted-key overrides split literal dots, including dots inside quoted paths.
    # Pass one parsed TOML table instead, preserving path/glob keys exactly.
    def inline(value):
        if isinstance(value, dict):
            return "{" + ",".join(json.dumps(k) + "=" + inline(v) for k, v in value.items()) + "}"
        if not isinstance(value, (str, bool)):
            raise ValueError("Permission values must be strings, booleans, or tables")
        return json.dumps(value)
    table = inline(permissions)
    if tomllib.loads("profile=" + table)["profile"] != permissions:
        raise ValueError("Permission configuration did not round-trip")
    return [arg for key, value in OVERRIDES.items() for arg in ("-c", key + "=" + json.dumps(value))] + [
        "-c", f"permissions.{PERMISSION_PROFILE}={table}"]


def sandbox_command(binary, worktree, permissions, argv):
    return [binary, "sandbox", "-P", PERMISSION_PROFILE, "--include-managed-config",
            "-C", str(worktree), *config_arguments(permissions), "--", *argv]


def validate_effective(config, models, permissions):
    def without_unset(value):
        if isinstance(value, dict):
            return {k: without_unset(v) for k, v in value.items() if v is not None}
        return value
    for key, value in EXPECTED.items():
        if config.get(key) != value:
            raise ValueError(f"Effective config mismatch: {key}")
    for key in ("multi_agent", "goals", "apps", "plugins"):
        if config.get("features", {}).get(key) is not False:
            raise ValueError(f"Effective feature not disabled: {key}")
    if config.get("sandbox_mode") is not None or config.get("sandbox_workspace_write") is not None:
        raise ValueError("Legacy sandbox configuration overrides permission profiles; refuse execution")
    if without_unset(config.get("permissions", {}).get(PERMISSION_PROFILE)) != permissions:
        raise ValueError("Effective permission profile differs from the frozen isolation policy")
    if permissions.get("network", {}).get("enabled") is not False:
        raise ValueError("Tool network access not disabled")
    if config.get("web_search") != "disabled":
        raise ValueError("Web search not disabled")
    if any(s.get("enabled", True) for s in config.get("mcp_servers", {}).values()):
        raise ValueError("Enabled inherited MCP servers require explicit isolation review")
    if config.get("hooks") or config.get("features", {}).get("hooks"):
        raise ValueError("Inherited hooks require explicit isolation review")
    if models is not None:
        model = next((m for m in models if m.get("model") == MODEL), None)
        if not model or "medium" not in {e["reasoningEffort"] for e in model["supportedReasoningEfforts"]}:
            raise ValueError("Requested model/effort unavailable; never fall back automatically")
    # CLI protocol defines "default" as standard; serviceTiers may list only optional upgrades.
    return {**EXPECTED, "permissions": {PERMISSION_PROFILE: permissions},
            "catalog_checked": models is not None,
            "features": {k: False for k in ("multi_agent", "goals", "apps", "plugins")}}


def preflight(binary, worktree, directory, environment, *, check_catalog=True):
    """Read effective config/catalog, never start a thread/turn. Mocked in offline tests."""
    permissions = json.loads((directory / "permissions.json").read_text())
    if run_process(sandbox_command(binary, worktree, permissions, [binary, "--version"]),
                   worktree, directory / "isolation.log", 10, env=environment):
        raise ValueError("Sandbox cannot execute Codex itself; never widen permissions or fall back")
    if not (directory / "isolation.log").read_text().strip().startswith("codex-cli "):
        raise ValueError("Sandboxed executable did not identify itself as Codex CLI")
    command = [binary, "app-server", "--stdio", *config_arguments(permissions)]
    with (directory / "preflight.stderr").open("wb") as stderr:
        child = subprocess.Popen(command, cwd=worktree, env=environment, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=stderr, start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        buffer = b""
        sequence = 0
        deadline = time.monotonic() + 30
        def rpc(method, params):
            nonlocal buffer, sequence
            sequence += 1
            child.stdin.write((json.dumps({"id": sequence, "method": method, "params": params}) + "\n").encode())
            child.stdin.flush()
            while time.monotonic() < deadline:
                if b"\n" not in buffer:
                    if not selector.select(max(0, deadline - time.monotonic())):
                        break
                    data = os.read(child.stdout.fileno(), 65536)
                    if not data:
                        raise ValueError("Configuration preflight exited")
                    buffer += data
                    if len(buffer) > 8_000_000:
                        raise ValueError("Preflight response too large")
                    continue
                line, buffer = buffer.split(b"\n", 1)
                reply = json.loads(line)
                if reply.get("id") == sequence:
                    if "error" in reply:
                        raise ValueError("Configuration preflight RPC rejected")
                    return reply["result"]
            raise TimeoutError("Configuration preflight timed out")
        try:
            rpc("initialize", {"clientInfo": {"name": "geo-bounded-relay", "version": "1"}})
            child.stdin.write(b'{"method":"initialized"}\n')
            child.stdin.flush()
            config = rpc("config/read", {"cwd": str(worktree), "includeLayers": False})["config"]
            save_json(directory / "effective-permissions.json", {
                **{key: config.get(key) for key in (
                    "default_permissions", "sandbox_mode", "sandbox_workspace_write")},
                "permissions": {PERMISSION_PROFILE: config.get("permissions", {}).get(PERMISSION_PROFILE)}})
            if not check_catalog:
                return validate_effective(config, None, permissions)
            models, cursor = [], None
            for _ in range(10):
                page = rpc("model/list", {"cursor": cursor, "limit": 100, "includeHidden": True})
                models.extend(page["data"])
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            return validate_effective(config, models, permissions)
        finally:
            stop_group(child)
            selector.close()
            child.stdin.close()
            child.stdout.close()


def isolated_environment(directory):
    scratch = directory / "scratch"
    scratch.mkdir(exist_ok=True)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "SYSTEMROOT") if k in os.environ}
    env.update(TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch), PYTHONDONTWRITEBYTECODE="1",
               GEO_ACCEPTANCE_OFFLINE="1", GEO_RELAY_ACTIVE="1", MONITORING_WORKER="0",
               DATABASE_URL=f"sqlite:///{scratch / 'test-legacy.db'}",
               RELEASE_DATABASE_URL=f"sqlite:///{scratch / 'test-release.db'}",
               GEO_RELEASE_DATABASE_URL=f"sqlite:///{scratch / 'test-release.db'}",
               EVIDENCE_ARTIFACT_DIR=str(scratch / "evidence"), MONITORING_ARTIFACT_DIR=str(scratch / "monitoring"),
               WENXIN_PROFILE_DIR=str(scratch / "browser-profile"),
               REDIS_URL="redis://127.0.0.1:1/0", DEEPSEEK_API_KEY="", SILICONFLOW_API_KEY="",
               WENXIN_API_KEY="", WENXIN_SECRET_KEY="", ALLOW_EXTERNAL_LLM_STRATEGY_SYNTHESIS="false")
    backend, frontend = allocate_ports()
    env.update(BACKEND_PORT=str(backend), FRONTEND_PORT=str(frontend),
               GEO_API_PROXY_TARGET=f"http://127.0.0.1:{backend}")
    return env


def allocate_ports():
    # Reserve simultaneously to avoid selecting the same port twice; startup must still handle EADDRINUSE.
    sockets = [socket.socket(), socket.socket()]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        ports = [s.getsockname()[1] for s in sockets]
    finally:
        for sock in sockets:
            sock.close()
    if set(ports) & {5173, 8021, 6379}:
        raise ValueError("Allocated a protected production port")
    return ports


def permission_profile(root, worktree, directory, binary):
    """One official tool sandbox; controller/auth transport remain on the host."""
    root, worktree, directory = (Path(p).resolve() for p in (root, worktree, directory))
    filesystem = {":root": "deny", ":minimal": "read", ":tmpdir": "write", ":slash_tmp": "deny",
                  str(worktree): "write", str(directory / "scratch"): "write"}
    for path in (root / ".git", root / "geo-platform/backend/.venv",
                 root / "geo-platform/frontend/node_modules", Path(os.sys.base_prefix)):
        filesystem[str(path.resolve())] = "read"
    for name in (".git", ".agents", ".codex"):
        filesystem[str(worktree / name)] = "read"
    for name in (".aws", ".ssh"):
        filesystem[str(worktree / name)] = "deny"
    for name in (".codex", ".ssh", ".aws", ".config"):
        filesystem[str(Path.home() / name)] = "deny"
    # Canonical startup avoids granting an installer symlink directory and its siblings.
    filesystem[resolve_codex_binary(binary)] = "read"
    # Includes files created after policy compilation; never allow copied secrets/live DBs.
    filesystem[str(worktree)] = {".": "write"}
    for pattern in ("**/.env", "**/.env.*", "**/*.env", "**/*.db", "**/*.sqlite", "**/*.sqlite3",
                    "**/*.pem", "**/auth.json"):
        filesystem[str(worktree)][pattern] = "deny"
    return {"extends": ":workspace", "filesystem": filesystem, "network": {"enabled": False}}


def run_process(argv, cwd, output, timeout, stdin=None, *, env=None):
    """Bound wall time and terminate the complete child process group on interruption."""
    with output.open("wb") as stdout, output.with_suffix(".stderr").open("wb") as stderr:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            child.communicate(stdin.encode() if stdin is not None else None, timeout=timeout)
        finally:
            stop_group(child)
    return child.returncode


def changes(root):
    tracked = git(root, "diff", "--name-only", "HEAD").splitlines()
    untracked = git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(tracked + untracked))


def guard(worktree, head, allowed, oracles, dependency_links=None):
    if git(worktree, "rev-parse", "HEAD") != head:
        raise ValueError("Child changed HEAD; controller owns commits")
    for name, target in (dependency_links or {}).items():
        link = worktree / name
        if not link.is_symlink() or link.resolve() != target:
            raise ValueError("Controller dependency link changed: " + name)
    paths = changes(worktree)
    if set(paths) - set(allowed):
        raise ValueError("Out-of-scope edits: " + str(sorted(set(paths) - set(allowed))))
    for name in paths:
        p = worktree / name
        if p.is_symlink() or (p.exists() and not p.resolve().is_relative_to(worktree.resolve())):
            raise ValueError("Symlink escape in changed file")
    for name, expected in oracles.items():
        if hashlib.sha256((worktree / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Acceptance oracle changed")
    subprocess.run(["git", "diff", "--check"], cwd=worktree, check=True)
    return paths


def prompt_for(unit, feedback):
    return ("Execute ONLY this bounded GEO IMPLEMENTATION_CHANGE unit. Read repository AGENTS.md and its "
            "required documents; use current tasks/acceptance baseline. Do not pick another task, commit, "
            "merge, push, invoke Codex/subagents, change permissions, access secrets/live DBs, run external "
            "models/platforms, or weaken tests. No external business calls are authorized. Stop and report "
            "semantic risk or missing permission. Preserve user changes and v7. Run targeted checks, not "
            "the full suite repeatedly. Final response: changed files, actual tests, remaining risks.\n"
            + json.dumps(unit, ensure_ascii=False) + "\nPrior gate feedback: " + feedback)


def execute_batch(root, units, directory, *, binary, token_threshold, timeout, repairs,
                  runner=run_process, verifier=preflight, resume=False):
    """Units/gates are frozen in controller memory; never reread model-modified task data."""
    options = {"token_threshold": token_threshold, "timeout": timeout, "repairs": repairs, "model": MODEL}
    checkpoint = directory / "report.json"
    report = json.loads(checkpoint.read_text()) if resume else {
              "status": "RUNNING", "model": MODEL, "effort": "medium", "service_tier": "default",
              "activity_tokens": 0, "accounting_complete": True, "attempts": [], "accepted": {},
              "unit_hash": digest(units), "options": options, "product_status": "INCOMPLETE",
              "token_limit_kind": "POST_SESSION_STOP_NOT_HARD_REQUEST_CAP"}
    worktree = directory / "worktree"
    branch = "codex-relay/" + directory.name
    report["branch"] = branch
    try:
        requested_binary = binary
        binary = resolve_codex_binary(binary)
        report["codex_binary"] = {"requested": requested_binary, "resolved": binary}
        detached_integration(root)
        integration_head = git(root, "rev-parse", "refs/heads/" + INTEGRATION)
        if resume:
            if report["unit_hash"] != digest(units) or report["options"] != options:
                raise ValueError("Checkpoint unit/budget identity changed; review before recovery")
            if not report["accounting_complete"] or any(a["status"] == "RUNNING" for a in report["attempts"]):
                raise ValueError("Interrupted/unknown usage; no automatic model retry")
            if integration_head != report["integration_head"]:
                pending = report.get("pending_integration")
                if not pending or integration_head != pending["commit"]:
                    raise ValueError("Integration baseline moved; stop stale work")
        else:
            if checkpoint.exists():
                raise ValueError("Existing checkpoint requires explicit resume")
            report.update(base_commit=integration_head, integration_head=integration_head)
            save_json(checkpoint, report)
            git(root, "worktree", "add", "-b", branch, str(worktree), integration_head)
        environment = isolated_environment(directory)
        # Dependencies are read-only shared tools, never production data/config copies.
        dependency_links = {}
        for source in ("geo-platform/frontend/node_modules",):
            target = worktree / source
            if (root / source).exists():
                dependency_links[source] = (root / source).resolve()
                if not target.exists() and not target.is_symlink():
                    target.symlink_to(root / source, target_is_directory=True)
        permissions = permission_profile(root, worktree, directory, binary)
        save_json(directory / "permissions.json", permissions)
        report["isolation"] = {k: environment[k] for k in (
            "GEO_RELEASE_DATABASE_URL", "DATABASE_URL", "TMPDIR", "BACKEND_PORT", "FRONTEND_PORT")}
        report["effective_config"] = verifier(binary, worktree, directory, environment)
        save_json(checkpoint, report)

        def integrate(pending):
            detached_integration(root)
            current = git(root, "rev-parse", "refs/heads/" + INTEGRATION)
            if current == pending["before"]:
                # CAS prevents another invocation/user update from being silently overwritten.
                git(root, "update-ref", "refs/heads/" + INTEGRATION, pending["commit"], pending["before"])
            elif current != pending["commit"]:
                raise ValueError("Integration baseline moved before integration")
            report["integration_head"] = pending["commit"]
            report["accepted"][pending["unit"]] = pending["commit"]
            report["pending_integration"] = None
            save_json(checkpoint, report)

        if report.get("pending_integration"):
            pending = report["pending_integration"]
            if git(worktree, "rev-parse", "HEAD") != pending["commit"] or changes(worktree):
                raise ValueError("Pending integration worktree changed")
            integrate(pending)
        for unit in units:
            if unit["id"] in report["accepted"]:
                continue
            if report["activity_tokens"] >= token_threshold:
                raise ValueError("Activity threshold reached; no next task")
            head = git(worktree, "rev-parse", "HEAD")
            if head != report["integration_head"] or git(root, "rev-parse", INTEGRATION) != head:
                raise ValueError("Task did not start from integrated predecessor")
            oracles = {p: hashlib.sha256((worktree / p).read_bytes()).hexdigest()
                       for g in unit["gates"] for p in g["protected_files"]}
            feedback = "none"
            previous = [a for a in report["attempts"] if a["unit"] == unit["id"]]
            if previous and previous[-1]["status"] not in {"MODEL_DONE", "GATE_FAILED"}:
                raise ValueError("Prior process failure requires review, not automatic retry")
            if previous and previous[-1].get("oracles") != oracles:
                raise ValueError("Oracle changed since checkpoint")
            redo_gates = bool(previous and previous[-1]["status"] == "MODEL_DONE")
            if previous:
                feedback = previous[-1].get("feedback", "none")
            start = len(previous) - int(redo_gates)
            for attempt in range(start, repairs + 1):
                row = previous[-1] if redo_gates else {
                    "unit": unit["id"], "attempt": attempt + 1, "status": "RUNNING", "oracles": oracles}
                stem = directory / f"{unit['id']}-{attempt + 1}"
                output = stem.with_suffix(".jsonl")
                if not redo_gates:
                    report["attempts"].append(row)
                    report["accounting_complete"] = False
                    save_json(checkpoint, report)
                    started = time.monotonic()
                    rc = runner(codex_command(binary, worktree, permissions), worktree, output, timeout,
                                prompt_for(unit, feedback), env=environment)
                    row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    row["usage"] = read_usage(output)
                    report["activity_tokens"] += row["usage"]["activity_tokens"]
                    report["accounting_complete"] = True
                    row["status"] = "PROCESS_FAILED" if rc else "MODEL_DONE"
                    save_json(checkpoint, report)
                    if rc:
                        raise ValueError(f"Codex exited {rc}; no automatic transport/model retry")
                redo_gates = False
                paths = guard(worktree, head, unit["allowed_files"], oracles, dependency_links)
                gates = []
                for index, gate in enumerate(unit["gates"]):
                    argv = [s.replace("{python}", os.sys.executable) for s in gate["argv"]]
                    log = directory / f"{unit['id']}-{attempt + 1}-gate{index}.log"
                    code = runner(sandbox_command(binary, worktree / gate["cwd"], permissions, argv),
                                  worktree / gate["cwd"], log, min(timeout, 300), env=environment)
                    gates.append({"exit_code": code, "log": str(log)})
                row["gates"] = gates
                paths = guard(worktree, head, unit["allowed_files"], oracles, dependency_links)
                if all(g["exit_code"] == 0 for g in gates):
                    if paths:
                        git(worktree, "add", "--", *paths)
                        git(worktree, "commit", "-m", f"{unit['task_id']}: {unit['id']} (scoped gates)")
                    row.update(status="SCOPED_GATES_PASS_REVIEW_REQUIRED", commit=git(worktree, "rev-parse", "HEAD"))
                    report["pending_integration"] = {"unit": unit["id"], "before": head, "commit": row["commit"]}
                    save_json(checkpoint, report)
                    integrate(report["pending_integration"])
                    break
                row["status"] = "GATE_FAILED"
                feedback = "\n".join(Path(g["log"]).read_text()[-4000:] for g in gates if g["exit_code"])
                row["feedback"] = feedback
                save_json(checkpoint, report)
                if report["activity_tokens"] >= token_threshold:
                    raise ValueError("Activity threshold reached; no repair or next task")
            else:
                raise ValueError("Repair limit reached; keep failed evidence and worktree")
            if report["activity_tokens"] >= token_threshold:
                raise ValueError("Activity threshold reached; no next task")
        report["status"] = "BATCH_GATES_PASS_REVIEW_REQUIRED"
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="STOPPED", reason=f"{type(exc).__name__}: {exc}")
    finally:
        save_json(checkpoint, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly allow paid Codex child sessions")
    parser.add_argument("--resume", action="store_true", help="Recover the exact last batch, never reset usage/retries")
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--session-seconds", type=int, default=900)
    parser.add_argument("--token-threshold", type=int, default=100000)
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args()
    if not 0 <= args.max_repairs <= 2 or not 1 <= args.session_seconds <= 1800 or args.token_threshold <= 0:
        parser.error("repairs=0..2, session-seconds=1..1800, positive token threshold required")
    ledger = json.loads((ROOT / LEDGER).read_text())
    units = select_units(ledger, args.max_tasks)
    if not args.execute:
        print(json.dumps({"status": "DRY_RUN", "units": units, "model": MODEL,
                          "integration_branch": INTEGRATION, "config_overrides": OVERRIDES,
                          "effective_config": "NOT_CHECKED_NO_CODEX_PROCESS_STARTED",
                          "max_sessions": len(units) * (args.max_repairs + 1),
                          "activity_stop_threshold": args.token_threshold,
                          "session_seconds": args.session_seconds, "external_calls": 0}, ensure_ascii=False, indent=2))
        return 0
    if not units:
        parser.error("No READY bounded units; no session started")
    if git(ROOT, "status", "--porcelain"):
        parser.error("Checkpoint/commit existing edits before execution")
    if os.environ.get("GEO_RELAY_ACTIVE"):
        parser.error("Nested relay invocation is forbidden")
    if git(ROOT, "branch", "--show-current") == INTEGRATION:
        parser.error("Integration must not be checked out; controller updates it by compare-and-swap")
    base = ROOT / "geo-platform/backend/artifacts/codex_usage"
    base.mkdir(parents=True, exist_ok=True)
    with (base / "relay.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another relay controller is active; no session started")
        # Deliberately retain this receipt: a new invocation cannot replay a batch silently.
        receipt = base / "unreviewed-batch.json"
        if receipt.exists() and not args.resume:
            parser.error("Prior batch awaits review; reconcile receipt and ledger before another batch")
        if args.resume:
            if not receipt.exists():
                parser.error("No checkpoint to recover")
            directory = Path(json.loads(receipt.read_text())["directory"])
            if not directory.resolve().is_relative_to(base.resolve()):
                parser.error("Invalid checkpoint directory")
        else:
            directory = base / (time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
            directory.mkdir(mode=0o700)
            save_json(receipt, {"directory": str(directory), "units": [u["id"] for u in units]})
        report = execute_batch(ROOT, units, directory, binary=args.codex,
                               token_threshold=args.token_threshold, timeout=args.session_seconds,
                               repairs=args.max_repairs, resume=args.resume)
        print(json.dumps({"status": report["status"], "report": str(directory / "report.json")}))
        return 0 if report["status"] == "BATCH_GATES_PASS_REVIEW_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

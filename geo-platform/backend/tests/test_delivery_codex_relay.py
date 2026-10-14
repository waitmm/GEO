import json
from pathlib import Path
import subprocess
import sys
import time
import tomllib

import pytest

from scripts.delivery_codex_relay import (
    EXPECTED, INTEGRATION, MODEL, codex_command, execute_batch, guard, read_usage, run_process, select_units,
    isolated_environment, validate_effective, permission_profile,
)
from scripts import delivery_codex_relay as relay


@pytest.fixture(autouse=True)
def mock_ports(monkeypatch):
    monkeypatch.setattr(relay, "allocate_ports", lambda: (61001, 61002))
    resolve = relay.resolve_codex_binary
    monkeypatch.setattr(relay, "resolve_codex_binary", lambda binary: resolve(sys.executable)
                        if binary in {"FAKE_NOT_CODEX", "MOCK_NOT_CODEX", "MOCK"} else resolve(binary))


def unit(name="scope", **overrides):
    return {"id": name, "task_id": "T25", "requirements": ["OPS-002"], "status": "READY",
            "objective": "One isolated test change", "depends_on": [], "allowed_files": ["change.txt"],
            "gates": [{"cwd": ".", "argv": ["fake-gate"], "protected_files": ["oracle.txt"]}], **overrides}


def ledger(*units):
    return {"tasks": [{"id": "T25", "requirements": ["OPS-002"]}], "codex_relay": {"units": list(units)}}


def event(input_tokens=100, cached_input_tokens=80, output_tokens=10):
    return json.dumps({"type": "turn.completed", "usage": {
        "input_tokens": input_tokens, "cached_input_tokens": cached_input_tokens, "output_tokens": output_tokens}}) + "\n"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for key, value in [("user.name", "Isolated Test"), ("user.email", "test@example.invalid")]:
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    (root / "oracle.txt").write_text("independent expectation")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    subprocess.run(["git", "-C", str(root), "branch", INTEGRATION], check=True)
    return root


def batch(tmp_path, repo, units, runner, **options):
    directory = tmp_path / "batch"
    directory.mkdir(exist_ok=True)
    return execute_batch(repo, units, directory, binary="FAKE_NOT_CODEX", token_threshold=1000,
                         timeout=1, repairs=2, runner=runner,
                         verifier=lambda *args: dict(EXPECTED), **options)


def test_selector_bounded_dependencies_and_existing_task_binding():
    rows = [unit("a"), unit("b", depends_on=["a"]), unit("c"), unit("d")]
    assert [u["id"] for u in select_units(ledger(*rows), 3)] == ["a", "b", "c"]
    assert select_units(ledger(unit("unaccepted", status="BLOCKED"), unit(depends_on=["unaccepted"])), 1) == []
    for invalid in [0, 4]:
        with pytest.raises(ValueError):
            select_units(ledger(*rows), invalid)
    with pytest.raises(ValueError):
        select_units(ledger(unit(requirements=["INVENTED"])), 1)


@pytest.mark.parametrize("path", ["../outside", "/tmp/outside", "AGENTS.md", ".codex/config.toml",
                                  "geo-platform/backend/.env", "geo-platform/backend/geo_release.db",
                                  "geo-platform/docs/geo-v1.0/tasks.json", "oracle.txt"])
def test_protected_paths_and_oracles_are_not_agent_writable(path):
    with pytest.raises(ValueError):
        select_units(ledger(unit(allowed_files=[path])), 1)


def test_usage_cache_is_subset_and_reasoning_field_is_optional(tmp_path):
    path = tmp_path / "events"
    path.write_text(event() + event(200, 150, 20))
    assert read_usage(path) == {"input_tokens": 300, "cached_input_tokens": 230,
                                "output_tokens": 30, "activity_tokens": 330, "turns": 2}


@pytest.mark.parametrize("payload", ["", "not-json", '{"type":"turn.failed"}',
    '{"type":"turn.completed","usage":{"input_tokens":10}}', event(1, 2, 0),
    event(-1, 0, 0), event() + '{"type":"error"}'])
def test_unknown_usage_never_authorizes_next_session(tmp_path, payload):
    path = tmp_path / "events"
    path.write_text(payload)
    with pytest.raises((ValueError, KeyError)):
        read_usage(path)


def reconnect():
    return json.dumps({"type": "error", "message": "Reconnecting... 2/5 (request timed out)"}) + "\n"


def test_usage_reconnect_recovers_only_after_completion(tmp_path):
    path = tmp_path / "events"
    path.write_text(reconnect() * 4 + event(647278, 585088, 5933))
    observation = relay.inspect_usage(path)
    assert observation["accounting_complete"]
    assert observation["reconnect_events"] == 4
    assert read_usage(path)["activity_tokens"] == 653211


@pytest.mark.parametrize("suffix", [reconnect(), '{"type":"turn.started"}\n',
    '{"type":"turn.failed"}\n', '{"type":"error","message":"fatal"}\n',
    '{"type":"turn.completed","usage":{}}\n', 'null\n', '{"unfinished":',
    '{"type":"item.started"}\n'])
def test_usage_partial_stream_preserves_observed_lower_bound(tmp_path, suffix):
    path = tmp_path / "events"
    path.write_text(event() + suffix)
    observation = relay.inspect_usage(path)
    assert not observation["accounting_complete"]
    assert observation["observed_usage"]["activity_tokens"] == 110
    with pytest.raises(ValueError):
        read_usage(path)


@pytest.mark.parametrize("prefix", ['{"type":"turn.failed"}\n',
    '{"type":"error","message":"authentication failed"}\n', 'not-json\n'])
def test_usage_completion_does_not_erase_terminal_failure(tmp_path, prefix):
    path = tmp_path / "events"
    path.write_text(prefix + event())
    observation = relay.inspect_usage(path)
    assert not observation["accounting_complete"]
    assert observation["observed_usage"]["activity_tokens"] == 110


def test_usage_missing_is_unknown_not_measured_zero(tmp_path):
    observation = relay.inspect_usage(tmp_path / "missing")
    assert observation["observed_usage"] is None and not observation["accounting_complete"]


@pytest.mark.parametrize("mode", ["timeout", "exit", "incomplete", "gate_failed", "budget"])
def test_usage_reconnect_batch_keeps_observations_and_requires_gates(tmp_path, repo, mode):
    calls, gates = [], []
    directory = tmp_path / "batch"
    directory.mkdir()
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            calls.append(stdin)
            output.write_text(reconnect() + event(647278, 585088, 5933)
                              + (reconnect() if mode == "incomplete" else ""))
            if mode == "timeout":
                raise subprocess.TimeoutExpired(argv, timeout)
            return 71 if mode == "exit" else 0
        gates.append(argv)
        output.write_text("mock independent gate")
        return 1 if mode == "gate_failed" else 0
    report = execute_batch(repo, [unit("a"), unit("b")], directory, binary="MOCK",
                           token_threshold=30000, timeout=1, repairs=0, runner=runner,
                           verifier=lambda *args: dict(EXPECTED))
    assert report["status"] == "STOPPED" and len(calls) == 1
    assert report["observed_activity_tokens"] == report["activity_tokens"] == 653211
    assert report["accounting_complete"] == (mode not in {"timeout", "incomplete"})
    assert bool(gates) == (mode in {"gate_failed", "budget"})
    assert bool(report["accepted"]) == (mode == "budget")
    if mode == "budget":
        assert "no next task" in report["reason"]
    if mode == "timeout":
        again = execute_batch(repo, [unit("a"), unit("b")], directory, binary="MOCK",
                              token_threshold=30000, timeout=1, repairs=0, runner=runner,
                              verifier=lambda *args: dict(EXPECTED), resume=True)
        assert "unknown usage" in again["reason"] and len(calls) == 1


def test_prompt_limits_reading_without_waiving_instructions():
    prompt = relay.prompt_for(unit(), "none")
    assert "AGENTS.md" in prompt and "task-scoped" in prompt
    assert "only the target section" in prompt and "concrete dependency" in prompt
    assert "secrets/live DBs" in prompt and "semantic risk" in prompt
    assert "required documents" not in prompt


@pytest.mark.parametrize("name", ["中文说明.md", " spaced name .md", "tab\tline\nname.md", 'quote"back\\slash.md'])
def test_raw_git_paths_round_trip_tracked_and_untracked(tmp_path, repo, name):
    (repo / name).write_text("original")
    assert relay.changes(repo) == [name]
    relay.git(repo, "add", "--", name)
    relay.git(repo, "commit", "-m", "path fixture")
    head = relay.git(repo, "rev-parse", "HEAD")
    (repo / name).write_text("updated")
    assert guard(repo, head, [name], {}) == [name]
    with pytest.raises(ValueError, match="Out-of-scope"):
        guard(repo, head, ["different.md"], {})


def test_rename_cannot_hide_out_of_scope_source(repo):
    head = relay.git(repo, "rev-parse", "HEAD")
    relay.git(repo, "mv", "oracle.txt", "允许.md")
    assert set(relay.changes(repo)) == {"oracle.txt", "允许.md"}
    with pytest.raises(ValueError, match="Out-of-scope"):
        guard(repo, head, ["允许.md"], {})


def test_documentation_limits_do_not_change_business_defaults():
    assert relay.stream_limits(unit()) is None
    doc = unit(allowed_files=["说明.md"])
    assert relay.stream_limits(doc) == {"max_commands": 8, "max_output_chars": 20000}
    assert relay.stream_limits({**doc, "stream_limits": {"max_commands": 3}})["max_commands"] == 3


def test_document_small_type_and_product_independent_policy():
    doc = unit(task_type="DOCUMENT_SMALL", allowed_files=["说明.md"])
    assert relay.session_seconds(doc, 900) == 180
    assert relay.session_seconds(doc, 60) == 60
    assert relay.session_seconds({**doc, "session_seconds": 120}, 900) == 120
    product = {**doc, "task_type": "PRODUCT"}
    assert relay.stream_limits(product) is None and relay.session_seconds(product, 900) == 900
    product.update(stream_limits={"max_commands": 30, "max_output_chars": 80000}, session_seconds=600)
    assert relay.stream_limits(product) == {"max_commands": 30, "max_output_chars": 80000}
    assert relay.session_seconds(product, 900) == 600


@pytest.mark.parametrize("override", [{"task_type": "UNKNOWN"}, {"session_seconds": 0},
    {"session_seconds": True}, {"session_seconds": 1801}, {"session_seconds": "180"},
    {"task_type": "DOCUMENT_SMALL", "allowed_files": ["code.py"]},
    {"task_type": "PRODUCT", "stream_limits": {"max_commands": 8}}])
def test_invalid_task_policy_rejected_before_launch(override):
    candidate = unit(allowed_files=["doc.md"])
    candidate.update(override)
    with pytest.raises(ValueError):
        select_units(ledger(candidate), 1)


def test_document_policy_is_passed_to_runner_and_frozen_on_resume(tmp_path, repo):
    directory = tmp_path / "batch"
    directory.mkdir()
    doc = unit(allowed_files=["doc.md"], task_type="DOCUMENT_SMALL")
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            assert timeout == 180
            assert kwargs["limits"] == {"max_commands": 8, "max_output_chars": 20000}
            output.write_text(event())
            return 0
        raise KeyboardInterrupt()
    args = dict(binary="MOCK", token_threshold=1000, timeout=900, repairs=0,
                verifier=lambda *a: dict(EXPECTED))
    report = execute_batch(repo, [doc], directory, runner=runner, **args)
    assert report["attempts"][0]["session_seconds"] == 180
    assert report["options"]["unit_execution_limits"]["scope"]["task_type"] == "DOCUMENT_SMALL"
    report["options"]["unit_execution_limits"]["scope"]["session_seconds"] = 181
    relay.save_json(directory / "report.json", report)
    def forbidden(*args, **kwargs):
        pytest.fail("Changed frozen limits cannot resume")
    resumed = execute_batch(repo, [doc], directory, runner=forbidden, resume=True, **args)
    assert "Checkpoint unit/budget identity changed" in resumed["reason"]


@pytest.mark.parametrize("limits", [{"max_commands": 0}, {"max_output_chars": -1},
    {"max_commands": True}, {"unknown": 1}, None])
def test_invalid_documentation_limits_rejected_before_execution(limits):
    with pytest.raises(ValueError):
        select_units(ledger(unit(allowed_files=["doc.md"], stream_limits=limits)), 1)


def command_event(identity="cmd1", output="", kind="item.completed"):
    return json.dumps({"type": kind, "item": {"id": identity, "type": "command_execution",
                                              "aggregated_output": output}}) + "\n"


def test_stream_meter_deduplicates_incremental_snapshots_and_chunks():
    meter = relay.StreamMeter({"max_commands": 2, "max_output_chars": 5})
    data = (command_event(kind="item.started") + command_event(output="中文", kind="item.updated")
            + command_event(output="中文abc") + command_event(output="中文abc")).encode()
    for byte in data:
        meter.feed(bytes([byte]))
    assert meter.snapshot() == {"commands": 1, "output_chars": 5}
    with pytest.raises(relay.StreamLimitExceeded, match="OUTPUT_LIMIT"):
        meter.feed(command_event("cmd2", "x").encode())


@pytest.mark.parametrize("mode", ["commands", "output", "partial"])
def test_stream_stop_kills_descendants_and_records_real_returncode(tmp_path, mode):
    heartbeat = tmp_path / "heartbeat"
    descendant = ("import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                  f"p=pathlib.Path({str(heartbeat)!r});\nwhile True: p.write_text(str(time.time())); time.sleep(.01)")
    payload = (command_event("a", kind="item.started") + command_event("b", kind="item.started")
               if mode == "commands" else command_event(output="x" * 6) if mode == "output" else "x" * 66000)
    parent = (f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
              f"time.sleep(.2); sys.stdout.write({payload!r}); sys.stdout.flush(); time.sleep(60)")
    record = {}
    with pytest.raises(relay.StreamLimitExceeded):
        run_process([sys.executable, "-c", parent], tmp_path, tmp_path / "events", 5,
                    limits={"max_commands": 1, "max_output_chars": 5}, record=record)
    assert record["returncode"] < 0 and not record["timed_out"]
    assert record["exit_reason"] == {"commands": "COMMAND_LIMIT", "output": "OUTPUT_LIMIT",
                                    "partial": "STREAM_BUFFER_LIMIT"}[mode]
    stamp = heartbeat.read_text()
    time.sleep(.1)
    assert heartbeat.read_text() == stamp


@pytest.mark.parametrize("mode", ["normal", "nonzero", "signal", "timeout", "limit", "missing", "failed"])
def test_process_receipt_and_acceptance_with_local_mock_child(tmp_path, repo, mode):
    directory = tmp_path / "batch"
    directory.mkdir()
    calls = []
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is None:
            output.write_text("local mock independent gate")
            return 0
        calls.append(argv)
        payload = "" if mode == "missing" else event()
        if mode == "failed":
            payload += '{"type":"turn.failed"}\n'
        if mode == "limit":
            payload += command_event("a") + command_event("b")
        script = f"import sys,time; print({payload!r},end='',flush=True); "
        script += ("time.sleep(60)" if mode in {"timeout", "limit"} else "sys.exit(7)" if mode == "nonzero"
                   else "import os,signal; os.kill(os.getpid(),signal.SIGTERM)" if mode == "signal" else "sys.exit(0)")
        # Allow interpreter startup under suite load; limit tests must stop by count, not time.
        return run_process([sys.executable, "-c", script], cwd, output, 2 if mode == "timeout" else 10,
                           stdin=stdin, **kwargs)
    units = [unit("doc", allowed_files=["doc.md"], stream_limits={"max_commands": 1}), unit("next")]
    report = execute_batch(repo, units[:1] if mode == "normal" else units, directory, binary="MOCK",
                           token_threshold=1000, timeout=1, repairs=0, runner=runner,
                           verifier=lambda *args: dict(EXPECTED))
    row = json.loads((directory / "report.json").read_text())["attempts"][0]
    assert len(calls) == 1
    assert row["timed_out"] == (mode == "timeout")
    assert row["returncode"] == (0 if mode in {"normal", "missing", "failed"} else 7 if mode == "nonzero" else -15)
    assert row["observed_usage"] is None if mode == "missing" else row["observed_usage"]["activity_tokens"] == 110
    assert row["accounting_complete"] == (mode in {"normal", "nonzero", "signal"})
    assert bool(report["accepted"]) == (mode == "normal")
    assert row["exit_reason"] == {"normal": "NORMAL_EXIT", "nonzero": "NONZERO_EXIT", "signal": "SIGNAL_EXIT", "timeout": "TIMEOUT",
                                  "limit": "COMMAND_LIMIT", "missing": "NORMAL_EXIT", "failed": "NORMAL_EXIT"}[mode]


@pytest.mark.parametrize("failure,reason", [(OSError("spawn failed"), "PROCESS_ERROR"),
                                          (KeyboardInterrupt(), "INTERRUPTED")])
def test_start_failure_and_interrupt_persist_unknown_receipt(tmp_path, repo, failure, reason):
    def runner(*args, **kwargs):
        raise failure
    report = batch(tmp_path, repo, [unit()], runner)
    row = report["attempts"][0]
    assert row["returncode"] is None and row["exit_reason"] == reason
    assert row["observed_usage"] is None and not row["accounting_complete"]
    assert not row["timed_out"] and report["status"] == "STOPPED"


def test_legacy_missing_process_receipt_cannot_resume_gate_or_repair(tmp_path, repo):
    def interrupted_gate(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is None:
            raise KeyboardInterrupt()
        return good_runner(argv, cwd, output, timeout, stdin, **kwargs)
    first = batch(tmp_path, repo, [unit()], interrupted_gate)
    assert first["attempts"][0]["status"] == "MODEL_DONE"
    first["attempts"][0].pop("returncode")
    relay.save_json(tmp_path / "batch/report.json", first)
    def forbidden(*args, **kwargs):
        pytest.fail("No model or gate without a verified process receipt")
    report = batch(tmp_path, repo, [unit()], forbidden, resume=True)
    assert "Missing verified process receipt" in report["reason"] and not report["accepted"]


def test_pending_integration_requires_process_receipt_even_after_gates(tmp_path, repo):
    report = batch(tmp_path, repo, [unit()], good_runner)
    row = report["attempts"][0]
    report["pending_integration"] = {"unit": "scope", "before": report["base_commit"], "commit": row["commit"]}
    report["accepted"] = {}
    row.pop("returncode")
    relay.save_json(tmp_path / "batch/report.json", report)
    def forbidden(*args, **kwargs):
        pytest.fail("No new model invocation during checkpoint recovery")
    resumed = batch(tmp_path, repo, [unit()], forbidden, resume=True)
    assert resumed["status"] == "STOPPED" and not resumed["accepted"]
    assert "Integration requires verified process" in resumed["reason"]


def test_cleanup_error_still_preserves_real_exit_record(tmp_path, monkeypatch):
    cleanup = relay.stop_group
    def rejected_cleanup(child):
        cleanup(child)
        raise PermissionError("mock cleanup rejection after real cleanup")
    monkeypatch.setattr(relay, "stop_group", rejected_cleanup)
    record = {}
    with pytest.raises(PermissionError):
        run_process([sys.executable, "-c", "pass"], tmp_path, tmp_path / "out", 10, record=record)
    assert record["returncode"] == 0 and record["exit_reason"] == "CLEANUP_FAILED"
    assert record["termination_trigger"] == "NORMAL_EXIT" and "PermissionError" in record["cleanup_error"]


def test_command_is_fresh_medium_standard_sandboxed_without_policy_bypass():
    cmd = codex_command("codex", Path("/tmp/test"), policy())
    text = " ".join(cmd)
    assert "gpt-5.6-sol" in cmd and 'model_reasoning_effort="medium"' in cmd
    assert 'service_tier="default"' in cmd and "features.multi_agent=false" in cmd
    assert 'default_permissions="geo-relay"' in cmd and 'approval_policy="never"' in cmd
    assert "--sandbox" not in cmd and "sandbox-exec" not in text and "sandbox_mode=" not in text
    assert not any(x in text for x in ["resume", "--ignore", "dangerously", "priority"])


def test_codex_symlink_chain_resolves_dynamically_with_only_file_permission(tmp_path, monkeypatch):
    install = tmp_path / ".codex/packages/standalone"
    real = install / "releases/test-version/bin/codex"
    real.parent.mkdir(parents=True)
    real.write_text("offline executable fixture")
    real.chmod(0o700)
    (install / "current").symlink_to("releases/test-version", target_is_directory=True)
    link = tmp_path / "bin/codex"
    link.parent.mkdir()
    link.symlink_to(install / "current/bin/codex")
    monkeypatch.setenv("PATH", str(link.parent))
    assert relay.resolve_codex_binary("codex") == str(real)
    permissions = permission_profile(tmp_path / "repo", tmp_path / "wt", tmp_path / "batch", str(link))
    fs = permissions["filesystem"]
    assert fs[str(real)] == "read" and fs[str(Path.home() / ".codex")] == "deny"
    assert all(str(p) not in fs for p in (link, install, install / "current", real.parent, real.parent.parent))
    assert str(Path.home() / ".codex/auth.json") not in fs
    assert "project_doc_max_bytes" not in " ".join(relay.config_arguments(permissions))


@pytest.mark.parametrize("kind", ["missing", "dangling", "loop", "directory", "non_executable"])
def test_invalid_codex_binary_is_rejected(tmp_path, kind):
    binary = tmp_path / "codex"
    if kind == "dangling":
        binary.symlink_to(tmp_path / "missing")
    elif kind == "loop":
        binary.symlink_to(binary)
    elif kind == "directory":
        binary.mkdir()
    elif kind == "non_executable":
        binary.write_text("fixture")
        binary.chmod(0o600)
    with pytest.raises(ValueError):
        relay.resolve_codex_binary(str(binary))


@pytest.mark.parametrize("rc,version", [(71, ""), (0, "not the Codex CLI")])
def test_failed_codex_self_execution_stops_before_rpc(tmp_path, monkeypatch, rc, version):
    relay.save_json(tmp_path / "permissions.json", policy())
    def probe(argv, cwd, output, timeout, **kwargs):
        output.write_text(version)
        return rc
    monkeypatch.setattr(relay, "run_process", probe)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("No RPC/model after failed self probe"))
    with pytest.raises(ValueError):
        relay.preflight("MOCK_NOT_CODEX", tmp_path, tmp_path, isolated_environment(tmp_path))


def test_two_successful_units_use_fresh_calls_commits_and_leave_main_untouched(tmp_path, repo):
    calls = []
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            assert argv[1] == "exec" and "profile" not in kwargs
            assert "sandbox-exec" not in " ".join(argv) and "--sandbox" not in argv
            if calls:
                assert (cwd / "change.txt").read_text() == "1"
                integrated = subprocess.check_output(["git", "-C", str(repo), "rev-parse", INTEGRATION])
                assert subprocess.check_output(["git", "-C", str(cwd), "rev-parse", "HEAD"]) == integrated
            calls.append(argv)
            (cwd / "change.txt").write_text(str(len(calls)))
            output.write_text(event())
        else:
            assert argv[1] == "sandbox" and "--include-managed-config" in argv
            assert "profile" not in kwargs
            output.write_text("independent gate passed")
        return 0
    report = batch(tmp_path, repo, [unit("a"), unit("b")], runner)
    assert report["status"] == "BATCH_GATES_PASS_REVIEW_REQUIRED"
    assert report["codex_binary"]["resolved"] == str(Path(sys.executable).resolve())
    assert all(call[0] == report["codex_binary"]["resolved"] for call in calls)
    assert report["activity_tokens"] == 220 and len(calls) == 2
    assert report["attempts"][0]["commit"] != report["attempts"][1]["commit"]
    assert not (repo / "change.txt").exists()
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]) == head


def test_two_repairs_then_stop_and_no_next_unit(tmp_path, repo):
    calls = []
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            calls.append(stdin)
            output.write_text(event())
            return 0
        output.write_text("independent expectation failed")
        return 1
    report = batch(tmp_path, repo, [unit("a"), unit("b")], runner)
    assert report["status"] == "STOPPED" and len(calls) == 3
    assert "independent expectation failed" in calls[1]
    assert {a["unit"] for a in report["attempts"]} == {"a"}


@pytest.mark.parametrize("mode", ["budget", "usage", "timeout", "scope", "oracle", "exit"])
def test_stop_conditions_do_not_start_repairs_or_next_unit(tmp_path, repo, mode):
    calls = []
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            calls.append(stdin)
            if mode == "timeout":
                raise subprocess.TimeoutExpired(argv, timeout)
            output.write_text("" if mode == "usage" else event(2000 if mode == "budget" else 100))
            if mode in {"scope", "oracle"}:
                (cwd / ("forbidden.txt" if mode == "scope" else "oracle.txt")).write_text("changed")
            return 1 if mode == "exit" else 0
        output.write_text("gate failed")
        return 1
    report = batch(tmp_path, repo, [unit("a"), unit("b")], runner)
    assert report["status"] == "STOPPED" and len(calls) == 1
    assert (tmp_path / "batch/report.json").is_file()


def test_real_subprocess_timeout_keeps_log_and_exits(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path, tmp_path / "out", 0.05)
    assert (tmp_path / "out").exists()


def test_symlink_is_not_committed(tmp_path, repo):
    (repo / "change.txt").symlink_to(tmp_path / "outside")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    with pytest.raises(ValueError, match="Symlink"):
        guard(repo, head, ["change.txt"], {})


def policy():
    return permission_profile(Path("/mock/repo"), Path("/mock/worktree"), Path("/mock/batch"), sys.executable)


def effective_config():
    return {**EXPECTED, "features": {k: False for k in ("multi_agent", "goals", "apps", "plugins")},
            "permissions": {relay.PERMISSION_PROFILE: policy()}, "web_search": "disabled"}


def models():
    return [{"model": MODEL, "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
             "serviceTiers": [{"id": "default"}]}]


@pytest.mark.parametrize("key,value", [("model_reasoning_effort", "high"), ("service_tier", "priority"),
    ("model", "gpt-6.1-sol"), ("approval_policy", "on-request"), ("sandbox_mode", "danger-full-access"),
    ("features", {"multi_agent": True}), ("mcp_servers", {"production": {"enabled": True}}),
    ("sandbox_workspace_write", {"network_access": True})])
def test_effective_config_mismatch_blocks_execution(key, value):
    with pytest.raises(ValueError):
        validate_effective({**effective_config(), key: value}, models(), policy())


@pytest.mark.parametrize("legacy", ["read-only", "workspace-write", "danger-full-access"])
def test_legacy_mode_never_silently_overrides_permission_profile(legacy):
    with pytest.raises(ValueError, match="Legacy sandbox"):
        validate_effective({**effective_config(), "sandbox_mode": legacy}, models(), policy())


@pytest.mark.parametrize("section,key,value", [
    ("filesystem", ":root", "read"), ("network", "enabled", True),
    ("filesystem", "/unauthorized", "read"), ("workspace_roots", "/production", True),
])
def test_effective_permission_expansion_is_rejected(section, key, value):
    config = effective_config()
    config["permissions"][relay.PERMISSION_PROFILE].setdefault(section, {})[key] = value
    with pytest.raises(ValueError, match="permission profile"):
        validate_effective(config, models(), policy())


def test_cli_permission_table_roundtrip_preserves_dotted_paths_and_globs(tmp_path):
    permissions = permission_profile(tmp_path, tmp_path / 'space.and "quote"', tmp_path / "batch", sys.executable)
    args = relay.config_arguments(permissions)
    value = args[-1].split("=", 1)[1]
    assert tomllib.loads("profile=" + value)["profile"] == permissions
    assert not any("sandbox_mode=" in arg or "sandbox_workspace_write" in arg for arg in args)


def test_app_server_nullable_defaults_are_not_permission_expansions():
    config = effective_config()
    selected = config["permissions"][relay.PERMISSION_PROFILE]
    selected.update(description=None, workspace_roots=None)
    selected["filesystem"]["glob_scan_max_depth"] = None
    selected["network"].update(domains=None, allow_local_binding=None)
    assert validate_effective(config, models(), policy())["default_permissions"] == relay.PERMISSION_PROFILE


def test_gate_uses_official_profile_once_and_preserves_gate_cwd(tmp_path):
    cwd = tmp_path / "worktree/backend"
    cmd = relay.sandbox_command("codex", cwd, policy(), ["python", "-m", "pytest"])
    assert cmd[1] == "sandbox" and cmd.count("sandbox") == 1
    assert cmd[cmd.index("-C") + 1] == str(cwd)
    assert cmd[cmd.index("--") + 1:] == ["python", "-m", "pytest"]
    assert "sandbox-exec" not in cmd and "--sandbox" not in cmd


def test_config_and_catalog_must_both_validate_without_automatic_model_fallback():
    assert validate_effective(effective_config(), models(), policy())["model_reasoning_effort"] == "medium"
    with pytest.raises(ValueError):
        validate_effective(effective_config(), [], policy())


def test_standard_tier_is_not_an_optional_catalog_upgrade():
    catalog = models()
    catalog[0]["serviceTiers"] = [{"id": "priority"}]
    assert validate_effective(effective_config(), catalog, policy())["service_tier"] == "default"
    for tier in ("priority", "fast", "ultrafast", "auto"):
        with pytest.raises(ValueError, match="service_tier"):
            validate_effective({**effective_config(), "service_tier": tier}, catalog, policy())


@pytest.mark.parametrize("retarget", [False, True])
def test_controller_dependency_symlink_is_ignored_but_pinned(tmp_path, repo, retarget):
    source = repo / "geo-platform/frontend/node_modules"
    source.mkdir(parents=True)
    (source / "tool.txt").write_text("read-only shared dependency")
    (source.parent / "package.json").write_text("{}")
    (repo / ".gitignore").write_text((relay.ROOT / ".gitignore").read_text())
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore", "geo-platform/frontend/package.json"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "dependency ignore"], check=True)
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/heads/" + INTEGRATION, "HEAD"], check=True)
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            link = cwd / "geo-platform/frontend/node_modules"
            assert link.is_symlink()
            assert not relay.changes(cwd)
            if retarget:
                link.unlink()
                link.symlink_to(tmp_path)
        return good_runner(argv, cwd, output, timeout, stdin, **kwargs)
    result = batch(tmp_path, repo, [unit()], runner)
    if retarget:
        assert result["status"] == "STOPPED" and "dependency link changed" in result["reason"]
        assert not result["accepted"]
    else:
        assert result["status"] == "BATCH_GATES_PASS_REVIEW_REQUIRED"


def test_smoke_document_oracle_accepts_correct_and_rejects_wrong_example(tmp_path):
    task = json.loads((relay.ROOT / relay.LEDGER).read_text())["codex_relay"]["units"][0]
    gate = task["gates"][0]
    cwd = tmp_path / gate["cwd"]
    cwd.mkdir(parents=True)
    doc = tmp_path / task["allowed_files"][0]
    doc.parent.mkdir(parents=True)
    example = dict(input_tokens=1000, cached_input_tokens=800, output_tokens=200,
                   reasoning_output_tokens=50, activity_tokens=1200)
    for total, expected in [(1200, 0), (2050, 1)]:
        example["activity_tokens"] = total
        doc.write_text("### Token 记账示例（假设数据）\n```json\n" + json.dumps(example)
                       + "\n```\n假设不能换算套餐；用量缺失停止；30,000是软阈值，不是硬上限。\n### 下一节\n")
        result = subprocess.run([a.replace("{python}", sys.executable) for a in gate["argv"]],
                                cwd=cwd, capture_output=True)
        assert result.returncode == expected


def test_reasoning_is_not_added_to_total(tmp_path):
    payload = json.loads(event())
    payload["usage"]["reasoning_output_tokens"] = 7
    path = tmp_path / "usage"
    path.write_text(json.dumps(payload))
    assert read_usage(path)["activity_tokens"] == 110


def test_isolated_resources_drop_inherited_database_keys_and_ports(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://production/private")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-placeholder")
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", "sqlite:///production.db")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-placeholder")
    env = isolated_environment(tmp_path)
    assert env["GEO_RELEASE_DATABASE_URL"] == f"sqlite:///{tmp_path / 'scratch/test-release.db'}"
    assert env["DATABASE_URL"] == f"sqlite:///{tmp_path / 'scratch/test-legacy.db'}"
    assert env["DEEPSEEK_API_KEY"] == "" and "OPENAI_API_KEY" not in env
    assert env["BACKEND_PORT"] == "61001" and env["MONITORING_WORKER"] == "0"
    permissions = permission_profile(tmp_path / "production", tmp_path / "wt", tmp_path, sys.executable)
    assert permissions["network"] == {"enabled": False}
    assert permissions["filesystem"][":root"] == "deny"
    assert permissions["filesystem"][str(tmp_path / "scratch")] == "write"
    assert permissions["filesystem"][str(Path.home() / ".codex")] == "deny"


def test_invalid_dependency_graph_and_unordered_valid_graph():
    for rows in [(unit(depends_on=["missing"]),), (unit("a", depends_on=["b"]), unit("b", depends_on=["a"]))]:
        with pytest.raises(ValueError):
            select_units(ledger(*rows), 3)
    assert [u["id"] for u in select_units(ledger(unit("b", depends_on=["a"]), unit("a")), 3)] == ["a", "b"]


def good_runner(argv, cwd, output, timeout, stdin=None, **kwargs):
    output.write_text(event() if stdin is not None else "gate passed")
    if stdin is not None:
        (cwd / "change.txt").write_text("accepted change")
    return 0


def test_completed_checkpoint_resume_is_idempotent(tmp_path, repo):
    first = batch(tmp_path, repo, [unit()], good_runner)
    def forbidden(*args, **kwargs):
        pytest.fail("Accepted unit must not invoke a model or repeat gates")
    second = batch(tmp_path, repo, [unit()], forbidden, resume=True)
    assert first["accepted"] == second["accepted"] and second["activity_tokens"] == 110
    assert second["status"] == "BATCH_GATES_PASS_REVIEW_REQUIRED"


def test_interrupted_call_cannot_be_replayed(tmp_path, repo):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    first = batch(tmp_path, repo, [unit()], interrupted)
    assert not first["accounting_complete"]
    second = batch(tmp_path, repo, [unit()], good_runner, resume=True)
    assert "unknown usage" in second["reason"] and len(second["attempts"]) == 1


def test_resume_offline_gate_without_repeating_model(tmp_path, repo):
    def interrupted_gate(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is None:
            raise KeyboardInterrupt()
        return good_runner(argv, cwd, output, timeout, stdin, **kwargs)
    first = batch(tmp_path, repo, [unit()], interrupted_gate)
    assert first["attempts"][0]["status"] == "MODEL_DONE"
    def only_gate(argv, cwd, output, timeout, stdin=None, **kwargs):
        assert stdin is None
        output.write_text("gate passed")
        return 0
    second = batch(tmp_path, repo, [unit()], only_gate, resume=True)
    assert second["status"] == "BATCH_GATES_PASS_REVIEW_REQUIRED" and second["activity_tokens"] == 110


def test_resume_rejects_changed_task_and_stale_integration(tmp_path, repo):
    batch(tmp_path, repo, [unit()], good_runner)
    second = batch(tmp_path, repo, [unit(objective="new scope")], good_runner, resume=True)
    assert "identity changed" in second["reason"]
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/heads/" + INTEGRATION,
                    subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()], check=True)
    third = batch(tmp_path, repo, [unit()], good_runner, resume=True)
    assert "baseline moved" in third["reason"]


def test_failure_then_success_uses_bounded_fresh_repair(tmp_path, repo):
    attempts = []
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            attempts.append(stdin)
            return good_runner(argv, cwd, output, timeout, stdin, **kwargs)
        output.write_text("first gate failed" if len(attempts) == 1 else "gate passed")
        return int(len(attempts) == 1)
    result = batch(tmp_path, repo, [unit()], runner)
    assert result["status"] == "BATCH_GATES_PASS_REVIEW_REQUIRED"
    assert len(attempts) == 2 and result["activity_tokens"] == 220
    assert "first gate failed" in attempts[1]


def test_main_default_dry_run_has_no_process_or_filesystem_effect(tmp_path, monkeypatch, capsys):
    path = tmp_path / relay.LEDGER
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ledger(unit())))
    monkeypatch.setattr(relay, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["relay"])
    monkeypatch.setattr(relay, "execute_batch", lambda *a, **k: pytest.fail("dry-run executed"))
    assert relay.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["external_calls"] == 0 and result["max_sessions"] == 3
    assert not (tmp_path / "geo-platform/backend/artifacts").exists()


def test_main_refuses_dirty_worktree_before_execution(repo, monkeypatch):
    path = repo / relay.LEDGER
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ledger(unit())))
    monkeypatch.setattr(relay, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["relay", "--execute"])
    monkeypatch.setattr(relay, "execute_batch", lambda *a, **k: pytest.fail("dirty tree executed"))
    with pytest.raises(SystemExit) as result:
        relay.main()
    assert result.value.code == 2


@pytest.mark.parametrize("check_catalog", [False, True])
def test_configuration_preflight_rpc_with_local_mock_only(tmp_path, monkeypatch, check_catalog):
    def mock_version(argv, cwd, output, timeout, **kwargs):
        assert argv[-2:] == ["MOCK_NOT_CODEX", "--version"]
        output.write_text("codex-cli MOCK\n")
        return 0
    monkeypatch.setattr(relay, "run_process", mock_version)
    relay.save_json(tmp_path / "permissions.json", policy())
    script = tmp_path / "mock_app_server.py"
    script.write_text("import json, sys\n"
        + "config = " + repr(effective_config()) + "\nmodels = " + repr(models()) + "\n"
        + "for line in sys.stdin:\n"
        + "    message = json.loads(line)\n"
        + "    assert message['method'] in ('initialize','initialized','config/read','model/list')\n"
        + ("    assert message['method'] != 'model/list'\n" if not check_catalog else "")
        + "    if 'id' not in message: continue\n"
        + "    result = {'config': config} if message['method']=='config/read' else {'data': models} if message['method']=='model/list' else {}\n"
        + "    print(json.dumps({'id':message['id'], 'result':result}), flush=True)\n")
    original = subprocess.Popen
    def fake_process(argv, **kwargs):
        assert argv[1:3] == ["app-server", "--stdio"]
        assert 'service_tier="default"' in argv and 'model_reasoning_effort="medium"' in argv
        return original([sys.executable, str(script)], **kwargs)
    monkeypatch.setattr(subprocess, "Popen", fake_process)
    result = relay.preflight("MOCK_NOT_CODEX", tmp_path, tmp_path, isolated_environment(tmp_path),
                             check_catalog=check_catalog)
    assert result["model"] == MODEL and result["catalog_checked"] is check_catalog


def test_descendant_ignoring_term_is_killed_on_timeout(tmp_path):
    heartbeat = tmp_path / "heartbeat"
    descendant = ("import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                  f"p=pathlib.Path({str(heartbeat)!r});\nwhile True: p.write_text(str(time.time())); time.sleep(.01)")
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(60)"
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", parent], tmp_path, tmp_path / "group.log", 0.5)
    assert heartbeat.exists()
    stamp = heartbeat.read_text()
    time.sleep(0.1)
    assert heartbeat.read_text() == stamp


def test_recover_after_integration_cas_before_checkpoint_no_duplicate_call(tmp_path, repo, monkeypatch):
    save = relay.save_json
    def crash_after_integrating(path, value):
        if value.get("accepted"):
            raise SystemExit("simulated crash after integration CAS")
        save(path, value)
    with monkeypatch.context() as m:
        m.setattr(relay, "save_json", crash_after_integrating)
        with pytest.raises(SystemExit):
            batch(tmp_path, repo, [unit()], good_runner)
    checkpoint = json.loads((tmp_path / "batch/report.json").read_text())
    assert checkpoint["pending_integration"] and not checkpoint["accepted"]
    def no_call(*args, **kwargs):
        pytest.fail("Recovery must finish integration bookkeeping without a new model call")
    recovered = batch(tmp_path, repo, [unit()], no_call, resume=True)
    assert recovered["accepted"]["scope"] == checkpoint["pending_integration"]["commit"]
    assert recovered["activity_tokens"] == 110 and len(recovered["attempts"]) == 1


def test_retries_are_not_reset_by_resume(tmp_path, repo):
    def failed(argv, cwd, output, timeout, stdin=None, **kwargs):
        output.write_text(event() if stdin else "gate failed")
        return 0 if stdin else 1
    batch(tmp_path, repo, [unit()], failed)
    def no_call(*args, **kwargs):
        pytest.fail("Exhausted retries cannot restart on resume")
    again = batch(tmp_path, repo, [unit()], no_call, resume=True)
    assert len(again["attempts"]) == 3 and "Repair limit" in again["reason"]


def test_checked_out_integration_is_protected(tmp_path, repo):
    subprocess.run(["git", "-C", str(repo), "switch", INTEGRATION], check=True)
    result = batch(tmp_path, repo, [unit()], good_runner)
    assert "checked out" in result["reason"] and not result["attempts"]


def test_child_commit_is_not_accepted(tmp_path, repo):
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        good_runner(argv, cwd, output, timeout, stdin, **kwargs)
        subprocess.run(["git", "-C", str(cwd), "add", "."], check=True)
        subprocess.run(["git", "-C", str(cwd), "commit", "-qm", "unauthorized child commit"], check=True)
        return 0
    result = batch(tmp_path, repo, [unit()], runner)
    assert "Child changed HEAD" in result["reason"] and not result["accepted"]


def test_effective_preflight_rejection_starts_no_model(tmp_path, repo):
    directory = tmp_path / "batch"
    directory.mkdir()
    def reject(*args):
        raise ValueError("Effective config mismatch: service_tier")
    def no_call(*args, **kwargs):
        pytest.fail("Preflight rejection must not start codex exec")
    result = execute_batch(repo, [unit()], directory, binary="MOCK", token_threshold=1000, timeout=1,
                           repairs=2, runner=no_call, verifier=reject)
    assert "service_tier" in result["reason"] and not result["attempts"]


@pytest.mark.parametrize("reason", ["receipt", "lock"])
def test_controller_refuses_duplicate_batch_before_call(repo, monkeypatch, reason):
    path = repo / relay.LEDGER
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ledger(unit())))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "mock queue"], check=True)
    base = repo / "geo-platform/backend/artifacts/codex_usage"
    base.mkdir(parents=True)
    # This is a runtime directory, as it is in the actual repository.
    (repo / ".git/info/exclude").write_text("artifacts/\n")
    if reason == "receipt":
        (base / "unreviewed-batch.json").write_text('{"existing":true}')
    else:
        def locked(*args):
            raise BlockingIOError()
        monkeypatch.setattr(relay.fcntl, "flock", locked)
    monkeypatch.setattr(relay, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["relay", "--execute"])
    monkeypatch.setattr(relay, "execute_batch", lambda *a, **k: pytest.fail("duplicate execution"))
    with pytest.raises(SystemExit) as result:
        relay.main()
    assert result.value.code == 2

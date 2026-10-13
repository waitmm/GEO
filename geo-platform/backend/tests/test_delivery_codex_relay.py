import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from scripts.delivery_codex_relay import (
    EXPECTED, INTEGRATION, MODEL, codex_command, execute_batch, guard, read_usage, run_process, select_units,
    isolated_environment, validate_effective, sandbox_profile,
)
from scripts import delivery_codex_relay as relay


@pytest.fixture(autouse=True)
def mock_ports(monkeypatch):
    monkeypatch.setattr(relay, "allocate_ports", lambda: (61001, 61002))


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


def test_command_is_fresh_medium_standard_sandboxed_without_policy_bypass():
    cmd = codex_command("codex", Path("/tmp/test"))
    text = " ".join(cmd)
    assert "gpt-6.1-sol" in cmd and 'model_reasoning_effort="medium"' in cmd
    assert 'service_tier="default"' in cmd and "features.multi_agent=false" in cmd
    assert "workspace-write" in cmd and 'approval_policy="never"' in cmd
    assert not any(x in text for x in ["resume", "--ignore", "dangerously", "priority"])


def test_two_successful_units_use_fresh_calls_commits_and_leave_main_untouched(tmp_path, repo):
    calls = []
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
    def runner(argv, cwd, output, timeout, stdin=None, **kwargs):
        if stdin is not None:
            if calls:
                assert (cwd / "change.txt").read_text() == "1"
                integrated = subprocess.check_output(["git", "-C", str(repo), "rev-parse", INTEGRATION])
                assert subprocess.check_output(["git", "-C", str(cwd), "rev-parse", "HEAD"]) == integrated
            calls.append(argv)
            (cwd / "change.txt").write_text(str(len(calls)))
            output.write_text(event())
        else:
            output.write_text("independent gate passed")
        return 0
    report = batch(tmp_path, repo, [unit("a"), unit("b")], runner)
    assert report["status"] == "BATCH_GATES_PASS_REVIEW_REQUIRED"
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


def effective_config():
    return {**EXPECTED, "features": {k: False for k in ("multi_agent", "goals", "apps", "plugins")},
            "sandbox_workspace_write": {"network_access": False}, "web_search": "disabled"}


def models():
    return [{"model": MODEL, "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
             "serviceTiers": [{"id": "default"}]}]


@pytest.mark.parametrize("key,value", [("model_reasoning_effort", "high"), ("service_tier", "priority"),
    ("model", "gpt-5.6-sol"), ("approval_policy", "on-request"), ("sandbox_mode", "danger-full-access"),
    ("features", {"multi_agent": True}), ("mcp_servers", {"production": {"enabled": True}}),
    ("sandbox_workspace_write", {"network_access": True})])
def test_effective_config_mismatch_blocks_execution(key, value):
    with pytest.raises(ValueError):
        validate_effective({**effective_config(), key: value}, models())


def test_config_and_catalog_must_both_validate_without_automatic_model_fallback():
    assert validate_effective(effective_config(), models())["model_reasoning_effort"] == "medium"
    with pytest.raises(ValueError):
        validate_effective(effective_config(), [])


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
    policy = sandbox_profile(tmp_path / "production", tmp_path / "wt", tmp_path, env)
    assert '(deny network*)' in policy and '(deny file-read*' in policy
    assert "8021" not in policy and "5173" not in policy and '*:443' not in policy
    assert 'remote tcp "localhost:61001"' in policy


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


def test_configuration_preflight_rpc_with_local_mock_only(tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "run_process", lambda *a, **k: 0)
    script = tmp_path / "mock_app_server.py"
    script.write_text("import json, sys\n"
        + "config = " + repr(effective_config()) + "\nmodels = " + repr(models()) + "\n"
        + "for line in sys.stdin:\n"
        + "    message = json.loads(line)\n"
        + "    assert message['method'] in ('initialize','initialized','config/read','model/list')\n"
        + "    if 'id' not in message: continue\n"
        + "    result = {'config': config} if message['method']=='config/read' else {'data': models} if message['method']=='model/list' else {}\n"
        + "    print(json.dumps({'id':message['id'], 'result':result}), flush=True)\n")
    original = subprocess.Popen
    def fake_process(argv, **kwargs):
        assert argv[1:3] == ["app-server", "--stdio"]
        assert 'service_tier="default"' in argv and 'model_reasoning_effort="medium"' in argv
        return original([sys.executable, str(script)], **kwargs)
    monkeypatch.setattr(subprocess, "Popen", fake_process)
    assert relay.preflight("MOCK_NOT_CODEX", tmp_path, tmp_path, isolated_environment(tmp_path))["model"] == MODEL


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

import hashlib
from pathlib import Path
import subprocess
import sys

from scripts.delivery_browser_check import _copy_sqlite_artifact, _file_hashes, _joint_readonly_args


def test_joint_readonly_requires_explicit_frozen_ids(tmp_path: Path):
    database = tmp_path / "joint-release.db"
    database.write_bytes(b"isolated fixture bytes")

    args = _joint_readonly_args([
        "--joint-readonly", "--database", str(database), "--project-id", "7",
        "--t07-prompt-id", "41", "--t07-other-prompt-id", "42",
        "--t21-prompt-id", "43", "--comparison-id", "comparison-fixed-v1",
    ])

    assert args.joint_readonly is True
    assert args.database == database
    assert (args.project_id, args.t07_prompt_id, args.t07_other_prompt_id, args.t21_prompt_id) == (7, 41, 42, 43)
    assert args.comparison_id == "comparison-fixed-v1"
    assert _file_hashes(database)[str(database)] == hashlib.sha256(b"isolated fixture bytes").hexdigest()


def test_joint_readonly_copies_database_and_existing_sidecars_without_opening_source(tmp_path: Path):
    source = tmp_path / "joint-release.db"
    source.write_bytes(b"main")
    Path(f"{source}-wal").write_bytes(b"wal")
    Path(f"{source}-shm").write_bytes(b"shm")
    before = _file_hashes(source)

    copied = _copy_sqlite_artifact(source, tmp_path / "runtime-release.db")

    assert copied.read_bytes() == b"main"
    assert Path(f"{copied}-wal").read_bytes() == b"wal"
    assert Path(f"{copied}-shm").read_bytes() == b"shm"
    assert _file_hashes(source) == before


def test_joint_readonly_opens_antd_prompt_with_visible_selector():
    source = (Path(__file__).parents[1] / "scripts" / "delivery_browser_check.py").read_text()

    assert 'page.locator(".prompt-select .ant-select-selector")' in source
    assert 'expect(prompt_control).to_have_attribute("aria-expanded", "true")' in source
    assert '"monitor-switch-refresh.png"' in source
    assert '"saved-comparison-refresh.png"' in source
    assert "prompt_control.click()" not in source


def test_joint_readonly_reads_visible_antd_history_selection():
    source = (Path(__file__).parents[1] / "scripts" / "delivery_browser_check.py").read_text()

    assert 'history_control = page.get_by_role("combobox", name="历史比较", exact=True)' in source
    assert 'expect(history_selection).to_contain_text(args.comparison_id)' in source
    assert '.locator(".ant-select-selection-item")).to_contain_text(args.comparison_id)' in source
    assert 'name="历史比较", exact=True)).to_have_value' not in source


def test_direct_script_invocation_exposes_backend_scripts_package():
    backend = Path(__file__).parents[1]
    script = backend / "scripts" / "delivery_browser_check.py"
    probe = (
        "import runpy; "
        f"runpy.run_path({str(script)!r}); "
        "from scripts.release_upgrade_check import business_fingerprint; "
        "assert callable(business_fingerprint)"
    )

    completed = subprocess.run([sys.executable, "-c", probe], cwd=backend, text=True, capture_output=True)

    assert completed.returncode == 0, completed.stderr

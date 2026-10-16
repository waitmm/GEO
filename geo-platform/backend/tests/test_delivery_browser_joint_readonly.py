import hashlib
from pathlib import Path

from scripts.delivery_browser_check import _file_hashes, _joint_readonly_args


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

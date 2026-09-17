from __future__ import annotations

from pathlib import Path

import pytest

from app.permissions.policy import PermissionLevel, PermissionPolicy
from app.permissions.sandbox import PathResolutionError, PathSandbox


def test_green_yellow_red_and_workspace(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
    sandbox = PathSandbox(tmp_path)
    policy = PermissionPolicy(sandbox)

    green = policy.evaluate("read_file", {"path": "app.py"})
    assert green.level == PermissionLevel.GREEN
    assert green.allowed

    yellow = policy.evaluate("write_file", {"path": ".env", "content": "SECRET=1"})
    assert yellow.level == PermissionLevel.YELLOW
    assert yellow.requires_approval
    assert not yellow.allowed
    policy.approve(policy.fingerprint("write_file", {"path": ".env", "content": "SECRET=1"}))
    yellow2 = policy.evaluate("write_file", {"path": ".env", "content": "SECRET=1"})
    assert yellow2.allowed

    red_cmd = policy.evaluate("run_terminal", {"command": "rm -rf /"})
    assert red_cmd.level == PermissionLevel.RED
    assert not red_cmd.allowed

    with pytest.raises(PathResolutionError):
        sandbox.resolve("../outside.txt")

    money = policy.evaluate("run_terminal", {"command": "python place_order --live"})
    assert money.code == "financial_blocked"
    bypass = policy.evaluate(
        "write_file",
        {"path": "config.py", "content": "live_trading = true\nsafety_lock = false\n"},
    )
    assert bypass.level == PermissionLevel.RED

    key = policy.evaluate("read_file", {"path": "id_rsa"})
    assert key.level == PermissionLevel.RED

    wipe = policy.evaluate("delete_file", {"path": "."})
    assert red_cmd.level == PermissionLevel.RED
    assert wipe.level == PermissionLevel.RED

    # Test create_directory - should be GREEN (autonomous)
    mkdir = policy.evaluate("create_directory", {"path": "src/components"})
    assert mkdir.level == PermissionLevel.GREEN
    assert mkdir.allowed

    # Test delete_directory - should be GREEN for normal directories
    rmdir = policy.evaluate("delete_directory", {"path": "temp"})
    assert rmdir.level == PermissionLevel.GREEN
    assert rmdir.allowed

    # Test delete_directory on workspace root - should be RED
    rmdir_root = policy.evaluate("delete_directory", {"path": "."})
    assert rmdir_root.level == PermissionLevel.RED
    assert not rmdir_root.allowed

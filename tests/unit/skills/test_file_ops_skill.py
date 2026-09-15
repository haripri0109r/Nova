"""
Unit tests for FileOpsSkill.
Tests all 9 actions, parameter matrix validation, overwrite protections,
extension allowlists/blacklists, and error handling.
"""

import sys
import unittest.mock
import pytest
from pathlib import Path

from nova.skills.files.file_ops import FileOpsSkill


@pytest.fixture
def file_ops():
    return FileOpsSkill()


# ---------------------------------------------------------------------------
# Parameter Matrix Tests
# ---------------------------------------------------------------------------

def test_unknown_action_rejected(file_ops):
    res = file_ops.execute({"intent": "file_operation", "action": "wipe_hard_drive"})
    assert res["status"] == "error"
    assert "Invalid or missing action" in res["message"]


def test_unexpected_parameters_rejected(file_ops, tmp_path):
    # list_directory with forbidden source parameter
    res = file_ops.execute({
        "intent": "file_operation",
        "action": "list_directory",
        "path": str(tmp_path),
        "source": "evil",
    })
    assert res["status"] == "error"
    assert "does not accept 'source'" in res["message"]

    # delete_file with forbidden content parameter
    res = file_ops.execute({
        "intent": "file_operation",
        "action": "delete_file",
        "path": str(tmp_path / "foo.txt"),
        "content": "extra",
    })
    assert res["status"] == "error"
    assert "does not accept 'content'" in res["message"]

    # rename_file missing destination
    res = file_ops.execute({
        "intent": "file_operation",
        "action": "rename_file",
        "source": str(tmp_path / "foo.txt"),
    })
    assert res["status"] == "error"
    assert "requires 'destination'" in res["message"]


# ---------------------------------------------------------------------------
# Action Execution Tests
# ---------------------------------------------------------------------------

def test_list_directory(file_ops, tmp_path):
    f1 = tmp_path / "doc1.txt"
    f1.write_text("hello", encoding="utf-8")
    d1 = tmp_path / "sub"
    d1.mkdir()

    res = file_ops.execute({
        "intent": "file_operation",
        "action": "list_directory",
        "path": str(tmp_path),
    })
    assert res["status"] == "ok"
    assert res["count"] >= 2
    names = [e["name"] for e in res["entries"]]
    assert "doc1.txt" in names
    assert "sub" in names


def test_get_file_info(file_ops, tmp_path):
    f = tmp_path / "report.csv"
    f.write_text("a,b,c\n1,2,3", encoding="utf-8")

    res = file_ops.execute({
        "intent": "file_operation",
        "action": "get_file_info",
        "path": str(f),
    })
    assert res["status"] == "ok"
    assert res["name"] == "report.csv"
    assert res["is_file"] is True
    assert res["extension"] == ".csv"
    assert res["size"] > 0


def test_open_file_security(file_ops, tmp_path):
    # Allowed extension (.pdf)
    safe_file = tmp_path / "paper.pdf"
    safe_file.write_text("%PDF-1.4", encoding="utf-8")

    with unittest.mock.patch("os.startfile", create=True) as mock_startfile:
        res = file_ops.execute({
            "intent": "file_operation",
            "action": "open_file",
            "path": str(safe_file),
        })
        assert res["status"] == "ok"
        if sys.platform == "win32":
            mock_startfile.assert_called_once()

    # Forbidden executable (.exe)
    danger_file = tmp_path / "virus.exe"
    danger_file.write_text("MZ...", encoding="utf-8")
    res_danger = file_ops.execute({
        "intent": "file_operation",
        "action": "open_file",
        "path": str(danger_file),
    })
    assert res_danger["status"] == "error"
    assert "Forbidden file type" in res_danger["message"]


def test_create_folder(file_ops, tmp_path):
    new_dir = tmp_path / "new_project"
    res = file_ops.execute({
        "intent": "file_operation",
        "action": "create_folder",
        "path": str(new_dir),
    })
    assert res["status"] == "ok"
    assert new_dir.is_dir()

    # Conflict fails safely
    res_conflict = file_ops.execute({
        "intent": "file_operation",
        "action": "create_folder",
        "path": str(new_dir),
    })
    assert res_conflict["status"] == "error"
    assert "already exists" in res_conflict["message"]


def test_create_file_and_overwrite_prevention(file_ops, tmp_path):
    target = tmp_path / "notes.txt"
    res = file_ops.execute({
        "intent": "file_operation",
        "action": "create_file",
        "path": str(target),
        "content": "Nova file test",
    })
    assert res["status"] == "ok"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "Nova file test"

    # Invariant: V1 overwrite is ALWAYS false
    res_overwrite = file_ops.execute({
        "intent": "file_operation",
        "action": "create_file",
        "path": str(target),
        "content": "Overwriting content",
    })
    assert res_overwrite["status"] == "error"
    assert "already exists" in res_overwrite["message"]
    assert target.read_text(encoding="utf-8") == "Nova file test"


def test_rename_file(file_ops, tmp_path):
    src = tmp_path / "initial.txt"
    dst = tmp_path / "renamed.txt"
    src.write_text("Initial text", encoding="utf-8")

    res = file_ops.execute({
        "intent": "file_operation",
        "action": "rename_file",
        "source": str(src),
        "destination": str(dst),
    })
    assert res["status"] == "ok"
    assert not src.exists()
    assert dst.is_file()
    assert dst.read_text(encoding="utf-8") == "Initial text"

    # If destination exists, rename must fail
    another = tmp_path / "another.txt"
    another.write_text("another", encoding="utf-8")
    res_fail = file_ops.execute({
        "intent": "file_operation",
        "action": "rename_file",
        "source": str(another),
        "destination": str(dst),
    })
    assert res_fail["status"] == "error"
    assert "already exists" in res_fail["message"]


def test_copy_file(file_ops, tmp_path):
    src = tmp_path / "source.txt"
    dst = tmp_path / "copy.txt"
    src.write_text("Copy me", encoding="utf-8")

    res = file_ops.execute({
        "intent": "file_operation",
        "action": "copy_file",
        "source": str(src),
        "destination": str(dst),
    })
    assert res["status"] == "ok"
    assert src.exists()
    assert dst.exists()

    # Destination conflict fails
    res_conflict = file_ops.execute({
        "intent": "file_operation",
        "action": "copy_file",
        "source": str(src),
        "destination": str(dst),
    })
    assert res_conflict["status"] == "error"
    assert "already exists" in res_conflict["message"]


def test_move_file(file_ops, tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    src = tmp_path / "to_move.txt"
    dst = sub / "moved.txt"
    src.write_text("Move me", encoding="utf-8")

    res = file_ops.execute({
        "intent": "file_operation",
        "action": "move_file",
        "source": str(src),
        "destination": str(dst),
    })
    assert res["status"] == "ok"
    assert not src.exists()
    assert dst.is_file()


def test_delete_file_safety(file_ops, tmp_path):
    target = tmp_path / "delete_me.txt"
    target.write_text("Delete me", encoding="utf-8")

    res = file_ops.execute({
        "intent": "file_operation",
        "action": "delete_file",
        "path": str(target),
    })
    assert res["status"] == "ok"
    assert not target.exists()

    # Refuse to delete directory
    sub = tmp_path / "folder"
    sub.mkdir()
    res_dir = file_ops.execute({
        "intent": "file_operation",
        "action": "delete_file",
        "path": str(sub),
    })
    assert res_dir["status"] == "error"
    assert "Refusing to delete directory" in res_dir["message"]
    assert sub.exists()

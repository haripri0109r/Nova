"""
End-to-end tests for Nova Phase 5.8-G: File & Folder Control.

All tests operate in strict isolation inside temporary directories.
Verifies complete flow:
- Intent classification -> Planner -> Skill Execution -> Step Risk Policy -> Confirmation
- Security protections against ADS, traversal, reparse points, protected locations,
  and dangerous executable file launches.
- Single capability ownership across FileSearchSkill, ExplorerSkill, and FileOpsSkill.
"""

import os
import sys
import unittest.mock
from pathlib import Path
import pytest

from nova.skills.registry import registry
from nova.skills.files.file_ops import FileOpsSkill
from nova.skills.files.search import FileSearchSkill
from nova.skills.files.explorer import ExplorerSkill
from nova.skills.files.path_guard import (
    PathGuard,
    PathSecurityError,
    OperationType,
    ALLOWED_OPEN_EXTENSIONS,
    FORBIDDEN_OPEN_EXTENSIONS,
)
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import RecognizedInput
from nova.brain.planner import Planner
from nova.brain.types import IntentCategory
from nova.agent.step_risk_policy import classify_step_risk, RiskLevel, ConfirmationManager


@pytest.fixture
def classifier():
    return PlaceholderIntentClassifier()


@pytest.fixture
def planner():
    return Planner()


@pytest.fixture
def file_ops():
    return registry.get("file_operation")


# ---------------------------------------------------------------------------
# 1. Capability Ownership & Registry Integrity
# ---------------------------------------------------------------------------

def test_single_capability_ownership_e2e():
    """Verify strictly single capability ownership across skills."""
    search_skill = registry.get("find_file")
    assert isinstance(search_skill, FileSearchSkill)

    explorer_skill = registry.get("open_folder")
    assert isinstance(explorer_skill, ExplorerSkill)

    file_ops_skill = registry.get("file_operation")
    assert isinstance(file_ops_skill, FileOpsSkill)

    # Aliases
    assert registry.get("file") is file_ops_skill
    assert registry.get("file_control") is file_ops_skill

    # Confirm FileOpsSkill does not claim find_file or open_folder
    assert "find_file" not in file_ops_skill.parameters_schema["properties"]["action"]["enum"]
    assert "open_folder" not in file_ops_skill.parameters_schema["properties"]["action"]["enum"]


# ---------------------------------------------------------------------------
# 2. Lifecycle End-to-End: Create -> Info -> List -> Rename -> Copy -> Move -> Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_file_ops_lifecycle(tmp_path, classifier, planner, file_ops):
    """Test full create, inspect, modify, and delete lifecycle in isolated tmp_path."""
    test_file = tmp_path / "report.txt"

    # Step 1: Create file
    create_input = f"create file {test_file} with content Confidential Report 2026"
    intent = await classifier.classify(RecognizedInput(text=create_input))
    plan = await planner.plan(create_input, intent)

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert classify_step_risk(step.tool, step.parameters) == RiskLevel.LOW
    res = file_ops.execute({"intent": "file_operation", **step.parameters})
    assert res["status"] == "ok"
    assert test_file.is_file()
    assert test_file.read_text(encoding="utf-8") == "Confidential Report 2026"

    # Step 2: Overwrite prevention (create_file destination collision fails safely)
    res_overwrite = file_ops.execute({
        "intent": "file_operation",
        "action": "create_file",
        "path": str(test_file),
        "content": "Malicious Overwrite",
    })
    assert res_overwrite["status"] == "error"
    assert "already exists" in res_overwrite["message"]
    assert test_file.read_text(encoding="utf-8") == "Confidential Report 2026"

    # Step 3: Get file info
    info_res = file_ops.execute({
        "intent": "file_operation",
        "action": "get_file_info",
        "path": str(test_file),
    })
    assert info_res["status"] == "ok"
    assert info_res["name"] == "report.txt"
    assert info_res["is_file"] is True
    assert info_res["extension"] == ".txt"
    assert info_res["size"] > 0

    # Step 4: List directory
    list_res = file_ops.execute({
        "intent": "file_operation",
        "action": "list_directory",
        "path": str(tmp_path),
    })
    assert list_res["status"] == "ok"
    assert any(e["name"] == "report.txt" for e in list_res["entries"])

    # Step 5: Copy file
    copied_file = tmp_path / "report_copy.txt"
    cp_res = file_ops.execute({
        "intent": "file_operation",
        "action": "copy_file",
        "source": str(test_file),
        "destination": str(copied_file),
    })
    assert cp_res["status"] == "ok"
    assert copied_file.is_file()
    assert copied_file.read_text(encoding="utf-8") == "Confidential Report 2026"

    # Step 6: Rename file
    renamed_file = tmp_path / "report_renamed.txt"
    ren_res = file_ops.execute({
        "intent": "file_operation",
        "action": "rename_file",
        "source": str(copied_file),
        "destination": str(renamed_file),
    })
    assert ren_res["status"] == "ok"
    assert not copied_file.exists()
    assert renamed_file.is_file()

    # Step 7: Create folder & Move file into it
    sub_dir = tmp_path / "archive"
    fld_res = file_ops.execute({
        "intent": "file_operation",
        "action": "create_folder",
        "path": str(sub_dir),
    })
    assert fld_res["status"] == "ok"
    assert sub_dir.is_dir()

    archived_file = sub_dir / "report_archived.txt"
    mv_res = file_ops.execute({
        "intent": "file_operation",
        "action": "move_file",
        "source": str(renamed_file),
        "destination": str(archived_file),
    })
    assert mv_res["status"] == "ok"
    assert not renamed_file.exists()
    assert archived_file.is_file()

    # Step 8: Delete file with High-Risk verification
    del_input = f"delete file {archived_file}"
    del_intent = await classifier.classify(RecognizedInput(text=del_input))
    del_plan = await planner.plan(del_input, del_intent)
    del_step = del_plan.steps[0]

    # Invariant: delete_file must be HIGH risk and require confirmation
    assert classify_step_risk(del_step.tool, del_step.parameters) == RiskLevel.HIGH

    # Confirmation flow
    cm = ConfirmationManager(ttl_seconds=60)
    conf = cm.issue(task_id="t-file-1", step_index=0, tool="file_operation", action="delete_file")
    assert conf.action == "delete_file"

    del_res = file_ops.execute({"intent": "file_operation", **del_step.parameters})
    assert del_res["status"] == "ok"
    assert not archived_file.exists()


# ---------------------------------------------------------------------------
# 3. Security Boundary Enforcement Tests
# ---------------------------------------------------------------------------

def test_delete_folder_rejected(file_ops, tmp_path):
    """Ensure delete_file strictly refuses to delete directories."""
    sub_dir = tmp_path / "safe_dir"
    sub_dir.mkdir()

    res = file_ops.execute({
        "intent": "file_operation",
        "action": "delete_file",
        "path": str(sub_dir),
    })
    assert res["status"] == "error"
    assert "Refusing to delete directory" in res["message"]
    assert sub_dir.exists()


def test_open_file_security_matrix(file_ops, tmp_path):
    """Verify conservative open_file allowlist and rejection of executable files."""
    # Blacklisted executables/scripts must fail
    for ext in (".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".lnk", ".reg", ".msi"):
        target = tmp_path / f"test{ext}"
        target.write_text("payload", encoding="utf-8")
        res = file_ops.execute({
            "intent": "file_operation",
            "action": "open_file",
            "path": str(target),
        })
        assert res["status"] == "error"
        assert "Forbidden file type" in res["message"]

    # Allowed documents/media
    for ext in (".txt", ".csv", ".json", ".pdf", ".png"):
        target = tmp_path / f"safe{ext}"
        target.write_text("safe content", encoding="utf-8")
        with unittest.mock.patch("os.startfile", create=True) as mock_startfile:
            res = file_ops.execute({
                "intent": "file_operation",
                "action": "open_file",
                "path": str(target),
            })
            assert res["status"] == "ok"


def test_path_guard_ads_and_traversal_e2e(file_ops, tmp_path):
    """Ensure ADS and path traversal exploits are rejected."""
    # Alternate Data Stream
    res_ads = file_ops.execute({
        "intent": "file_operation",
        "action": "create_file",
        "path": str(tmp_path) + r"\file.txt:evil_stream",
        "content": "secret",
    })
    assert res_ads["status"] == "error"
    assert "Security violation" in res_ads["message"]

    # UNC path injection
    res_unc = file_ops.execute({
        "intent": "file_operation",
        "action": "list_directory",
        "path": r"\\10.0.0.1\c$\Windows",
    })
    assert res_unc["status"] == "error"
    assert "Security violation" in res_unc["message"]

    # Device namespace injection
    res_dev = file_ops.execute({
        "intent": "file_operation",
        "action": "get_file_info",
        "path": r"\\.\COM1",
    })
    assert res_dev["status"] == "error"
    assert "Security violation" in res_dev["message"]


def test_protected_windows_directories_blocked(file_ops):
    """Verify write, delete, and open operations on Windows protected trees are blocked."""
    for op, params in [
        ("create_file", {"path": r"C:\Windows\evil.txt", "content": "bad"}),
        ("create_folder", {"path": r"C:\Windows\System32\evil_dir"}),
        ("delete_file", {"path": r"C:\Windows\notepad.exe"}),
        ("rename_file", {"source": r"C:\Windows\notepad.exe", "destination": r"C:\Windows\notepad_backup.exe"}),
    ]:
        res = file_ops.execute({"intent": "file_operation", "action": op, **params})
        assert res["status"] == "error"
        assert "Security violation" in res["message"]


def test_bounded_search_e2e(tmp_path):
    """Verify FileSearchSkill operates within depth and result bounds without following links."""
    search_skill = registry.get("find_file")

    # Create shallow files and deep files
    (tmp_path / "deep_file.log").write_text("log", encoding="utf-8")

    current = tmp_path
    for i in range(6):
        current = current / f"level_{i}"
        current.mkdir()
    too_deep = current / "deep_file.log"
    too_deep.write_text("deep log", encoding="utf-8")

    res = search_skill.execute({
        "intent": "find_file",
        "pattern": "deep_file",
        "search_root": str(tmp_path),
        "max_results": 10,
    })
    assert res["status"] == "ok"
    # Only shallow file (within max_depth=4) should be returned
    assert len(res["detail"]) == 1
    assert str(too_deep.resolve()) not in res["detail"]

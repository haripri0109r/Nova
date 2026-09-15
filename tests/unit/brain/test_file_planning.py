"""
Unit tests for File & Folder Control planning and intent classification.
Verifies intent classification, deterministic planning, single capability ownership,
and step risk policy integration.
"""

import pytest
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import RecognizedInput
from nova.brain.planner import Planner
from nova.brain.types import IntentCategory
from nova.agent.step_risk_policy import classify_step_risk, RiskLevel
from nova.skills.registry import registry
from nova.skills.files.file_ops import FileOpsSkill
from nova.skills.files.search import FileSearchSkill
from nova.skills.files.explorer import ExplorerSkill


@pytest.fixture
def classifier():
    clf = PlaceholderIntentClassifier()
    return clf


@pytest.fixture
def planner():
    return Planner()


# ---------------------------------------------------------------------------
# Single Capability Ownership & Registry Tests
# ---------------------------------------------------------------------------

def test_single_capability_ownership():
    # find_file -> FileSearchSkill
    search_skill = registry.get("find_file")
    assert isinstance(search_skill, FileSearchSkill)

    # open_folder -> ExplorerSkill
    explorer_skill = registry.get("open_folder")
    assert isinstance(explorer_skill, ExplorerSkill)

    # file_operation -> FileOpsSkill
    ops_skill = registry.get("file_operation")
    assert isinstance(ops_skill, FileOpsSkill)

    # Aliases
    assert isinstance(registry.get("file"), FileOpsSkill)
    assert isinstance(registry.get("file_control"), FileOpsSkill)


# ---------------------------------------------------------------------------
# Intent Classification Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intent_file_operations(classifier):
    # 1. list_directory
    res_list = await classifier.classify(RecognizedInput(text="list files in C:\\projects"))
    assert res_list.category == IntentCategory.FILE_OPERATION
    assert res_list.entities.get("action") == "list_directory"
    assert "c:\\projects" in res_list.entities.get("path", "")

    # 2. get_file_info
    res_info = await classifier.classify(RecognizedInput(text="file details for report.pdf"))
    assert res_info.category == IntentCategory.FILE_OPERATION
    assert res_info.entities.get("action") == "get_file_info"
    assert res_info.entities.get("path") == "report.pdf"

    # 3. open_file
    res_open = await classifier.classify(RecognizedInput(text="open file notes.txt"))
    assert res_open.category == IntentCategory.FILE_OPERATION
    assert res_open.entities.get("action") == "open_file"
    assert res_open.entities.get("path") == "notes.txt"

    # 4. create_folder
    res_cfol = await classifier.classify(RecognizedInput(text="create folder test_dir"))
    assert res_cfol.category == IntentCategory.FILE_OPERATION
    assert res_cfol.entities.get("action") == "create_folder"
    assert res_cfol.entities.get("path") == "test_dir"

    # 5. create_file
    res_cfile = await classifier.classify(RecognizedInput(text="create file notes.txt with content Hello World"))
    assert res_cfile.category == IntentCategory.FILE_OPERATION
    assert res_cfile.entities.get("action") == "create_file"
    assert res_cfile.entities.get("path") == "notes.txt"
    assert res_cfile.entities.get("content") == "Hello World"

    # 6. rename_file
    res_ren = await classifier.classify(RecognizedInput(text="rename file old.txt to new.txt"))
    assert res_ren.category == IntentCategory.FILE_OPERATION
    assert res_ren.entities.get("action") == "rename_file"
    assert res_ren.entities.get("source") == "old.txt"
    assert res_ren.entities.get("destination") == "new.txt"

    # 7. copy_file
    res_cp = await classifier.classify(RecognizedInput(text="copy file doc.txt to backup.txt"))
    assert res_cp.category == IntentCategory.FILE_OPERATION
    assert res_cp.entities.get("action") == "copy_file"
    assert res_cp.entities.get("source") == "doc.txt"
    assert res_cp.entities.get("destination") == "backup.txt"

    # 8. move_file
    res_mv = await classifier.classify(RecognizedInput(text="move file a.txt to b.txt"))
    assert res_mv.category == IntentCategory.FILE_OPERATION
    assert res_mv.entities.get("action") == "move_file"
    assert res_mv.entities.get("source") == "a.txt"
    assert res_mv.entities.get("destination") == "b.txt"

    # 9. delete_file
    res_del = await classifier.classify(RecognizedInput(text="delete file obsolete.txt"))
    assert res_del.category == IntentCategory.FILE_OPERATION
    assert res_del.entities.get("action") == "delete_file"
    assert res_del.entities.get("path") == "obsolete.txt"


@pytest.mark.asyncio
async def test_intent_isolation_from_find_file_and_app_launch(classifier):
    # find_file must remain FIND_FILE
    res_find = await classifier.classify(RecognizedInput(text="find resume.pdf"))
    assert res_find.category == IntentCategory.FIND_FILE

    # open application must remain OPEN_APPLICATION
    res_app = await classifier.classify(RecognizedInput(text="open notepad"))
    assert res_app.category == IntentCategory.OPEN_APPLICATION


# ---------------------------------------------------------------------------
# Planner Fast-Path Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_planner_file_operations_fast_path(classifier, planner):
    # Test create_file plan
    inp = RecognizedInput(text="create file my_notes.txt with content Important Note")
    intent = await classifier.classify(inp)
    plan = await planner.plan(inp.text, intent)

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.tool == "file_operation"
    assert step.parameters.get("action") == "create_file"
    assert step.parameters.get("path") == "my_notes.txt"
    assert step.parameters.get("content") == "Important Note"
    assert step.depends_on == []


@pytest.mark.asyncio
async def test_planner_delete_file_fast_path(classifier, planner):
    inp = RecognizedInput(text="delete file temp.log")
    intent = await classifier.classify(inp)
    plan = await planner.plan(inp.text, intent)

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.tool == "file_operation"
    assert step.parameters.get("action") == "delete_file"
    assert step.parameters.get("path") == "temp.log"


# ---------------------------------------------------------------------------
# Step Risk Policy Tests
# ---------------------------------------------------------------------------

def test_step_risk_policy_file_operations():
    # delete_file must be HIGH risk
    assert classify_step_risk("file_operation", {"action": "delete_file", "path": "file.txt"}) == RiskLevel.HIGH
    assert classify_step_risk("file", {"action": "delete_file", "path": "file.txt"}) == RiskLevel.HIGH
    assert classify_step_risk("file_control", {"action": "delete_file", "path": "file.txt"}) == RiskLevel.HIGH

    # Non-destructive actions must be LOW risk
    for action in (
        "list_directory", "get_file_info", "open_file",
        "create_folder", "create_file", "rename_file", "copy_file", "move_file"
    ):
        assert classify_step_risk("file_operation", {"action": action, "path": "file.txt"}) == RiskLevel.LOW

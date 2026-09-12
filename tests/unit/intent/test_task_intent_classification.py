"""
Unit tests for Task Command Intent Classification and Entity Extraction.
Phase 5.3A foundation.
"""
import pytest
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import RecognizedInput
from nova.brain.types import IntentCategory
from nova.agent.models import TaskAction, TaskCommand, TaskStatus


@pytest.fixture
def classifier():
    return PlaceholderIntentClassifier()


@pytest.mark.asyncio
async def test_task_control_pause(classifier):
    """Test pause task variations map to TASK_CONTROL and PAUSE."""
    variations = [
        ("pause", None),
        ("pause task", None),
        ("pause my task", None),
        ("pause the task", None),
        ("pause current task", None),
        ("pause task 491c", "491c"),
        ("pause task #491c", "491c"),
        ("pause task: 491c", "491c"),
        ("pause 491c", "491c"),
    ]
    for text, expected_id in variations:
        res = await classifier.classify(RecognizedInput(text=text))
        assert res.category == IntentCategory.TASK_CONTROL, f"Failed on: {text}"
        assert res.entities.get("action") == TaskAction.PAUSE.value
        assert res.entities.get("task_id") == expected_id
        cmd = TaskCommand.from_entities(res.entities)
        assert cmd.action == TaskAction.PAUSE
        assert cmd.task_id == expected_id


@pytest.mark.asyncio
async def test_task_control_resume(classifier):
    """Test resume task variations map to TASK_CONTROL and RESUME."""
    variations = [
        ("resume", None),
        ("resume task", None),
        ("continue task", None),
        ("resume my task", None),
        ("resume task 491c", "491c"),
        ("continue task 491c", "491c"),
        ("resume task abc123", "abc123"),
        ("resume abc123", "abc123"),
    ]
    for text, expected_id in variations:
        res = await classifier.classify(RecognizedInput(text=text))
        assert res.category == IntentCategory.TASK_CONTROL, f"Failed on: {text}"
        assert res.entities.get("action") == TaskAction.RESUME.value
        assert res.entities.get("task_id") == expected_id
        cmd = TaskCommand.from_entities(res.entities)
        assert cmd.action == TaskAction.RESUME
        assert cmd.task_id == expected_id


@pytest.mark.asyncio
async def test_task_control_cancel(classifier):
    """Test cancel task variations map to TASK_CONTROL and CANCEL."""
    variations = [
        ("cancel", None),
        ("cancel task", None),
        ("cancel my task", None),
        ("stop task", None),
        ("abort task", None),
        ("cancel task 491c", "491c"),
        ("stop task 491c", "491c"),
        ("abort task 491c", "491c"),
    ]
    for text, expected_id in variations:
        res = await classifier.classify(RecognizedInput(text=text))
        assert res.category == IntentCategory.TASK_CONTROL, f"Failed on: {text}"
        assert res.entities.get("action") == TaskAction.CANCEL.value
        assert res.entities.get("task_id") == expected_id
        cmd = TaskCommand.from_entities(res.entities)
        assert cmd.action == TaskAction.CANCEL
        assert cmd.task_id == expected_id


@pytest.mark.asyncio
async def test_task_control_retry_step(classifier):
    """Test retry step variations map to TASK_CONTROL and RETRY_STEP."""
    variations = [
        ("retry step", None, None),
        ("retry that step", None, None),
        ("retry the step", None, None),
        ("retry step 2", 2, None),
        ("retry step #2", 2, None),
        ("redo step 3", 3, None),
        ("retry step 2 for task 491c", 2, "491c"),
    ]
    for text, expected_idx, expected_id in variations:
        res = await classifier.classify(RecognizedInput(text=text))
        assert res.category == IntentCategory.TASK_CONTROL, f"Failed on: {text}"
        assert res.entities.get("action") == TaskAction.RETRY_STEP.value
        assert res.entities.get("step_index") == expected_idx
        assert res.entities.get("task_id") == expected_id
        cmd = TaskCommand.from_entities(res.entities)
        assert cmd.action == TaskAction.RETRY_STEP
        assert cmd.step_index == expected_idx
        assert cmd.task_id == expected_id


@pytest.mark.asyncio
async def test_task_control_skip_step(classifier):
    """Test skip step variations map to TASK_CONTROL and SKIP_STEP."""
    variations = [
        ("skip step", None, None),
        ("skip that step", None, None),
        ("skip the step", None, None),
        ("skip step 2", 2, None),
        ("skip step #3", 3, None),
        ("skip step 4 for task 491c", 4, "491c"),
    ]
    for text, expected_idx, expected_id in variations:
        res = await classifier.classify(RecognizedInput(text=text))
        assert res.category == IntentCategory.TASK_CONTROL, f"Failed on: {text}"
        assert res.entities.get("action") == TaskAction.SKIP_STEP.value
        assert res.entities.get("step_index") == expected_idx
        assert res.entities.get("task_id") == expected_id
        cmd = TaskCommand.from_entities(res.entities)
        assert cmd.action == TaskAction.SKIP_STEP
        assert cmd.step_index == expected_idx
        assert cmd.task_id == expected_id


@pytest.mark.asyncio
async def test_task_query_status(classifier):
    """Test task status queries map to TASK_QUERY and STATUS."""
    variations = [
        ("task status", None),
        ("what is my task doing?", None),
        ("how is my task going?", None),
        ("how is the task progressing?", None),
        ("status of task 491c", "491c"),
        ("status of the task 491c", "491c"),
        ("status of task", None),
        ("what is task 491c doing?", "491c"),
        ("status 491c", "491c"),
    ]
    for text, expected_id in variations:
        res = await classifier.classify(RecognizedInput(text=text))
        assert res.category == IntentCategory.TASK_QUERY, f"Failed on: {text}"
        assert res.entities.get("action") == TaskAction.STATUS.value
        assert res.entities.get("task_id") == expected_id
        cmd = TaskCommand.from_entities(res.entities)
        assert cmd.action == TaskAction.STATUS
        assert cmd.task_id == expected_id


@pytest.mark.asyncio
async def test_task_query_list(classifier):
    """Test task list queries map to TASK_QUERY and LIST."""
    variations = [
        ("list tasks", None),
        ("show tasks", None),
        ("show running tasks", TaskStatus.RUNNING),
        ("what tasks are running?", TaskStatus.RUNNING),
        ("show paused tasks", TaskStatus.PAUSED),
        ("list running tasks", TaskStatus.RUNNING),
        ("list all tasks", None),
        ("tasks list", None),
    ]
    for text, expected_status in variations:
        res = await classifier.classify(RecognizedInput(text=text))
        assert res.category == IntentCategory.TASK_QUERY, f"Failed on: {text}"
        assert res.entities.get("action") == TaskAction.LIST.value
        if expected_status:
            assert res.entities.get("filter_status") == expected_status.value
        cmd = TaskCommand.from_entities(res.entities)
        assert cmd.action == TaskAction.LIST
        assert cmd.filter_status == expected_status


@pytest.mark.asyncio
async def test_conservative_conversational_rejection(classifier):
    """
    Ensure vague conversational phrases are NOT mapped to mutating task commands.
    Must NOT become PAUSE / CANCEL / RESUME.
    """
    phrases = [
        "wait a second",
        "hold on",
        "one moment",
        "give me a second",
        "pause video",
        "stop listening",
        "continue talking",
        "tell me a joke",
        "hello there",
    ]
    for phrase in phrases:
        res = await classifier.classify(RecognizedInput(text=phrase))
        assert res.category != IntentCategory.TASK_CONTROL, f"Phrase incorrectly classified as TASK_CONTROL: {phrase}"
        if "action" in res.entities:
            assert res.entities["action"] not in (
                TaskAction.PAUSE.value,
                TaskAction.CANCEL.value,
                TaskAction.RESUME.value,
                TaskAction.RETRY_STEP.value,
                TaskAction.SKIP_STEP.value,
            ), f"Phrase gave task action: {phrase} -> {res.entities['action']}"

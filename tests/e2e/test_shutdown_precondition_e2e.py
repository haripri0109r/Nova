"""
Real Windows End-to-End Test for Nova Shutdown Precondition Workflow.

Exercises the real native Windows execution flow:
1. Launch real native Notepad process (notepad.exe).
2. Wait for its real top-level window to appear on the desktop.
3. Call check_shutdown_precondition():
   - Verify ready == False
   - Verify "Notepad" is present in open_applications.
4. Process user command via BrainEngine: "Shutdown my laptop".
   - Verify Nova blocks shutdown and response mentions Notepad.
   - Verify pending shutdown workflow is created.
5. Process user command: "Done".
   - Verify Notepad is STILL detected.
   - Verify shutdown is STILL blocked.
6. Gracefully close Notepad via WM_CLOSE (no p.terminate, no taskkill, no force kill).
7. Poll check_shutdown_precondition() until Notepad disappears.
8. Process user continuation command: "Done, shutdown".
   - Verify second check succeeds.
   - Verify Nova reaches existing HIGH-RISK shutdown confirmation state.
9. Verify actual Windows shutdown command was NOT executed.
10. Guaranteed cleanup in try/finally.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import subprocess
import sys
import time
from unittest.mock import patch
import pytest

from nova.agent.orchestrator import get_agent_orchestrator
from nova.brain.engine import BrainEngine
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import BrainResponse
from nova.brain.shutdown_workflow import get_shutdown_workflow_manager
from nova.skills.system.app_detector import (
    check_shutdown_precondition,
    get_open_user_applications,
)
from nova.skills.system.shutdown import ShutdownSkill


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
@pytest.mark.asyncio
async def test_real_windows_shutdown_precondition_workflow():
    """Real Windows E2E test for the shutdown precondition workflow."""
    u32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    proc: Optional[subprocess.Popen] = None
    session_id = "e2e_shutdown_session"

    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.clear_all()

    # Safety guardrail: ensure ShutdownSkill.execute is NEVER called
    with patch.object(ShutdownSkill, "execute") as mock_shutdown_skill:
        try:
            # 1. Start real native notepad.exe
            proc = subprocess.Popen(["notepad.exe"])

            # 2. Wait until its real top-level window exists (up to 5s)
            notepad_found = False
            for _ in range(25):
                await asyncio.sleep(0.2)
                apps = get_open_user_applications()
                if any("notepad" in a["process"].lower() for a in apps):
                    notepad_found = True
                    break

            assert notepad_found, "Real Notepad window was not detected after launching."

            # 3. Inspect precondition directly
            precond = check_shutdown_precondition()
            assert precond["ready"] is False, f"Expected ready=False with Notepad open, got {precond}"
            assert "Notepad" in precond["open_applications"], f"Expected 'Notepad' in open apps: {precond['open_applications']}"

            # 4. Initialize real BrainEngine
            engine = BrainEngine()
            engine._intent_classifier = PlaceholderIntentClassifier()
            await engine.initialize()

            # Process "Shutdown my laptop"
            resp1: BrainResponse = await engine.process_text("Shutdown my laptop", session_id=session_id)
            assert "Notepad" in resp1.response_text
            assert "still open" in resp1.response_text
            assert wf_mgr.is_pending(session_id) is True

            # 5. User says "Done" while Notepad is STILL running
            resp2: BrainResponse = await engine.process_text("Done", session_id=session_id)
            assert "Notepad is still open" in resp2.response_text
            assert "before I shut down" in resp2.response_text
            assert wf_mgr.is_pending(session_id) is True

            # 6. Gracefully close Notepad using WM_CLOSE
            # IMPORTANT: NO p.terminate(), NO taskkill, NO force killing.
            apps_before_close = get_open_user_applications()
            notepad_hwnds = [a["hwnd"] for a in apps_before_close if "notepad" in a["process"].lower()]
            assert len(notepad_hwnds) >= 1, "Expected at least one Notepad window HWND"

            for hwnd in notepad_hwnds:
                u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

            # 7. Poll until Notepad disappears from application detection
            notepad_closed = False
            for _ in range(25):
                await asyncio.sleep(0.2)
                current_apps = get_open_user_applications()
                if not any("notepad" in a["process"].lower() for a in current_apps):
                    notepad_closed = True
                    break

            assert notepad_closed, "Notepad failed to close gracefully via WM_CLOSE."

            # 8. Check for any other background user apps that might be open on the test machine
            # (e.g. developer's Chrome or WhatsApp). If there are, isolate the second check
            # to verify that with all user apps closed, Nova proceeds to confirmation.
            remaining_precond = check_shutdown_precondition()
            is_clean_desktop = remaining_precond["ready"]

            if is_clean_desktop:
                # Completely clean environment: run directly on real Windows state
                resp3: BrainResponse = await engine.process_text("Done, shutdown", session_id=session_id)
            else:
                # If the developer has personal apps open (e.g. Chrome/IDE), simulate
                # the moment the user has finished closing all apps:
                with patch("nova.skills.system.app_detector.check_shutdown_precondition", return_value={"ready": True, "open_applications": [], "windows": []}):
                    resp3 = await engine.process_text("Done, shutdown", session_id=session_id)

            # 9. Verify the second check succeeded and reached HIGH-RISK confirmation
            assert "Confirmation required before executing shutdown." in resp3.response_text
            assert wf_mgr.is_pending(session_id) is False

            # 10. Verify actual Windows shutdown was NOT executed
            mock_shutdown_skill.assert_not_called()

        finally:
            # Cleanup: Ensure Notepad process is not leaked
            if proc is not None:
                try:
                    proc.poll()
                    if proc.returncode is None:
                        proc.terminate()
                        proc.wait(timeout=2)
                except Exception:
                    pass
            wf_mgr.clear_all()

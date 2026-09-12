"""
End-to-End Runtime Path Verification Script for Nova Phase A
Tests the 5 canonical input commands through the actual production runtime pipeline.
"""
import asyncio
import os
import sys

# Ensure src and root are on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import nova.skills  # load and register skills
from nova.application.application import NovaApplication
from nova.brain.engine import BrainEngine
from nova.skills.registry import registry


async def run_verifications():
    print("=" * 60)
    print("NOVA PHASE A RUNTIME VERIFICATION")
    print("=" * 60)

    # Initialize NovaApplication and BrainEngine
    app = NovaApplication()
    brain = app._brain
    await brain.initialize()

    # -------------------------------------------------------------
    # TEST 1: "open chrome"
    # -------------------------------------------------------------
    print("\n--- TEST 1: 'open chrome' ---")
    resp1 = await brain.process_text("open chrome")
    print(f"Response Text: {resp1.response_text}")
    print(f"Metadata: {resp1.metadata}")
    print(f"Plan: {resp1.plan}")
    if resp1.plan and resp1.plan.steps:
        step = resp1.plan.steps[0]
        print(f"Plan Step 0: tool={step.tool}, parameters={step.parameters}")
        selected_skill = registry.get(step.tool, {"intent": step.tool, **step.parameters})
        print(f"Resolved Skill: {selected_skill.__class__.__name__ if selected_skill else None}")

    # -------------------------------------------------------------
    # TEST 2: "launch notepad"
    # -------------------------------------------------------------
    print("\n--- TEST 2: 'launch notepad' ---")
    resp2 = await brain.process_text("launch notepad")
    print(f"Response Text: {resp2.response_text}")
    print(f"Metadata: {resp2.metadata}")
    print(f"Plan: {resp2.plan}")
    if resp2.plan and resp2.plan.steps:
        step = resp2.plan.steps[0]
        print(f"Plan Step 0: tool={step.tool}, parameters={step.parameters}")
        selected_skill = registry.get(step.tool, {"intent": step.tool, **step.parameters})
        print(f"Resolved Skill: {selected_skill.__class__.__name__ if selected_skill else None}")

    # -------------------------------------------------------------
    # TEST 3: "reduce volume"
    # -------------------------------------------------------------
    print("\n--- TEST 3: 'reduce volume' ---")
    resp3 = await brain.process_text("reduce volume")
    print(f"Response Text: {resp3.response_text}")
    print(f"Metadata: {resp3.metadata}")
    print(f"Plan: {resp3.plan}")
    if resp3.plan and resp3.plan.steps:
        step = resp3.plan.steps[0]
        print(f"Plan Step 0: tool={step.tool}, parameters={step.parameters}")
        selected_skill = registry.get(step.tool, {"intent": step.tool, **step.parameters})
        print(f"Resolved Skill: {selected_skill.__class__.__name__ if selected_skill else None}")

    # -------------------------------------------------------------
    # TEST 4: "what is on my screen"
    # -------------------------------------------------------------
    print("\n--- TEST 4: 'what is on my screen' ---")
    resp4 = await brain.process_text("what is on my screen")
    print(f"Response Text: {resp4.response_text}")
    print(f"Metadata: {resp4.metadata}")
    print(f"Plan: {resp4.plan}")
    if resp4.plan and resp4.plan.steps:
        step = resp4.plan.steps[0]
        print(f"Plan Step 0: tool={step.tool}, parameters={step.parameters}")
        selected_skill = registry.get(step.tool, {"intent": step.tool, **step.parameters})
        print(f"Resolved Skill: {selected_skill.__class__.__name__ if selected_skill else None}")

    # -------------------------------------------------------------
    # TEST 5: "open chrome, then open notepad"
    # -------------------------------------------------------------
    print("\n--- TEST 5: 'open chrome, then open notepad' ---")
    resp5 = await brain.process_text("open chrome, then open notepad")
    print(f"Response Text: {resp5.response_text}")
    print(f"Metadata: {resp5.metadata}")
    print(f"Plan: {resp5.plan}")
    if resp5.plan and resp5.plan.steps:
        print(f"Number of steps planned: {len(resp5.plan.steps)}")
        for idx, step in enumerate(resp5.plan.steps):
            print(f"  Step {idx}: tool={step.tool}, parameters={step.parameters}")

    print("\n" + "=" * 60)
    print("END OF VERIFICATIONS")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_verifications())

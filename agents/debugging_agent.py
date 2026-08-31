"""Debugging agent (section 22) - the core agentic behaviour of the POC.

It sees the failing tests and every previous attempt, so it cannot silently
retry the same fix.  The loop that calls it is bounded by ``max_iterations`` and
by failure fingerprinting; those limits are enforced in :mod:`graph.routing`,
never by the model.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, parse_json_payload
from graph.state import AgentState
from tools.base import ToolContext

DEBUG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string", "description": "Why the test failed - the root cause."},
        "fix_applied": {"type": "boolean", "description": "True if you changed a file."},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
    },
    "required": ["analysis", "fix_applied", "changed_files", "confidence"],
    "additionalProperties": False,
}


class DebuggingAgent(Agent):
    name = "debugging"
    output_schema = DEBUG_SCHEMA
    max_tool_turns = 14

    async def debug(self, state: AgentState, tool_context: ToolContext) -> dict[str, Any]:
        failures = "\n\n".join(state.get("test_failures", [])) or "(no parsed failures)"
        previous = "\n".join(f"- {item}" for item in state.get("previous_failures", []))
        iteration = state.get("iteration", 0)

        system = self.system_prompt()
        user = (
            f"Engineering issue:\n{state['issue']}\n\n"
            f"Debugging iteration {iteration} of {state.get('max_iterations', 3)}.\n\n"
            f"Current test failures:\n{failures}\n\n"
            f"Test run output:\n{state.get('test_results', '')[:4000]}\n\n"
            f"Previous attempts:\n{previous or '- (this is the first attempt)'}\n\n"
            "Diagnose the root cause and apply the smallest fix. If the failure is in a "
            "test you wrote and the production behaviour is correct, fix the test instead."
        )
        outcome = await self.run(system=system, user_message=user, tool_context=tool_context)
        payload = parse_json_payload(outcome)

        touched = [entry["path"] for entry in outcome.files_touched if entry.get("path")]
        analysis = str(payload.get("analysis", "")).strip()

        return {
            "debugging_analysis": analysis,
            "debug_changed_files": sorted(set(touched)),
            "fix_applied": bool(payload.get("fix_applied", bool(touched))),
            "confidence": str(payload.get("confidence", "LOW")).upper(),
            "_usage": outcome.usage,
        }

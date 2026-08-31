"""Testing agent (section 21).

Writes regression tests from the acceptance criteria and the change it can see
in the workspace.  It does not run the suite - the ``run_tests`` node does that,
so the pass/fail signal is produced by the platform, not reported by a model.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, parse_json_payload
from graph.state import AgentState
from tools.base import ToolContext

TEST_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "test_cases": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The behaviours covered by the tests you added.",
        },
        "test_files": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "test_cases", "test_files"],
    "additionalProperties": False,
}


class TestingAgent(Agent):
    name = "testing"
    output_schema = TEST_PLAN_SCHEMA
    max_tool_turns = 14

    async def generate(self, state: AgentState, tool_context: ToolContext) -> dict[str, Any]:
        criteria = "\n".join(f"- {item}" for item in state.get("acceptance_criteria", []))
        changed = "\n".join(f"- {path}" for path in state.get("modified_files", []))
        notes = "\n".join(f"- {note}" for note in state.get("test_notes", []))

        system = self.system_prompt()
        user = (
            f"Engineering issue:\n{state['issue']}\n\n"
            f"Acceptance criteria:\n{criteria or '- (none)'}\n\n"
            f"Files already changed:\n{changed or '- (none)'}\n\n"
            f"Notes from the implementation:\n{notes or '- (none)'}\n\n"
            "Find the existing test project, match its conventions, and add regression "
            "tests. Do not modify production code."
        )
        outcome = await self.run(system=system, user_message=user, tool_context=tool_context)
        payload = parse_json_payload(outcome)

        touched = [entry["path"] for entry in outcome.files_touched if entry.get("path")]
        return {
            "test_plan_summary": str(payload.get("summary", "")).strip(),
            "test_commands": [str(case) for case in payload.get("test_cases", [])],
            "test_files": sorted(set(touched or [str(p) for p in payload.get("test_files", [])])),
            "_usage": outcome.usage,
        }

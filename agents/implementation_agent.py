"""Implementation agent.

The only agent besides the debugger allowed to change production source.  It
works exclusively inside the task's Git worktree; every write goes through
``apply_patch``/``create_file``, so it is policy-checked and audited.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, parse_json_payload
from graph.state import AgentState
from tools.base import ToolContext

IMPLEMENTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What was changed and why."},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "notes_for_tests": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Behaviour the test agent should cover.",
        },
    },
    "required": ["summary", "changed_files", "notes_for_tests"],
    "additionalProperties": False,
}


class ImplementationAgent(Agent):
    name = "implementation"
    output_schema = IMPLEMENTATION_SCHEMA
    max_tool_turns = 16

    async def implement(self, state: AgentState, tool_context: ToolContext) -> dict[str, Any]:
        plan = "\n".join(f"- {step}" for step in state.get("plan", []))
        criteria = "\n".join(f"- {item}" for item in state.get("acceptance_criteria", []))
        files = "\n".join(f"- {path}" for path in state.get("relevant_files", []))
        findings = "\n".join(f"- {item}" for item in state.get("repository_context", []))

        system = self.system_prompt()
        user = (
            f"Engineering issue:\n{state['issue']}\n\n"
            f"Plan:\n{plan or '- (none)'}\n\n"
            f"Acceptance criteria:\n{criteria or '- (none)'}\n\n"
            f"Relevant files:\n{files or '- (none)'}\n\n"
            f"Repository findings:\n{findings or '- (none)'}\n\n"
            "Implement the smallest correct change. Read before you patch."
        )
        outcome = await self.run(system=system, user_message=user, tool_context=tool_context)
        payload = parse_json_payload(outcome)

        touched = [entry["path"] for entry in outcome.files_touched if entry.get("path")]
        declared = [str(path) for path in payload.get("changed_files", []) if str(path).strip()]
        # Trust what the tools actually wrote over what the model claims.
        changed = touched or declared

        return {
            "implementation_summary": str(payload.get("summary", "")).strip(),
            "modified_files": sorted(set(changed)),
            "test_notes": [str(note) for note in payload.get("notes_for_tests", [])],
            "_usage": outcome.usage,
        }

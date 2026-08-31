"""Repository agent (section 11).

Answers one question - where is the code relevant to this issue - and hands the
implementation agent a compact context package instead of a whole repository.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, parse_json_payload
from graph.state import AgentState
from tools.base import ToolContext

CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevant_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Repository-relative paths, most relevant first.",
        },
        "findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What each file contributes and where the defect most likely lives.",
        },
        "entry_point": {
            "type": "string",
            "description": "The single file and member most likely to need the fix.",
        },
    },
    "required": ["relevant_files", "findings", "entry_point"],
    "additionalProperties": False,
}


class RepositoryAgent(Agent):
    name = "repository"
    output_schema = CONTEXT_SCHEMA
    max_tool_turns = 14

    async def analyze(self, state: AgentState, tool_context: ToolContext) -> dict[str, Any]:
        plan_text = "\n".join(f"- {step}" for step in state.get("plan", []))
        criteria = "\n".join(f"- {item}" for item in state.get("acceptance_criteria", []))
        system = self.system_prompt()
        user = (
            f"Engineering issue:\n{state['issue']}\n\n"
            f"Plan:\n{plan_text or '- (no plan)'}\n\n"
            f"Acceptance criteria:\n{criteria or '- (none)'}\n\n"
            "Locate the relevant code with the search tools, read what you need, then "
            "return the context package."
        )
        outcome = await self.run(system=system, user_message=user, tool_context=tool_context)
        payload = parse_json_payload(outcome)

        files = [str(path).strip() for path in payload.get("relevant_files", []) if str(path).strip()]
        findings = [str(item) for item in payload.get("findings", []) if str(item).strip()]
        entry_point = str(payload.get("entry_point", "")).strip()
        if entry_point and entry_point not in files:
            files.insert(0, entry_point)

        return {
            "relevant_files": files,
            "repository_context": findings,
            "_entry_point": entry_point,
            "_usage": outcome.usage,
        }

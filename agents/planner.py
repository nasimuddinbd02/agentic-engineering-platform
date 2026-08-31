"""Planner agent (section 10).

Turns an engineering issue into steps and acceptance criteria.  It has no tools
at all - it cannot read or modify the repository - which keeps planning cheap
and makes "the planner changed code" impossible by construction.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, AgentOutcome, parse_json_payload
from graph.state import AgentState
from tools.base import ToolContext

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "One line describing the intended change."},
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered investigation and implementation steps.",
        },
        "acceptance_criteria": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Observable conditions that make the task complete.",
        },
    },
    "required": ["summary", "steps", "acceptance_criteria"],
    "additionalProperties": False,
}


class PlannerAgent(Agent):
    name = "planner"
    output_schema = PLAN_SCHEMA

    async def plan(self, state: AgentState, tool_context: ToolContext) -> dict[str, Any]:
        system = self.system_prompt()
        user = (
            f"Repository: {state.get('repository_url', '')}\n\n"
            f"Engineering issue:\n{state['issue']}\n\n"
            "Produce the plan."
        )
        outcome: AgentOutcome = await self.run(
            system=system,
            user_message=user,
            tool_context=tool_context,
            use_tools=False,
        )
        payload = parse_json_payload(outcome)
        steps = [str(step) for step in payload.get("steps", []) if str(step).strip()]
        criteria = [
            str(item) for item in payload.get("acceptance_criteria", []) if str(item).strip()
        ]
        return {
            "plan": steps,
            "plan_summary": str(payload.get("summary", "")).strip(),
            "acceptance_criteria": criteria,
            "_usage": outcome.usage,
        }

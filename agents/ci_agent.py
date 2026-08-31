"""CI debugging agent (section 26).

Reads pipeline logs - which fail for reasons local tests never show, like a
missing restore or a platform-specific path - and applies a fix.  Bounded by
``max_ci_iterations``, a separate budget from the local debugging loop.
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, parse_json_payload
from graph.state import AgentState
from tools.base import ToolContext

CI_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "fix_applied": {"type": "boolean"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "requires_human": {
            "type": "boolean",
            "description": "True when the failure is infrastructural rather than a code defect.",
        },
    },
    "required": ["analysis", "fix_applied", "changed_files", "requires_human"],
    "additionalProperties": False,
}


class CIAgent(Agent):
    name = "ci"
    output_schema = CI_SCHEMA
    max_tool_turns = 10

    async def diagnose(self, state: AgentState, tool_context: ToolContext) -> dict[str, Any]:
        system = self.system_prompt()
        user = (
            f"Engineering issue:\n{state['issue']}\n\n"
            f"Branch: {state.get('git_branch', '')}\n"
            f"CI status: {state.get('ci_status', '')}\n"
            f"CI iteration {state.get('ci_iteration', 0)} of {state.get('max_ci_iterations', 2)}\n\n"
            f"CI logs:\n{state.get('ci_logs', '')[:6000]}\n\n"
            f"Files changed by this task:\n"
            + ("\n".join(f"- {path}" for path in state.get('modified_files', [])) or "- (none)")
            + "\n\nDiagnose the pipeline failure and fix it if it is a code defect."
        )
        outcome = await self.run(system=system, user_message=user, tool_context=tool_context)
        payload = parse_json_payload(outcome)
        touched = [entry["path"] for entry in outcome.files_touched if entry.get("path")]

        return {
            "ci_analysis": str(payload.get("analysis", "")).strip(),
            "ci_changed_files": sorted(set(touched)),
            "fix_applied": bool(payload.get("fix_applied", bool(touched))),
            "requires_human": bool(payload.get("requires_human", False)),
            "_usage": outcome.usage,
        }

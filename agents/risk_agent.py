"""Risk assessment.

The model classifies intent; the policy engine decides authorization.  The final
risk level is the stronger of the two, and only the deterministic half can force
approval or a block (section 25).
"""

from __future__ import annotations

from typing import Any

from agents.base import Agent, parse_json_payload
from core.domain import PolicyAction, RiskLevel, max_risk
from graph.state import AgentState
from tools.base import ToolContext

RISK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "blast_radius": {"type": "string", "description": "What else this change could affect."},
    },
    "required": ["risk_level", "reasons", "blast_radius"],
    "additionalProperties": False,
}


class RiskAgent(Agent):
    name = "risk"
    output_schema = RISK_SCHEMA
    max_tool_turns = 6

    async def assess(self, state: AgentState, tool_context: ToolContext) -> dict[str, Any]:
        files = state.get("relevant_files", [])
        context_notes = "\n".join(f"- {item}" for item in state.get("repository_context", []))
        system = self.system_prompt()
        user = (
            f"Engineering issue:\n{state['issue']}\n\n"
            f"Candidate files:\n"
            + ("\n".join(f"- {path}" for path in files) or "- (none)")
            + "\n\n"
            f"Repository findings:\n{context_notes or '- (none)'}\n\n"
            "Assess the risk of making this change."
        )
        outcome = await self.run(system=system, user_message=user, tool_context=tool_context)
        payload = parse_json_payload(outcome)

        model_risk = str(payload.get("risk_level", RiskLevel.LOW.value)).upper()
        if model_risk not in RiskLevel.__members__:
            model_risk = RiskLevel.LOW.value
        reasons = [str(item) for item in payload.get("reasons", []) if str(item).strip()]
        blast_radius = str(payload.get("blast_radius", "")).strip()
        if blast_radius:
            reasons.append(f"blast radius: {blast_radius}")

        # Deterministic half: do the candidate paths hit a policy rule?  Change
        # scope is not known yet, so the scope thresholds stay off until the
        # security_policy node sees the real diff.
        decision = self.context.policy.evaluate(files=files, apply_scope_thresholds=False)
        combined = max_risk(RiskLevel(model_risk), decision.risk)
        reasons.extend(decision.reasons())

        return {
            "risk_level": combined.value,
            "risk_reasons": reasons,
            "approval_required": decision.action is not PolicyAction.ALLOW
            or combined is RiskLevel.HIGH,
            "policy_action": decision.action.value,
            "_blocked": decision.blocked,
            "_usage": outcome.usage,
        }

"""Deterministic offline provider.

Not a model: it replays a script.  It exists so the control plane - queue,
worker, graph, tools, policy, git, approval - can be exercised in CI and on a
laptop with no API key, and so graph tests never depend on model sampling.

A script is a list of turns keyed by agent name.  Each turn is either text
(optionally JSON) or a set of tool calls.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from llm.base import LLMProvider, LLMResponse, ToolInvocation, ToolSpec, Usage


@dataclass
class ScriptedTurn:
    text: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @classmethod
    def json(cls, payload: dict[str, Any]) -> ScriptedTurn:
        return cls(text=json.dumps(payload))

    @classmethod
    def call(cls, tool: str, **arguments: Any) -> ScriptedTurn:
        return cls(tool_calls=[(tool, arguments)])


class ScriptedLLMProvider(LLMProvider):
    name = "scripted"

    def __init__(self, script: dict[str, list[ScriptedTurn]] | None = None) -> None:
        self.script: dict[str, list[ScriptedTurn]] = defaultdict(list, script or {})
        self._cursor: dict[str, int] = defaultdict(int)
        self.calls: list[dict[str, Any]] = []

    def register(self, agent: str, turns: list[ScriptedTurn]) -> None:
        self.script[agent] = turns
        self._cursor[agent] = 0

    @classmethod
    def from_file(cls, path: str | Path) -> ScriptedLLMProvider:
        """Load a script from YAML.

        Each agent maps to a list of turns; a turn is either ``json:`` (a
        structured answer) or ``tool:`` plus ``arguments:`` (a tool call).

            implementation:
              - tool: read_file
                arguments: {path: src/A.cs}
              - json: {summary: "...", changed_files: ["src/A.cs"]}
        """
        import yaml

        document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        script: dict[str, list[ScriptedTurn]] = {}
        for agent, turns in document.items():
            parsed: list[ScriptedTurn] = []
            for turn in turns or []:
                if "tool" in turn:
                    parsed.append(
                        ScriptedTurn(
                            tool_calls=[(turn["tool"], dict(turn.get("arguments", {})))]
                        )
                    )
                elif "json" in turn:
                    parsed.append(ScriptedTurn.json(turn["json"]))
                elif "text" in turn:
                    parsed.append(ScriptedTurn(text=str(turn["text"])))
            script[agent] = parsed
        return cls(script)

    async def generate(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> LLMResponse:
        agent = _agent_of(system)
        self.calls.append({"agent": agent, "messages": len(messages)})
        turns = self.script.get(agent, [])
        index = self._cursor[agent]
        if index >= len(turns):
            # Nothing scripted left: end the turn cleanly so loops terminate.
            return LLMResponse(text="", stop_reason="end_turn", usage=Usage())
        self._cursor[agent] = index + 1
        turn = turns[index]

        tool_calls = [
            ToolInvocation(id=f"toolu_{agent}_{index}_{position}", name=name, arguments=args)
            for position, (name, args) in enumerate(turn.tool_calls)
        ]
        assistant_content: list[dict[str, Any]] = []
        if turn.text:
            assistant_content.append({"type": "text", "text": turn.text})
        for call in tool_calls:
            assistant_content.append(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            )

        parsed: dict[str, Any] | None = None
        if turn.text:
            try:
                candidate = json.loads(turn.text)
                parsed = candidate if isinstance(candidate, dict) else None
            except json.JSONDecodeError:
                parsed = None

        return LLMResponse(
            text=turn.text,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=Usage(input_tokens=0, output_tokens=0),
            parsed=parsed,
        )


def _agent_of(system: str) -> str:
    """Scripts key off the ``[agent:NAME]`` marker every prompt template carries."""
    marker = "[agent:"
    start = system.find(marker)
    if start == -1:
        return "default"
    end = system.find("]", start)
    return system[start + len(marker) : end].strip() if end != -1 else "default"

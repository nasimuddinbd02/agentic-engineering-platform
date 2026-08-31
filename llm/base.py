"""LLM provider abstraction (section 50).

The agent graph never imports a vendor SDK.  It builds provider-neutral
messages, tool specs and (optionally) a JSON schema, and gets back a
:class:`LLMResponse`.  Swapping providers - or pointing at an enterprise model
gateway - is a change in :mod:`llm.factory` only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolInvocation:
    """A tool the model asked to run."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0

    def merge(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolInvocation] = field(default_factory=list)
    #: Provider-native assistant content, echoed back verbatim on the next turn.
    assistant_content: Any = None
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)
    parsed: dict[str, Any] | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


def text_message(role: Role, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def tool_result_message(results: list[dict[str, Any]]) -> dict[str, Any]:
    """All results for one assistant turn go back in a single user message."""
    return {"role": "user", "content": results}


def tool_result_block(
    tool_use_id: str, content: str, *, is_error: bool = False
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if is_error:
        block["is_error"] = True
    return block


class LLMProvider(ABC):
    """Every provider adapter implements exactly this."""

    name: str = "abstract"

    @abstractmethod
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
        """One model turn.  Implementations must not execute tools themselves."""

    async def close(self) -> None:  # pragma: no cover - adapters override
        return None

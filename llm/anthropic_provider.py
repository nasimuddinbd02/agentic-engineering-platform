"""Claude adapter for :class:`llm.base.LLMProvider`.

Uses the Messages API through the official ``anthropic`` SDK:

* adaptive thinking plus ``output_config.effort`` - the current controls on
  Claude Opus 5 (``budget_tokens`` is rejected on this model family);
* streaming with ``get_final_message()`` so large ``max_tokens`` values cannot
  hit an HTTP timeout;
* ``output_config.format`` for the nodes that must return strict JSON
  (planner, risk, debugging analysis);
* the agentic loop lives in :mod:`agents.base`, not here, because every tool
  call has to be policy-checked and written to the audit tables first.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from core.errors import ConfigurationError, TransientInfrastructureError
from core.logging import get_logger
from llm.base import LLMProvider, LLMResponse, ToolInvocation, ToolSpec, Usage

log = get_logger(__name__)

#: USD per million tokens, for the cost metric in section 42.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rate_in, rate_out = PRICING.get(model, (0.0, 0.0))
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "claude-opus-5",
        max_tokens: int = 16000,
        effort: str = "high",
    ) -> None:
        # An unset key is not necessarily fatal: the SDK also resolves
        # ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile.
        try:
            self.client = (
                anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()
            )
        except Exception as exc:  # pragma: no cover - constructor rarely fails
            raise ConfigurationError(f"cannot construct Anthropic client: {exc}") from exc
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort

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
        output_config: dict[str, Any] = {"effort": effort or self.effort}
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}

        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
        }
        if tools:
            request["tools"] = [tool.to_dict() for tool in tools]

        try:
            async with self.client.messages.stream(**request) as stream:
                message = await stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise TransientInfrastructureError(f"rate limited: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise TransientInfrastructureError(f"connection error: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientInfrastructureError(f"upstream {exc.status_code}") from exc
            raise

        return self._to_response(message)

    def _to_response(self, message: Any) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolInvocation] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolInvocation(id=block.id, name=block.name, arguments=dict(block.input))
                )

        text = "\n".join(text_parts).strip()
        parsed: dict[str, Any] | None = None
        if text:
            try:
                candidate = json.loads(text)
                parsed = candidate if isinstance(candidate, dict) else None
            except json.JSONDecodeError:
                parsed = None

        usage = Usage(
            input_tokens=getattr(message.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(message.usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
        )
        usage.cost_usd = estimate_cost(self.model, usage.input_tokens, usage.output_tokens)

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            log.warning(
                "llm.refusal", category=getattr(details, "category", None), model=self.model
            )

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            assistant_content=message.content,
            stop_reason=message.stop_reason or "end_turn",
            usage=usage,
            parsed=parsed,
        )

    async def close(self) -> None:
        await self.client.close()

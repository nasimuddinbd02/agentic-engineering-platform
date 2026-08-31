"""Base agent: the bounded, audited tool-calling loop.

The loop lives here rather than in the provider SDK because every tool call has
to pass three gates first - the agent's allowlist, the workspace boundary, and
the policy engine - and be written to ``tool_calls`` afterwards.  That is the
control plane the whole platform exists to demonstrate.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from core.domain import EventType
from core.errors import PolicyViolationError, ToolValidationError, WorkspaceViolationError
from core.logging import get_logger
from graph.context import WorkflowContext
from llm.base import (
    LLMResponse,
    ToolSpec,
    Usage,
    text_message,
    tool_result_block,
    tool_result_message,
)
from tools.base import ToolContext, ToolResult

log = get_logger(__name__)

MAX_TOOL_TURNS = 12


@dataclass
class AgentOutcome:
    text: str = ""
    parsed: dict[str, Any] | None = None
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[str] = field(default_factory=list)
    files_touched: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    stopped_reason: str = "end_turn"


class Agent:
    """One reasoning role from section 8."""

    #: Key into the prompt directory and the tool allowlist.
    name: str = "abstract"
    #: Optional strict JSON schema for nodes that must return structured output.
    output_schema: dict[str, Any] | None = None
    max_tool_turns: int = MAX_TOOL_TURNS

    def __init__(self, context: WorkflowContext) -> None:
        self.context = context

    # ------------------------------------------------------------- prompting

    def system_prompt(self, **variables: Any) -> str:
        template = self.context.load_prompt(self.name)
        # The marker lets the offline scripted provider identify the caller.
        header = f"[agent:{self.name}]\n"
        try:
            return header + template.format(**variables)
        except KeyError as exc:  # pragma: no cover - prompt/variable mismatch
            raise ToolValidationError(
                f"prompt '{self.name}' references unknown variable {exc}"
            ) from exc

    def tool_specs(self) -> list[ToolSpec]:
        return self.context.tools.specs_for_agent(self.name)

    # ------------------------------------------------------------------ loop

    async def run(
        self,
        *,
        system: str,
        user_message: str,
        tool_context: ToolContext,
        use_tools: bool = True,
        json_schema: dict[str, Any] | None = None,
    ) -> AgentOutcome:
        messages: list[dict[str, Any]] = [text_message("user", user_message)]
        specs = self.tool_specs() if use_tools else []
        outcome = AgentOutcome()

        for turn in range(1, self.max_tool_turns + 1):
            outcome.turns = turn
            response: LLMResponse = await self.context.llm.generate(
                system=system,
                messages=messages,
                tools=specs or None,
                json_schema=json_schema if json_schema is not None else self.output_schema,
            )
            outcome.usage = outcome.usage.merge(response.usage)
            outcome.text = response.text or outcome.text
            if response.parsed is not None:
                outcome.parsed = response.parsed

            if not response.wants_tools:
                outcome.stopped_reason = response.stop_reason
                return outcome

            messages.append({"role": "assistant", "content": response.assistant_content})

            results: list[dict[str, Any]] = []
            for invocation in response.tool_calls:
                outcome.tool_calls.append(invocation.name)
                result = await self._execute_tool(
                    invocation.name, invocation.arguments, tool_context
                )
                if result.data.get("path"):
                    outcome.files_touched.append(result.data)
                results.append(
                    tool_result_block(
                        invocation.id, result.content, is_error=not result.ok
                    )
                )
            messages.append(tool_result_message(results))

        outcome.stopped_reason = "max_tool_turns"
        log.warning("agent.tool_turns_exhausted", agent=self.name, turns=self.max_tool_turns)
        return outcome

    # ------------------------------------------------------------ tool gate

    async def _execute_tool(
        self, name: str, arguments: dict[str, Any], tool_context: ToolContext
    ) -> ToolResult:
        context = self.context
        started = time.perf_counter()

        # Gate 1: is this agent allowed to call this tool at all?
        if not context.tools.is_allowed(self.name, name):
            message = f"tool '{name}' is not available to the {self.name} agent"
            await self._audit(name, arguments, ToolResult.failure(message), started)
            return ToolResult.failure(message)

        try:
            tool = context.tools.get(name)
        except ToolValidationError as exc:
            await self._audit(name, arguments, ToolResult.failure(str(exc)), started)
            return ToolResult.failure(str(exc))

        # Gate 2: deterministic policy, before the write happens.
        if tool.mutating:
            path = str(arguments.get("path", ""))
            decision = context.policy.check_path_writable(path)
            if decision.blocked:
                message = f"policy blocked write to {path}: {decision.summary()}"
                await context.emit(
                    EventType.POLICY_BLOCKED, tool=name, path=path, reasons=decision.reasons()
                )
                await self._audit(name, arguments, ToolResult.failure(message), started)
                raise PolicyViolationError(message)

        await context.emit(EventType.TOOL_CALLED, tool=name, arguments=_preview_arguments(arguments))

        # Gate 3: the workspace boundary, enforced inside the tool itself.
        try:
            result = await tool.run(tool_context, **arguments)
        except WorkspaceViolationError as exc:
            result = ToolResult.failure(f"workspace violation: {exc}")
        except TypeError as exc:
            result = ToolResult.failure(f"invalid arguments for {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a tool failure must not kill the run
            log.exception("tool.unhandled_error", tool=name)
            result = ToolResult.failure(f"{type(exc).__name__}: {exc}")

        await self._audit(name, arguments, result, started)
        if result.ok and tool.mutating and result.data.get("path"):
            await context.record_file_change(
                path=result.data["path"],
                change_type=result.data.get("change_type", "MODIFIED"),
                iteration=tool_context.iteration,
                lines_added=result.data.get("lines_added", 0),
                lines_removed=result.data.get("lines_removed", 0),
            )
            await context.emit(EventType.FILE_CHANGED, path=result.data["path"])
        return result

    async def _audit(
        self, name: str, arguments: dict[str, Any], result: ToolResult, started: float
    ) -> None:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await self.context.record_tool_call(
            tool=name,
            arguments=_preview_arguments(arguments),
            ok=result.ok,
            result_preview=result.content[:2000],
            error=None if result.ok else result.content[:2000],
            exit_code=result.exit_code,
            duration_ms=duration_ms,
        )
        await self.context.emit(
            EventType.TOOL_COMPLETED if result.ok else EventType.TOOL_FAILED,
            tool=name,
            ok=result.ok,
            duration_ms=duration_ms,
        )


def _preview_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Keep audit rows small: long text arguments are truncated, not stored whole."""
    preview: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 500:
            preview[key] = value[:500] + f"...[{len(value) - 500} more chars]"
        else:
            preview[key] = value
    return preview


def parse_json_payload(outcome: AgentOutcome) -> dict[str, Any]:
    """Structured output first; fall back to the largest JSON object in the text."""
    if outcome.parsed is not None:
        return outcome.parsed
    text = outcome.text.strip()
    if not text:
        return {}
    fenced = text.split("```")
    for candidate in ([text] + fenced):
        cleaned = candidate.strip().removeprefix("json").strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}

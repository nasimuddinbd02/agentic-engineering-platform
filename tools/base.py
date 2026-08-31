"""Tool contract and execution context.

Every tool answers the section 19 questions before it does anything: which
task, which workspace, which file, which command.  The context carries that
identity - a tool can never be called without one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm.base import ToolSpec
from tools.workspace import Workspace


@dataclass
class ToolContext:
    """Identity and capabilities handed to a tool for one call."""

    task_id: str
    repository_path: Path
    workspace: Workspace | None = None
    iteration: int = 0
    agent_run_id: str | None = None
    #: Set by the policy engine; tools consult it before writing.
    write_allowed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        """Where reads and writes are anchored: the worktree once it exists."""
        return self.workspace.path if self.workspace else self.repository_path

    def resolve(self, relative: str) -> Path:
        from tools.workspace import resolve_inside

        return resolve_inside(self.root, relative)

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = None
    duration_ms: int | None = None

    @classmethod
    def success(cls, content: str, **data: Any) -> ToolResult:
        return cls(ok=True, content=content, data=data)

    @classmethod
    def failure(cls, content: str, **data: Any) -> ToolResult:
        return cls(ok=False, content=content, data=data)


class Tool(ABC):
    """A capability offered to an agent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    #: Tools that change files are gated by policy and by ``write_allowed``.
    mutating: bool = False

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description, input_schema=self.input_schema
        )

    @abstractmethod
    async def run(self, context: ToolContext, **arguments: Any) -> ToolResult: ...


def string_schema(**properties: str) -> dict[str, Any]:
    """Shorthand for the common all-strings, all-required schema."""
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": desc} for name, desc in properties.items()},
        "required": list(properties),
        "additionalProperties": False,
    }

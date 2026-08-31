"""Tool registry and per-agent allowlists (sections 9 and 53).

The supervisor - not the model - decides which tools an agent may call.  The
planner cannot write files; the repository agent cannot run builds; only the
implementation and debugging agents get mutating tools.
"""

from __future__ import annotations

from core.config import Settings, get_settings
from core.errors import ToolValidationError
from llm.base import ToolSpec
from tools.base import Tool
from tools.filesystem.apply_patch import ApplyPatchTool, CreateFileTool
from tools.filesystem.list_directory import ListDirectoryTool
from tools.filesystem.read_file import ReadFileTool
from tools.git.diff import GitDiffTool, GitStatusTool
from tools.repository.dependency_search import GetDependenciesTool
from tools.repository.search_code import SearchCodeTool
from tools.repository.symbol_search import FindReferencesTool, FindSymbolTool
from tools.testing.test import BuildTool, RunTestsTool

#: Which tools each agent is permitted to call.
AGENT_TOOL_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "planner": (),
    "repository": (
        "search_code",
        "read_file",
        "list_directory",
        "find_symbol",
        "find_references",
        "get_dependencies",
    ),
    "implementation": (
        "read_file",
        "search_code",
        "find_symbol",
        "list_directory",
        "apply_patch",
        "create_file",
        "git_diff",
    ),
    "testing": (
        "read_file",
        "search_code",
        "find_symbol",
        "list_directory",
        "apply_patch",
        "create_file",
        "run_build",
    ),
    "debugging": (
        "read_file",
        "search_code",
        "find_symbol",
        "find_references",
        "apply_patch",
        "create_file",
        "git_diff",
    ),
    "ci": ("read_file", "search_code", "apply_patch", "git_diff"),
    "risk": ("read_file", "git_diff", "list_directory"),
}


class ToolRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        timeout = settings.command_timeout_seconds
        tools: list[Tool] = [
            ReadFileTool(),
            ListDirectoryTool(),
            ApplyPatchTool(),
            CreateFileTool(),
            SearchCodeTool(),
            FindSymbolTool(),
            FindReferencesTool(),
            GetDependenciesTool(),
            GitDiffTool(),
            GitStatusTool(),
            BuildTool(timeout=timeout),
            RunTestsTool(timeout=timeout),
        ]
        self._tools: dict[str, Tool] = {tool.name: tool for tool in tools}

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolValidationError(f"unknown tool: {name}")
        return tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def for_agent(self, agent: str) -> list[Tool]:
        allowed = AGENT_TOOL_ALLOWLIST.get(agent)
        if allowed is None:
            raise ToolValidationError(f"no tool allowlist defined for agent: {agent}")
        return [self._tools[name] for name in allowed if name in self._tools]

    def specs_for_agent(self, agent: str) -> list[ToolSpec]:
        return [tool.spec() for tool in self.for_agent(agent)]

    def is_allowed(self, agent: str, tool_name: str) -> bool:
        return tool_name in AGENT_TOOL_ALLOWLIST.get(agent, ())

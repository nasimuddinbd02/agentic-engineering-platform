"""search_code - level 1 retrieval (section 12).

ripgrep when it is installed, a bounded pure-Python walk otherwise, so the POC
never depends on an external binary being present.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from tools.base import Tool, ToolContext, ToolResult

SKIP_DIRECTORIES = {".git", "bin", "obj", "node_modules", ".vs", "__pycache__", ".next", "packages"}
TEXT_SUFFIXES = {
    ".cs",
    ".csproj",
    ".sln",
    ".json",
    ".xml",
    ".config",
    ".md",
    ".yml",
    ".yaml",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sql",
    ".sh",
    ".props",
    ".targets",
    ".txt",
}
MAX_MATCHES = 60
MAX_FILE_BYTES = 2_000_000


@dataclass
class Match:
    path: str
    line_number: int
    line: str

    def render(self) -> str:
        return f"{self.path}:{self.line_number}: {self.line.strip()}"


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        files.append(path)
    return files


def search_python(
    root: Path, pattern: str, *, glob: str | None = None, limit: int = MAX_MATCHES
) -> list[Match]:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"invalid regular expression: {exc}") from exc

    matches: list[Match] = []
    for path in iter_source_files(root):
        relative = path.relative_to(root).as_posix()
        if glob and not Path(relative).match(glob):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                matches.append(Match(relative, number, line))
                if len(matches) >= limit:
                    return matches
    return matches


async def search_ripgrep(
    root: Path, pattern: str, *, glob: str | None, limit: int
) -> list[Match] | None:
    """Returns None when ripgrep is unavailable, so the caller can fall back."""
    executable = shutil.which("rg")
    if not executable:
        return None
    import asyncio

    command = [executable, "--line-number", "--no-heading", "--ignore-case", "--max-count", "10"]
    for directory in SKIP_DIRECTORIES:
        command += ["--glob", f"!{directory}/**"]
    if glob:
        command += ["--glob", glob]
    command += ["--regexp", pattern, "."]

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    if process.returncode not in (0, 1):
        return None

    matches: list[Match] = []
    for raw in stdout.decode("utf-8", errors="replace").splitlines():
        parts = raw.split(":", 2)
        if len(parts) < 3:
            continue
        path, number, line = parts
        try:
            matches.append(Match(path.replace("\\", "/").lstrip("./"), int(number), line))
        except ValueError:
            continue
        if len(matches) >= limit:
            break
    return matches


class SearchCodeTool(Tool):
    name = "search_code"
    description = (
        "Search the repository for a regular expression. Returns path:line matches. "
        "This is the fastest way to locate relevant code - start here."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression, case-insensitive."},
            "glob": {"type": "string", "description": "Optional path filter, e.g. '**/*.cs'."},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    async def run(
        self, context: ToolContext, *, pattern: str, glob: str | None = None, **_: Any
    ) -> ToolResult:
        root = context.root
        try:
            matches = await search_ripgrep(root, pattern, glob=glob, limit=MAX_MATCHES)
            if matches is None:
                matches = search_python(root, pattern, glob=glob, limit=MAX_MATCHES)
        except ValueError as exc:
            return ToolResult.failure(str(exc))

        if not matches:
            return ToolResult.success(f"no matches for /{pattern}/")
        files = sorted({match.path for match in matches})
        body = "\n".join(match.render() for match in matches)
        return ToolResult.success(
            f"{len(matches)} match(es) in {len(files)} file(s):\n{body}",
            files=files,
            match_count=len(matches),
        )

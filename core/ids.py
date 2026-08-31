"""Identifier helpers.  Human-readable task ids, uuid4 for everything else."""

from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def task_id() -> str:
    return new_id("TASK")


def run_id() -> str:
    return new_id("run")


def event_id() -> str:
    return new_id("evt")


def tool_call_id() -> str:
    return new_id("tc")

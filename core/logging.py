"""Structured logging bound to task ids (section 41)."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str, **initial: Any) -> Any:
    return structlog.get_logger(name).bind(**initial)


def bind_task(task_id: str, **extra: Any) -> None:
    """Bind the task id to every log line emitted on this task/coroutine."""
    structlog.contextvars.bind_contextvars(task_id=task_id, **extra)


def clear_task_context() -> None:
    structlog.contextvars.clear_contextvars()

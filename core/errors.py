"""Typed errors.  The retry classifier (section 51) routes on these."""

from __future__ import annotations


class AgentPlatformError(Exception):
    """Base class for every error the platform raises deliberately."""


class ConfigurationError(AgentPlatformError):
    """Missing or invalid configuration - never retried."""


class TransientInfrastructureError(AgentPlatformError):
    """Network/database blip - safe to retry."""


class ToolValidationError(AgentPlatformError):
    """The agent called a tool with bad arguments - the agent should correct itself."""


class WorkspaceViolationError(AgentPlatformError):
    """A path or command escaped the task workspace - hard stop (section 19)."""


class PolicyViolationError(AgentPlatformError):
    """A deterministic policy rule blocked the operation - hard stop (section 25)."""


class TaskNotFoundError(AgentPlatformError):
    pass


class InvalidTaskTransitionError(AgentPlatformError):
    """Attempted a state-machine transition that is not legal (section 30)."""

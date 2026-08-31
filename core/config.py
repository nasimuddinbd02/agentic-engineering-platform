"""Central configuration.

Every knob the platform has is an environment variable (section 35).  Nothing
reads ``os.environ`` directly outside this module.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # persistence / coordination
    database_url: str = "sqlite+aiosqlite:///./data/agent.db"
    redis_url: str = "memory://"

    # llm
    llm_provider: str = "scripted"
    llm_api_key: str = ""
    llm_model: str = "claude-opus-5"
    llm_effort: str = "high"
    llm_max_tokens: int = 16000

    # source control / ci
    scm_provider: str = "local"
    ci_provider: str = "none"
    github_token: str = ""
    github_repository: str = ""

    # workspaces
    workspace_root: Path = Path("./workspaces")
    artifact_root: Path = Path("./artifacts")

    # limits (section 22 / 26 / 38)
    max_agent_iterations: int = 3
    max_ci_iterations: int = 2
    task_lease_seconds: int = 900
    #: How often a worker reconciles the queue against the tasks table.
    queue_sweep_seconds: int = 15
    worker_concurrency: int = 2
    command_timeout_seconds: int = 600
    max_files_per_task: int = 25

    log_level: str = "INFO"
    api_port: int = 8000

    queue_name: str = Field(default="agent:tasks")
    event_channel_prefix: str = Field(default="agent:events")

    @property
    def uses_memory_backend(self) -> bool:
        return self.redis_url.startswith("memory://")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()

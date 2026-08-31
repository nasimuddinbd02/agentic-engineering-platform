"""Provider selection for source control and CI."""

from __future__ import annotations

from core.config import Settings, get_settings
from core.errors import ConfigurationError
from providers.ci.base import CIPipelineProvider
from providers.scm.base import SourceControlProvider


def build_scm_provider(settings: Settings | None = None) -> SourceControlProvider:
    settings = settings or get_settings()
    provider = settings.scm_provider.lower()

    if provider == "local":
        from providers.scm.local import LocalGitProvider

        return LocalGitProvider(settings.artifact_root)

    if provider == "github":
        from providers.scm.github import GitHubProvider

        return GitHubProvider(settings.github_token, settings.github_repository)

    if provider in ("azure", "azure_devops"):
        from providers.scm.azure_devops import AzureDevOpsProvider

        organization, project, repository = _split_azure_target(settings.github_repository)
        return AzureDevOpsProvider(
            organization=organization,
            project=project,
            repository=repository,
            token=settings.github_token,
        )

    raise ConfigurationError(f"unknown SCM_PROVIDER: {settings.scm_provider}")


def build_ci_provider(settings: Settings | None = None) -> CIPipelineProvider:
    settings = settings or get_settings()
    provider = settings.ci_provider.lower()

    if provider in ("none", "noop", ""):
        from providers.ci.noop import NoopCIProvider

        return NoopCIProvider()

    if provider in ("github", "github_actions"):
        from providers.ci.github_actions import GitHubActionsProvider

        return GitHubActionsProvider(settings.github_token, settings.github_repository)

    raise ConfigurationError(f"unknown CI_PROVIDER: {settings.ci_provider}")


def _split_azure_target(target: str) -> tuple[str, str, str]:
    parts = [part for part in target.split("/") if part]
    if len(parts) != 3:
        raise ConfigurationError(
            "for Azure DevOps set GITHUB_REPOSITORY to 'organization/project/repository'"
        )
    return parts[0], parts[1], parts[2]

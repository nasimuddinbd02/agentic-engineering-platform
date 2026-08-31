# Worker image (section 34).
#
# Unlike the API, the worker needs the target project's toolchain: it builds and
# tests the code it changes. The .NET SDK is here because the sample target is a
# .NET service; a Java or Node target would swap this base layer.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    WORKSPACE_ROOT=/workspaces

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install "."

COPY core ./core
COPY persistence ./persistence
COPY infrastructure ./infrastructure
COPY llm ./llm
COPY agents ./agents
COPY graph ./graph
COPY tools ./tools
COPY providers ./providers
COPY retrieval ./retrieval
COPY policies ./policies
COPY prompts ./prompts
COPY apps ./apps

# Workspaces are deliberately local and disposable (section 39): durable state
# lives in PostgreSQL, so losing this volume loses nothing that matters.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /workspaces /artifacts \
    && chown -R agent:agent /app /workspaces /artifacts
USER agent

VOLUME ["/workspaces"]

CMD ["python", "-m", "apps.worker.main"]

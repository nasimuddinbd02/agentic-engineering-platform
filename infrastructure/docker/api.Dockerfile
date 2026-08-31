# API image (section 34). Build from the repository root:
#   docker build -f infrastructure/docker/api.Dockerfile -t agent-api .
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The API talks to git only through the health of the system; the worker is the
# image that needs a toolchain.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

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

# Never run as root: the API has no reason to write anywhere.
RUN useradd --create-home --uid 10001 agent && chown -R agent:agent /app
USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

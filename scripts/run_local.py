"""Run the API and a worker in one process.

Convenience for ``REDIS_URL=memory://``, where the queue is in-process and the
two halves therefore have to share one runtime.  This is a development
shortcut, not the architecture: with Redis the API and worker are separate
deployments that scale independently (sections 2.2 and 38).

    python -m scripts.run_local
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))


async def main_async(port: int) -> None:
    import uvicorn

    from apps.worker.consumer import WorkerConsumer
    from core.config import get_settings
    from core.logging import configure_logging, get_logger
    from infrastructure import build_coordination, worker_identity
    from persistence.db import create_schema, dispose_engine

    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("run_local")

    if not settings.uses_memory_backend:
        log.warning(
            "run_local.redis_configured",
            hint="With Redis you should run `make api` and `make worker` separately.",
        )

    await create_schema(settings)

    worker_id = worker_identity("worker")
    coordination = build_coordination(settings, consumer_name=worker_id)
    consumer = WorkerConsumer(settings, coordination, worker_id)

    server = uvicorn.Server(
        uvicorn.Config(
            "apps.api.main:app",
            host="127.0.0.1",
            port=port,
            log_level=settings.log_level.lower(),
            lifespan="on",
        )
    )

    log.info("run_local.starting", port=port, backend=coordination.backend)
    worker_task = asyncio.create_task(consumer.run_forever())
    try:
        await server.serve()
    finally:
        await consumer.stop()
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        await coordination.close()
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the API and a worker together.")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main_async(arguments.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

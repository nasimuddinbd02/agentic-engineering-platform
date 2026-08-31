"""Worker entry point.

Run as many of these as you like: ``python -m apps.worker.main``.  They
coordinate through Redis and PostgreSQL, never through each other.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from apps.worker.consumer import WorkerConsumer
from core.config import get_settings
from core.logging import configure_logging, get_logger
from infrastructure import build_coordination, worker_identity
from persistence.db import create_schema, dispose_engine

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await create_schema(settings)

    worker_id = worker_identity("worker")
    coordination = build_coordination(settings, consumer_name=worker_id)
    consumer = WorkerConsumer(settings, coordination, worker_id)

    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()

    def request_stop() -> None:
        log.info("worker.stop_requested", worker=worker_id)
        stopping.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(getattr(signal, signal_name), request_stop)

    runner = asyncio.create_task(consumer.run_forever())
    await stopping.wait()
    await consumer.stop()
    runner.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await runner

    await coordination.close()
    await dispose_engine()
    log.info("worker.stopped", worker=worker_id)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())

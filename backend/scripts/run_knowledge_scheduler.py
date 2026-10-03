from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.services.knowledge_pipeline import create_pipeline_runtime


def configure_scheduler(
    scheduler: Any,
    job: Callable[[], Awaitable[object]],
    *,
    interval_minutes: int,
) -> None:
    scheduler.add_job(
        job,
        "interval",
        minutes=interval_minutes,
        id="knowledge-pipeline",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


async def run_scheduler() -> None:
    settings = Settings()
    runtime = create_pipeline_runtime(settings)
    scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop(), timezone="Asia/Shanghai")
    configure_scheduler(
        scheduler,
        runtime.pipeline.run_once,
        interval_minutes=settings.knowledge_mining_interval_minutes,
    )
    scheduler.start()
    try:
        await runtime.pipeline.run_once()
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=True)
        await runtime.close()


def main() -> None:
    try:
        asyncio.run(run_scheduler())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

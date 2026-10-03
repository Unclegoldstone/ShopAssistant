from __future__ import annotations

import asyncio

from app.services.knowledge_pipeline import create_pipeline_runtime


async def run_once() -> None:
    runtime = create_pipeline_runtime()
    try:
        result = await runtime.pipeline.run_once()
        print(result)
        if result.errors:
            raise SystemExit(1)
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(run_once())

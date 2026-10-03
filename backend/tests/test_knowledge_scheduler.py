from __future__ import annotations

import pytest

from app.services.knowledge_pipeline import KnowledgePipeline
from scripts.run_knowledge_scheduler import configure_scheduler


class FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, dict[str, object]]] = []

    def add_job(self, function: object, trigger: str, **kwargs: object) -> None:
        self.calls.append((function, trigger, kwargs))


def test_scheduler_registers_one_non_overlapping_coalesced_job() -> None:
    scheduler = FakeScheduler()

    async def job() -> None:
        return None

    configure_scheduler(scheduler, job, interval_minutes=15)

    assert scheduler.calls == [
        (
            job,
            "interval",
            {
                "minutes": 15,
                "id": "knowledge-pipeline",
                "replace_existing": True,
                "max_instances": 1,
                "coalesce": True,
            },
        )
    ]


@pytest.mark.asyncio
async def test_pipeline_runs_all_stages_and_continues_after_one_failure() -> None:
    events: list[str] = []

    class Stage:
        def __init__(self, name: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        async def run_once(self):  # noqa: ANN201
            events.append(self.name)
            if self.fail:
                raise RuntimeError(self.name)
            return self.name

    class VectorStage:
        async def run_until_idle(self):  # noqa: ANN201
            events.append("vectorize")
            return "vectorize"

    pipeline = KnowledgePipeline(
        mining=Stage("mine"),
        deduplication=Stage("deduplicate", fail=True),
        vectorization=VectorStage(),
    )

    result = await pipeline.run_once()

    assert events == ["mine", "deduplicate", "vectorize"]
    assert result.errors == {"deduplicate": "RuntimeError: deduplicate"}


@pytest.mark.asyncio
async def test_pipeline_redacts_secrets_from_stage_errors() -> None:
    class FailingStage:
        async def run_once(self):  # noqa: ANN201
            raise RuntimeError("request failed token=super-secret")

    class IdleStage:
        async def run_once(self):  # noqa: ANN201
            return None

        async def run_until_idle(self):  # noqa: ANN201
            return None

    pipeline = KnowledgePipeline(
        mining=FailingStage(),
        deduplication=IdleStage(),
        vectorization=IdleStage(),
    )

    result = await pipeline.run_once()

    assert "super-secret" not in result.errors["mine"]
    assert "token=[redacted]" in result.errors["mine"]

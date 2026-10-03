from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from app.knowledge.embedding import BgeM3Embedder, EmbeddingError


class StubBgeModel:
    def __init__(self, *, delay: float = 0) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.delay = delay

    def encode(self, texts: list[str], **kwargs: object) -> dict[str, np.ndarray]:
        self.calls.append((texts, kwargs))
        if self.delay:
            time.sleep(self.delay)
        rows = [[float(index + 1), 0.5, -0.5] for index, _ in enumerate(texts)]
        return {"dense_vecs": np.asarray(rows, dtype=np.float32)}


@pytest.mark.asyncio
async def test_embedder_is_lazy_dense_only_and_returns_plain_vectors() -> None:
    loaded: list[tuple[str, bool, str]] = []
    model = StubBgeModel()

    def load(model_path: str, use_fp16: bool, device: str) -> StubBgeModel:
        loaded.append((model_path, use_fp16, device))
        return model

    embedder = BgeM3Embedder(
        model_name_or_path="local-bge-m3",
        device="cpu",
        use_fp16=False,
        batch_size=2,
        max_length=128,
        dimension=3,
        model_loader=load,
    )
    assert loaded == []

    vectors = await embedder.embed(["问题", "答案"])

    assert loaded == [("local-bge-m3", False, "cpu")]
    assert vectors == [[1.0, 0.5, -0.5], [2.0, 0.5, -0.5]]
    assert model.calls == [
        (
            ["问题", "答案"],
            {
                "batch_size": 2,
                "max_length": 128,
                "return_dense": True,
                "return_sparse": False,
                "return_colbert_vecs": False,
            },
        )
    ]


@pytest.mark.asyncio
async def test_embedder_rejects_bad_shape_and_non_finite_values() -> None:
    class BadModel:
        def encode(self, texts: list[str], **kwargs: object) -> dict[str, np.ndarray]:
            return {"dense_vecs": np.asarray([[float("nan"), 0.0]])}

    embedder = BgeM3Embedder(
        model_name_or_path="bad",
        device="cpu",
        use_fp16=False,
        batch_size=1,
        max_length=32,
        dimension=2,
        model_loader=lambda *_: BadModel(),
    )

    with pytest.raises(EmbeddingError, match="有限数"):
        await embedder.embed(["bad"])


@pytest.mark.asyncio
async def test_embedding_runs_off_event_loop_and_limits_concurrency() -> None:
    model = StubBgeModel(delay=0.08)
    embedder = BgeM3Embedder(
        model_name_or_path="slow",
        device="cpu",
        use_fp16=False,
        batch_size=1,
        max_length=32,
        dimension=3,
        max_concurrency=1,
        model_loader=lambda *_: model,
    )

    started = time.perf_counter()
    first = asyncio.create_task(embedder.embed(["a"]))
    second = asyncio.create_task(embedder.embed(["b"]))
    await asyncio.sleep(0.02)
    assert time.perf_counter() - started < 0.07
    await asyncio.gather(first, second)
    assert time.perf_counter() - started >= 0.14


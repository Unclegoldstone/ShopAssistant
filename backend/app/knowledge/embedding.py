from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np


class EmbeddingError(RuntimeError):
    """Raised when dense embedding generation returns an unusable result."""


class Embedder(Protocol):
    dimension: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _load_bge_model(model_name_or_path: str, use_fp16: bool, device: str) -> Any:
    from FlagEmbedding import BGEM3FlagModel

    return BGEM3FlagModel(
        model_name_or_path,
        use_fp16=use_fp16,
        devices=[device],
    )


class BgeM3Embedder:
    """Lazy, process-local BGE-M3 dense embedder safe for async callers."""

    _models: dict[tuple[object, ...], Any] = {}
    _models_lock = threading.Lock()

    def __init__(
        self,
        *,
        model_name_or_path: str,
        device: str,
        use_fp16: bool,
        batch_size: int,
        max_length: int,
        dimension: int = 1024,
        max_concurrency: int = 1,
        model_loader: Callable[[str, bool, str], Any] = _load_bge_model,
    ) -> None:
        if dimension <= 0 or batch_size <= 0 or max_length <= 0 or max_concurrency <= 0:
            raise ValueError("嵌入配置必须为正数")
        self.model_name_or_path = model_name_or_path
        self.device = device
        self.use_fp16 = use_fp16
        self.batch_size = batch_size
        self.max_length = max_length
        self.dimension = dimension
        self._model_loader = model_loader
        self._model_key = (model_name_or_path, device, use_fp16, id(model_loader))
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def _get_model(self) -> Any:
        model = self._models.get(self._model_key)
        if model is not None:
            return model
        with self._models_lock:
            model = self._models.get(self._model_key)
            if model is None:
                model = self._model_loader(
                    self.model_name_or_path,
                    self.use_fp16,
                    self.device,
                )
                self._models[self._model_key] = model
        return model

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        try:
            result = self._get_model().encode(
                texts,
                batch_size=self.batch_size,
                max_length=self.max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            vectors = np.asarray(result["dense_vecs"], dtype=np.float32)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"BGE-M3 dense 嵌入失败：{type(exc).__name__}") from exc

        expected_shape = (len(texts), self.dimension)
        if vectors.shape != expected_shape:
            raise EmbeddingError(
                f"BGE-M3 向量维度异常：期望 {expected_shape}，实际 {vectors.shape}"
            )
        if not np.isfinite(vectors).all():
            raise EmbeddingError("BGE-M3 返回了非有限数向量")
        return vectors.astype(float).tolist()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = [text.strip() for text in texts]
        if not normalized:
            return []
        if any(not text for text in normalized):
            raise EmbeddingError("待嵌入文本不能为空")
        async with self._semaphore:
            return await asyncio.to_thread(self._embed_sync, normalized)


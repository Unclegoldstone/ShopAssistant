from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class VectorStoreError(RuntimeError):
    """Wraps vector database failures without exposing credentials."""


class VectorStoreSchemaError(VectorStoreError):
    """Raised when an existing collection does not match the required schema."""


@dataclass(frozen=True, slots=True)
class VectorRecord:
    chunk_id: int
    vector: list[float]
    version: str


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    chunk_id: int
    score: float


class VectorStore(Protocol):
    async def ensure_collection(self) -> None: ...

    async def upsert(self, records: Sequence[VectorRecord]) -> None: ...

    async def search(self, vector: Sequence[float], *, top_k: int) -> list[VectorSearchHit]: ...

    async def delete(self, chunk_ids: Sequence[int]) -> None: ...


class MilvusKnowledgeStore:
    def __init__(
        self,
        *,
        uri: str,
        token: str,
        database: str,
        collection: str,
        dimension: int,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        if dimension <= 0 or timeout_seconds <= 0:
            raise ValueError("Milvus 维度和超时必须为正数")
        if client is None:
            from pymilvus import MilvusClient

            client = MilvusClient(
                uri=uri,
                token=token,
                db_name=database,
                timeout=timeout_seconds,
            )
        self._client = client
        self.collection = collection
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds

    async def _call(self, method_name: str, **kwargs: object) -> Any:
        method = getattr(self._client, method_name)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(method, **kwargs),
                timeout=self.timeout_seconds,
            )
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(f"Milvus {method_name} 失败：{type(exc).__name__}") from exc

    @staticmethod
    def _field_by_name(description: dict[str, Any], name: str) -> dict[str, Any] | None:
        fields = description.get("fields") or description.get("schema", {}).get("fields", [])
        return next((field for field in fields if field.get("name") == name), None)

    def _validate_schema(self, description: dict[str, Any]) -> None:
        from pymilvus import DataType

        chunk_id = self._field_by_name(description, "chunk_id")
        vector = self._field_by_name(description, "vector")
        version = self._field_by_name(description, "embedding_version")
        if chunk_id is None or vector is None or version is None:
            raise VectorStoreSchemaError("Milvus knowledge 集合字段不完整，拒绝静默重建")

        chunk_type = chunk_id.get("type", chunk_id.get("data_type"))
        vector_type = vector.get("type", vector.get("data_type"))
        chunk_type_matches = chunk_type == DataType.INT64 or "INT64" in str(chunk_type).upper()
        vector_type_matches = (
            vector_type == DataType.FLOAT_VECTOR or "FLOAT_VECTOR" in str(vector_type).upper()
        )
        if not chunk_type_matches or not chunk_id.get("is_primary"):
            raise VectorStoreSchemaError("Milvus chunk_id 必须是显式 INT64 主键")
        if not vector_type_matches:
            raise VectorStoreSchemaError("Milvus vector 必须是 FLOAT_VECTOR")
        params = vector.get("params") or vector.get("type_params") or {}
        actual_dimension = int(params.get("dim", 0))
        if actual_dimension != self.dimension:
            raise VectorStoreSchemaError(
                f"Milvus 向量维度不匹配：期望 {self.dimension}，实际 {actual_dimension}"
            )

    async def ensure_collection(self) -> None:
        exists = await self._call(
            "has_collection",
            collection_name=self.collection,
            timeout=self.timeout_seconds,
        )
        if exists:
            description = await self._call(
                "describe_collection",
                collection_name=self.collection,
                timeout=self.timeout_seconds,
            )
            self._validate_schema(description)
            return

        from pymilvus import DataType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=self.dimension)
        schema.add_field(
            field_name="embedding_version",
            datatype=DataType.VARCHAR,
            max_length=255,
        )
        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        await self._call(
            "create_collection",
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
            timeout=self.timeout_seconds,
        )

    def _validate_vector(self, vector: Sequence[float]) -> list[float]:
        values = [float(value) for value in vector]
        if len(values) != self.dimension:
            raise VectorStoreError(
                f"向量维度不匹配：期望 {self.dimension}，实际 {len(values)}"
            )
        return values

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        data = [
            {
                "chunk_id": record.chunk_id,
                "vector": self._validate_vector(record.vector),
                "embedding_version": record.version,
            }
            for record in records
        ]
        await self._call(
            "upsert",
            collection_name=self.collection,
            data=data,
            timeout=self.timeout_seconds,
        )

    async def search(
        self,
        vector: Sequence[float],
        *,
        top_k: int,
    ) -> list[VectorSearchHit]:
        if top_k <= 0:
            raise ValueError("top_k 必须为正数")
        result = await self._call(
            "search",
            collection_name=self.collection,
            data=[self._validate_vector(vector)],
            anns_field="vector",
            limit=top_k,
            search_params={"metric_type": "COSINE", "params": {}},
            output_fields=["chunk_id"],
            timeout=self.timeout_seconds,
        )
        rows = result[0] if result else []
        return [
            VectorSearchHit(
                chunk_id=int(row.get("id", row.get("entity", {}).get("chunk_id"))),
                score=float(row.get("distance", row.get("score"))),
            )
            for row in rows
        ]

    async def delete(self, chunk_ids: Sequence[int]) -> None:
        if not chunk_ids:
            return
        await self._call(
            "delete",
            collection_name=self.collection,
            ids=list(chunk_ids),
            timeout=self.timeout_seconds,
        )

    async def count(self) -> int:
        rows = await self._call(
            "query",
            collection_name=self.collection,
            filter="",
            output_fields=["count(*)"],
            timeout=self.timeout_seconds,
        )
        return int(rows[0]["count(*)"]) if rows else 0

    async def drop_collection(self) -> None:
        exists = await self._call(
            "has_collection",
            collection_name=self.collection,
            timeout=self.timeout_seconds,
        )
        if exists:
            await self._call(
                "drop_collection",
                collection_name=self.collection,
                timeout=self.timeout_seconds,
            )

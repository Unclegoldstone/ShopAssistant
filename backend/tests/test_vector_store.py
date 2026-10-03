from __future__ import annotations

import os
import uuid

import pytest

from app.knowledge.vector_store import (
    MilvusKnowledgeStore,
    VectorRecord,
    VectorStoreSchemaError,
)


class FakeMilvusClient:
    def __init__(self, *, description: dict[str, object] | None = None) -> None:
        self.description = description
        self.created: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []
        self.searches: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []

    class IndexParams:
        def __init__(self) -> None:
            self.indexes: list[dict[str, object]] = []

        def add_index(self, **kwargs: object) -> None:
            self.indexes.append(kwargs)

    def prepare_index_params(self) -> IndexParams:
        return self.IndexParams()

    def has_collection(self, *, collection_name: str, **kwargs: object) -> bool:
        return self.description is not None

    def describe_collection(self, *, collection_name: str, **kwargs: object) -> dict[str, object]:
        assert self.description is not None
        return self.description

    def create_collection(self, **kwargs: object) -> None:
        self.created.append(kwargs)

    def upsert(self, **kwargs: object) -> dict[str, int]:
        self.upserts.append(kwargs)
        return {"upsert_count": len(kwargs["data"])}  # type: ignore[arg-type]

    def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
        self.searches.append(kwargs)
        return [[{"id": 8, "distance": 0.91}, {"id": 3, "distance": 0.72}]]

    def delete(self, **kwargs: object) -> dict[str, int]:
        self.deletes.append(kwargs)
        return {"delete_count": 1}


@pytest.mark.asyncio
async def test_store_creates_explicit_cosine_collection_and_maps_operations() -> None:
    client = FakeMilvusClient()
    store = MilvusKnowledgeStore(
        uri="http://milvus:19530",
        token="secret",
        database="default",
        collection="knowledge_test",
        dimension=3,
        timeout_seconds=4,
        client=client,
    )

    await store.ensure_collection()
    await store.upsert([VectorRecord(chunk_id=8, vector=[1.0, 0.0, 0.0], version="v1")])
    hits = await store.search([1.0, 0.0, 0.0], top_k=2)
    await store.delete([8])

    create = client.created[0]
    assert create["collection_name"] == "knowledge_test"
    assert create["consistency_level"] == "Strong"
    assert client.upserts[0]["data"] == [
        {"chunk_id": 8, "vector": [1.0, 0.0, 0.0], "embedding_version": "v1"}
    ]
    assert [(hit.chunk_id, hit.score) for hit in hits] == [(8, 0.91), (3, 0.72)]
    assert client.deletes[0]["ids"] == [8]


@pytest.mark.asyncio
async def test_store_rejects_existing_collection_with_wrong_dimension() -> None:
    description = {
        "fields": [
            {"name": "chunk_id", "type": "INT64", "is_primary": True, "auto_id": False},
            {"name": "vector", "type": "FLOAT_VECTOR", "params": {"dim": 4}},
            {"name": "embedding_version", "type": "VARCHAR"},
        ]
    }
    store = MilvusKnowledgeStore(
        uri="http://milvus:19530",
        token="secret",
        database="default",
        collection="knowledge_test",
        dimension=3,
        timeout_seconds=4,
        client=FakeMilvusClient(description=description),
    )

    with pytest.raises(VectorStoreSchemaError, match="维度"):
        await store.ensure_collection()


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_MILVUS_TESTS") != "1", reason="需要真实 Milvus")
@pytest.mark.asyncio
async def test_real_milvus_upsert_search_and_delete_is_idempotent() -> None:
    collection = f"test_knowledge_{uuid.uuid4().hex}"
    store = MilvusKnowledgeStore(
        uri=os.getenv("MILVUS_URI", "http://127.0.0.1:19530"),
        token=os.getenv("MILVUS_TOKEN", "root:Milvus"),
        database="default",
        collection=collection,
        dimension=3,
        timeout_seconds=10,
    )
    try:
        await store.ensure_collection()
        await store.upsert(
            [
                VectorRecord(1, [1.0, 0.0, 0.0], "test"),
                VectorRecord(2, [0.0, 1.0, 0.0], "test"),
            ]
        )
        await store.upsert([VectorRecord(1, [0.9, 0.1, 0.0], "test-2")])
        assert await store.count() == 2
        hits = await store.search([1.0, 0.0, 0.0], top_k=1)
        assert hits[0].chunk_id == 1
        await store.delete([1])
        assert await store.count() == 1
    finally:
        await store.drop_collection()

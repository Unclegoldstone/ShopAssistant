from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from app.config import PROJECT_ROOT, Settings
from app.db.session import create_database_runtime
from app.knowledge.embedding import BgeM3Embedder
from app.knowledge.markdown import MarkdownKnowledgeSplitter
from app.knowledge.vector_store import MilvusKnowledgeStore
from app.services.knowledge_ingestion import KnowledgeIngestionService
from app.services.knowledge_vectorization import KnowledgeVectorizationWorker


async def run(command: str) -> None:
    settings = Settings()
    runtime = create_database_runtime(settings)
    try:
        splitter = MarkdownKnowledgeSplitter(
            chunk_size=settings.knowledge_chunk_size,
            chunk_overlap=settings.knowledge_chunk_overlap,
        )
        ingestion = KnowledgeIngestionService(runtime.session_factory, splitter=splitter)
        if command in {"ingest", "all"}:
            markdown = await ingestion.ingest_markdown(PROJECT_ROOT / "knowledge" / "source")
            faq = await ingestion.ingest_faqs()
            print(f"ingest markdown={markdown} faq={faq}")

        if command in {"vectorize", "all"}:
            embedder = BgeM3Embedder(
                model_name_or_path=settings.bge_model_name_or_path,
                device=settings.bge_offline_device,
                use_fp16=settings.bge_use_fp16,
                batch_size=settings.bge_batch_size,
                max_length=settings.bge_max_length,
            )
            store = MilvusKnowledgeStore(
                uri=str(settings.milvus_uri),
                token=settings.milvus_token.get_secret_value(),
                database=settings.milvus_database,
                collection=settings.milvus_collection,
                dimension=embedder.dimension,
                timeout_seconds=settings.milvus_timeout_seconds,
            )
            worker = KnowledgeVectorizationWorker(
                session_factory=runtime.session_factory,
                embedder=embedder,
                vector_store=store,
                embedding_model=settings.bge_model_name_or_path,
                embedding_version=settings.bge_model_name_or_path,
                batch_size=settings.knowledge_vector_batch_size,
                lease_timeout=timedelta(seconds=settings.knowledge_vector_lease_seconds),
                max_attempts=settings.knowledge_vector_max_attempts,
            )
            print(f"vectorize {await worker.run_until_idle()}")
    finally:
        await runtime.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="构建并补偿 ShopAssistant 知识库")
    parser.add_argument("command", choices=("ingest", "vectorize", "all"))
    args = parser.parse_args()
    asyncio.run(run(args.command))


if __name__ == "__main__":
    main()

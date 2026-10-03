def test_knowledge_runtime_dependencies_are_importable() -> None:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from FlagEmbedding import FlagAutoModel
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )
    from pymilvus import MilvusClient
    from python_multipart import __version__ as multipart_version

    assert AsyncIOScheduler is not None
    assert FlagAutoModel is not None
    assert MarkdownHeaderTextSplitter is not None
    assert RecursiveCharacterTextSplitter is not None
    assert MilvusClient is not None
    assert multipart_version


def test_fastapi_runtime_only_imports_packaged_app_modules() -> None:
    from app.main import KnowledgePipeline

    assert KnowledgePipeline.__module__ == "app.services.knowledge_pipeline"

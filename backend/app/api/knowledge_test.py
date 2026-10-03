from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.dependencies import get_knowledge_test_service
from app.knowledge.test_schemas import (
    KbIngestResponse,
    KbPreviewResponse,
    KbSearchRequest,
    KbVectorizeRequest,
)
from app.services.knowledge_test import (
    KnowledgeTestService,
    KnowledgeTestUnavailableError,
    KnowledgeUploadError,
)

router = APIRouter(prefix="/v1/tests/knowledge", tags=["knowledge-test-lab"])


def _raise_error(exc: Exception) -> NoReturn:
    if isinstance(exc, KnowledgeUploadError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    if isinstance(exc, KnowledgeTestUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "knowledge_runtime_unavailable", "message": str(exc)},
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "knowledge_test_failed", "message": type(exc).__name__},
    ) from exc


async def _read_upload(file: UploadFile, service: KnowledgeTestService) -> bytes:
    try:
        return await file.read(service.upload_max_bytes + 1)
    finally:
        await file.close()


@router.post("/preview", response_model=KbPreviewResponse)
async def preview_markdown(
    file: Annotated[UploadFile, File(description="UTF-8 Markdown 文件")],
    service: Annotated[KnowledgeTestService, Depends(get_knowledge_test_service)],
) -> KbPreviewResponse:
    try:
        return service.preview(file.filename or "", await _read_upload(file, service))
    except Exception as exc:
        _raise_error(exc)


@router.post("/ingest", response_model=KbIngestResponse)
async def ingest_markdown(
    file: Annotated[UploadFile, File(description="UTF-8 Markdown 文件")],
    service: Annotated[KnowledgeTestService, Depends(get_knowledge_test_service)],
) -> KbIngestResponse:
    try:
        return await service.ingest(file.filename or "", await _read_upload(file, service))
    except Exception as exc:
        _raise_error(exc)


@router.post("/vectorize")
async def vectorize_test_knowledge(
    payload: KbVectorizeRequest,
    service: Annotated[KnowledgeTestService, Depends(get_knowledge_test_service)],
) -> object:
    try:
        return await service.vectorize(payload.fault_stage)
    except Exception as exc:
        _raise_error(exc)


@router.post("/search")
async def search_knowledge(
    payload: KbSearchRequest,
    service: Annotated[KnowledgeTestService, Depends(get_knowledge_test_service)],
) -> object:
    try:
        return {
            "query": payload.query,
            "top_k": payload.top_k,
            "matches": await service.search(payload.query, top_k=payload.top_k),
        }
    except Exception as exc:
        _raise_error(exc)


@router.post("/pipeline")
async def run_knowledge_pipeline(
    service: Annotated[KnowledgeTestService, Depends(get_knowledge_test_service)],
) -> object:
    try:
        return await service.run_pipeline()
    except Exception as exc:
        _raise_error(exc)


@router.get("/snapshot")
async def knowledge_snapshot(
    service: Annotated[KnowledgeTestService, Depends(get_knowledge_test_service)],
) -> object:
    try:
        return await service.snapshot()
    except Exception as exc:
        _raise_error(exc)

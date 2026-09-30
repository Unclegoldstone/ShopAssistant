from __future__ import annotations

import logging
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_faq_crud_service
from app.schemas import FaqCreate, FaqItem, FaqUpdate
from app.services.faq_crud import FaqCrudService, FaqNotFoundError, FaqReadOnlyError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/tests/faqs", tags=["test-lab"])


def _raise_service_error(exc: Exception) -> NoReturn:
    if isinstance(exc, FaqNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "faq_not_found", "message": "指定的 FAQ 记录不存在"},
        ) from exc
    if isinstance(exc, FaqReadOnlyError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "faq_read_only", "message": "业务 FAQ 只读，仅功能测试记录可变更"},
        ) from exc
    logger.error("faq CRUD failed error_type=%s", type(exc).__name__)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "faq_crud_failed", "message": "数据库操作失败，请稍后重试"},
    ) from exc


@router.get("", response_model=list[FaqItem])
async def list_faqs(
    service: Annotated[FaqCrudService, Depends(get_faq_crud_service)],
) -> list[FaqItem]:
    try:
        return await service.list_items()
    except Exception as exc:
        _raise_service_error(exc)


@router.post("", response_model=FaqItem, status_code=status.HTTP_201_CREATED)
async def create_faq(
    payload: FaqCreate,
    service: Annotated[FaqCrudService, Depends(get_faq_crud_service)],
) -> FaqItem:
    try:
        return await service.create(payload)
    except Exception as exc:
        _raise_service_error(exc)


@router.put("/{faq_id}", response_model=FaqItem)
async def update_faq(
    faq_id: int,
    payload: FaqUpdate,
    service: Annotated[FaqCrudService, Depends(get_faq_crud_service)],
) -> FaqItem:
    try:
        return await service.update(faq_id, payload)
    except Exception as exc:
        _raise_service_error(exc)


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: int,
    service: Annotated[FaqCrudService, Depends(get_faq_crud_service)],
) -> Response:
    try:
        await service.delete(faq_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        _raise_service_error(exc)

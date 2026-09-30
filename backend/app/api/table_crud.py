from __future__ import annotations

import logging
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_table_crud_service
from app.schemas import DatabaseTableName, TableRecord, TableRecordWrite
from app.services.table_crud import (
    TableCrudService,
    TableRecordConflictError,
    TableRecordNotFoundError,
    TableRecordReadOnlyError,
    TableRecordValidationError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/tests/tables", tags=["test-lab"])


def _raise_service_error(exc: Exception) -> NoReturn:
    if isinstance(exc, TableRecordNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "record_not_found", "message": "指定记录不存在"},
        ) from exc
    if isinstance(exc, TableRecordReadOnlyError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "operation_forbidden", "message": "该记录不允许执行此操作"},
        ) from exc
    if isinstance(exc, TableRecordValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_record", "message": str(exc)},
        ) from exc
    if isinstance(exc, TableRecordConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "record_conflict", "message": str(exc)},
        ) from exc
    logger.error("table CRUD failed error_type=%s", type(exc).__name__)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "table_crud_failed", "message": "数据库操作失败，请稍后重试"},
    ) from exc


@router.get("/{table_name}", response_model=list[TableRecord])
async def list_records(
    table_name: DatabaseTableName,
    service: Annotated[TableCrudService, Depends(get_table_crud_service)],
) -> list[TableRecord]:
    try:
        return await service.list_records(table_name)
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/{table_name}", response_model=TableRecord, status_code=status.HTTP_201_CREATED)
async def create_record(
    table_name: DatabaseTableName,
    payload: TableRecordWrite,
    service: Annotated[TableCrudService, Depends(get_table_crud_service)],
) -> TableRecord:
    try:
        return await service.create(table_name, payload)
    except Exception as exc:
        _raise_service_error(exc)


@router.put("/{table_name}/{record_key}", response_model=TableRecord)
async def update_record(
    table_name: DatabaseTableName,
    record_key: str,
    payload: TableRecordWrite,
    service: Annotated[TableCrudService, Depends(get_table_crud_service)],
) -> TableRecord:
    try:
        return await service.update(table_name, record_key, payload)
    except Exception as exc:
        _raise_service_error(exc)


@router.delete("/{table_name}/{record_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    table_name: DatabaseTableName,
    record_key: str,
    service: Annotated[TableCrudService, Depends(get_table_crud_service)],
) -> Response:
    try:
        await service.delete(table_name, record_key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        _raise_service_error(exc)

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_database_test_service
from app.schemas import DatabaseTestResult
from app.services.database_test import DatabaseTestService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/v1/tests/database", response_model=DatabaseTestResult)
async def run_database_test(
    service: Annotated[DatabaseTestService, Depends(get_database_test_service)],
) -> DatabaseTestResult:
    try:
        return await service.run()
    except Exception as exc:
        logger.error("database self-test failed error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_test_failed",
                "message": "数据库测试未通过，请确认 MySQL 容器和连接配置",
            },
        ) from exc

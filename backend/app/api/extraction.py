from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_extraction_service
from app.schemas import AfterSalesInfo, AfterSalesRequest
from app.services.extraction import ExtractionService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/v1/after-sales/extract", response_model=AfterSalesInfo)
async def extract_after_sales(
    payload: AfterSalesRequest,
    extraction_service: Annotated[ExtractionService, Depends(get_extraction_service)],
) -> AfterSalesInfo:
    try:
        return await extraction_service.extract(payload.text)
    except Exception as exc:
        logger.error("structured extraction failed error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "structured_output_error",
                "message": "结构化抽取暂时不可用，请稍后重试",
            },
        ) from exc

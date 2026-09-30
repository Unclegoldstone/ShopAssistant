from __future__ import annotations

import logging
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_conversation_history_service
from app.schemas import (
    ConversationHistory,
    ConversationId,
    ConversationSummary,
    UserId,
)
from app.services.conversation_history import (
    ConversationHistoryNotFoundError,
    ConversationHistoryService,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def _raise_history_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ConversationHistoryNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "conversation_not_found",
                "message": "指定会话不存在",
            },
        ) from exc
    logger.error("conversation history failed error_type=%s", type(exc).__name__)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "conversation_history_failed",
            "message": "会话历史暂时无法读取",
        },
    ) from exc


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    user: UserId,
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
) -> list[ConversationSummary]:
    try:
        return await service.list_conversations(user)
    except Exception as exc:
        _raise_history_error(exc)


@router.get("/{conversation_id}/messages", response_model=ConversationHistory)
async def get_conversation_history(
    conversation_id: ConversationId,
    user: UserId,
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
) -> ConversationHistory:
    try:
        return await service.get_history(conversation_id, user)
    except Exception as exc:
        _raise_history_error(exc)

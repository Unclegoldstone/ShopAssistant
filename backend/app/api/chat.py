from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.config import Settings
from app.conversation_store import InputTooLongError
from app.dependencies import get_chat_service, get_settings
from app.schemas import ChatCompletionRequest
from app.services.chat import ChatService

router = APIRouter()


@router.get("/v1/models")
async def list_models(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            {
                "id": settings.model_name,
                "object": "model",
                "created": 0,
                "owned_by": "aliyun",
            }
        ],
    }


@router.post("/v1/chat/completions", response_class=StreamingResponse)
async def create_chat_completion(
    payload: ChatCompletionRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    if payload.model != settings.model_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "model_mismatch",
                "message": "请求模型与服务端配置不一致",
            },
        )

    user_input = payload.messages[0].content
    try:
        await chat_service.validate_input(payload.conversation_id, user_input)
    except InputTooLongError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "input_too_long", "message": str(exc)},
        ) from exc

    return StreamingResponse(
        chat_service.stream(payload.conversation_id, user_input),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

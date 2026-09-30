from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.config import Settings
from app.conversation_store import ConversationAccessError, InputTooLongError
from app.dependencies import get_chat_service, get_settings
from app.schemas import ChatCompletionRequest
from app.services.chat import ChatPreparationError, ChatService

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
        prepared = await chat_service.prepare_turn(
            payload.conversation_id,
            user_input,
            user_id=payload.user,
        )
    except InputTooLongError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "input_too_long", "message": str(exc)},
        ) from exc
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "conversation_not_found",
                "message": "指定会话不存在",
            },
        ) from exc
    except ChatPreparationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "chat_preparation_error", "message": str(exc)},
        ) from exc

    response_headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    if prepared.tool_name is not None:
        response_headers["X-Shop-Assistant-Tool"] = prepared.tool_name

    return StreamingResponse(
        chat_service.stream_prepared(prepared),
        media_type="text/event-stream",
        headers=response_headers,
    )

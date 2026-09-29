from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ConversationId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(StrictModel):
    role: Literal["user"]
    content: NonBlankText


class ChatCompletionRequest(StrictModel):
    model: NonBlankText
    conversation_id: ConversationId
    messages: list[ChatMessage] = Field(min_length=1, max_length=1)
    stream: Literal[True] = True


class AfterSalesRequest(StrictModel):
    text: NonBlankText


class AfterSalesInfo(StrictModel):
    """Fixed fields extracted from an after-sales description."""

    order_id: str | None = Field(description="用户明确提供的订单号；原文缺失时为 null")
    request_type: str | None = Field(description="用户的售后诉求类型；原文缺失时为 null")
    expected_solution: str | None = Field(description="用户明确期望的解决方案；原文缺失时为 null")

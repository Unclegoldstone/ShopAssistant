from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

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
UserId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
FaqQuestion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
FaqAnswer = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
]
FaqCategory = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
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
    user: UserId = "demo-user"


class AfterSalesRequest(StrictModel):
    text: NonBlankText


class AfterSalesInfo(StrictModel):
    """Fixed fields extracted from an after-sales description."""

    order_id: str | None = Field(description="用户明确提供的订单号；原文缺失时为 null")
    request_type: str | None = Field(description="用户的售后诉求类型；原文缺失时为 null")
    expected_solution: str | None = Field(description="用户明确期望的解决方案；原文缺失时为 null")


class DatabaseTestStep(StrictModel):
    operation: Literal["connect", "create", "read", "update", "delete"]
    ok: bool
    detail: str


class DatabaseTestResult(StrictModel):
    ok: bool
    database: str
    steps: list[DatabaseTestStep]


class FaqCreate(StrictModel):
    question: FaqQuestion
    answer: FaqAnswer
    category: FaqCategory


class FaqUpdate(FaqCreate):
    pass


class FaqItem(FaqCreate):
    id: int


DatabaseTableName = Literal["faq", "conversations", "messages", "tickets"]


class TableRecordWrite(StrictModel):
    values: dict[str, Any]


class TableRecord(StrictModel):
    key: str
    values: dict[str, Any]
    editable: bool = False
    can_update: bool = False
    can_delete: bool = False


class ConversationSummary(StrictModel):
    id: ConversationId
    status: Literal["active", "waiting_human", "closed", "failed"]
    created_at: datetime
    last_message_at: datetime
    preview: str
    message_count: int = Field(ge=0)


class ConversationHistoryMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: NonBlankText
    tool_name: str | None = None


class ConversationHistory(StrictModel):
    conversation_id: ConversationId
    messages: list[ConversationHistoryMessage]

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.dependencies import get_conversation_history_service
from app.main import create_app
from app.schemas import (
    ConversationHistory,
    ConversationHistoryMessage,
    ConversationSummary,
)
from app.services.conversation_history import ConversationHistoryNotFoundError
from tests.fakes import FakeStreamingModel
from tests.test_chat_api import make_settings


class FakeConversationHistoryService:
    async def list_conversations(self, user_id: str) -> list[ConversationSummary]:
        return [
            ConversationSummary(
                id=f"conversation-{user_id}",
                status="active",
                created_at=datetime(2026, 9, 29, 10, 0, 0),
                last_message_at=datetime(2026, 9, 29, 10, 5, 0),
                preview=f"{user_id} 的问题",
                message_count=2,
            )
        ]

    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
    ) -> ConversationHistory:
        if conversation_id != f"conversation-{user_id}":
            raise ConversationHistoryNotFoundError(conversation_id)
        return ConversationHistory(
            conversation_id=conversation_id,
            messages=[
                ConversationHistoryMessage(
                    role="user",
                    content=f"{user_id} 的问题",
                ),
                ConversationHistoryMessage(
                    role="assistant",
                    content=f"{user_id} 的回答",
                    tool_name="query_faq",
                ),
            ],
        )


class FailingConversationHistoryService:
    async def list_conversations(self, user_id: str) -> list[ConversationSummary]:
        raise RuntimeError("mysql-password-must-not-leak")


def make_client() -> TestClient:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    app.dependency_overrides[get_conversation_history_service] = (
        FakeConversationHistoryService
    )
    return TestClient(app)


def test_conversation_history_api_lists_and_reads_current_user() -> None:
    with make_client() as client:
        listed = client.get("/v1/conversations", params={"user": "demo-user"})
        history = client.get(
            "/v1/conversations/conversation-demo-user/messages",
            params={"user": "demo-user"},
        )

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "conversation-demo-user"
    assert listed.json()[0]["preview"] == "demo-user 的问题"
    assert history.status_code == 200
    assert history.json()["messages"][1] == {
        "role": "assistant",
        "content": "demo-user 的回答",
        "tool_name": "query_faq",
    }


def test_conversation_history_api_returns_404_for_cross_user_access() -> None:
    with make_client() as client:
        response = client.get(
            "/v1/conversations/conversation-user1/messages",
            params={"user": "demo-user"},
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "conversation_not_found"


def test_conversation_history_api_validates_user_and_conversation_id() -> None:
    with make_client() as client:
        invalid_user = client.get("/v1/conversations", params={"user": ""})
        invalid_conversation = client.get(
            "/v1/conversations/not allowed/messages",
            params={"user": "demo-user"},
        )

    assert invalid_user.status_code == 422
    assert invalid_conversation.status_code == 422


def test_conversation_history_api_hides_database_errors() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    app.dependency_overrides[get_conversation_history_service] = (
        FailingConversationHistoryService
    )

    with TestClient(app) as client:
        response = client.get("/v1/conversations", params={"user": "demo-user"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "conversation_history_failed"
    assert "mysql-password" not in response.text

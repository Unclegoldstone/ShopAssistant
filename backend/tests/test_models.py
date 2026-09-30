from __future__ import annotations

from sqlalchemy import JSON, Boolean, Enum, ForeignKeyConstraint
from sqlalchemy.dialects.mysql import LONGTEXT

from app.db.base import Base
from app.models import (
    Conversation,
    ConversationStatus,
    Faq,
    Message,
    MessageRole,
    Ticket,
    TicketStatus,
)


def test_chapter_two_declares_exactly_four_domain_tables() -> None:
    assert set(Base.metadata.tables) == {
        "faq",
        "conversations",
        "messages",
        "tickets",
    }


def test_faq_columns_and_indexes_match_the_design() -> None:
    table = Faq.__table__

    assert table.c.id.primary_key
    assert table.c.id.autoincrement is True
    assert table.c.question.nullable is False
    assert table.c.answer.nullable is False
    assert table.c.category.nullable is False
    assert isinstance(table.c.is_test.type, Boolean)
    assert table.c.is_test.nullable is False
    assert table.c.is_test.server_default is not None
    assert table.c.question.index
    assert table.c.category.index


def test_conversation_status_is_a_database_enum() -> None:
    table = Conversation.__table__

    assert table.c.id.primary_key
    assert table.c.user_id.index
    assert isinstance(table.c.status.type, Enum)
    assert set(table.c.status.type.enums) == {status.value for status in ConversationStatus}
    assert table.c.created_at.server_default is not None


def test_message_keeps_tool_call_data_and_cascades_with_conversation() -> None:
    table = Message.__table__
    foreign_key = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    )

    assert isinstance(table.c.role.type, Enum)
    assert set(table.c.role.type.enums) == {role.value for role in MessageRole}
    assert isinstance(table.c.content.type, LONGTEXT)
    assert isinstance(table.c.tool_calls.type, JSON)
    assert table.c.tool_calls.nullable
    assert table.c.tool_call_id.nullable
    assert table.c.conversation_id.index
    assert foreign_key.ondelete == "CASCADE"


def test_ticket_columns_and_status_match_the_design() -> None:
    table = Ticket.__table__

    assert table.c.ticket_no.primary_key
    assert table.c.conversation_id.index
    assert table.c.issue_description.nullable is False
    assert table.c.ticket_type.nullable is False
    assert isinstance(table.c.status.type, Enum)
    assert set(table.c.status.type.enums) == {status.value for status in TicketStatus}
    assert table.c.created_at.server_default is not None

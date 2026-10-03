from __future__ import annotations

from sqlalchemy import JSON, Boolean, Enum, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT

from app.db.base import Base
from app.models import (
    Conversation,
    ConversationStatus,
    Faq,
    KnowledgeChunk,
    KnowledgeContentType,
    KnowledgeMiningRun,
    KnowledgeMiningRunStatus,
    KnowledgeSourceType,
    KnowledgeStaging,
    KnowledgeStagingStatus,
    KnowledgeVectorStatus,
    Message,
    MessageRole,
    Ticket,
    TicketStatus,
)


def test_metadata_declares_chapter_two_and_knowledge_tables() -> None:
    assert set(Base.metadata.tables) == {
        "faq",
        "conversations",
        "messages",
        "tickets",
        "knowledge_chunks",
        "knowledge_staging",
        "knowledge_mining_runs",
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


def test_knowledge_chunk_keeps_authoritative_text_and_vector_state() -> None:
    table = KnowledgeChunk.__table__

    assert table.c.id.primary_key
    assert table.c.id.autoincrement is True
    assert isinstance(table.c.source_type.type, Enum)
    assert set(table.c.source_type.type.enums) == {
        item.value for item in KnowledgeSourceType
    }
    assert table.c.source_key.unique
    assert table.c.source_revision.nullable is False
    assert isinstance(table.c.questions.type, JSON)
    assert isinstance(table.c.answer.type, LONGTEXT)
    assert isinstance(table.c.section_path.type, JSON)
    assert isinstance(table.c.content_type.type, Enum)
    assert set(table.c.content_type.type.enums) == {
        item.value for item in KnowledgeContentType
    }
    assert isinstance(table.c.is_critical.type, Boolean)
    assert isinstance(table.c.vector_status.type, Enum)
    assert set(table.c.vector_status.type.enums) == {
        item.value for item in KnowledgeVectorStatus
    }
    assert table.c.content_fingerprint.index
    assert table.c.vector_status.index
    assert table.c.vector_attempts.server_default is not None
    assert table.c.is_active.server_default is not None
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None

    foreign_keys = {
        next(iter(constraint.columns)).name: constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys["previous_chunk_id"].referred_table.name == "knowledge_chunks"
    assert foreign_keys["previous_chunk_id"].ondelete == "SET NULL"
    assert foreign_keys["next_chunk_id"].referred_table.name == "knowledge_chunks"
    assert foreign_keys["next_chunk_id"].ondelete == "SET NULL"


def test_knowledge_staging_tracks_source_range_and_deduplication() -> None:
    table = KnowledgeStaging.__table__

    assert table.c.id.primary_key
    assert isinstance(table.c.questions.type, JSON)
    assert isinstance(table.c.answer.type, LONGTEXT)
    assert isinstance(table.c.status.type, Enum)
    assert set(table.c.status.type.enums) == {
        item.value for item in KnowledgeStagingStatus
    }
    assert table.c.content_fingerprint.index
    assert table.c.status.index
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "conversation_id",
        "first_message_id",
        "last_message_id",
        "item_index",
    ) in unique_columns


def test_knowledge_mining_run_tracks_cursor_counts_and_status() -> None:
    table = KnowledgeMiningRun.__table__

    assert table.c.id.primary_key
    assert table.c.batch_id.unique
    assert isinstance(table.c.status.type, Enum)
    assert set(table.c.status.type.enums) == {
        item.value for item in KnowledgeMiningRunStatus
    }
    assert table.c.status.index
    assert table.c.processed_conversations.server_default is not None
    assert table.c.processed_messages.server_default is not None
    assert table.c.extracted_count.server_default is not None
    assert table.c.promoted_count.server_default is not None
    assert table.c.started_at.server_default is not None
    assert table.c.finished_at.nullable

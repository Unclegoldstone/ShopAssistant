"""add knowledge base tables

Revision ID: c3a1b2c3d4e5
Revises: 9d5c2a71b3e4
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "c3a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "9d5c2a71b3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_mining_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "completed",
                "failed",
                name="knowledge_mining_run_status",
            ),
            server_default="running",
            nullable=False,
        ),
        sa.Column("cursor_start_message_id", sa.BigInteger(), nullable=True),
        sa.Column("cursor_end_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "processed_conversations",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "processed_messages",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "extracted_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "promoted_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id"),
    )
    op.create_index(
        op.f("ix_knowledge_mining_runs_status"),
        "knowledge_mining_runs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "source_type",
            sa.Enum("markdown", "faq", "conversation", name="knowledge_source_type"),
            nullable=False,
        ),
        sa.Column("source_key", sa.String(length=512), nullable=False),
        sa.Column("source_revision", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("answer", mysql.LONGTEXT(), nullable=False),
        sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column(
            "content_type",
            sa.Enum(
                "policy",
                "product_faq",
                "after_sales_manual",
                "conversation_qa",
                name="knowledge_content_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "is_critical",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("previous_chunk_id", sa.BigInteger(), nullable=True),
        sa.Column("next_chunk_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "vector_status",
            sa.Enum(
                "pending",
                "vectorizing",
                "vectorized",
                "failed",
                "pending_delete",
                name="knowledge_vector_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("vector_id", sa.String(length=64), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("embedding_version", sa.String(length=128), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "vector_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("vector_error", sa.Text(), nullable=True),
        sa.Column("vectorizing_started_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["next_chunk_id"],
            ["knowledge_chunks.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_chunk_id"],
            ["knowledge_chunks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key"),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_content_fingerprint"),
        "knowledge_chunks",
        ["content_fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_chunks_vector_status"),
        "knowledge_chunks",
        ["vector_status"],
        unique=False,
    )

    op.create_table(
        "knowledge_staging",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("mining_run_id", sa.BigInteger(), nullable=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("first_message_id", sa.BigInteger(), nullable=False),
        sa.Column("last_message_id", sa.BigInteger(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("answer", mysql.LONGTEXT(), nullable=False),
        sa.Column(
            "is_critical",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "extracted",
                "exact_duplicate",
                "candidate",
                "merged",
                "conflict",
                "promoted",
                "rejected",
                "failed",
                name="knowledge_staging_status",
            ),
            server_default="extracted",
            nullable=False,
        ),
        sa.Column("duplicate_target_chunk_id", sa.BigInteger(), nullable=True),
        sa.Column("promoted_chunk_id", sa.BigInteger(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("extraction_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_target_chunk_id"],
            ["knowledge_chunks.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["mining_run_id"],
            ["knowledge_mining_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["promoted_chunk_id"],
            ["knowledge_chunks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "first_message_id",
            "last_message_id",
            "item_index",
            name="uq_knowledge_staging_source_range_item",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_staging_content_fingerprint"),
        "knowledge_staging",
        ["content_fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_staging_conversation_id"),
        "knowledge_staging",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_staging_mining_run_id"),
        "knowledge_staging",
        ["mining_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_staging_status"),
        "knowledge_staging",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("knowledge_staging")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_mining_runs")

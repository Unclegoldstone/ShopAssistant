from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from app.config import Settings
from app.db.session import create_database_runtime

BACKEND_ROOT = Path(__file__).resolve().parents[1]


async def get_table_names(database_url: str) -> set[str]:
    runtime = create_database_runtime(
        Settings(
            _env_file=None,
            model_base_url="https://example.test/v1",
            model_name="qwen-test",
            model_api_key="model-secret",
            database_url=database_url,
        )
    )
    try:
        async with runtime.engine.connect() as connection:
            return set(
                await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_table_names()
                )
            )
    finally:
        await runtime.dispose()


@pytest.mark.skipif(
    not os.getenv("SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL"),
    reason="requires an explicit isolated migration test database URL",
)
def test_alembic_upgrade_and_downgrade_are_reversible() -> None:
    config = Config(BACKEND_ROOT / "alembic.ini")
    database_url = os.environ["SHOP_ASSISTANT_MIGRATION_TEST_DATABASE_URL"]
    config.attributes["database_url"] = database_url

    command.downgrade(config, "base")
    try:
        assert asyncio.run(get_table_names(database_url)) <= {"alembic_version"}

        command.upgrade(config, "head")
        assert asyncio.run(get_table_names(database_url)) == {
            "alembic_version",
            "conversations",
            "faq",
            "knowledge_chunks",
            "knowledge_mining_runs",
            "knowledge_staging",
            "messages",
            "tickets",
        }
    finally:
        command.upgrade(config, "head")

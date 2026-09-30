from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.config import Settings
from app.db.session import create_database_runtime


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        model_base_url="https://example.test/v1",
        model_name="qwen-test",
        model_api_key="model-secret",
        database_url="mysql+asyncmy://shop:db-secret@localhost:3306/shop_assistant",
    )


@pytest.mark.asyncio
async def test_database_runtime_uses_async_mysql_and_safe_session_defaults() -> None:
    runtime = create_database_runtime(make_settings())

    assert runtime.engine.url.drivername == "mysql+asyncmy"
    assert runtime.engine.pool._pre_ping is True
    assert runtime.session_factory.kw["expire_on_commit"] is False

    await runtime.dispose()


@pytest.mark.skipif(
    os.getenv("SHOP_ASSISTANT_RUN_MYSQL_TESTS") != "1",
    reason="requires the Docker MySQL integration environment",
)
@pytest.mark.asyncio
async def test_database_runtime_connects_to_mysql() -> None:
    runtime = create_database_runtime(
        Settings(
            _env_file=None,
            model_base_url="https://example.test/v1",
            model_name="qwen-test",
            model_api_key="model-secret",
        )
    )

    try:
        async with runtime.engine.connect() as connection:
            result = await connection.execute(text("SELECT DATABASE(), 1"))
            database_name, value = result.one()

        assert database_name == "shop_assistant"
        assert value == 1
    finally:
        await runtime.dispose()

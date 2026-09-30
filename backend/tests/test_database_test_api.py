from __future__ import annotations

from fastapi.testclient import TestClient

from app.dependencies import get_database_test_service
from app.main import create_app
from app.schemas import DatabaseTestResult, DatabaseTestStep
from tests.fakes import FakeStreamingModel
from tests.test_chat_api import make_settings


class FakeDatabaseTestService:
    async def run(self) -> DatabaseTestResult:
        return DatabaseTestResult(
            ok=True,
            database="shop_assistant",
            steps=[
                DatabaseTestStep(operation="connect", ok=True, detail="数据库连接正常"),
                DatabaseTestStep(operation="create", ok=True, detail="临时记录新增成功"),
                DatabaseTestStep(operation="read", ok=True, detail="临时记录查询成功"),
                DatabaseTestStep(operation="update", ok=True, detail="临时记录更新成功"),
                DatabaseTestStep(operation="delete", ok=True, detail="临时记录删除成功"),
            ],
        )


def test_database_test_endpoint_returns_crud_steps() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    app.dependency_overrides[get_database_test_service] = FakeDatabaseTestService

    with TestClient(app) as client:
        response = client.post("/v1/tests/database")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert [step["operation"] for step in response.json()["steps"]] == [
        "connect",
        "create",
        "read",
        "update",
        "delete",
    ]


class FailingDatabaseTestService:
    async def run(self) -> DatabaseTestResult:
        raise RuntimeError("mysql://secret-user:secret-password@example.invalid")


def test_database_test_endpoint_sanitizes_database_errors() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    app.dependency_overrides[get_database_test_service] = FailingDatabaseTestService

    with TestClient(app) as client:
        response = client.post("/v1/tests/database")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_test_failed"
    assert "secret-password" not in response.text

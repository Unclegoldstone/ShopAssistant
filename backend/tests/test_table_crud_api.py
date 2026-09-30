from __future__ import annotations

from fastapi.testclient import TestClient

from app.dependencies import get_table_crud_service
from app.main import create_app
from app.schemas import TableRecord, TableRecordWrite
from tests.fakes import FakeStreamingModel
from tests.test_chat_api import make_settings


class FakeTableCrudService:
    async def list_records(self, table_name: str) -> list[TableRecord]:
        return [TableRecord(key="1", values={"table": table_name, "name": "demo"})]

    async def create(self, table_name: str, payload: TableRecordWrite) -> TableRecord:
        return TableRecord(key="new", values={"table": table_name, **payload.values})

    async def update(
        self,
        table_name: str,
        record_key: str,
        payload: TableRecordWrite,
    ) -> TableRecord:
        return TableRecord(key=record_key, values={"table": table_name, **payload.values})

    async def delete(self, table_name: str, record_key: str) -> None:
        return None


def make_client() -> TestClient:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    app.dependency_overrides[get_table_crud_service] = FakeTableCrudService
    return TestClient(app)


def test_table_crud_api_supports_all_four_tables() -> None:
    with make_client() as client:
        for table_name in ("faq", "conversations", "messages", "tickets"):
            listed = client.get(f"/v1/tests/tables/{table_name}")
            created = client.post(
                f"/v1/tests/tables/{table_name}",
                json={"values": {"name": "created"}},
            )
            updated = client.put(
                f"/v1/tests/tables/{table_name}/new",
                json={"values": {"name": "updated"}},
            )
            deleted = client.delete(f"/v1/tests/tables/{table_name}/new")

            assert listed.status_code == 200
            assert listed.json()[0]["values"]["table"] == table_name
            assert created.status_code == 201
            assert updated.status_code == 200
            assert deleted.status_code == 204


def test_table_crud_api_rejects_unknown_table() -> None:
    with make_client() as client:
        response = client.get("/v1/tests/tables/users")

    assert response.status_code == 422

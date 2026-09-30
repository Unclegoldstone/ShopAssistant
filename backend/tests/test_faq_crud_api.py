from __future__ import annotations

from fastapi.testclient import TestClient

from app.dependencies import get_faq_crud_service
from app.main import create_app
from app.schemas import FaqCreate, FaqItem, FaqUpdate
from app.services.faq_crud import FaqNotFoundError
from tests.fakes import FakeStreamingModel
from tests.test_chat_api import make_settings


class FakeFaqCrudService:
    def __init__(self) -> None:
        self.item = FaqItem(id=7, question="怎么退货", answer="七天内可退货", category="售后")

    async def list_items(self) -> list[FaqItem]:
        return [self.item]

    async def create(self, payload: FaqCreate) -> FaqItem:
        return FaqItem(id=8, **payload.model_dump())

    async def update(self, faq_id: int, payload: FaqUpdate) -> FaqItem:
        if faq_id != 7:
            raise FaqNotFoundError(faq_id)
        return FaqItem(id=faq_id, **payload.model_dump())

    async def delete(self, faq_id: int) -> None:
        if faq_id != 7:
            raise FaqNotFoundError(faq_id)


def make_client() -> TestClient:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))
    app.dependency_overrides[get_faq_crud_service] = FakeFaqCrudService
    return TestClient(app)


def test_faq_crud_endpoints_cover_list_create_update_and_delete() -> None:
    with make_client() as client:
        listed = client.get("/v1/tests/faqs")
        created = client.post(
            "/v1/tests/faqs",
            json={"question": "发票怎么开", "answer": "订单页申请", "category": "发票"},
        )
        updated = client.put(
            "/v1/tests/faqs/7",
            json={"question": "如何退货", "answer": "签收后七天内", "category": "售后"},
        )
        deleted = client.delete("/v1/tests/faqs/7")

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == 7
    assert created.status_code == 201
    assert created.json()["id"] == 8
    assert updated.status_code == 200
    assert updated.json()["question"] == "如何退货"
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_faq_crud_returns_404_for_unknown_id() -> None:
    with make_client() as client:
        updated = client.put(
            "/v1/tests/faqs/999",
            json={"question": "未知", "answer": "未知", "category": "测试"},
        )
        deleted = client.delete("/v1/tests/faqs/999")

    assert updated.status_code == 404
    assert updated.json()["detail"]["code"] == "faq_not_found"
    assert deleted.status_code == 404


def test_faq_crud_cors_preflight_allows_put_and_delete() -> None:
    with make_client() as client:
        for method in ("PUT", "DELETE"):
            response = client.options(
                "/v1/tests/faqs/7",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert response.status_code == 200
            assert method in response.headers["access-control-allow-methods"]

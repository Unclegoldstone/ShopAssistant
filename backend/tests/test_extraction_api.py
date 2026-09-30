from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import AfterSalesInfo
from tests.fakes import FakeStreamingModel
from tests.test_chat_api import make_settings


def test_after_sales_endpoint_returns_fixed_json_fields() -> None:
    model = FakeStreamingModel(
        [],
        structured_response=AfterSalesInfo(
            order_id="20260928001",
            request_type="换货",
            expected_solution="更换为 42 码",
        ),
    )
    app = create_app(settings=make_settings(), model=model)

    with TestClient(app) as client:
        response = client.post(
            "/v1/after-sales/extract",
            json={"text": "订单 20260928001 的鞋子小了，想换 42 码"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "order_id": "20260928001",
        "request_type": "换货",
        "expected_solution": "更换为 42 码",
    }


def test_after_sales_endpoint_preserves_null_for_missing_information() -> None:
    model = FakeStreamingModel(
        [],
        structured_response=AfterSalesInfo(
            order_id=None,
            request_type="退款",
            expected_solution=None,
        ),
    )
    app = create_app(settings=make_settings(), model=model)

    with TestClient(app) as client:
        response = client.post(
            "/v1/after-sales/extract",
            json={"text": "我想退款"},
        )

    assert response.status_code == 200
    assert response.json()["order_id"] is None
    assert response.json()["expected_solution"] is None


def test_after_sales_endpoint_rejects_blank_input() -> None:
    app = create_app(settings=make_settings(), model=FakeStreamingModel([]))

    with TestClient(app) as client:
        response = client.post("/v1/after-sales/extract", json={"text": "  "})

    assert response.status_code == 422


def test_after_sales_endpoint_sanitizes_upstream_errors() -> None:
    model = FakeStreamingModel(
        [],
        structured_response=RuntimeError("secret provider response"),
    )
    app = create_app(settings=make_settings(), model=model)

    with TestClient(app) as client:
        response = client.post(
            "/v1/after-sales/extract",
            json={"text": "订单坏了"},
        )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "structured_output_error"
    assert "secret provider response" not in response.text

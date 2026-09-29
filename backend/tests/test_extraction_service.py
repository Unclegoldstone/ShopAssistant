from __future__ import annotations

import pytest

from app.schemas import AfterSalesInfo
from app.services.extraction import ExtractionService
from tests.fakes import FakeStreamingModel


@pytest.mark.asyncio
async def test_service_binds_provider_json_schema_and_formats_prompt() -> None:
    expected = AfterSalesInfo(
        order_id="A100",
        request_type="换货",
        expected_solution="换成 42 码",
    )
    model = FakeStreamingModel([], structured_response=expected)

    service = ExtractionService(model)
    result = await service.extract("订单 A100 的鞋小了，我想换成 42 码")

    assert model.structured_calls == [(AfterSalesInfo, "json_schema", True)]
    assert result == expected
    assert "订单 A100 的鞋小了" in model.structured_runnable.calls[0][-1].content


@pytest.mark.asyncio
async def test_service_validates_mapping_result_with_pydantic() -> None:
    model = FakeStreamingModel(
        [],
        structured_response={
            "order_id": None,
            "request_type": "退款",
            "expected_solution": "原路退款",
        },
    )

    result = await ExtractionService(model).extract("商品有问题，希望原路退款")

    assert isinstance(result, AfterSalesInfo)
    assert result.order_id is None

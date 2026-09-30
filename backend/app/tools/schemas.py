from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrderIdArgs(StrictToolArgs):
    order_id: str = Field(min_length=1, max_length=64, description="需要查询的订单号")


class ProductKeywordArgs(StrictToolArgs):
    keyword: str = Field(min_length=1, max_length=100, description="商品名称或关键词")


class FaqKeywordArgs(StrictToolArgs):
    keyword: str = Field(min_length=1, max_length=100, description="用户问题中的场景关键词")


class CreateTicketArgs(StrictToolArgs):
    issue_description: str = Field(
        min_length=1,
        max_length=1000,
        description="需要人工处理的问题描述",
    )
    ticket_type: str = Field(min_length=1, max_length=64, description="工单类型")

from __future__ import annotations

from typing import Any

from app.prompts import extraction_prompt
from app.schemas import AfterSalesInfo


class ExtractionService:
    def __init__(self, model: Any) -> None:
        self._structured_model = model.with_structured_output(
            AfterSalesInfo,
            method="json_schema",
            strict=True,
        )

    async def extract(self, description: str) -> AfterSalesInfo:
        messages = extraction_prompt.format_messages(description=description)
        result = await self._structured_model.ainvoke(messages)
        if isinstance(result, AfterSalesInfo):
            return result
        return AfterSalesInfo.model_validate(result)

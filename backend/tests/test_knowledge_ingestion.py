from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.knowledge.markdown import MarkdownKnowledgeSplitter
from app.models import KnowledgeContentType, KnowledgeSourceType
from app.services.knowledge_ingestion import faq_to_draft, load_markdown_drafts


def test_markdown_files_map_to_stable_source_keys_and_neighbors(tmp_path: Path) -> None:
    source = tmp_path / "policies"
    source.mkdir()
    (source / "shipping.md").write_text(
        "# 配送政策\n\n## 运费\n\n第一条完整规则。第二条完整规则。",
        encoding="utf-8",
    )
    splitter = MarkdownKnowledgeSplitter(chunk_size=12, chunk_overlap=3)

    items = load_markdown_drafts(tmp_path, splitter=splitter)

    assert len(items) == 2
    assert items[0].draft.source_key.startswith("markdown:policies/shipping.md:配送政策/运费:")
    assert items[0].previous_source_key is None
    assert items[0].next_source_key == items[1].draft.source_key
    assert items[1].previous_source_key == items[0].draft.source_key
    assert items[1].next_source_key is None


def test_faq_maps_to_one_authoritative_draft() -> None:
    faq = SimpleNamespace(id=7, question="如何退货", answer="在订单页申请。", category="售后")

    draft = faq_to_draft(faq)

    assert draft.source_type is KnowledgeSourceType.FAQ
    assert draft.source_key == "faq:7"
    assert draft.questions == ("如何退货",)
    assert draft.answer == "在订单页申请。"
    assert draft.section_path == ("FAQ", "售后")
    assert draft.content_type is KnowledgeContentType.PRODUCT_FAQ


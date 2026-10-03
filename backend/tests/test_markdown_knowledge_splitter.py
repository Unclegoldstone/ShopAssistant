from __future__ import annotations

from app.knowledge.markdown import MarkdownKnowledgeSplitter
from app.models import KnowledgeContentType


def test_heading_path_maps_policy_fields_and_neighbor_ordinals() -> None:
    markdown = """# 配送政策

## 运费规则

普通地区订单满九十九元包邮。

### 偏远地区

偏远地区不参与包邮活动。
"""
    chunks = MarkdownKnowledgeSplitter(chunk_size=80, chunk_overlap=10).split(
        "policies/shipping.md", markdown
    )

    assert [chunk.section_path for chunk in chunks] == [
        ("配送政策", "运费规则"),
        ("配送政策", "运费规则", "偏远地区"),
    ]
    assert chunks[0].category == "配送政策"
    assert chunks[0].questions == ("运费规则",)
    assert chunks[0].content_type is KnowledgeContentType.POLICY
    assert chunks[0].previous_ordinal is None
    assert chunks[0].next_ordinal == 1
    assert chunks[1].previous_ordinal == 0
    assert chunks[1].next_ordinal is None


def test_long_body_splits_only_on_sentence_boundaries_with_sentence_overlap() -> None:
    markdown = """# 售后手册

## 处理流程

第一句话说明如何登记问题。第二句话说明如何核实订单。第三句话说明如何给出处理方案。第四句话说明如何完成回访。
"""
    chunks = MarkdownKnowledgeSplitter(chunk_size=34, chunk_overlap=15).split(
        "manuals/after-sales.md", markdown
    )

    assert len(chunks) >= 2
    assert all(chunk.answer.endswith("。") for chunk in chunks)
    assert all(not chunk.answer.startswith(("，", "。")) for chunk in chunks)
    assert any("第二句话说明如何核实订单。" in chunk.answer for chunk in chunks[1:])
    assert all(chunk.warning is None for chunk in chunks)


def test_single_oversized_sentence_is_preserved_and_reported() -> None:
    sentence = "这是一个不能从中间截断的超长条款" * 10 + "。"
    chunks = MarkdownKnowledgeSplitter(chunk_size=40, chunk_overlap=8).split(
        "policies/returns.md", f"# 退货政策\n\n## 特殊条款\n\n{sentence}"
    )

    assert [chunk.answer for chunk in chunks] == [sentence]
    assert chunks[0].warning == "single_sentence_exceeds_chunk_size"


def test_large_table_repeats_header_without_repeating_data_rows() -> None:
    markdown = """# 商品 FAQ

## 尺码表

| 型号 | 尺寸 | 适用范围 |
| --- | --- | --- |
| A | 10 | 小型 |
| B | 20 | 中型 |
| C | 30 | 大型 |
| D | 40 | 超大型 |
"""
    chunks = MarkdownKnowledgeSplitter(chunk_size=75, chunk_overlap=10).split(
        "product-faq/demo-products.md", markdown
    )

    assert len(chunks) >= 2
    assert all(chunk.is_table for chunk in chunks)
    table_header = "| 型号 | 尺寸 | 适用范围 |\n| --- | --- | --- |"
    assert all(chunk.answer.startswith(table_header) for chunk in chunks)
    combined = "\n".join(chunk.answer for chunk in chunks)
    rows = (
        "| A | 10 | 小型 |",
        "| B | 20 | 中型 |",
        "| C | 30 | 大型 |",
        "| D | 40 | 超大型 |",
    )
    for row in rows:
        assert combined.count(row) == 1


def test_important_marker_sets_critical_metadata() -> None:
    markdown = """# 退货政策

## 时限

> [!IMPORTANT]
> 签收后七天内才能申请无理由退货。
"""
    chunk = MarkdownKnowledgeSplitter(chunk_size=100, chunk_overlap=10).split(
        "policies/returns.md", markdown
    )[0]

    assert chunk.is_critical is True
    assert "签收后七天内" in chunk.answer
    assert "[!IMPORTANT]" not in chunk.answer


def test_neighbors_never_cross_source_files() -> None:
    splitter = MarkdownKnowledgeSplitter(chunk_size=30, chunk_overlap=5)
    first = splitter.split("policies/a.md", "# A\n\n## A1\n\n第一条。第二条。第三条。")
    second = splitter.split("policies/b.md", "# B\n\n## B1\n\n第四条。第五条。")

    assert first[-1].next_ordinal is None
    assert second[0].previous_ordinal is None

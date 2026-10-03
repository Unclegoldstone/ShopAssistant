from __future__ import annotations

from app.knowledge.text import (
    build_content_fingerprint,
    build_vector_text,
    clean_display_text,
    normalize_questions,
)
from app.knowledge.types import KnowledgeDraft
from app.models import KnowledgeContentType, KnowledgeSourceType


def make_draft(**overrides: object) -> KnowledgeDraft:
    values: dict[str, object] = {
        "source_type": KnowledgeSourceType.MARKDOWN,
        "source_key": "markdown:policies/shipping.md:运费规则:0",
        "source_revision": "revision-1",
        "category": "配送政策",
        "questions": ("运费怎么计算？", "哪些地区包邮？"),
        "answer": "普通地区订单满 99 元包邮。",
        "section_path": ("配送政策", "运费规则"),
        "content_type": KnowledgeContentType.POLICY,
        "is_critical": True,
    }
    values.update(overrides)
    return KnowledgeDraft(**values)  # type: ignore[arg-type]


def test_clean_display_text_normalizes_unicode_and_whitespace() -> None:
    assert clean_display_text("  ＡＢＣ\r\n  运费\t规则  ") == "ABC 运费 规则"


def test_questions_are_cleaned_deduplicated_and_stably_sorted() -> None:
    assert normalize_questions(
        [" 运费是多少？ ", "运费是多少?", "包邮条件", "", "  包邮条件  "]
    ) == ("包邮条件", "运费是多少?", "运费是多少?")[:2]


def test_vector_text_contains_only_category_questions_and_answer() -> None:
    draft = make_draft()

    vector_text = build_vector_text(draft)

    assert vector_text == (
        "分类：配送政策\n"
        "问题：\n"
        "- 哪些地区包邮?\n"
        "- 运费怎么计算?\n"
        "答案：普通地区订单满 99 元包邮。"
    )
    assert draft.source_key not in vector_text
    assert "运费规则" not in vector_text
    assert "critical" not in vector_text


def test_fingerprint_ignores_spacing_punctuation_and_question_order() -> None:
    first = make_draft(
        category=" 配送政策 ",
        questions=("运费是多少？", "包邮条件。"),
        answer="订单满 99 元，包邮。",
    )
    second = make_draft(
        category="配送政策",
        questions=("包邮条件", " 运费是多少? "),
        answer="订单满99元包邮",
    )

    assert build_content_fingerprint(first) == build_content_fingerprint(second)


def test_draft_is_immutable_and_normalizes_business_fields() -> None:
    draft = make_draft(
        category="  配送政策 ",
        questions=("运费怎么计算？", "运费怎么计算?"),
        answer="  普通地区订单满 99 元包邮。  ",
        section_path=(" 配送政策 ", " 运费规则 "),
    )

    assert draft.category == "配送政策"
    assert draft.questions == ("运费怎么计算?",)
    assert draft.answer == "普通地区订单满 99 元包邮。"
    assert draft.section_path == ("配送政策", "运费规则")

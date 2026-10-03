from __future__ import annotations

from dataclasses import dataclass

from app.models import KnowledgeContentType, KnowledgeSourceType


@dataclass(frozen=True, slots=True)
class KnowledgeDraft:
    source_type: KnowledgeSourceType
    source_key: str
    source_revision: str
    category: str
    questions: tuple[str, ...]
    answer: str
    section_path: tuple[str, ...]
    content_type: KnowledgeContentType
    is_critical: bool = False

    def __post_init__(self) -> None:
        from app.knowledge.text import clean_display_text, normalize_questions

        source_key = clean_display_text(self.source_key)
        source_revision = clean_display_text(self.source_revision)
        category = clean_display_text(self.category)
        questions = normalize_questions(self.questions)
        answer = clean_display_text(self.answer)
        section_path = tuple(
            item
            for item in (clean_display_text(value) for value in self.section_path)
            if item
        )

        if not source_key:
            raise ValueError("source_key 不能为空")
        if not source_revision:
            raise ValueError("source_revision 不能为空")
        if not category:
            raise ValueError("category 不能为空")
        if not questions:
            raise ValueError("questions 不能为空")
        if not answer:
            raise ValueError("answer 不能为空")

        object.__setattr__(self, "source_key", source_key)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "questions", questions)
        object.__setattr__(self, "answer", answer)
        object.__setattr__(self, "section_path", section_path)

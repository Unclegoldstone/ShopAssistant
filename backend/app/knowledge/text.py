from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.knowledge.types import KnowledgeDraft

_WHITESPACE = re.compile(r"\s+")


def clean_display_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return _WHITESPACE.sub(" ", normalized).strip()


def _fingerprint_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def normalize_questions(values: Iterable[str]) -> tuple[str, ...]:
    by_key: dict[str, str] = {}
    for value in values:
        display = clean_display_text(value)
        key = _fingerprint_token(display)
        if display and key and key not in by_key:
            by_key[key] = display
    return tuple(by_key[key] for key in sorted(by_key))


def build_vector_text(draft: KnowledgeDraft) -> str:
    question_lines = "\n".join(f"- {question}" for question in draft.questions)
    return f"分类：{draft.category}\n问题：\n{question_lines}\n答案：{draft.answer}"


def build_content_fingerprint(draft: KnowledgeDraft) -> str:
    payload = {
        "category": _fingerprint_token(draft.category),
        "questions": sorted(_fingerprint_token(item) for item in draft.questions),
        "answer": _fingerprint_token(draft.answer),
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

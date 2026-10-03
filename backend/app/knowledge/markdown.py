from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.knowledge.text import clean_display_text
from app.knowledge.types import KnowledgeDraft
from app.models import KnowledgeContentType, KnowledgeSourceType

_SENTENCE_PATTERN = re.compile(r".*?[。！？!?；;.]|.+$", re.DOTALL)
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_HEADERS = [("#" * level, f"h{level}") for level in range(1, 7)]


@dataclass(frozen=True, slots=True)
class MarkdownKnowledgeChunk:
    source_path: str
    source_revision: str
    ordinal: int
    category: str
    questions: tuple[str, ...]
    answer: str
    section_path: tuple[str, ...]
    content_type: KnowledgeContentType
    is_critical: bool
    is_table: bool
    warning: str | None = None
    previous_ordinal: int | None = None
    next_ordinal: int | None = None

    @property
    def char_count(self) -> int:
        return len(self.answer)

    def to_draft(self) -> KnowledgeDraft:
        section_key = "/".join(self.section_path)
        return KnowledgeDraft(
            source_type=KnowledgeSourceType.MARKDOWN,
            source_key=f"markdown:{self.source_path}:{section_key}:{self.ordinal}",
            source_revision=self.source_revision,
            category=self.category,
            questions=self.questions,
            answer=self.answer,
            section_path=self.section_path,
            content_type=self.content_type,
            is_critical=self.is_critical,
        )


class MarkdownKnowledgeSplitter:
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=_HEADERS,
            strip_headers=True,
        )
        self._recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""],
            keep_separator="end",
        )

    def split(self, source_path: str, markdown: str) -> list[MarkdownKnowledgeChunk]:
        normalized_path = PurePosixPath(source_path.replace("\\", "/")).as_posix()
        content_type = _content_type_for_path(normalized_path)
        source_revision = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        raw_chunks: list[MarkdownKnowledgeChunk] = []

        for document in self._header_splitter.split_text(markdown):
            section_path = tuple(
                clean_display_text(str(document.metadata[key]))
                for key in (f"h{level}" for level in range(1, 7))
                if key in document.metadata and clean_display_text(str(document.metadata[key]))
            )
            if not section_path:
                section_path = (PurePosixPath(normalized_path).stem,)
            category = " / ".join(section_path[:-1]) or section_path[-1]
            questions = (section_path[-1],)
            cleaned_text, is_critical = _clean_important_markers(document.page_content)

            for block, is_table in _extract_blocks(cleaned_text):
                if is_table:
                    pieces = self._split_table(block)
                else:
                    pieces = self._split_prose(block)
                for answer, warning in pieces:
                    raw_chunks.append(
                        MarkdownKnowledgeChunk(
                            source_path=normalized_path,
                            source_revision=source_revision,
                            ordinal=len(raw_chunks),
                            category=category,
                            questions=questions,
                            answer=answer,
                            section_path=section_path,
                            content_type=content_type,
                            is_critical=is_critical,
                            is_table=is_table,
                            warning=warning,
                        )
                    )

        last_index = len(raw_chunks) - 1
        return [
            replace(
                chunk,
                previous_ordinal=chunk.ordinal - 1 if chunk.ordinal > 0 else None,
                next_ordinal=chunk.ordinal + 1 if chunk.ordinal < last_index else None,
            )
            for chunk in raw_chunks
        ]

    def _split_prose(self, text: str) -> list[tuple[str, str | None]]:
        text = clean_display_text(text)
        if not text:
            return []
        # Invoke LangChain's recursive splitter for its maintained separator handling;
        # final boundaries below are expanded back to complete sentences.
        self._recursive_splitter.split_text(text)
        sentences = [
            clean_display_text(match.group()) for match in _SENTENCE_PATTERN.finditer(text)
        ]
        sentences = [sentence for sentence in sentences if sentence]
        output: list[tuple[str, str | None]] = []
        current: list[str] = []

        for sentence in sentences:
            if len(sentence) > self._chunk_size:
                if current:
                    output.append(("".join(current), None))
                    current = []
                output.append((sentence, "single_sentence_exceeds_chunk_size"))
                continue

            if current and len("".join(current)) + len(sentence) > self._chunk_size:
                output.append(("".join(current), None))
                overlap: list[str] = []
                for previous in reversed(current):
                    if len(previous) + len("".join(overlap)) > self._chunk_overlap:
                        break
                    overlap.insert(0, previous)
                while overlap and len("".join(overlap)) + len(sentence) > self._chunk_size:
                    overlap.pop(0)
                current = overlap
            current.append(sentence)

        if current:
            output.append(("".join(current), None))
        return output

    def _split_table(self, text: str) -> list[tuple[str, str | None]]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        header = lines[:2]
        rows = lines[2:]
        if len(header) < 2:
            return [(clean_display_text(text), None)]
        chunks: list[tuple[str, str | None]] = []
        current_rows: list[str] = []
        header_text = "\n".join(header)
        for row in rows:
            candidate = "\n".join([header_text, *current_rows, row])
            if current_rows and len(candidate) > self._chunk_size:
                chunks.append(("\n".join([header_text, *current_rows]), None))
                current_rows = []
            current_rows.append(row)
        if current_rows or not rows:
            chunks.append(("\n".join([header_text, *current_rows]), None))
        return chunks


def _content_type_for_path(source_path: str) -> KnowledgeContentType:
    parts = set(PurePosixPath(source_path).parts)
    if "product-faq" in parts:
        return KnowledgeContentType.PRODUCT_FAQ
    if "manuals" in parts:
        return KnowledgeContentType.AFTER_SALES_MANUAL
    return KnowledgeContentType.POLICY


def _clean_important_markers(text: str) -> tuple[str, bool]:
    is_critical = False
    output: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        quote_content = stripped[1:].lstrip() if stripped.startswith(">") else stripped
        if quote_content.upper() == "[!IMPORTANT]":
            is_critical = True
            continue
        output.append(quote_content if stripped.startswith(">") else line)
    return "\n".join(output).strip(), is_critical


def _extract_blocks(text: str) -> list[tuple[str, bool]]:
    lines = text.splitlines()
    blocks: list[tuple[str, bool]] = []
    prose: list[str] = []
    index = 0

    def flush_prose() -> None:
        value = "\n".join(prose).strip()
        if value:
            blocks.append((value, False))
        prose.clear()

    while index < len(lines):
        if (
            "|" in lines[index]
            and index + 1 < len(lines)
            and _TABLE_SEPARATOR.match(lines[index + 1])
        ):
            flush_prose()
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            blocks.append(("\n".join(table_lines), True))
            continue
        prose.append(lines[index])
        index += 1
    flush_prose()
    return blocks

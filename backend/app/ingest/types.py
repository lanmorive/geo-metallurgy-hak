"""Внутренние типы ingest-пайплайна."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockType = Literal["paragraph", "heading", "table"]


@dataclass
class Block:
    type: BlockType
    text: str
    level: int | None = None
    page: int | None = None
    section: str = "frontmatter"


@dataclass
class DocMeta:
    file_metadata_author: str | None = None
    created: str | None = None
    pages: int | None = None
    ocr_pages: int = 0
    ocr_skipped_pages: int = 0
    ocr_low_yield_pages: int = 0
    scan_low_value: bool = False


@dataclass
class ParseResult:
    markdown_text: str
    blocks: list[Block]
    doc_meta: DocMeta = field(default_factory=DocMeta)

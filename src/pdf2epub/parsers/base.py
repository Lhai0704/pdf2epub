from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from pdf2epub.domain.models import Asset, Page


class ParseOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    include_images: bool = True
    max_page_pixels: int = Field(default=40_000_000, gt=0)


@dataclass(frozen=True, slots=True)
class PageContext:
    source_path: Path
    project_root: Path
    source_sha256: str
    page_index: int


@dataclass(frozen=True, slots=True)
class PageParseResult:
    page: Page
    assets: tuple[Asset, ...]
    parse_fingerprint: str
    cache_hit: bool = False


class DocumentParser(Protocol):
    parser_id: str
    parser_version: str

    def can_parse(self, context: PageContext) -> bool: ...

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult: ...

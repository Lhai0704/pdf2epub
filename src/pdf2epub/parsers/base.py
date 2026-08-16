from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from pdf2epub.domain.models import Asset, BBox, Block, Page


class ParseOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    include_images: bool = True
    max_page_pixels: int = Field(default=25_000_000, gt=0)


class OcrParseOptions(ParseOptions):
    device: Literal["cpu", "gpu:0"] = "gpu:0"
    precision: Literal["fp32"] = "fp32"
    dpi: int = Field(default=200, ge=72, le=600)
    cpu_threads: int = Field(default=8, ge=1, le=32)
    recognition_batch_size: int = Field(default=4, ge=1, le=32)
    text_det_limit_side_len: int = Field(default=2200, ge=256, le=4000)
    text_det_limit_type: Literal["max"] = "max"
    text_det_thresh: float = Field(default=0.3, ge=0, le=1)
    text_det_box_thresh: float = Field(default=0.6, ge=0, le=1)
    text_det_unclip_ratio: float = Field(default=1.5, gt=0, le=5)
    text_rec_score_thresh: float = Field(default=0.0, ge=0, le=1)
    allow_model_download: bool = False
    bypass_cache: bool = False


@dataclass(frozen=True, slots=True)
class PageContext:
    source_path: Path
    project_root: Path
    source_sha256: str
    page_index: int
    language: str = "en"


@dataclass(frozen=True, slots=True)
class PageParseResult:
    page: Page
    assets: tuple[Asset, ...]
    parse_fingerprint: str
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class RegionParseRequest:
    region: BBox
    command_id: str


@dataclass(frozen=True, slots=True)
class RegionParseResult:
    blocks: tuple[Block, ...]
    assets: tuple[Asset, ...]
    warnings: tuple[str, ...]
    parse_fingerprint: str
    cache_hit: bool = False


class DocumentParser(Protocol):
    parser_id: str
    parser_version: str
    capabilities: tuple[str, ...]
    cancellation_boundary: Literal["page"]

    def can_parse(self, context: PageContext) -> bool: ...

    def fingerprint(self, context: PageContext, options: ParseOptions) -> tuple[str, str]: ...

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult: ...


class RegionDocumentParser(DocumentParser, Protocol):
    def parse_region(
        self,
        context: PageContext,
        request: RegionParseRequest,
        options: ParseOptions,
    ) -> RegionParseResult: ...

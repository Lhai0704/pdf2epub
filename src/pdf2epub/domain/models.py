from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class BBox(StrictModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def validate_coordinates(self) -> BBox:
        values = (self.x0, self.y0, self.x1, self.y1)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bbox coordinates must be finite")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox end coordinates must not precede start coordinates")
        return self

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1

    @classmethod
    def from_tuple(cls, values: tuple[float, float, float, float]) -> BBox:
        return cls(x0=values[0], y0=values[1], x1=values[2], y1=values[3])

    @classmethod
    def union(cls, boxes: list[BBox]) -> BBox:
        if not boxes:
            raise ValueError("Cannot union an empty bbox list")
        return cls(
            x0=min(box.x0 for box in boxes),
            y0=min(box.y0 for box in boxes),
            x1=max(box.x1 for box in boxes),
            y1=max(box.y1 for box in boxes),
        )


class TextStyle(StrictModel):
    font_name: str | None = None
    font_size: float | None = Field(default=None, ge=0)
    bold: bool = False
    italic: bool = False


class ProcessingProvenance(StrictModel):
    source_sha256: str = Field(min_length=64, max_length=64)
    parser_id: str
    parser_version: str
    options_hash: str
    source_span_ids: list[str] = Field(default_factory=list)
    raw_cache_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
    user_edited: bool = False


TranslationStatus = Literal[
    "untranslated",
    "queued",
    "translating",
    "translated",
    "failed",
    "user_edited",
    "stale",
]


class GlossaryEntry(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class TranslationSettings(StrictModel):
    target_language: str = Field(default="zh-CN", min_length=1)
    provider_id: str = Field(default="longcat", min_length=1)
    model: str = Field(default="LongCat-2.0", min_length=1)
    prompt_version: str = Field(default="translate-v1", min_length=1)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    style_instructions: str | None = None
    remote_consent_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def glossary_version(self) -> str:
        payload = json.dumps(
            [
                entry.model_dump()
                for entry in sorted(self.glossary, key=lambda value: (value.source, value.target))
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TranslationUsage(StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class TranslationProvenance(StrictModel):
    origin: Literal["provider", "cache", "manual"]
    provider_id: str
    model: str
    prompt_version: str
    glossary_version: str = Field(min_length=64, max_length=64)
    request_id: str | None = None
    usage: TranslationUsage | None = None


class TranslationRecord(StrictModel):
    text: str | None = None
    status: Literal["translated", "failed", "user_edited", "stale"]
    source_fingerprint: str = Field(min_length=64, max_length=64)
    cache_key: str | None = Field(default=None, min_length=64, max_length=64)
    provenance: TranslationProvenance
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_translation(self) -> TranslationRecord:
        if self.status in {"translated", "user_edited"} and not (self.text or "").strip():
            raise ValueError("valid translations require non-empty text")
        if self.status == "translated" and self.provenance.origin == "manual":
            raise ValueError("provider translations cannot have manual provenance")
        if self.status == "user_edited" and self.provenance.origin != "manual":
            raise ValueError("user-edited translations require manual provenance")
        return self


class BlockBase(StrictModel):
    id: str
    bbox: BBox
    reading_order: int = Field(ge=0)
    provenance: ProcessingProvenance


class TextBlockBase(BlockBase):
    source_text_raw: str
    source_text_normalized: str
    source_text_user: str | None = None
    style: TextStyle = Field(default_factory=TextStyle)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_text(self) -> str:
        if self.source_text_user is not None:
            return self.source_text_user
        return self.source_text_normalized


class ParagraphBlock(TextBlockBase):
    type: Literal["paragraph"] = "paragraph"
    translation: TranslationRecord | None = None


class HeadingBlock(TextBlockBase):
    type: Literal["heading"] = "heading"
    level: int = Field(default=1, ge=1, le=6)


class ImageBlock(BlockBase):
    type: Literal["image"] = "image"
    asset_id: str
    alt_text: str = ""


Block = Annotated[ParagraphBlock | HeadingBlock | ImageBlock, Field(discriminator="type")]
TextBlock = ParagraphBlock | HeadingBlock


class NativeTextQuality(StrictModel):
    status: Literal["usable", "suspect", "no_text"]
    character_count: int = Field(ge=0)
    replacement_character_ratio: float = Field(ge=0, le=1)
    control_character_ratio: float = Field(ge=0, le=1)
    image_coverage_ratio: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class Page(StrictModel):
    page_index: int = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: int = 0
    parser_id: str = "pymupdf_native"
    parse_status: Literal["unparsed", "parsed", "stale", "failed"] = "unparsed"
    parse_fingerprint: str | None = None
    quality: NativeTextQuality | None = None
    blocks: list[Block] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_page(self) -> Page:
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("block IDs must be unique within a page")
        for block in self.blocks:
            if block.bbox.x0 < -0.01 or block.bbox.y0 < -0.01:
                raise ValueError("block bbox starts outside its page")
            if block.bbox.x1 > self.width + 0.01 or block.bbox.y1 > self.height + 0.01:
                raise ValueError("block bbox ends outside its page")
        orders = [block.reading_order for block in self.blocks]
        if orders != sorted(orders):
            raise ValueError("page blocks must be stored in reading order")
        return self


class Asset(StrictModel):
    id: str
    sha256: str = Field(min_length=64, max_length=64)
    mime_type: str
    relative_path: str
    source_page_index: int = Field(ge=0)
    bbox: BBox
    extraction_method: Literal["embedded", "rendered_crop", "generated"]

    @model_validator(mode="after")
    def validate_relative_path(self) -> Asset:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("asset path must stay within the project directory")
        return self


class BookMetadata(StrictModel):
    title: str
    language: str = "en"
    creator: str | None = None


class SourceDocument(StrictModel):
    original_name: str
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)


class BookDocument(StrictModel):
    schema_version: Literal["1.1"] = "1.1"
    document_id: str
    metadata: BookMetadata
    source: SourceDocument
    pages: list[Page] = Field(default_factory=list)
    assets: dict[str, Asset] = Field(default_factory=dict)
    translation_settings: TranslationSettings = Field(default_factory=TranslationSettings)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_document(self) -> BookDocument:
        page_indexes = [page.page_index for page in self.pages]
        if len(page_indexes) != len(set(page_indexes)):
            raise ValueError("page indexes must be unique")
        block_ids = [block.id for page in self.pages for block in page.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("block IDs must be unique within a document")
        for key, asset in self.assets.items():
            if key != asset.id:
                raise ValueError("asset dictionary keys must match asset IDs")
        for page in self.pages:
            for block in page.blocks:
                if isinstance(block, ImageBlock) and block.asset_id not in self.assets:
                    raise ValueError(f"missing asset for image block {block.id}")
        return self


class ProjectSource(StrictModel):
    mode: Literal["copy"] = "copy"
    relative_path: str = "source/original.pdf"
    original_name: str
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_path(self) -> ProjectSource:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source path must stay within the project directory")
        return self


class ProjectManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    document_path: str = "document.json"
    source: ProjectSource
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_document_path(self) -> ProjectManifest:
        path = PurePosixPath(self.document_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("document path must stay within the project directory")
        return self


class LoadedProject(StrictModel):
    root: str
    manifest: ProjectManifest
    document: BookDocument
    source_changed: bool = False
    migrated_from_schema: str | None = None

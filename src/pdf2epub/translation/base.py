from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from pdf2epub.domain.models import GlossaryEntry, LoadedProject, TranslationUsage


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paragraph_id: str
    source_text: str
    source_language: str
    target_language: str
    provider_id: str
    model: str
    prompt_version: str
    chapter_heading: str | None = None
    previous_paragraph: str | None = None
    next_paragraph: str | None = None
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    glossary_version: str = Field(min_length=64, max_length=64)
    style_instructions: str | None = None


class TranslationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    provider_id: str
    model: str
    request_id: str | None = None
    usage: TranslationUsage | None = None


class CachedTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    provider_id: str
    model: str
    prompt_version: str
    glossary_version: str = Field(min_length=64, max_length=64)
    request_id: str | None = None
    usage: TranslationUsage | None = None


class BatchItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paragraph_id: str
    status: Literal[
        "queued",
        "translating",
        "translated",
        "cache_hit",
        "failed",
        "skipped",
        "cancelled",
    ]
    message: str | None = None


class BatchTranslationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: LoadedProject
    items: list[BatchItemResult]
    cancelled: bool = False
    fatal_error: str | None = None

    @property
    def translated_count(self) -> int:
        return sum(item.status == "translated" for item in self.items)

    @property
    def cache_hit_count(self) -> int:
        return sum(item.status == "cache_hit" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)


class Translator(Protocol):
    provider_id: str

    async def translate(self, request: TranslationRequest) -> TranslationResult: ...


class TranslationCache(Protocol):
    def get(self, key: str) -> CachedTranslation | None: ...

    def put(self, key: str, value: CachedTranslation) -> None: ...


ProgressCallback = Callable[[int, int, BatchItemResult], None]
CancelCallback = Callable[[], bool]

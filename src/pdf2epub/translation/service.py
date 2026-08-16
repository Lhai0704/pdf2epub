from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pdf2epub.domain.errors import (
    TranslationConfigurationError,
    TranslationProviderError,
)
from pdf2epub.domain.models import (
    BookDocument,
    LoadedProject,
    ParagraphBlock,
    TranslationProvenance,
    TranslationRecord,
)
from pdf2epub.persistence.project_store import ProjectStore
from pdf2epub.persistence.translation_cache import JsonTranslationCache
from pdf2epub.translation.base import (
    BatchItemResult,
    BatchTranslationResult,
    CachedTranslation,
    CancelCallback,
    ProgressCallback,
    TranslationCache,
    Translator,
)
from pdf2epub.translation.cache import source_fingerprint, translation_cache_key
from pdf2epub.translation.context import build_translation_request


def _paragraphs(document: BookDocument) -> list[ParagraphBlock]:
    return [
        block
        for page in sorted(document.pages, key=lambda value: value.page_index)
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    ]


def _replace_translation(
    document: BookDocument, paragraph_id: str, translation: TranslationRecord | None
) -> BookDocument:
    found = False
    pages = []
    for page in document.pages:
        blocks = []
        page_changed = False
        for block in page.blocks:
            if block.id == paragraph_id and isinstance(block, ParagraphBlock):
                block = block.model_copy(update={"translation": translation})
                found = True
                page_changed = True
            blocks.append(block)
        pages.append(page.model_copy(update={"blocks": blocks}) if page_changed else page)
    if not found:
        raise KeyError(f"Paragraph not found: {paragraph_id}")
    return document.model_copy(update={"pages": pages, "updated_at": datetime.now(UTC)})


class TranslationService:
    def __init__(
        self,
        translator: Translator,
        *,
        store: ProjectStore | None = None,
        cache: TranslationCache | None = None,
    ) -> None:
        self.translator = translator
        self.store = store or ProjectStore()
        self.cache = cache

    async def translate_selection(
        self,
        project: LoadedProject,
        paragraph_ids: list[str],
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
    ) -> BatchTranslationResult:
        requested = list(dict.fromkeys(paragraph_ids))
        available = {paragraph.id: paragraph for paragraph in _paragraphs(project.document)}
        selected = [
            paragraph.id for paragraph in _paragraphs(project.document) if paragraph.id in requested
        ]
        items = [
            BatchItemResult(
                paragraph_id=paragraph_id,
                status="skipped",
                message="Selection is not a paragraph",
            )
            for paragraph_id in requested
            if paragraph_id not in available
        ]
        cache = self.cache or JsonTranslationCache(Path(project.root))
        total = len(selected)
        fatal_error: str | None = None

        if progress is not None:
            for paragraph_id in selected:
                progress(
                    0,
                    total,
                    BatchItemResult(paragraph_id=paragraph_id, status="queued"),
                )

        for index, paragraph_id in enumerate(selected):
            if cancelled is not None and cancelled():
                return BatchTranslationResult(
                    project=project,
                    items=items,
                    cancelled=True,
                    fatal_error=fatal_error,
                )
            paragraph = next(
                item for item in _paragraphs(project.document) if item.id == paragraph_id
            )
            fingerprint = source_fingerprint(paragraph.effective_text)
            existing = paragraph.translation
            if (
                existing is not None
                and existing.status in {"translated", "user_edited"}
                and existing.source_fingerprint == fingerprint
            ):
                item = BatchItemResult(paragraph_id=paragraph_id, status="skipped")
                items.append(item)
                if progress is not None:
                    progress(index + 1, total, item)
                continue

            if progress is not None:
                progress(
                    index,
                    total,
                    BatchItemResult(paragraph_id=paragraph_id, status="translating"),
                )

            request = build_translation_request(project.document, paragraph_id).model_copy(
                update={"provider_id": self.translator.provider_id}
            )
            key = translation_cache_key(request)
            cached = cache.get(key)
            if cached is not None:
                record = TranslationRecord(
                    text=cached.text,
                    status="translated",
                    source_fingerprint=fingerprint,
                    cache_key=key,
                    provenance=TranslationProvenance(
                        origin="cache",
                        provider_id=cached.provider_id,
                        model=cached.model,
                        prompt_version=cached.prompt_version,
                        glossary_version=cached.glossary_version,
                        request_id=cached.request_id,
                        usage=cached.usage,
                    ),
                    created_at=existing.created_at if existing else datetime.now(UTC),
                )
                document = _replace_translation(project.document, paragraph_id, record)
                project = self.store.save(project.model_copy(update={"document": document}))
                item = BatchItemResult(paragraph_id=paragraph_id, status="cache_hit")
                items.append(item)
                if progress is not None:
                    progress(index + 1, total, item)
                continue

            try:
                result = await self.translator.translate(request)
                current = next(
                    item for item in _paragraphs(project.document) if item.id == paragraph_id
                )
                if source_fingerprint(current.effective_text) != fingerprint:
                    stale = existing.model_copy(update={"status": "stale"}) if existing else None
                    document = _replace_translation(project.document, paragraph_id, stale)
                    project = self.store.save(project.model_copy(update={"document": document}))
                    item = BatchItemResult(
                        paragraph_id=paragraph_id,
                        status="failed",
                        message="Source text changed while translation was running",
                    )
                else:
                    cached_value = CachedTranslation(
                        text=result.text,
                        provider_id=result.provider_id,
                        model=result.model,
                        prompt_version=request.prompt_version,
                        glossary_version=request.glossary_version,
                        request_id=result.request_id,
                        usage=result.usage,
                    )
                    cache.put(key, cached_value)
                    record = TranslationRecord(
                        text=result.text,
                        status="translated",
                        source_fingerprint=fingerprint,
                        cache_key=key,
                        provenance=TranslationProvenance(
                            origin="provider",
                            provider_id=result.provider_id,
                            model=result.model,
                            prompt_version=request.prompt_version,
                            glossary_version=request.glossary_version,
                            request_id=result.request_id,
                            usage=result.usage,
                        ),
                        created_at=existing.created_at if existing else datetime.now(UTC),
                    )
                    document = _replace_translation(project.document, paragraph_id, record)
                    project = self.store.save(project.model_copy(update={"document": document}))
                    item = BatchItemResult(paragraph_id=paragraph_id, status="translated")
            except TranslationConfigurationError as exc:
                fatal_error = str(exc)
                item, project = self._record_failure(
                    project, paragraph_id, fingerprint, key, "configuration_error", str(exc)
                )
            except TranslationProviderError as exc:
                item, project = self._record_failure(
                    project, paragraph_id, fingerprint, key, exc.code, str(exc)
                )
                if exc.fatal:
                    fatal_error = str(exc)

            items.append(item)
            if progress is not None:
                progress(index + 1, total, item)
            if fatal_error is not None:
                break
            if cancelled is not None and cancelled():
                return BatchTranslationResult(
                    project=project,
                    items=items,
                    cancelled=True,
                    fatal_error=fatal_error,
                )

        return BatchTranslationResult(
            project=project,
            items=items,
            cancelled=False,
            fatal_error=fatal_error,
        )

    def _record_failure(
        self,
        project: LoadedProject,
        paragraph_id: str,
        fingerprint: str,
        cache_key: str,
        code: str,
        message: str,
    ) -> tuple[BatchItemResult, LoadedProject]:
        paragraph = next(item for item in _paragraphs(project.document) if item.id == paragraph_id)
        existing = paragraph.translation
        settings = project.document.translation_settings
        record = TranslationRecord(
            text=existing.text if existing else None,
            status="failed",
            source_fingerprint=fingerprint,
            cache_key=cache_key,
            provenance=TranslationProvenance(
                origin="provider",
                provider_id=self.translator.provider_id,
                model=settings.model,
                prompt_version=settings.prompt_version,
                glossary_version=settings.glossary_version,
            ),
            error_code=code,
            error_message=message,
            created_at=existing.created_at if existing else datetime.now(UTC),
        )
        document = _replace_translation(project.document, paragraph_id, record)
        saved = self.store.save(project.model_copy(update={"document": document}))
        return BatchItemResult(paragraph_id=paragraph_id, status="failed", message=message), saved

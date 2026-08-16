from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import (
    ProjectPersistenceError,
    TranslationCacheError,
    TranslationProviderError,
)
from pdf2epub.domain.models import LoadedProject, ParagraphBlock
from pdf2epub.persistence.project_store import ProjectStore
from pdf2epub.translation.base import BatchItemResult, TranslationRequest, TranslationResult
from pdf2epub.translation.fake import FakeTranslator
from pdf2epub.translation.service import TranslationService


def _paragraph_ids(project: object) -> list[str]:
    document = project.document  # type: ignore[attr-defined]
    return [
        block.id
        for page in document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    ]


def test_batch_partial_failure_retry_cache_and_stale(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "translation.bepub-project",
        fixture_corpus / "digital_single_column.pdf",
    )
    project, _ = workflow.parse_all(project)
    ids = _paragraph_ids(project)
    assert len(ids) >= 2

    fake = FakeTranslator(failures={ids[1]})
    first = asyncio.run(
        TranslationService(fake, store=workflow.store).translate_selection(project, ids[:2])
    )
    assert first.translated_count == 1
    assert first.failed_count == 1
    reopened = workflow.load_project(Path(first.project.root))
    paragraphs = {
        block.id: block
        for page in reopened.document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    }
    first_translation = paragraphs[ids[0]].translation
    failed_translation = paragraphs[ids[1]].translation
    assert first_translation is not None
    assert first_translation.status == "translated"
    assert failed_translation is not None
    assert failed_translation.status == "failed"

    retry = FakeTranslator()
    second = asyncio.run(
        TranslationService(retry, store=workflow.store).translate_selection(reopened, ids[:2])
    )
    assert retry.call_count == 1
    assert second.translated_count == 1

    document = DocumentEditor().edit_text(second.project.document, 0, ids[0], "Changed source")
    changed = workflow.store.save(second.project.model_copy(update={"document": document}))
    changed_paragraphs = {
        block.id: block
        for page in changed.document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    }
    stale_translation = changed_paragraphs[ids[0]].translation
    valid_translation = changed_paragraphs[ids[1]].translation
    assert stale_translation is not None
    assert stale_translation.status == "stale"
    assert valid_translation is not None
    assert valid_translation.status == "translated"


def test_persisted_cache_is_used_without_provider_call(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "cache.bepub-project", fixture_corpus / "digital_single_column.pdf"
    )
    project, _ = workflow.parse_all(project)
    paragraph_id = _paragraph_ids(project)[0]
    first_fake = FakeTranslator()
    first = asyncio.run(
        TranslationService(first_fake, store=workflow.store).translate_selection(
            project, [paragraph_id]
        )
    )
    assert first_fake.call_count == 1

    pages = []
    for page in first.project.document.pages:
        blocks = [
            block.model_copy(update={"translation": None})
            if isinstance(block, ParagraphBlock) and block.id == paragraph_id
            else block
            for block in page.blocks
        ]
        pages.append(page.model_copy(update={"blocks": blocks}))
    cleared_document = first.project.document.model_copy(update={"pages": pages})
    cleared = workflow.store.save(first.project.model_copy(update={"document": cleared_document}))

    second_fake = FakeTranslator()
    second = asyncio.run(
        TranslationService(second_fake, store=workflow.store).translate_selection(
            cleared, [paragraph_id]
        )
    )
    assert second.cache_hit_count == 1
    assert second_fake.call_count == 0


def test_cancel_preserves_completed_items_and_corrupt_cache_is_non_destructive(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "cancel.bepub-project", fixture_corpus / "digital_single_column.pdf"
    )
    project, _ = workflow.parse_all(project)
    ids = _paragraph_ids(project)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    result = asyncio.run(
        TranslationService(FakeTranslator(), store=workflow.store).translate_selection(
            project, ids, cancelled=cancelled
        )
    )
    assert result.cancelled
    assert result.translated_count == 1

    cache_path = Path(result.project.root) / "cache" / "translation" / "index.json"
    cache_path.write_text("not json", encoding="utf-8")
    before = result.project.document
    with pytest.raises(TranslationCacheError):
        asyncio.run(
            TranslationService(FakeTranslator(), store=workflow.store).translate_selection(
                result.project, ids
            )
        )
    assert workflow.load_project(Path(result.project.root)).document == before


def test_selection_is_deduplicated_ordered_and_reports_task_states(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "selection.bepub-project", fixture_corpus / "digital_single_column.pdf"
    )
    project, _ = workflow.parse_all(project)
    ids = _paragraph_ids(project)
    fake = FakeTranslator()
    events: list[BatchItemResult] = []
    result = asyncio.run(
        TranslationService(fake, store=workflow.store).translate_selection(
            project,
            [ids[1], "not-a-paragraph", ids[0], ids[1]],
            progress=lambda _current, _total, item: events.append(item),
        )
    )
    assert [request.paragraph_id for request in fake.requests] == ids[:2]
    assert sum(item.paragraph_id == "not-a-paragraph" for item in result.items) == 1
    assert {event.status for event in events} >= {"queued", "translating", "translated"}


def test_save_failure_keeps_prior_paragraph_and_does_not_mark_later_items_successful(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    class FailingSecondSaveStore(ProjectStore):
        def __init__(self) -> None:
            self.calls = 0

        def save(self, project: LoadedProject) -> LoadedProject:
            self.calls += 1
            if self.calls == 2:
                raise ProjectPersistenceError("simulated save failure")
            return super().save(project)

    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "save-failure.bepub-project",
        fixture_corpus / "digital_single_column.pdf",
    )
    project, _ = workflow.parse_all(project)
    ids = _paragraph_ids(project)
    store = FailingSecondSaveStore()
    fake = FakeTranslator()
    with pytest.raises(ProjectPersistenceError, match="simulated save failure"):
        asyncio.run(TranslationService(fake, store=store).translate_selection(project, ids))

    reopened = workflow.load_project(Path(project.root))
    translations = {
        block.id: block.translation
        for page in reopened.document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    }
    first = translations[ids[0]]
    assert first is not None
    assert first.status == "translated"
    assert translations[ids[1]] is None
    assert all(translations[paragraph_id] is None for paragraph_id in ids[1:])


def test_fatal_provider_failure_stops_the_batch(fixture_corpus: Path, tmp_path: Path) -> None:
    class FatalTranslator:
        provider_id = "fatal-test"

        def __init__(self) -> None:
            self.call_count = 0

        async def translate(self, request: TranslationRequest) -> TranslationResult:
            self.call_count += 1
            raise TranslationProviderError(
                "authentication failed", code="authentication_error", fatal=True
            )

    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "fatal.bepub-project", fixture_corpus / "digital_single_column.pdf"
    )
    project, _ = workflow.parse_all(project)
    ids = _paragraph_ids(project)
    translator = FatalTranslator()
    result = asyncio.run(
        TranslationService(translator, store=workflow.store).translate_selection(project, ids)
    )
    assert translator.call_count == 1
    assert result.fatal_error == "authentication failed"
    assert result.failed_count == 1
    reopened = workflow.load_project(Path(project.root))
    translations = [
        block.translation
        for page in reopened.document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    ]
    assert translations[0] is not None
    assert all(translation is None for translation in translations[1:])

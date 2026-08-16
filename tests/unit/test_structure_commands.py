from __future__ import annotations

from pathlib import Path

import pytest

from pdf2epub.application.commands import SessionCommandStack, StructureCommandService
from pdf2epub.application.editing import DocumentEditor
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import TranslationConflictError
from pdf2epub.domain.models import PageHeaderBlock, ParagraphBlock
from pdf2epub.epub.xhtml import build_chapters


def _parsed_project(fixture_corpus: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "commands.bepub-project",
        fixture_corpus / "digital_single_column.pdf",
    )
    project, _ = workflow.parse_page(project, 0)
    return workflow, project


def test_text_edit_undo_redo_restores_translation_state(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow, project = _parsed_project(fixture_corpus, tmp_path)
    paragraph = next(
        block for block in project.document.pages[0].blocks if isinstance(block, ParagraphBlock)
    )
    document = DocumentEditor().edit_translation(project.document, paragraph.id, "manual")
    project = workflow.store.save(project.model_copy(update={"document": document}))
    service = StructureCommandService(store=workflow.store)

    changed = service.execute_edit(
        project,
        0,
        paragraph.id,
        text=f"{paragraph.effective_text} changed",
        block_type="paragraph",
    )
    changed_block = next(
        block for block in changed.project.document.pages[0].blocks if block.id == paragraph.id
    )
    assert isinstance(changed_block, ParagraphBlock)
    assert changed_block.translation is not None
    assert changed_block.translation.status == "stale"
    assert changed.project.document.edit_audit[-1].action == "execute"

    undone = service.undo(changed.project)
    restored = next(
        block for block in undone.project.document.pages[0].blocks if block.id == paragraph.id
    )
    assert isinstance(restored, ParagraphBlock)
    assert restored.translation is not None
    assert restored.translation.status == "user_edited"
    redone = service.redo(undone.project)
    assert redone.project.document.edit_audit[-1].action == "redo"
    assert service.stack.can_undo
    assert not service.stack.can_redo


def test_header_conversion_requires_translation_confirmation_and_preserves_id(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow, project = _parsed_project(fixture_corpus, tmp_path)
    paragraph = next(
        block for block in project.document.pages[0].blocks if isinstance(block, ParagraphBlock)
    )
    document = DocumentEditor().edit_translation(project.document, paragraph.id, "manual")
    project = workflow.store.save(project.model_copy(update={"document": document}))
    service = StructureCommandService(store=workflow.store)
    with pytest.raises(TranslationConflictError):
        service.execute_edit(
            project,
            0,
            paragraph.id,
            text=paragraph.effective_text,
            block_type="page_header",
        )
    result = service.execute_edit(
        project,
        0,
        paragraph.id,
        text=paragraph.effective_text,
        block_type="page_header",
        confirm_translation_loss=True,
    )
    header = next(
        block for block in result.project.document.pages[0].blocks if block.id == paragraph.id
    )
    assert isinstance(header, PageHeaderBlock)
    assert result.translation_disposition == "removed"
    assert header.effective_text not in "\n".join(
        chapter.body_html for chapter in build_chapters(result.project.document)
    )
    restored = service.undo(result.project)
    block = next(
        block for block in restored.project.document.pages[0].blocks if block.id == paragraph.id
    )
    assert isinstance(block, ParagraphBlock)
    assert block.translation is not None


def test_merge_and_split_commands_are_auditable_and_stable(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow, project = _parsed_project(fixture_corpus, tmp_path)
    paragraphs = [
        block for block in project.document.pages[0].blocks if isinstance(block, ParagraphBlock)
    ]
    service = StructureCommandService(store=workflow.store)
    merged = service.execute_merge(project, 0, paragraphs[0].id)
    merged_id = merged.selected_block_id
    assert merged_id is not None and merged_id.startswith("merge-")
    undone = service.undo(merged.project)
    redone = service.redo(undone.project)
    assert any(block.id == merged_id for block in redone.project.document.pages[0].blocks)
    merged_block = next(
        block for block in redone.project.document.pages[0].blocks if block.id == merged_id
    )
    assert isinstance(merged_block, ParagraphBlock)
    split = service.execute_split(
        redone.project, 0, merged_id, max(1, len(merged_block.effective_text) // 2)
    )
    split_ids = [
        block.id
        for block in split.project.document.pages[0].blocks
        if block.id.startswith("split-")
    ]
    assert len(split_ids) == 2
    assert all(
        split.command_id in block.provenance.edit_operation_ids
        for block in split.project.document.pages[0].blocks
        if block.id in split_ids
    )


def test_session_stack_enforces_its_finite_limit(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow, project = _parsed_project(fixture_corpus, tmp_path)
    paragraph = next(
        block for block in project.document.pages[0].blocks if isinstance(block, ParagraphBlock)
    )
    service = StructureCommandService(
        store=workflow.store,
        stack=SessionCommandStack(limit=2),
    )
    current = project
    for suffix in ("one", "two", "three"):
        result = service.execute_edit(
            current,
            0,
            paragraph.id,
            text=f"{paragraph.effective_text} {suffix}",
            block_type="paragraph",
        )
        current = result.project
    current = service.undo(current).project
    current = service.undo(current).project
    with pytest.raises(ValueError, match="Nothing to undo"):
        service.undo(current)

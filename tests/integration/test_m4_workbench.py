from __future__ import annotations

from pathlib import Path

from pdf2epub.application.commands import StructureCommandService
from pdf2epub.application.warnings import acknowledge_warning, synchronize_page_parser_warnings
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import ParagraphBlock


def test_m4_audit_and_warning_state_persist_but_undo_stack_does_not(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    root = tmp_path / "m4-reopen.bepub-project"
    project = workflow.create_project(root, fixture_corpus / "digital_single_column.pdf")
    project, _ = workflow.parse_page(project, 0)
    paragraph = next(
        block for block in project.document.pages[0].blocks if isinstance(block, ParagraphBlock)
    )
    commands = StructureCommandService(store=workflow.store)
    changed = commands.execute_edit(
        project,
        0,
        paragraph.id,
        text=f"{paragraph.effective_text} audited",
        block_type="paragraph",
    )
    page = changed.project.document.pages[0].model_copy(
        update={"parse_warnings": ["m4_manual_review"]}
    )
    document = changed.project.document.model_copy(update={"pages": [page]})
    document = synchronize_page_parser_warnings(document, 0)
    document = acknowledge_warning(document, document.warnings[0].id)
    saved = workflow.store.save(changed.project.model_copy(update={"document": document}))

    reopened = workflow.load_project(root)
    assert reopened.document == saved.document
    assert reopened.document.edit_audit[-1].kind == "edit_block"
    assert reopened.document.warnings[0].acknowledged_at is not None
    fresh_commands = StructureCommandService(store=workflow.store)
    assert not fresh_commands.stack.can_undo
    assert not fresh_commands.stack.can_redo

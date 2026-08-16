from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import HeadingBlock, ParagraphBlock
from pdf2epub.epub.builder import EpubBuilder
from pdf2epub.epub.validator import EpubValidator


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the non-GUI M1 vertical slice")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--epubcheck-jar", type=Path, required=True)
    arguments = parser.parse_args()

    workspace = arguments.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    project_root = workspace / "digital-single-column.bepub-project"
    if project_root.exists():
        raise SystemExit(f"Verification project already exists: {project_root}")

    workflow = BookWorkflow()
    project = workflow.create_project(project_root, arguments.pdf, title="Digital Single Column")
    project, first_parse_count = workflow.parse_all(project)
    project, second_parse_count = workflow.parse_all(project)
    if first_parse_count == 0 or second_parse_count != 0:
        raise RuntimeError("Parse cache verification failed")

    first_text = next(
        block
        for page in project.document.pages
        for block in page.blocks
        if isinstance(block, (ParagraphBlock, HeadingBlock))
    )
    edited_text = f"{first_text.effective_text} (edited)"
    document = DocumentEditor().edit_text(
        project.document, project.document.pages[0].page_index, first_text.id, edited_text
    )
    project = workflow.store.save(project.model_copy(update={"document": document}))
    reopened = workflow.load_project(project_root)
    reopened_text = next(
        block
        for page in reopened.document.pages
        for block in page.blocks
        if block.id == first_text.id
    )
    if not isinstance(reopened_text, (ParagraphBlock, HeadingBlock)):
        raise RuntimeError("Edited block unexpectedly changed to a non-text type")
    if reopened_text.effective_text != edited_text:
        raise RuntimeError("Edited text did not survive project round-trip")

    output = workspace / "exports" / "digital-single-column.epub"
    build = EpubBuilder().build(reopened.document, project_root, output)
    validation = EpubValidator(arguments.epubcheck_jar).validate(output)
    print(
        json.dumps(
            {
                "project": str(project_root),
                "first_parse_count": first_parse_count,
                "second_parse_count": second_parse_count,
                "build": build.model_dump(),
                "validation": validation.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if validation.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())

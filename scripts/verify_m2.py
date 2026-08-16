from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import ParagraphBlock
from pdf2epub.epub.builder import EpubBuilder, EpubBuildOptions
from pdf2epub.epub.validator import EpubValidator
from pdf2epub.translation.fake import FakeTranslator
from pdf2epub.translation.service import TranslationService


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the deterministic M2 vertical slice")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--epubcheck-jar", type=Path, required=True)
    arguments = parser.parse_args()

    workspace = arguments.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    project_root = workspace / "m2.bepub-project"
    if project_root.exists():
        raise SystemExit(f"Verification project already exists: {project_root}")

    workflow = BookWorkflow()
    project = workflow.create_project(project_root, arguments.pdf, title="M2 Fixture")
    project, _ = workflow.parse_all(project)
    paragraph_ids = [
        block.id
        for page in project.document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    ]
    if len(paragraph_ids) < 2:
        raise RuntimeError("M2 verification requires at least two paragraphs")

    partial_fake = FakeTranslator(failures={paragraph_ids[-1]})
    partial = asyncio.run(
        TranslationService(partial_fake, store=workflow.store).translate_selection(
            project, paragraph_ids
        )
    )
    if partial.failed_count != 1:
        raise RuntimeError("Partial failure verification failed")

    retry_fake = FakeTranslator()
    retried = asyncio.run(
        TranslationService(retry_fake, store=workflow.store).translate_selection(
            partial.project, paragraph_ids
        )
    )
    if retry_fake.call_count != 1:
        raise RuntimeError("Retry unexpectedly called already translated paragraphs")

    editor = DocumentEditor()
    document = editor.edit_text(
        retried.project.document, 0, paragraph_ids[0], "Changed synthetic source paragraph."
    )
    project = workflow.store.save(retried.project.model_copy(update={"document": document}))
    first = next(
        block
        for page in project.document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock) and block.id == paragraph_ids[0]
    )
    if first.translation is None or first.translation.status != "stale":
        raise RuntimeError("Source edit did not mark its translation stale")

    final_fake = FakeTranslator()
    final = asyncio.run(
        TranslationService(final_fake, store=workflow.store).translate_selection(
            project, paragraph_ids
        )
    )
    calls_before_repeat = final_fake.call_count
    repeated = asyncio.run(
        TranslationService(final_fake, store=workflow.store).translate_selection(
            final.project, paragraph_ids
        )
    )
    if final_fake.call_count != calls_before_repeat:
        raise RuntimeError("Repeated translation did not use valid IR/cache state")

    output = workspace / "exports" / "m2-bilingual.epub"
    build = EpubBuilder().build(
        repeated.project.document,
        project_root,
        output,
        options=EpubBuildOptions(mode="source_translation"),
    )
    validation = EpubValidator(arguments.epubcheck_jar).validate(output)
    print(
        json.dumps(
            {
                "project": str(project_root),
                "partial_failure_count": partial.failed_count,
                "retry_calls": retry_fake.call_count,
                "repeat_calls": final_fake.call_count,
                "build": build.model_dump(),
                "validation": validation.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if validation.passed and not build.warnings else 3


if __name__ == "__main__":
    raise SystemExit(main())

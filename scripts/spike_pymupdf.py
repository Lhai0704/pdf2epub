# mypy: disallow-untyped-calls=False
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import HeadingBlock, ImageBlock, Page, ParagraphBlock


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reproducible PyMuPDF M1 spike")
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    names = (
        "digital_single_column.pdf",
        "digital_two_column.pdf",
        "digital_image_caption.pdf",
        "digital_structure_edges.pdf",
    )
    results: dict[str, object] = {}
    workflow = BookWorkflow()
    for name in names:
        source = arguments.fixtures / name
        project_root = arguments.output / f"{source.stem}.bepub-project"
        if project_root.exists():
            raise SystemExit(f"Spike project already exists: {project_root}")
        project = workflow.create_project(project_root, source)
        project, _ = workflow.parse_all(project)
        text_blocks = [
            block
            for page in project.document.pages
            for block in page.blocks
            if isinstance(block, (ParagraphBlock, HeadingBlock))
        ]
        results[name] = {
            "pages": len(project.document.pages),
            "headings": [
                block.effective_text for block in text_blocks if isinstance(block, HeadingBlock)
            ],
            "paragraph_count": sum(isinstance(block, ParagraphBlock) for block in text_blocks),
            "image_count": sum(
                isinstance(block, ImageBlock)
                for page in project.document.pages
                for block in page.blocks
            ),
            "first_text": text_blocks[0].effective_text if text_blocks else None,
            "last_text": text_blocks[-1].effective_text if text_blocks else None,
            "representations": _representation_counts(source),
        }
        _write_overlays(source, project.document.pages, arguments.output / "overlays" / source.stem)
    (arguments.output / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(arguments.output / "summary.json")
    return 0


def _representation_counts(source: Path) -> list[dict[str, int]]:
    counts = []
    with pymupdf.open(source) as document:
        for page in document:
            dictionary = page.get_text("dict", sort=False)
            raw_dictionary = page.get_text("rawdict", sort=False)
            counts.append(
                {
                    "blocks": len(page.get_text("blocks", sort=False)),
                    "words": len(page.get_text("words", sort=False)),
                    "dict_blocks": len(dictionary.get("blocks", [])),
                    "rawdict_blocks": len(raw_dictionary.get("blocks", [])),
                    "images": len(page.get_images(full=True)),
                }
            )
    return counts


def _write_overlays(source: Path, pages: list[Page], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(source) as document:
        for page_model in pages:
            page_index = page_model.page_index
            page = document.load_page(page_index)
            for block in page_model.blocks:
                bbox = block.bbox
                page.draw_rect(
                    pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                    color=(0.1, 0.35, 0.9),
                    width=1,
                    overlay=True,
                )
            page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(
                output / f"page-{page_index + 1:03d}.png"
            )


if __name__ == "__main__":
    raise SystemExit(main())

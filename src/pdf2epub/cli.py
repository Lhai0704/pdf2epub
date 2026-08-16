from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import Pdf2EpubError
from pdf2epub.epub.builder import EpubBuilder
from pdf2epub.epub.validator import EpubValidator
from pdf2epub.fixtures import generate_fixture_corpus
from pdf2epub.pdf.analyzer import PdfAnalyzer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2epub", description="Local-first PDF to EPUB workbench"
    )
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    fixtures = commands.add_parser("fixtures", help="Generate the legal PDF fixture corpus")
    fixture_commands = fixtures.add_subparsers(dest="fixture_command", required=True)
    fixture_generate = fixture_commands.add_parser("generate")
    fixture_generate.add_argument("--output", type=Path, required=True)

    inspect = commands.add_parser(
        "inspect", help="Inspect native PDF suitability without logging text"
    )
    inspect.add_argument("pdf", type=Path)

    project = commands.add_parser("project", help="Create a versioned project")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    project_create = project_commands.add_parser("create")
    project_create.add_argument("--source", type=Path, required=True)
    project_create.add_argument("--destination", type=Path, required=True)
    project_create.add_argument("--title")

    parse = commands.add_parser("parse", help="Parse one page or all pages into Document IR")
    parse.add_argument("project", type=Path)
    parse.add_argument("--page", type=int, help="One-based page number; omit for all pages")

    export = commands.add_parser("export", help="Build and validate a monolingual EPUB")
    export.add_argument("project", type=Path)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--epubcheck-jar", type=Path)

    validate = commands.add_parser("validate", help="Run EPUBCheck")
    validate.add_argument("epub", type=Path)
    validate.add_argument("--epubcheck-jar", type=Path)

    gui = commands.add_parser("gui", help="Open the PySide6 workbench")
    gui.add_argument("--source", type=Path)
    gui.add_argument("--project", type=Path, required=True)
    gui.add_argument("--epubcheck-jar", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if arguments.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        return _dispatch(arguments)
    except (Pdf2EpubError, ValueError, KeyError) as exc:
        logging.error("%s", exc)
        return 2


def _dispatch(arguments: argparse.Namespace) -> int:
    if arguments.command == "fixtures":
        for path in generate_fixture_corpus(arguments.output):
            print(path)
        return 0
    if arguments.command == "inspect":
        inspection = PdfAnalyzer().inspect_document(arguments.pdf)
        print(inspection.model_dump_json(indent=2))
        return 0

    workflow = BookWorkflow()
    if arguments.command == "project":
        project = workflow.create_project(
            arguments.destination, arguments.source, title=arguments.title
        )
        print(project.root)
        return 0
    if arguments.command == "parse":
        project = workflow.load_project(arguments.project)
        if arguments.page is not None:
            if arguments.page < 1 or arguments.page > len(project.document.pages):
                raise ValueError("Page number is outside the project")
            project, cache_hit = workflow.parse_page(project, arguments.page - 1)
            print(json.dumps({"page": arguments.page, "cache_hit": cache_hit}))
        else:
            _, parsed_count = workflow.parse_all(project)
            print(json.dumps({"parsed_pages": parsed_count}))
        return 0
    if arguments.command == "export":
        project = workflow.load_project(arguments.project)
        project, _ = workflow.parse_all(project)
        build = EpubBuilder().build(project.document, Path(project.root), arguments.output)
        report = EpubValidator(arguments.epubcheck_jar).validate(arguments.output)
        print(
            json.dumps(
                {"build": build.model_dump(), "validation": report.model_dump()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if report.passed else 3
    if arguments.command == "validate":
        report = EpubValidator(arguments.epubcheck_jar).validate(arguments.epub)
        print(report.model_dump_json(indent=2))
        return 0 if report.passed else 3
    if arguments.command == "gui":
        from pdf2epub.gui.app import run_gui

        return run_gui(arguments.project, arguments.source, arguments.epubcheck_jar)
    raise AssertionError(f"Unhandled command: {arguments.command}")


if __name__ == "__main__":
    sys.exit(main())

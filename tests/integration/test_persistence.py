from __future__ import annotations

import os
from pathlib import Path

import pytest

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import ProjectPersistenceError
from pdf2epub.persistence.project_store import ProjectStore, atomic_write_json


def test_project_create_parse_save_load_and_source_change(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    root = tmp_path / "book.bepub-project"
    project = workflow.create_project(root, fixture_corpus / "digital_single_column.pdf")
    copied = root / "source" / "original.pdf"
    assert copied.is_file()
    project, cache_hit = workflow.parse_page(project, 0)
    assert not cache_hit
    reopened = workflow.load_project(root)
    assert reopened.document == project.document
    with copied.open("ab") as handle:
        handle.write(b"changed")
    changed = workflow.load_project(root)
    assert changed.source_changed
    assert changed.document.pages[0].parse_status == "stale"


def test_atomic_write_failure_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "document.json"
    output.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ProjectPersistenceError):
        atomic_write_json(output, '{"new": true}')
    assert output.read_text(encoding="utf-8") == '{"old": true}\n'


def test_project_suffix_is_required(fixture_corpus: Path, tmp_path: Path) -> None:
    with pytest.raises(ProjectPersistenceError):
        ProjectStore().create(
            tmp_path / "not-a-project", fixture_corpus / "digital_single_column.pdf"
        )

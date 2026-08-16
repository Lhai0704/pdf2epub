from __future__ import annotations

import json
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


def test_m1_document_is_migrated_in_memory_then_saved_as_1_3(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    root = tmp_path / "legacy.bepub-project"
    project = workflow.create_project(root, fixture_corpus / "digital_single_column.pdf")
    project, _ = workflow.parse_page(project, 0)
    document_path = root / "document.json"
    payload = json.loads(document_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.0"
    payload.pop("translation_settings")
    for page in payload["pages"]:
        for block in page["blocks"]:
            block.pop("translation", None)
    document_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = workflow.load_project(root)
    assert loaded.migrated_from_schema == "1.0"
    assert loaded.document.schema_version == "1.3"
    assert loaded.document.pages[0].blocks[0].id == project.document.pages[0].blocks[0].id
    saved = workflow.store.save(loaded)
    assert saved.migrated_from_schema is None
    assert json.loads(document_path.read_text(encoding="utf-8"))["schema_version"] == "1.3"


def test_m2_document_11_migrates_without_reparse_or_translation_loss(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    root = tmp_path / "legacy-m2.bepub-project"
    project = workflow.create_project(root, fixture_corpus / "digital_single_column.pdf")
    project, _ = workflow.parse_page(project, 0)
    original_ids = [block.id for block in project.document.pages[0].blocks]
    document_path = root / "document.json"
    payload = json.loads(document_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.1"
    for page in payload["pages"]:
        for field in (
            "parser_version",
            "parser_options",
            "model_versions",
            "parser_override",
            "classification",
            "parse_error",
            "parse_warnings",
        ):
            page.pop(field, None)
        for block in page["blocks"]:
            block.pop("confidence", None)
            provenance = block["provenance"]
            for field in (
                "provider_id",
                "engine",
                "device",
                "precision",
                "model_versions",
                "raw_payload_schema",
                "raw_element_ids",
            ):
                provenance.pop(field, None)
    document_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = workflow.load_project(root)
    assert loaded.migrated_from_schema == "1.1"
    assert loaded.document.schema_version == "1.3"
    assert [block.id for block in loaded.document.pages[0].blocks] == original_ids
    assert loaded.document.pages[0].parser_id == "pymupdf_native"
    assert loaded.document.pages[0].parse_status == "parsed"


def test_m3_document_12_migrates_warnings_and_provenance_without_reparse(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    root = tmp_path / "legacy-m3.bepub-project"
    project = workflow.create_project(root, fixture_corpus / "digital_single_column.pdf")
    project, _ = workflow.parse_page(project, 0)
    document_path = root / "document.json"
    payload = json.loads(document_path.read_text(encoding="utf-8"))
    original_ids = [block["id"] for block in payload["pages"][0]["blocks"]]
    payload["schema_version"] = "1.2"
    payload.pop("edit_audit")
    payload.pop("warnings")
    payload["pages"][0]["parse_warnings"] = ["legacy_parser_warning"]
    for block in payload["pages"][0]["blocks"]:
        provenance = block["provenance"]
        provenance.pop("derived_from_block_ids")
        provenance.pop("edit_operation_ids")
        provenance.pop("source_region")
    document_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = workflow.load_project(root)
    assert loaded.migrated_from_schema == "1.2"
    assert loaded.document.schema_version == "1.3"
    assert [block.id for block in loaded.document.pages[0].blocks] == original_ids
    assert loaded.document.warnings[0].message == "legacy_parser_warning"
    assert loaded.document.warnings[0].affects_export


@pytest.mark.parametrize("invalid_shape", ["future-schema", "extra-field", "task-status"])
def test_invalid_document_shapes_are_rejected(
    invalid_shape: str, fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    root = tmp_path / f"invalid-{invalid_shape}.bepub-project"
    project = workflow.create_project(root, fixture_corpus / "digital_single_column.pdf")
    project, _ = workflow.parse_page(project, 0)
    document_path = root / "document.json"
    payload = json.loads(document_path.read_text(encoding="utf-8"))
    if invalid_shape == "future-schema":
        payload["schema_version"] = "2.0"
    elif invalid_shape == "extra-field":
        payload["unexpected"] = True
    else:
        paragraph = next(
            block
            for page in payload["pages"]
            for block in page["blocks"]
            if block["type"] == "paragraph"
        )
        paragraph["translation"] = {"status": "translating"}
    document_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProjectPersistenceError):
        workflow.load_project(root)

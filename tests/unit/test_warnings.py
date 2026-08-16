from __future__ import annotations

from pdf2epub.application.warnings import (
    acknowledge_warning,
    active_export_warnings,
    synchronize_page_parser_warnings,
)
from pdf2epub.domain.models import BookDocument, BookMetadata, Page, SourceDocument


def _document() -> BookDocument:
    return BookDocument(
        document_id="doc-warning",
        metadata=BookMetadata(title="Warnings"),
        source=SourceDocument(original_name="warning.pdf", sha256="a" * 64, size_bytes=1),
        pages=[
            Page(
                page_index=0,
                width=100,
                height=200,
                parse_warnings=["native_content_may_be_incomplete"],
            )
        ],
    )


def test_warning_identity_acknowledgement_and_resolution() -> None:
    document = synchronize_page_parser_warnings(_document(), 0)
    assert len(document.warnings) == 1
    warning_id = document.warnings[0].id
    acknowledged = acknowledge_warning(document, warning_id)
    assert acknowledged.warnings[0].acknowledged_at is not None
    assert active_export_warnings(acknowledged)

    page = acknowledged.pages[0].model_copy(update={"parse_warnings": []})
    cleared = acknowledged.model_copy(update={"pages": [page]})
    resolved = synchronize_page_parser_warnings(cleared, 0)
    assert resolved.warnings[0].id == warning_id
    assert resolved.warnings[0].resolved_at is not None
    assert active_export_warnings(resolved) == []

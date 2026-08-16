from __future__ import annotations

import html

from PySide6.QtWidgets import QTextBrowser

from pdf2epub.application.warnings import ProvenanceView


class ProvenanceInspector(QTextBrowser):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("provenanceInspector")
        self.setHtml("<p>Select a block to inspect its provenance.</p>")

    def show_provenance(self, value: ProvenanceView) -> None:
        rows = {
            "Page": str(value.page_index + 1),
            "Block": value.block_id,
            "Type": value.block_type,
            "BBox": ", ".join(f"{item:.2f}" for item in value.bbox),
            "Confidence": "n/a" if value.confidence is None else f"{value.confidence:.3f}",
            "Parser": f"{value.parser_id} {value.parser_version}",
            "Provider/engine": f"{value.provider_id or 'n/a'} / {value.engine or 'n/a'}",
            "Device/precision": f"{value.device or 'n/a'} / {value.precision or 'n/a'}",
            "Models": ", ".join(f"{key}={item}" for key, item in value.model_versions) or "n/a",
            "Options hash": value.options_hash,
            "Raw cache": value.raw_cache_path or "n/a",
            "Source spans": ", ".join(value.source_span_ids) or "n/a",
            "Raw elements": ", ".join(value.raw_element_ids) or "n/a",
            "Derived from": ", ".join(value.derived_from_block_ids) or "n/a",
            "Edit operations": ", ".join(value.edit_operation_ids) or "n/a",
            "Source region": (
                ", ".join(f"{item:.2f}" for item in value.source_region)
                if value.source_region is not None
                else "n/a"
            ),
            "Warnings": ", ".join(value.warning_codes) or "none",
        }
        body = "".join(
            f"<tr><th align='left'>{html.escape(label)}</th><td>{html.escape(content)}</td></tr>"
            for label, content in rows.items()
        )
        self.setHtml(f"<table>{body}</table>")

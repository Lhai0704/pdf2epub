from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pdf2epub.domain.models import BookDocument, ProjectWarning


def stable_warning_id(
    source: str,
    code: str,
    *,
    page_index: int | None = None,
    block_id: str | None = None,
) -> str:
    payload = json.dumps(
        [source, code, page_index, block_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"warn-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def synchronize_page_parser_warnings(document: BookDocument, page_index: int) -> BookDocument:
    page = next(page for page in document.pages if page.page_index == page_index)
    known_blocks = {block.id for block in page.blocks}
    desired: dict[str, ProjectWarning] = {}
    for raw in page.parse_warnings:
        parts = raw.split(":")
        code = parts[0]
        block_id = next((part for part in reversed(parts[1:]) if part in known_blocks), None)
        warning_id = stable_warning_id("parser", code, page_index=page_index, block_id=block_id)
        desired[warning_id] = ProjectWarning(
            id=warning_id,
            code=code,
            severity="warning",
            source="parser",
            message=raw,
            page_index=page_index,
            block_id=block_id,
            affects_export=True,
        )

    now = datetime.now(UTC)
    updated: list[ProjectWarning] = []
    seen: set[str] = set()
    for warning in document.warnings:
        if warning.source != "parser" or warning.page_index != page_index:
            updated.append(warning)
            continue
        replacement = desired.get(warning.id)
        if replacement is None:
            updated.append(
                warning.model_copy(
                    update={"resolved_at": warning.resolved_at or now, "block_id": None}
                )
            )
        else:
            updated.append(
                replacement.model_copy(
                    update={
                        "created_at": warning.created_at,
                        "acknowledged_at": warning.acknowledged_at,
                        "resolved_at": None,
                    }
                )
            )
            seen.add(warning.id)
    updated.extend(warning for key, warning in desired.items() if key not in seen)
    return document.model_copy(update={"warnings": updated})


def acknowledge_warning(document: BookDocument, warning_id: str) -> BookDocument:
    now = datetime.now(UTC)
    found = False
    warnings = []
    for warning in document.warnings:
        if warning.id == warning_id:
            warning = warning.model_copy(update={"acknowledged_at": now})
            found = True
        warnings.append(warning)
    if not found:
        raise KeyError(f"Warning not found: {warning_id}")
    return document.model_copy(update={"warnings": warnings, "updated_at": now})


def active_export_warnings(document: BookDocument) -> list[ProjectWarning]:
    return [warning for warning in document.warnings if warning.active and warning.affects_export]


@dataclass(frozen=True, slots=True)
class ProvenanceView:
    page_index: int
    block_id: str
    block_type: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    parser_id: str
    parser_version: str
    options_hash: str
    raw_cache_path: str | None
    provider_id: str | None
    engine: str | None
    device: str | None
    precision: str | None
    model_versions: tuple[tuple[str, str], ...]
    source_span_ids: tuple[str, ...]
    raw_element_ids: tuple[str, ...]
    derived_from_block_ids: tuple[str, ...]
    edit_operation_ids: tuple[str, ...]
    source_region: tuple[float, float, float, float] | None
    warning_codes: tuple[str, ...]


def provenance_view(document: BookDocument, block_id: str) -> ProvenanceView:
    for page in document.pages:
        for block in page.blocks:
            if block.id != block_id:
                continue
            value = block.provenance
            return ProvenanceView(
                page_index=page.page_index,
                block_id=block.id,
                block_type=block.type,
                bbox=block.bbox.as_tuple(),
                confidence=block.confidence,
                parser_id=value.parser_id,
                parser_version=value.parser_version,
                options_hash=value.options_hash,
                raw_cache_path=value.raw_cache_path,
                provider_id=value.provider_id,
                engine=value.engine,
                device=value.device,
                precision=value.precision,
                model_versions=tuple(sorted(value.model_versions.items())),
                source_span_ids=tuple(value.source_span_ids),
                raw_element_ids=tuple(value.raw_element_ids),
                derived_from_block_ids=tuple(value.derived_from_block_ids),
                edit_operation_ids=tuple(value.edit_operation_ids),
                source_region=(
                    value.source_region.as_tuple() if value.source_region is not None else None
                ),
                warning_codes=tuple(value.warnings),
            )
    raise KeyError(f"Block not found: {block_id}")

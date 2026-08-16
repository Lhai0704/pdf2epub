from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from pdf2epub.domain.errors import ProjectPersistenceError

CURRENT_DOCUMENT_SCHEMA = "1.3"


def _classification_from_quality(page: dict[str, Any]) -> dict[str, Any]:
    quality = page.get("quality") or {}
    status = quality.get("status")
    characters = int(quality.get("character_count", 0))
    image_ratio = float(quality.get("image_coverage_ratio", 0.0))
    if status == "usable":
        kind = "digital"
        recommended = "native"
        reasons = ["usable_text_layer"]
    elif status == "no_text" and image_ratio >= 0.8:
        kind = "scanned"
        recommended = "paddle_ppstructure_v3"
        reasons = ["large_page_image", "little_extractable_text"]
    elif status == "no_text" and image_ratio == 0:
        kind = "blank"
        recommended = "native"
        reasons = ["no_page_content"]
    else:
        kind = "suspect"
        recommended = "paddle_ppstructure_v3" if image_ratio >= 0.5 else "native"
        reasons = ["little_extractable_text" if characters < 20 else "invalid_text_layer"]
    return {
        "kind": kind,
        "confidence": 0.6,
        "reasons": reasons,
        "recommended_parser": recommended,
        "classifier_version": "migration-from-native-quality-v1",
    }


def _migrate_11_to_12(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(payload)
    migrated["schema_version"] = "1.2"
    for page in migrated.get("pages", []):
        blocks = page.get("blocks", [])
        parse_status = page.get("parse_status", "unparsed")
        if parse_status == "unparsed" and not blocks:
            page["parser_id"] = None
        page.setdefault("parser_version", None)
        if page["parser_version"] is None and blocks:
            page["parser_version"] = blocks[0].get("provenance", {}).get("parser_version")
        page.setdefault("parser_options", {})
        page.setdefault("model_versions", {})
        page.setdefault("parser_override", "auto")
        page.setdefault("classification", _classification_from_quality(page))
        page.setdefault("parse_error", None)
        page.setdefault("parse_warnings", [])
        for block in blocks:
            block.setdefault("confidence", None)
            provenance = block.get("provenance", {})
            provenance.setdefault("provider_id", None)
            provenance.setdefault("engine", None)
            provenance.setdefault("device", None)
            provenance.setdefault("precision", None)
            provenance.setdefault("model_versions", {})
            provenance.setdefault("raw_payload_schema", None)
            provenance.setdefault("raw_element_ids", [])
            provenance.setdefault("derived_from_block_ids", [])
            provenance.setdefault("edit_operation_ids", [])
            provenance.setdefault("source_region", None)
    return migrated


def _warning_id(page_index: int, code: str, ordinal: int) -> str:
    payload = json.dumps(
        ["parser", page_index, code, ordinal], ensure_ascii=False, separators=(",", ":")
    )
    return f"warn-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _migrate_12_to_13(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(payload)
    migrated["schema_version"] = "1.3"
    created_at = migrated.get("updated_at") or migrated.get("created_at")
    warnings: list[dict[str, Any]] = []
    for page in migrated.get("pages", []):
        page_index = int(page.get("page_index", 0))
        for ordinal, code in enumerate(page.get("parse_warnings", [])):
            warning = {
                "id": _warning_id(page_index, str(code), ordinal),
                "code": str(code).split(":", 1)[0],
                "severity": "warning",
                "source": "parser",
                "message": str(code),
                "page_index": page_index,
                "block_id": None,
                "affects_export": True,
                "acknowledged_at": None,
                "resolved_at": None,
            }
            if created_at is not None:
                warning["created_at"] = created_at
            warnings.append(warning)
        for block in page.get("blocks", []):
            provenance = block.get("provenance", {})
            provenance.setdefault("derived_from_block_ids", [])
            provenance.setdefault("edit_operation_ids", [])
            provenance.setdefault("source_region", None)
    migrated.setdefault("edit_audit", [])
    migrated.setdefault("warnings", warnings)
    return migrated


def migrate_document_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return a validated-shape candidate without mutating the loaded JSON object."""
    version = payload.get("schema_version")
    if version == CURRENT_DOCUMENT_SCHEMA:
        return payload, None
    if version not in {"1.0", "1.1", "1.2"}:
        raise ProjectPersistenceError(f"Unsupported document schema version: {version!r}")

    migrated = copy.deepcopy(payload)
    if version == "1.0":
        migrated["schema_version"] = "1.1"
        migrated.setdefault(
            "translation_settings",
            {
                "target_language": "zh-CN",
                "provider_id": "longcat",
                "model": "LongCat-2.0",
                "prompt_version": "translate-v1",
                "glossary": [],
                "style_instructions": None,
                "remote_consent_at": None,
            },
        )
        for page in migrated.get("pages", []):
            for block in page.get("blocks", []):
                if block.get("type") == "paragraph":
                    block.setdefault("translation", None)
    if migrated.get("schema_version") in {"1.0", "1.1"}:
        migrated = _migrate_11_to_12(migrated)
    return _migrate_12_to_13(migrated), str(version)

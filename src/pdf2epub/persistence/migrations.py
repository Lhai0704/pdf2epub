from __future__ import annotations

import copy
from typing import Any

from pdf2epub.domain.errors import ProjectPersistenceError

CURRENT_DOCUMENT_SCHEMA = "1.2"


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
    return migrated


def migrate_document_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return a validated-shape candidate without mutating the loaded JSON object."""
    version = payload.get("schema_version")
    if version == CURRENT_DOCUMENT_SCHEMA:
        return payload, None
    if version not in {"1.0", "1.1"}:
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
    return _migrate_11_to_12(migrated), str(version)

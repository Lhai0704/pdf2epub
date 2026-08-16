from __future__ import annotations

import copy
from typing import Any

from pdf2epub.domain.errors import ProjectPersistenceError

CURRENT_DOCUMENT_SCHEMA = "1.1"


def migrate_document_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return a validated-shape candidate without mutating the loaded JSON object."""
    version = payload.get("schema_version")
    if version == CURRENT_DOCUMENT_SCHEMA:
        return payload, None
    if version != "1.0":
        raise ProjectPersistenceError(f"Unsupported document schema version: {version!r}")

    migrated = copy.deepcopy(payload)
    migrated["schema_version"] = CURRENT_DOCUMENT_SCHEMA
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
    return migrated, "1.0"

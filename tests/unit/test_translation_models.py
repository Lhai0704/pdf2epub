from __future__ import annotations

import pytest
from pydantic import ValidationError

from pdf2epub.domain.models import (
    TranslationProvenance,
    TranslationRecord,
    TranslationSettings,
)

HASH = "a" * 64


def test_translation_settings_have_stable_glossary_version() -> None:
    first = TranslationSettings()
    second = TranslationSettings()
    assert first.glossary_version == second.glossary_version
    assert len(first.glossary_version) == 64


def test_valid_translation_requires_text_and_matching_origin() -> None:
    provenance = TranslationProvenance(
        origin="provider",
        provider_id="fake",
        model="fake-model",
        prompt_version="translate-v1",
        glossary_version=HASH,
    )
    with pytest.raises(ValidationError):
        TranslationRecord(
            status="translated",
            source_fingerprint=HASH,
            provenance=provenance,
        )
    with pytest.raises(ValidationError):
        TranslationRecord(
            text="manual",
            status="user_edited",
            source_fingerprint=HASH,
            provenance=provenance,
        )

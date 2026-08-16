from __future__ import annotations

import pytest

from pdf2epub.domain.models import NativeTextQuality
from pdf2epub.pdf.classifier import classify_page


def quality(
    *,
    characters: int,
    image: float,
    replacement: float = 0,
    control: float = 0,
) -> NativeTextQuality:
    return NativeTextQuality(
        status="usable" if characters >= 20 else "no_text",
        character_count=characters,
        replacement_character_ratio=replacement,
        control_character_ratio=control,
        image_coverage_ratio=image,
    )


@pytest.mark.parametrize(
    ("candidate", "rotation", "kind", "recommended"),
    [
        (quality(characters=0, image=0), 0, "blank", "native"),
        (quality(characters=19, image=0.8), 0, "scanned", "paddle_ppstructure_v3"),
        (quality(characters=80, image=0.8), 0, "image_text_layer", "native"),
        (
            quality(characters=79, image=0.8),
            0,
            "image_text_layer",
            "paddle_ppstructure_v3",
        ),
        (quality(characters=20, image=0.79), 0, "digital", "native"),
        (
            quality(characters=100, image=0.1, replacement=0.021),
            0,
            "suspect",
            "paddle_ppstructure_v3",
        ),
        (quality(characters=100, image=0.1), 90, "suspect", "native"),
    ],
)
def test_classifier_v1_thresholds(
    candidate: NativeTextQuality, rotation: int, kind: str, recommended: str
) -> None:
    result = classify_page(candidate, rotation)
    assert result.kind == kind
    assert result.recommended_parser == recommended
    assert result.reasons
    assert result.classifier_version == "native-signals-v1"


def test_classifier_reports_stable_invalid_text_reasons() -> None:
    result = classify_page(quality(characters=100, image=0.6, replacement=0.03, control=0.04), 0)
    assert result.kind == "suspect"
    assert result.confidence == 0.6
    assert {
        "invalid_text_layer",
        "high_replacement_rate",
        "high_control_rate",
        "large_page_image",
    }.issubset(result.reasons)

from __future__ import annotations

from pdf2epub.domain.models import NativeTextQuality, PageClassification, ParserChoice

CLASSIFIER_VERSION = "native-signals-v1"


def classify_page(quality: NativeTextQuality, rotation: int) -> PageClassification:
    """Classify a page from cheap, provider-neutral native PDF signals."""
    characters = quality.character_count
    image_ratio = quality.image_coverage_ratio
    replacement_ratio = quality.replacement_character_ratio
    control_ratio = quality.control_character_ratio
    invalid_text = replacement_ratio > 0.02 or control_ratio > 0.02
    reasons: list[str] = []

    if image_ratio >= 0.8:
        reasons.append("large_page_image")
        if characters < 20:
            reasons.append("little_extractable_text")
            return PageClassification(
                kind="scanned",
                confidence=0.95 if image_ratio >= 0.9 and characters < 10 else 0.8,
                reasons=reasons,
                recommended_parser="paddle_ppstructure_v3",
                classifier_version=CLASSIFIER_VERSION,
            )
        reasons.append("usable_text_layer" if not invalid_text else "invalid_text_layer")
        if replacement_ratio > 0.01:
            reasons.append("high_replacement_rate")
        if control_ratio > 0.01:
            reasons.append("high_control_rate")
        recommended: ParserChoice = (
            "native"
            if characters >= 80 and replacement_ratio <= 0.01 and control_ratio <= 0.01
            else "paddle_ppstructure_v3"
        )
        return PageClassification(
            kind="image_text_layer",
            confidence=0.95 if image_ratio >= 0.9 and characters >= 80 else 0.8,
            reasons=reasons,
            recommended_parser=recommended,
            classifier_version=CLASSIFIER_VERSION,
        )

    if characters == 0 and image_ratio == 0:
        return PageClassification(
            kind="blank",
            confidence=0.95,
            reasons=["no_page_content"],
            recommended_parser="native",
            classifier_version=CLASSIFIER_VERSION,
        )

    if characters >= 20 and not invalid_text and rotation == 0:
        confidence = (
            0.95
            if characters >= 80
            and replacement_ratio <= 0.01
            and control_ratio <= 0.01
            and image_ratio < 0.2
            else 0.8
        )
        return PageClassification(
            kind="digital",
            confidence=confidence,
            reasons=["usable_text_layer"],
            recommended_parser="native",
            classifier_version=CLASSIFIER_VERSION,
        )

    if characters < 20:
        reasons.append("little_extractable_text")
    if invalid_text:
        reasons.append("invalid_text_layer")
    if replacement_ratio > 0.02:
        reasons.append("high_replacement_rate")
    if control_ratio > 0.02:
        reasons.append("high_control_rate")
    if rotation != 0:
        reasons.append("rotated_page")
    if image_ratio >= 0.5:
        reasons.append("large_page_image")
    if not reasons:
        reasons.append("threshold_boundary")
    recommended = "paddle_ppstructure_v3" if image_ratio >= 0.5 or invalid_text else "native"
    return PageClassification(
        kind="suspect",
        confidence=0.6,
        reasons=reasons,
        recommended_parser=recommended,
        classifier_version=CLASSIFIER_VERSION,
    )

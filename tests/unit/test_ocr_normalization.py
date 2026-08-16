from __future__ import annotations

from pathlib import Path

from pdf2epub.domain.models import CaptionBlock, HeadingBlock, ImageBlock, ParagraphBlock
from pdf2epub.parsers.base import OcrParseOptions, PageContext
from pdf2epub.parsers.ocr_normalization import normalize_ppstructure_payload
from pdf2epub.pdf.analyzer import native_text_quality
from pdf2epub.pdf.classifier import classify_page


def test_fake_ppstructure_payload_normalizes_blocks_assets_and_provenance(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    source = fixture_corpus / "digital_single_column.pdf"
    quality = native_text_quality("", 612 * 792, 612 * 792)
    classification = classify_page(quality, 0)
    payload = {
        "res": {
            "width": 1700,
            "height": 2200,
            "parsing_res_list": [
                {
                    "block_label": "paragraph_title",
                    "block_content": "Chapter 1",
                    "block_bbox": [100, 100, 700, 250],
                    "block_id": 1,
                    "block_order": 1,
                },
                {
                    "block_label": "text",
                    "block_content": "repeat-\nable source text",
                    "block_bbox": [100, 300, 1200, 500],
                    "block_id": 2,
                    "block_order": 2,
                },
                {
                    "block_label": "table",
                    "block_content": "",
                    "block_bbox": [100, 600, 1200, 1100],
                    "block_id": 3,
                    "block_order": 3,
                },
                {
                    "block_label": "table_title",
                    "block_content": "Table 1. Generated values",
                    "block_bbox": [100, 1120, 1000, 1200],
                    "block_id": 4,
                    "block_order": 4,
                },
                {"block_label": "text", "block_bbox": [4, 3, 2, 1], "block_id": 5},
            ],
            "overall_ocr_res": {
                "rec_boxes": [[100, 100, 700, 250], [100, 300, 1200, 500]],
                "rec_scores": [0.99, 0.4],
            },
            "layout_det_res": {"boxes": []},
        }
    }
    context = PageContext(
        source_path=source,
        project_root=tmp_path,
        source_sha256="a" * 64,
        page_index=0,
        language="en",
    )
    result = normalize_ppstructure_payload(
        payload,
        context=context,
        options=OcrParseOptions(),
        page_width=612,
        page_height=792,
        rotation=0,
        quality=quality,
        classification=classification,
        parser_version="3.7.0",
        options_hash="options",
        parse_fingerprint="f" * 64,
        raw_cache_path="cache/parse/paddle/result.json.gz",
        package_versions={"paddleocr": "3.7.0", "paddlex": "3.7.2"},
        model_versions={"layout_model": "PP-DocLayout_plus-L"},
    )
    assert isinstance(result.page.blocks[0], HeadingBlock)
    paragraph = result.page.blocks[1]
    assert isinstance(paragraph, ParagraphBlock)
    assert paragraph.source_text_raw == "repeat-\nable source text"
    assert paragraph.source_text_normalized == "repeatable source text"
    assert paragraph.confidence == 0.4
    image = result.page.blocks[2]
    assert isinstance(image, ImageBlock)
    caption = result.page.blocks[3]
    assert isinstance(caption, CaptionBlock)
    assert caption.for_asset_id == image.asset_id
    assert result.assets[0].extraction_method == "rendered_crop"
    assert (tmp_path / result.assets[0].relative_path).is_file()
    assert any(warning.startswith("invalid_bbox_skipped") for warning in result.warnings)
    assert any(warning.startswith("low_ocr_confidence") for warning in result.warnings)
    assert paragraph.provenance.raw_payload_schema == "ppstructure-v3-result-json"
    assert paragraph.provenance.device == "gpu:0"

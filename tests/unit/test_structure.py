from __future__ import annotations

from pdf2epub.domain.models import BBox, TextStyle
from pdf2epub.structure.layout import LayoutItem, order_layout_items
from pdf2epub.structure.paragraphs import ExtractedLine, build_text_blocks


def test_two_column_reading_order() -> None:
    items = [
        LayoutItem((72, 100, 250, 115), "left-1"),
        LayoutItem((330, 100, 520, 115), "right-1"),
        LayoutItem((72, 125, 250, 140), "left-2"),
        LayoutItem((330, 125, 520, 140), "right-2"),
    ]
    assert [item.payload for item in order_layout_items(items, 612)] == [
        "left-1",
        "left-2",
        "right-1",
        "right-2",
    ]


def test_hyphenation_changes_normalized_text_only() -> None:
    lines = [
        ExtractedLine(
            ("span-1",), BBox(x0=10, y0=10, x1=100, y1=20), "repeat-", TextStyle(font_size=11)
        ),
        ExtractedLine(
            ("span-2",), BBox(x0=10, y0=22, x1=100, y1=32), "able text", TextStyle(font_size=11)
        ),
    ]
    blocks = build_text_blocks(
        lines,
        source_sha256="a" * 64,
        parser_id="test",
        parser_version="1",
        options_hash="options",
        raw_cache_path="cache/parse/test.json",
    )
    assert len(blocks) == 1
    assert blocks[0].source_text_raw == "repeat-\nable text"
    assert blocks[0].source_text_normalized == "repeatable text"

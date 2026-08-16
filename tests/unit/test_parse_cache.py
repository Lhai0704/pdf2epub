from __future__ import annotations

from pathlib import Path

from pdf2epub.domain.models import BBox, Page, ParagraphBlock, ProcessingProvenance
from pdf2epub.persistence.parse_cache import (
    OcrCacheKey,
    OcrCacheRecord,
    OcrParseCache,
    RegionOcrCacheKey,
    RegionOcrCacheRecord,
    RegionOcrParseCache,
)


def cache_key() -> OcrCacheKey:
    return OcrCacheKey(
        source_sha256="a" * 64,
        page_index=0,
        render_version="render-v1",
        dpi=200,
        rotation=0,
        parser_id="paddle_ppstructure_v3",
        parser_version="3.7.0",
        package_versions={"paddleocr": "3.7.0"},
        model_names={"layout": "layout"},
        model_hashes={"layout": "b" * 64},
        language="en",
        device="gpu:0",
        precision="fp32",
        engine="paddle_inference",
        options={"limit": 2200},
        normalization_schema="normalization-v1",
    )


def test_ocr_cache_round_trip_and_key_changes(tmp_path: Path) -> None:
    cache = OcrParseCache(tmp_path)
    key = cache_key()
    record = OcrCacheRecord(
        key=key,
        raw_data={"res": {"page_index": 0}},
        page=Page(page_index=0, width=100, height=200),
        assets=[],
    )
    path = cache.store(record)
    loaded = cache.load(key)
    assert loaded is not None
    assert loaded.raw_data == record.raw_data
    assert loaded.checksum
    changed = key.model_copy(update={"device": "cpu"})
    assert changed.fingerprint != key.fingerprint
    assert cache.load(changed) is None
    assert path.name == f"{key.fingerprint}.json.gz"


def test_corrupt_ocr_cache_becomes_miss_and_is_preserved(tmp_path: Path) -> None:
    cache = OcrParseCache(tmp_path)
    key = cache_key()
    path = cache.path_for(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not gzip")
    assert cache.load(key) is None
    assert not path.exists()
    assert list(path.parent.glob(f"{path.name}.corrupt-*"))


def test_region_cache_is_separate_and_region_sensitive(tmp_path: Path) -> None:
    base = cache_key().model_dump()
    key = RegionOcrCacheKey(**base, region=(10.0, 20.0, 80.0, 100.0))
    cache = RegionOcrParseCache(tmp_path)
    record = RegionOcrCacheRecord(
        key=key,
        raw_data={"res": {}},
        blocks=[
            ParagraphBlock(
                id="region-paragraph",
                bbox=BBox(x0=10, y0=20, x1=80, y1=40),
                reading_order=0,
                provenance=ProcessingProvenance(
                    source_sha256="a" * 64,
                    parser_id="paddle_ppstructure_v3",
                    parser_version="3.7.0",
                    options_hash="c" * 64,
                ),
                source_text_raw="Chapter 1",
                source_text_normalized="Chapter 1",
            )
        ],
        assets=[],
        warnings=[],
    )
    path = cache.store(record)
    loaded = cache.load(key)
    assert loaded is not None
    assert loaded.blocks[0].id == "region-paragraph"
    changed = key.model_copy(update={"region": (11.0, 20.0, 80.0, 100.0)})
    assert changed.fingerprint != key.fingerprint
    assert cache.load(changed) is None
    assert "regions" in path.parts

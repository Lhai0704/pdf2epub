from __future__ import annotations

import hashlib
from collections.abc import Iterable


def _stable_hash(parts: Iterable[str], *, length: int = 20) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()[:length]


def stable_span_id(
    source_sha256: str,
    page_index: int,
    bbox: tuple[float, float, float, float],
    raw_text: str,
) -> str:
    quantized = ",".join(f"{value:.2f}" for value in bbox)
    return f"span-{_stable_hash((source_sha256, str(page_index), quantized, raw_text))}"


def stable_block_id(source_span_ids: Iterable[str]) -> str:
    ids = tuple(source_span_ids)
    if not ids:
        raise ValueError("A block ID requires at least one source span ID")
    return f"blk-{_stable_hash(ids)}"


def merged_block_id(block_ids: Iterable[str]) -> str:
    ids = tuple(block_ids)
    if len(ids) < 2:
        raise ValueError("A merged block ID requires at least two block IDs")
    return f"merge-{_stable_hash(ids)}"


def split_block_id(parent_id: str, split_offset: int, side: str) -> str:
    if side not in {"left", "right"}:
        raise ValueError("side must be 'left' or 'right'")
    return f"split-{_stable_hash((parent_id, str(split_offset), side))}"


def stable_asset_id(content_sha256: str) -> str:
    return f"asset-{content_sha256[:20]}"

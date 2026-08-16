from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LayoutItem[T]:
    bbox: tuple[float, float, float, float]
    payload: T
    is_text: bool = True


def order_layout_items[T](items: list[LayoutItem[T]], page_width: float) -> list[LayoutItem[T]]:
    """Return an explainable one/two-column reading order for ordinary books."""
    if len(items) < 2:
        return items.copy()
    text_items = [item for item in items if item.is_text]
    starts = [item.bbox[0] for item in text_items]
    if len(starts) < 4 or max(starts, default=0) - min(starts, default=0) < page_width * 0.30:
        return sorted(items, key=lambda item: (item.bbox[1], item.bbox[0]))

    pivot = (min(starts) + max(starts)) / 2
    left_text = [item for item in text_items if item.bbox[0] <= pivot]
    right_text = [item for item in text_items if item.bbox[0] > pivot]
    if len(left_text) < 2 or len(right_text) < 2:
        return sorted(items, key=lambda item: (item.bbox[1], item.bbox[0]))

    full_width = [
        item
        for item in items
        if item.bbox[2] - item.bbox[0] >= page_width * 0.65 or not item.is_text
    ]
    narrow = [item for item in items if item not in full_width]
    left = [item for item in narrow if item.bbox[0] <= pivot]
    right = [item for item in narrow if item.bbox[0] > pivot]

    # Full-width content before the columns is emitted first; later figures are
    # placed by vertical position after the two simple columns.
    column_top = min((item.bbox[1] for item in narrow), default=0)
    before = [item for item in full_width if item.bbox[1] <= column_top]
    after = [item for item in full_width if item not in before]
    return (
        sorted(before, key=lambda item: (item.bbox[1], item.bbox[0]))
        + sorted(left, key=lambda item: (item.bbox[1], item.bbox[0]))
        + sorted(right, key=lambda item: (item.bbox[1], item.bbox[0]))
        + sorted(after, key=lambda item: (item.bbox[1], item.bbox[0]))
    )

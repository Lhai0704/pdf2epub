# PyMuPDF extraction spike

## Decision

M1 uses `Page.get_text("dict", sort=False)` as the adapter input. It exposes text blocks,
lines, spans, bbox values, font/style data, and displayed image blocks in one representation.

`blocks` is useful for fast diagnostics but loses span style detail. `words` is retained only
for future quality metrics. `rawdict` exposes character-level data that is unnecessarily large
for ordinary digital books.

Image bytes are separated into project assets immediately. A sanitized copy of the raw dict is
stored under `cache/parse/`; it is never exposed to GUI code or written to diagnostic logs.

The generated single-column, two-column, image/caption, and structure-edge fixtures are the
spike corpus. Tests assert structure summaries and bbox ranges rather than exact float bytes.

## Observed fixture results (PyMuPDF 1.28.2)

| Fixture | PyMuPDF blocks | words | IR headings | IR paragraphs | images |
| --- | ---: | ---: | ---: | ---: | ---: |
| single column | 6 | 50 | 1 | 3 | 0 |
| two column | 7 | 30 | 1 | 2 | 0 |
| image/caption | 4 text/image-summary blocks | 25 | 1 | 3 | 1 |
| structure edges | 10 across 3 pages | 46 | 1 | 8 | 0 |

`scripts/spike_pymupdf.py` reproduces the machine-readable counts and bbox overlay PNGs.

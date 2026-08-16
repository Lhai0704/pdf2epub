# ADR-008: Page routing, OCR cache, and fallback

Status: accepted for M3.

A provider-neutral parser registry exposes the existing `pymupdf_native` adapter and the
`paddle_ppstructure_v3` adapter. User-facing `native` maps to the stable legacy parser ID so M1/M2
provenance remains valid. Auto routing uses persisted classifier output; a per-page override wins.
The GUI and domain never consume Paddle response types.

Classification v1 uses native character count, replacement/control ratios, image coverage, and
rotation. The exact thresholds and stable reason codes are implemented in
`pdf2epub.pdf.classifier` and persisted with classifier version `native-signals-v1`.

OCR cache records are gzip JSON below `cache/parse/paddle_ppstructure_v3`. The key includes source
and page, raster version/DPI/rotation, parser and package versions, model names and artifact hashes,
language, device/precision/engine, every output-affecting option, and normalization schema. Records
include sanitized raw data, normalized IR/assets, checksum, and provenance. A 64 MiB uncompressed
limit, schema/key/checksum validation, and atomic replacement protect untrusted projects. Corrupt
records are preserved with a diagnostic suffix and treated as misses.

There is no automatic cross-parser or GPU-to-CPU fallback. Page failures continue only when they
are non-fatal; missing runtimes/models, resource failures, persistence failures, and GPU OOM stop
the batch. Retry, Force Native, and CPU retry are explicit user actions.

# ADR-011: Paddle-only regional reparse and separate cache

Status: accepted for M4.

M4 exposes regional reparse only when the actual parsed page adapter advertises `region_ocr`; the
only implementation is Paddle PP-StructureV3. Native pages and stale/unparsed/failed pages report
an explicit unsupported state. A region must cover at least half of one existing block. Linked
image/caption groups expand together.

The adapter renders only the selected PDF crop, maps crop-local coordinates back to page space and
returns a provider-neutral candidate. The project changes only after validation and confirmation;
failure, cancellation and empty output preserve existing blocks, assets and translations.

Region records use `paddle-region-cache-v1` below the Paddle parse cache. The key adds quantized
region geometry and region normalization/render versions to the M3 package/model/options key. The
whole-page cache remains unchanged. Cache payloads retain the M3 checksum, size limit, atomic write
and corrupt-record preservation guarantees.

# Document IR v1.0

`BookDocument` is the M0/M1 source of truth. It stores book/source metadata, ordered pages,
assets, and a discriminated union of paragraph, heading, and image blocks.

Text blocks keep three layers:

- `source_text_raw`: adapter output, never overwritten;
- `source_text_normalized`: deterministic line joining/hyphenation repair;
- `source_text_user`: optional user correction used by `effective_text`.

Block IDs derive from source hash, page, quantized bbox, and raw span identity. Editing/type
changes keep the ID; merge and split derive deterministic child IDs. Provenance records parser
and option versions, source span IDs, cache location, warnings, and manual-edit state.

Only schema version `1.0` is accepted. A future major version must add an explicit migration;
loaders reject unknown versions rather than silently discarding data.

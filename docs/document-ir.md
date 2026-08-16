# Document IR v1.1

`BookDocument` is the source of truth. It stores book/source metadata, ordered pages, assets,
translation settings, and a discriminated union of paragraph, heading, and image blocks.

Text blocks keep three layers:

- `source_text_raw`: adapter output, never overwritten;
- `source_text_normalized`: deterministic line joining/hyphenation repair;
- `source_text_user`: optional user correction used by `effective_text`.

Block IDs derive from source hash, page, quantized bbox, and raw span identity. Editing/type
changes keep the ID; merge and split derive deterministic child IDs. Provenance records parser
and option versions, source span IDs, cache location, warnings, and manual-edit state.

Paragraphs optionally contain a `TranslationRecord`. A missing record means untranslated;
terminal persisted states are `translated`, `failed`, `user_edited`, and `stale`. Provider/model,
prompt/glossary versions, source fingerprint, cache key, request ID, usage, timestamps, and a
sanitized error are retained. `queued` and `translating` are worker/UI states rather than crash-
sticky project states.

Headings are source-only in M2. A paragraph translation can receive heading and adjacent paragraph
context, but the response binds only to the current paragraph ID. Merge/split and heading-to-
paragraph conversion never guess a translation.

The loader explicitly migrates `1.0` documents to `1.1` in memory. The next normal save writes
`1.1` atomically. Unknown versions are rejected rather than silently discarding data.

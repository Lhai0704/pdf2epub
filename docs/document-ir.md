# Document IR v1.2

`BookDocument` is the source of truth. It stores source/book metadata, ordered pages, assets,
translation settings, and a discriminated union of paragraph, heading, image, and caption blocks.

## Pages and routing

`PageClassification` persists `kind`, confidence, stable reason codes, recommended parser, and
classifier version. Kinds are `digital`, `scanned`, `image_text_layer`, `suspect`, and `blank`.
User override is `auto`, `native`, or `paddle_ppstructure_v3`; range actions write the same field to
each selected page. `parser_id` records the adapter that produced current blocks and is null for an
unparsed page. Parser version/options/models, parse fingerprint/error/warnings, native quality, and
the terminal state are also persisted.

Changing an override does not replace content. If it targets another parser, an existing page
becomes `stale`. Parsing creates a candidate and atomically swaps it only after validation. A failed
reparse preserves old blocks; an empty failed page becomes `failed`.

## Blocks and provenance

Text blocks keep raw, deterministic normalized, and optional user-corrected source text. Optional
confidence is normalized to 0..1. Captions are minimal text blocks linked to an existing asset.

Native block IDs remain span-derived. OCR block IDs hash source/page, parser/model identity,
normalized bbox, and provider element identity. Identical inputs and cache replay produce identical
IDs. Edit/type changes preserve IDs; merge/split derive auditable IDs.

Provenance records source/parser/options, provider/engine/device/precision, package and model
versions/hashes, raw payload schema/element IDs, raw cache location, warnings, and manual-edit
state. Raw parser response formats never escape the adapter.

## Translation and reparse

Paragraphs optionally contain a terminal `TranslationRecord`: `translated`, `failed`,
`user_edited`, or `stale`. Queue/running states remain worker/UI-only. Provider/model,
prompt/glossary, source fingerprint, cache key, request ID, usage, timestamps, and sanitized errors
are retained.

Any user edit, merge/split block, or translation is a reparse conflict. Confirmation performs a
whole-page replacement, removes translations attached to replaced blocks, and does not infer block
matches. Old raw/cache data remains available. M3 has no undo or regional reparse.

## Migration

The loader migrates 1.0 -> 1.1 -> 1.2 and 1.1 -> 1.2 in memory. Existing IDs, text layers, edits,
translations, assets, and parsed content are preserved. A conservative classification with 0.60
confidence is derived from legacy native quality. The next normal save atomically writes 1.2.
Unknown future versions and invalid references are rejected.

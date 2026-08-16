# Document IR v1.3

`BookDocument` is the source of truth. It stores source/book metadata, ordered pages, assets,
translation settings, compact edit audit events, structured warnings, and a discriminated union of
paragraph, heading, image, caption, page-header, and page-footer blocks.

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
state. M4 also records derivation parent IDs, edit operation IDs and an optional source region. Raw
parser response formats never escape the adapter.

Page headers and footers are semantic text blocks rather than deleted content. Their IDs, text
layers, bbox and provenance persist and remain visible in the workbench, but they are not paragraph
translation units and are not serialized into EPUB.

## Translation and reparse

Paragraphs optionally contain a terminal `TranslationRecord`: `translated`, `failed`,
`user_edited`, or `stale`. Queue/running states remain worker/UI-only. Provider/model,
prompt/glossary, source fingerprint, cache key, request ID, usage, timestamps, and sanitized errors
are retained.

Any user edit, merge/split block, or translation is a reparse conflict. Confirmation performs a
whole-page replacement, removes translations attached to replaced blocks, and does not infer block
matches. Old raw/cache data remains available. M3 has no undo or regional reparse.

M4 structure changes are command-addressable. Text/type/heading changes retain IDs; merge derives
an ID from ordered inputs; split also includes the source fingerprint and offset. Execute, undo and
redo append `EditAuditEvent` records without duplicating book text. The finite inverse stack is
session-only. A structure operation that removes paragraph addressability requires confirmation and
does not infer translation inheritance; session undo restores the exact prior TranslationRecord.

Paddle regional reparse returns a candidate whose bbox values are mapped into full-page space. The
page-level parser ID and whole-page fingerprint remain unchanged; new blocks carry region and edit
operation provenance. Whole-page reparse treats those edits as conflicts.

## Warnings

`ProjectWarning` gives each warning a stable ID, code, severity, source, page/block reference,
export impact, acknowledgement and resolution timestamps. Acknowledgement never resolves a warning
or relaxes export. Old page/parser warning strings remain extraction evidence and are indexed into
structured warnings for the Warning Center.

## Migration

The loader migrates 1.0 -> 1.1 -> 1.2 -> 1.3, 1.1 -> 1.2 -> 1.3, and 1.2 -> 1.3 in memory.
Existing IDs, text layers, edits, translations, assets, routing and parsed content are preserved.
A conservative classification with 0.60 confidence is derived from legacy native quality. The next
normal save atomically writes 1.3. Unknown future versions and invalid references are rejected.

# ADR-007: Document IR 1.2 and whole-page reparse

Status: accepted for M3.

Document IR 1.2 adds persisted page classification, recommendation, parser override, actual parser
identity/version/options/models, parse errors/warnings, optional block confidence, expanded parser
provenance, and caption blocks linked to assets. Actual parser identity is null while a page is
unparsed. Persisted page states remain `unparsed`, `parsed`, `stale`, and `failed`.

The loader migrates 1.0 through 1.1 to 1.2 and migrates 1.1 directly. Existing IDs, raw/user text,
translations, assets, and parse output are retained. Migration derives a conservative low-
confidence classification from legacy native quality and never triggers parsing.

Changing an override only marks an incompatible existing parse stale. Reparse constructs and
validates a complete candidate before replacing a page. User edits, merge/split IDs, or any
translation require confirmation. Confirmed replacement does not match blocks or inherit
translations; old raw/cache files remain. Failed reparse preserves the old blocks and translations,
marking an existing page stale or an empty page failed. M3 intentionally has no undo, regional
reparse, or general structure-editing history.

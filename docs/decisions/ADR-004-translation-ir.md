# ADR-004: Translation IR 1.1 and migration

Status: accepted for M2.

Paragraph translation is stored directly on the paragraph in Document IR. The stable terminal
states are translated, failed, user-edited, and stale; queued/translating remain task state so a
crash cannot leave a project permanently running. Headings stay source-only in M2.

Document schema 1.0 is migrated deterministically to 1.1 in memory and written on the next normal
atomic save. Migration adds defaults only and does not alter block IDs, source text, assets, parse
state, or provenance. Unknown versions remain hard errors.

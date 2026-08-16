# ADR-010: Document IR 1.3 structure roles, audit, and warnings

Status: accepted for M4.

Document IR 1.3 adds semantic `page_header` and `page_footer` text blocks, compact edit audit
events, structured project warnings, and edit/derivation/region provenance. Header/footer blocks
retain source evidence and overlays but are excluded from translation and EPUB serialization.

Text/type/heading edits preserve block IDs. Merge IDs derive from ordered input IDs; split IDs also
include the source fingerprint and offset. Operations that change paragraph addressability never
guess translation inheritance and require confirmation when a TranslationRecord would be detached.

Warning acknowledgement means reviewed, not resolved. Active warnings marked `affects_export`
continue to require incomplete-export confirmation. The 1.2 to 1.3 migration preserves all prior
content and creates warning records from existing parser warning strings without reparsing.


# ADR-001: Document IR is the source of truth

Status: accepted for M0/M1.

Parser output is normalized into a strict, versioned Pydantic model. EPUB is regenerated from
the IR and is never loaded as project state. Raw extraction is retained separately with explicit
provenance; edits never overwrite raw text.

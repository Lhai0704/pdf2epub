# Repository instructions

## Mission
Build the local-first PDF-to-bilingual-EPUB desktop application described in `PROJECT_SPEC.md`.
Treat `PROJECT_SPEC.md` as the product and architecture source of truth.

## Scope discipline
Work milestone by milestone. Do not implement future milestones unless the user explicitly asks.
Prefer a working vertical slice over speculative abstractions.

## Architecture rules
- EPUB is an output format, never the internal source of truth.
- The versioned Document IR is the source of truth.
- Domain/core modules must not depend on PySide6.
- GUI must not depend on raw OCR/parser response formats.
- Every parser is behind an adapter/interface and normalizes into Document IR.
- Preserve raw extraction data and provenance.
- Never silently rewrite source book content with an LLM.
- Translation is paragraph-addressable, cached, and invalidated when source text changes.

## Quality gate
Before declaring a task complete:
- run `pytest`;
- run Ruff;
- run the configured type checker;
- for EPUB work, run EPUBCheck on a generated fixture;
- for GUI work, perform the documented smoke test;
- report what was verified and what was not.

## Tests
Add or update tests with every behavior change.
Prefer small legal fixtures and generated PDFs over copyrighted full books.
Use fake providers in automated tests; do not call paid AI APIs from CI.

## Dependencies
Add a new dependency only when it materially reduces complexity.
Record important architectural choices in `docs/decisions/`.
Do not add services such as Redis, Celery, or a web backend unless a demonstrated requirement justifies them.

## Safety / privacy
Treat PDFs as untrusted input.
Never commit API keys or user book content.
Do not include book text in diagnostic logs by default.

## Git
Keep changes reviewable and scoped to the active milestone.
Do not push, publish, or open a PR unless the user explicitly asks.

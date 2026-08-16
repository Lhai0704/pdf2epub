# M0-M4 architecture

```text
PDF analyzer -> page classification -> parser router
                                      /             \
                              Native adapter   Paddle adapter
                                      \             /
                                  Document IR 1.3
                                        |
                              application services
                    /             |                |          \
              PySide6 GUI   commands/reparse  translation   EPUB builder
                                                               |
                                                           EPUBCheck
```

- `domain` contains strict IR models, IDs, and errors. It has no PySide6, PyMuPDF, Paddle, or EPUB
  dependency.
- `pdf` performs safe inspection, provider-neutral page classification, and bounded rendering.
- `parsers` owns Native/Paddle response handling and emits only Document IR. Paddle is imported
  lazily when an OCR extra is installed and OCR is explicitly requested.
- `application` owns routing, page/range override, serial batch progress/cancellation, atomic
  candidate reparse, project workflows, structure commands, the session undo stack, warning
  lifecycle, and provider-neutral provenance queries.
- `persistence` owns copied sources, version migration, atomic project JSON, translation cache, and
  checksummed OCR parse cache.
- `gui` calls application services and never reads Paddle payloads. Opening a page only renders a
  preview; export never implicitly parses.
- `translation` remains paragraph-addressable. Source edits stale translations; confirmed reparse
  removes translations attached to replaced blocks rather than guessing a match.
- `epub` serializes IR and can add a visible incomplete-content notice after explicit confirmation.
  EPUB is never project state.

Auto routing uses the persisted classification recommendation unless a per-page Native/OCR
override is set. Actual parser identity describes the current blocks, so changing an override can
leave old content visible as `stale` until Parse/Reparse succeeds.

OCR runs one page at a time through one shared PP-StructureV3 pipeline. Cancellation is observed at
page boundaries. Each terminal page is atomically saved. Non-fatal page errors permit partial
progress; runtime, model, resource, OOM, and persistence failures stop the batch. No parser or
device fallback is silent.

Sanitized raw Native/OCR data and provenance are diagnostics/cache. Reopening a project uses
`document.json`; Document IR remains authoritative.

M4 structure commands validate and save a complete candidate before moving the in-memory undo/redo
cursor. Compact execute/undo/redo audit events persist, while inverse snapshots do not survive a
restart. Translation or whole-page parse changes clear the session stack.

Regional OCR is a Paddle-only adapter capability. It uses a separate region cache and returns a
candidate in full-page coordinates. GUI confirmation applies only the scoped blocks; cancellation
or failure does not mutate Document IR. Semantic page headers/footers remain inspectable but are
excluded from translation and EPUB. Active export-affecting warnings continue to require an
incomplete-content notice even after acknowledgement.

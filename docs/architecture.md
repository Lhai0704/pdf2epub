# M0/M1/M2 architecture

```text
PyMuPDF adapter -> Document IR <- project store
                       |
             application services
          /             |               \
    PySide6 GUI   translation pipeline   EPUB builder -> EPUBCheck
                         |
             Fake / LongCat adapters
```

- `domain` contains strict models, IDs, and error types. It has no PySide6, PyMuPDF, or EPUB
  dependency.
- `parsers` owns PyMuPDF response handling and emits only Document IR objects.
- `application` owns project workflows and the small auditable editor.
- `persistence` owns copied source files and atomic versioned JSON.
- `epub` serializes the IR but never becomes project state.
- `gui` calls application services and never reads parser payloads.
- `translation` owns provider-neutral requests, context, cache keys, batch orchestration, and
  provider adapters. Only a paragraph's result is persisted; headings and adjacent paragraphs
  are context only.
- Translation cache is an atomic project-local JSON optimization. The translation attached to
  the paragraph in Document IR remains the source of truth.

The native parser's sanitized payload cache is provenance/debug data. Reopening a project uses
`document.json`; unchanged pages are not reparsed.

M2 translation runs serially in a worker. Each terminal paragraph result is saved independently,
so cancellation or one provider failure does not roll back completed paragraphs. GUI project
mutation controls are disabled while a translation batch owns its project snapshot.

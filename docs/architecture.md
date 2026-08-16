# M0/M1 architecture

```text
PyMuPDF adapter -> Document IR <- project store
                       |
             application services
                /             \
          PySide6 GUI      EPUB builder -> EPUBCheck
```

- `domain` contains strict models, IDs, and error types. It has no PySide6, PyMuPDF, or EPUB
  dependency.
- `parsers` owns PyMuPDF response handling and emits only Document IR objects.
- `application` owns project workflows and the small auditable editor.
- `persistence` owns copied source files and atomic versioned JSON.
- `epub` serializes the IR but never becomes project state.
- `gui` calls application services and never reads parser payloads.

The native parser's sanitized payload cache is provenance/debug data. Reopening a project uses
`document.json`; unchanged pages are not reparsed.

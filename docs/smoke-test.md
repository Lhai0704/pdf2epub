# M1 GUI smoke test (Windows)

## Preparation

```powershell
Set-Location D:\Projects\pdf2epub
$uv = 'C:\Users\lhai0704\.local\bin\uv.exe'
& $uv run --locked python scripts\make_fixtures.py --output tmp\fixtures
& .\scripts\bootstrap_epubcheck.ps1
$jar = (Resolve-Path '.tools\epubcheck-5.3.0\epubcheck.jar').Path
& $uv run --locked pdf2epub gui `
  --source tmp\fixtures\digital_single_column.pdf `
  --project tmp\manual-smoke.bepub-project `
  --epubcheck-jar $jar
```

## Checklist

1. Confirm Pages, PDF Page, Structure, EPUB Preview, and Logs are visible.
2. Select a text block in either the overlay or block list; confirm the other view follows.
3. Zoom the PDF page, edit a paragraph, and click **Apply Edit**.
4. Merge two adjacent text blocks, then split a block at an interior cursor position.
5. Confirm the EPUB Preview updates and raw source is still present after save/reopen.
6. Export into the project's `exports` directory and confirm `EPUB validation: PASS`.
7. Close the app, reopen with `pdf2epub gui --project tmp\manual-smoke.bepub-project`, and
   confirm the edits remain.

The automated offscreen counterpart is `tests/gui/test_smoke.py`; it does not replace this
visual interaction check.

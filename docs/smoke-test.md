# M2 GUI smoke test (Windows)

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
8. In Translation, set source `en` and target `zh-CN`; select several paragraphs.
9. Confirm the LongCat privacy prompt lists the context sent remotely, then translate with a
   rotated key supplied only through `LONGCAT_API_KEY`.
10. Confirm progress, status/provider/model, retry, and Cancel remain responsive. A cancelled batch
    must retain already completed translations after reopen.
11. Edit one translation and confirm it becomes `user_edited`. Edit its source and confirm only
    that translation becomes `stale`.
12. Regenerate preview and confirm source then translation ordering. Export and confirm EPUBCheck
    PASS; if content is incomplete, confirm the UI labels it incomplete rather than fully complete.

The automated offscreen counterpart is `tests/gui/test_smoke.py`; it uses `FakeTranslator`, makes
no paid network calls, and does not replace this visual interaction check.

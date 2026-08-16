# pdf2epub

`pdf2epub` is a local-first PySide6 workbench that converts ordinary digital PDFs into an
editable, versioned Document IR and exports a reflowable source-to-translation EPUB 3.

M2 includes paragraph translation through a provider-neutral interface, deterministic fake,
LongCat adapter, project-local cache, editable translations, and bilingual preview/export. It
still excludes OCR, scanned/mixed PDF support, a complete EPUB reader, services, and installers.

## Development

```powershell
$uv = 'C:\Users\lhai0704\.local\bin\uv.exe'
& $uv sync --locked
& $uv run --locked pdf2epub --help
```

Generate the legal fixture corpus:

```powershell
& $uv run --locked python scripts\make_fixtures.py --output tmp\fixtures
```

Run all quality gates and the deterministic M1 verification:

```powershell
& $uv run --locked pytest
& $uv run --locked ruff check .
& $uv run --locked ruff format --check .
& $uv run --locked mypy src tests scripts
& .\scripts\bootstrap_epubcheck.ps1
$jar = (Resolve-Path '.tools\epubcheck-5.3.0\epubcheck.jar').Path
& $uv run --locked python scripts\verify_m1.py `
  --pdf tmp\fixtures\digital_single_column.pdf `
  --workspace tmp\m1-verify `
  --epubcheck-jar $jar

& $uv run --locked python scripts\verify_m2.py `
  --pdf tmp\fixtures\digital_single_column.pdf `
  --workspace tmp\m2-verify `
  --epubcheck-jar $jar
```

Run the GUI:

```powershell
& $uv run --locked pdf2epub gui --source tmp\fixtures\digital_single_column.pdf `
  --project tmp\manual-smoke.bepub-project
```

The project is licensed under AGPL-3.0-or-later. See `THIRD_PARTY_NOTICES.md` before
redistributing binaries.

See `docs/smoke-test.md` for the manual GUI acceptance pass.

Real translation reads a rotated key from `LONGCAT_API_KEY`. The key must not be written into the
project or shell history. `scripts/smoke_longcat.py --confirm-network` sends only a generated test
sentence and is an explicit, potentially paid manual check; pytest never calls it.

The verified M0/M1 baseline and historical M2 planning brief are in
`docs/handoffs/M2_PLAN_MODE_HANDOFF.md`.

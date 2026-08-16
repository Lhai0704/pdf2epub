# pdf2epub

`pdf2epub` is a local-first PySide6 workbench that converts digital, scanned, and mixed PDFs into an
editable, versioned Document IR and exports a reflowable source-to-translation EPUB 3.

M3 adds provider-neutral page classification/routing, per-page Native/OCR overrides,
PaddleOCR/PP-StructureV3, checksummed OCR cache, confidence/bbox provenance, serial batch progress
and cancellation, protected whole-page reparse, mixed EPUB, and explicit incomplete-content
export. M4 adds auditable structure commands, session Undo/Redo, semantic running headers/footers,
Paddle-only regional reparse with a separate cache, provenance inspection, and a persistent Warning
Center. It still excludes multiple OCR engines, a complete EPUB reader, services, and installers.

## Development

```powershell
$uv = 'C:\Users\lhai0704\.local\bin\uv.exe'
& $uv sync --locked
& $uv run --locked pdf2epub --help
```

OCR is optional and the CPU/GPU profiles are mutually exclusive. The RTX 4060 Windows profile was
verified with the GPU extra:

```powershell
& $uv sync --locked --extra ocr-gpu
```

Use `--extra ocr-cpu` only as a separately installed fallback. The first OCR model download is
never implicit: the GUI asks for confirmation, and the CLI requires `--allow-model-download`.

Generate the legal fixture corpus:

```powershell
& $uv run --locked python scripts\make_fixtures.py --output tmp\fixtures
```

Run all quality gates and the deterministic M1 verification:

```powershell
& $uv run --locked pytest
& $uv run --locked ruff check .
& $uv run --locked ruff format --check .
& $uv run --locked mypy --strict src tests
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

$m3 = Join-Path $env:TEMP ('pdf2epub-m3-verify-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $uv run --locked python scripts\verify_m3.py `
  --output-dir $m3 `
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

Real PaddleOCR is excluded from pytest. Run the explicit commands and GUI checklist in
`docs/smoke-test.md`; the measured GPU/CPU decision is in `docs/spikes/m3-spike-d.md`.

Historical milestone planning briefs remain under `docs/handoffs/`.

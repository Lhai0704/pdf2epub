# M3/M4 GUI and real OCR smoke test (Windows)

Automated tests use fake OCR. They do not prove that Paddle, the downloaded models, GPU, or visual
overlay work on the target machine. The following checks are explicit because the first OCR run
downloads models and real translation can send text remotely.

## Preparation and framework check

```powershell
Set-Location D:\Projects\pdf2epub
$uv = 'C:\Users\lhai0704\.local\bin\uv.exe'
$env:PADDLE_PDX_CACHE_HOME = Join-Path $env:LOCALAPPDATA 'pdf2epub\models\paddlex'
& $uv sync --locked --extra ocr-gpu
& $uv run --locked --extra ocr-gpu python scripts\smoke_paddleocr.py `
  --framework-check --device gpu:0 --no-model-download
```

The framework check must report CUDA enabled, one visible RTX 4060, `active_device` `gpu:0`, and
the expected matrix result. It does not download models. A clean GPU-extra installation downloads
about 1.3 GiB of CUDA/cuDNN runtime wheels; this is separate from the OCR model download below.

## Explicit real OCR and cache smoke

The first command downloads the three official models if they are absent. Review the cache path
and free disk space before confirming it.

```powershell
$first = Join-Path $env:TEMP ('pdf2epub-m3-real-ocr-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $uv run --locked --extra ocr-gpu python scripts\smoke_paddleocr.py `
  --device gpu:0 --confirm-model-download --benchmark-cpu --output-dir $first

$repeat = Join-Path $env:TEMP ('pdf2epub-m3-real-ocr-repeat-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $uv run --locked --extra ocr-gpu python scripts\smoke_paddleocr.py `
  --device gpu:0 --require-existing-models --require-cache-hit `
  --region-reparse --output-dir $repeat
```

Both runs must produce normalized blocks without logging their text. The repeat must report a
project cache hit and no missing models. The CPU benchmark note documents the bounded Spike D
result; the full high-quality CPU inference is not repeated because it exceeded 90 seconds and 20
GB RAM.

## GUI preparation

```powershell
& $uv run --locked python scripts\make_fixtures.py --output tmp\fixtures
.\scripts\bootstrap_epubcheck.ps1
$jar = (Resolve-Path '.tools\epubcheck-5.3.0\epubcheck.jar').Path
& $uv run --locked --extra ocr-gpu pdf2epub gui `
  --source tmp\fixtures\mixed.pdf `
  --project tmp\manual-m3-smoke.bepub-project `
  --epubcheck-jar $jar
```

## GUI checklist

1. Confirm opening digital and scanned pages renders previews but does not parse them.
2. Confirm Page List shows classification, recommendation, override, actual parser, status, and
   warning count; inspect reason/error tooltips.
3. Select one or multiple pages and apply Auto, Force Native, and Force OCR. A changed parser for
   existing content must mark the page stale without replacing blocks.
4. Parse the mixed fixture. The digital page must use Native and the scanned page must use Paddle.
5. Confirm progress stages update, the UI stays responsive, and Cancel stops after the current page.
6. Confirm OCR overlay tooltips show block type/confidence and low-confidence boxes are distinct.
   Selecting a box and block-list row must remain bidirectional.
7. Retry a failed page and explicitly Force Native if desired. No parser fallback may occur without
   that action. If GPU OOM is simulated/encountered, CPU retry requires confirmation.
8. Edit an OCR block, create a merge/split or translation, then Reparse. Confirm the conflict dialog
   reports affected counts. Cancel preserves everything; confirmed success replaces the page and
   does not inherit translations; failure preserves old content.
9. Disconnect the network after models exist and confirm OCR initializes from the local model
   cache. Missing models while offline must produce a clear error, not an implicit download loop.
10. Export with an unparsed/stale/failed/warning page. Cancel the confirmation and verify no file is
    generated; confirm it and verify a visible `Incomplete content notice` appears in the EPUB.
11. Export a complete mixed project and confirm it has no incomplete notice.
12. Run EPUBCheck on both EPUBs and require 0 fatals, 0 errors, and 0 warnings.
13. Close/reopen the project and confirm IR 1.3 page states, overrides, errors, edits, translations,
    assets, and OCR provenance remain intact.
14. Apply a source edit, type/heading change, merge and split. Confirm stable/derived block IDs,
    translation stale/detach confirmation, and exact session Undo/Redo behavior.
15. Mark blocks as Page Header and Page Footer. Confirm they remain in overlays and Provenance but
    disappear from Translation, preview, TOC, and EPUB. Undo must restore their prior type.
16. On a parsed Paddle page choose Select OCR Region and drag over at least half of an existing
    block. Cancel the candidate and verify zero content change; repeat, confirm, and verify only the
    listed scope changes. Region cache replay must be reported as a hit.
17. Confirm Native, unparsed, stale, and failed pages disable region OCR with a textual reason.
18. Open Provenance and verify parser/model/device/options/cache/element/edit metadata without a
    Paddle raw object or book text in Logs. Open Warnings, navigate to a page/block, acknowledge a
    warning, and confirm it still requires incomplete-export confirmation until resolved.
19. Close/reopen and confirm IR 1.3 audit, warnings, acknowledgement, header/footer and region
    provenance persist. Undo/Redo must be empty after reopen by design.
20. Export complete and warning-bearing M4 projects. Require a visible notice only for the latter,
    and require EPUBCheck 0 fatals, 0 errors, and 0 warnings for both.

The offscreen counterpart is `tests/gui/test_smoke.py`. Paid LongCat smoke remains separately
gated by `LONGCAT_API_KEY` and `scripts/smoke_longcat.py --confirm-network`.

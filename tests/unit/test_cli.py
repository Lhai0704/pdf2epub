from __future__ import annotations

from pdf2epub.cli import main


def test_cli_inspect_help(capsys) -> None:  # type: ignore[no-untyped-def]
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "Local-first PDF to EPUB workbench" in capsys.readouterr().out

from __future__ import annotations

import ast
from pathlib import Path


def test_domain_has_no_framework_or_adapter_imports() -> None:
    root = Path(__file__).parents[2] / "src" / "pdf2epub" / "domain"
    forbidden = ("PySide6", "pymupdf", "fitz", "pdf2epub.gui", "pdf2epub.parsers", "pdf2epub.epub")
    violations = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(forbidden):
                    violations.append(f"{path.name}: {name}")
    assert violations == []

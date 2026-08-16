from __future__ import annotations

from pathlib import Path

import pytest

from pdf2epub.fixtures import generate_fixture_corpus


@pytest.fixture(scope="session")
def fixture_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("fixture-corpus")
    generate_fixture_corpus(output)
    return output

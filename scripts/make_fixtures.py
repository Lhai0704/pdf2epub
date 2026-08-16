from __future__ import annotations

import argparse
from pathlib import Path

from pdf2epub.fixtures import generate_fixture_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the legal pdf2epub fixture corpus")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    for path in generate_fixture_corpus(arguments.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

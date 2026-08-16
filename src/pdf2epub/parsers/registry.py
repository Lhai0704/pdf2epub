from __future__ import annotations

from collections.abc import Callable

from pdf2epub.domain.errors import ParserUnavailableError
from pdf2epub.domain.models import Page
from pdf2epub.parsers.base import DocumentParser

NATIVE_PARSER_ID = "pymupdf_native"
OCR_PARSER_ID = "paddle_ppstructure_v3"

ParserFactory = Callable[[], DocumentParser]


class ParserRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ParserFactory] = {}
        self._instances: dict[str, DocumentParser] = {}

    def register(self, parser_id: str, factory: ParserFactory) -> None:
        if parser_id in self._factories:
            raise ValueError(f"Parser already registered: {parser_id}")
        self._factories[parser_id] = factory

    def get(self, parser_id: str) -> DocumentParser:
        if parser_id in self._instances:
            return self._instances[parser_id]
        factory = self._factories.get(parser_id)
        if factory is None:
            raise ParserUnavailableError(f"Parser is not registered: {parser_id}")
        parser = factory()
        if parser.parser_id != parser_id:
            raise ParserUnavailableError(
                f"Parser factory for {parser_id} returned {parser.parser_id}"
            )
        self._instances[parser_id] = parser
        return parser

    def registered_ids(self) -> tuple[str, ...]:
        return tuple(self._factories)


class ParserRouter:
    def __init__(self, registry: ParserRegistry) -> None:
        self.registry = registry

    @staticmethod
    def parser_id_for_page(page: Page) -> str:
        choice = page.parser_override
        if choice == "auto":
            choice = page.classification.recommended_parser if page.classification else "native"
        return NATIVE_PARSER_ID if choice == "native" else OCR_PARSER_ID

    def parser_for_page(self, page: Page) -> DocumentParser:
        return self.registry.get(self.parser_id_for_page(page))

"""User-facing error taxonomy without GUI dependencies."""


class Pdf2EpubError(Exception):
    """Base error for expected application failures."""


class SourceOpenError(Pdf2EpubError):
    """The source PDF could not be opened safely."""


class PageRenderError(Pdf2EpubError):
    """A page preview could not be rendered."""


class NativeTextExtractionError(Pdf2EpubError):
    """Native PDF text extraction failed."""


class ProjectPersistenceError(Pdf2EpubError):
    """A project could not be saved or loaded."""


class EpubBuildError(Pdf2EpubError):
    """EPUB serialization failed."""


class EpubValidationError(Pdf2EpubError):
    """EPUBCheck could not run or found conformance errors."""

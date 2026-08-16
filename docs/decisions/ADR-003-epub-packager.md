# ADR-003: Thin EPUB packager

Status: accepted for M1.

The M1 EPUB surface is small enough for a standard-library ZIP/XML implementation. This avoids
leaking third-party EPUB types and gives exact control of `mimetype`, manifest, spine, nav, and
XHTML. EPUBCheck remains the conformance authority.

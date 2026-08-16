# EPUB packaging spike

## Decision

M1 uses a thin standard-library packager rather than EbookLib. The required output is limited
to EPUB 3 metadata, navigation, spine, XHTML, CSS, and image assets. Direct packaging makes the
ZIP ordering and OPF/nav output deterministic and avoids another AGPL runtime dependency.

The spike builds self-authored text plus a generated image. It must pass EPUBCheck 5.3.0 before
the same builder is used by the Document IR export path.

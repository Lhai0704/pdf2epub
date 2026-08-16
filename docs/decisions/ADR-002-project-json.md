# ADR-002: Versioned JSON project persistence

Status: accepted for M0/M1.

Projects use a directory containing `project.json`, `document.json`, copied source PDF, assets,
caches, and exports. JSON remains debuggable and is written by atomic replacement. SQLite is
deferred until measured project size or query behavior justifies it.

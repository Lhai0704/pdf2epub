# ADR-009: Structure commands and session undo

Status: accepted for M4.

M4 routes source text edits, type/heading changes, merge/split, running-header/footer marking and
region replacement through provider-neutral structure commands. A command builds and validates a
candidate Document IR, atomically saves it, and only then enters a 100-entry session stack.

Undo/redo inverse snapshots are memory-only. Execute, undo and redo append compact audit events to
Document IR 1.3, but before/after content is not duplicated in project JSON. Closing a project,
translation changes and whole-page parsing clear the stack. Persistence failure leaves both the
saved project and stack position unchanged.

This keeps M4 finite and auditable without committing to persistent revision storage or SQLite.
Cross-restart undo is deferred until project size and recovery requirements justify it.


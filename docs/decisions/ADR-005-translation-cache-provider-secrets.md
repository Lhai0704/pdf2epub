# ADR-005: Translation cache, provider, and secrets

Status: accepted for M2.

Cache keys hash canonical effective source text, source/target languages, provider, model, prompt
version, glossary version, and a context fingerprint. EPUB styling is deliberately excluded. The
cache is a versioned atomic JSON file under `cache/translation`; Document IR remains authoritative.

M2 implements `FakeTranslator` and one real adapter: LongCat `LongCat-2.0` over its compatible Chat
Completions endpoint. The adapter uses HTTPX directly, disables streaming and thinking, applies
bounded timeouts/retries, and normalizes the response into project-owned types.

The API key is read only from `LONGCAT_API_KEY`. It is never stored in project JSON, cache, logs,
or Git. Automated tests use fake or mock transports; the real smoke is explicit and may incur cost.

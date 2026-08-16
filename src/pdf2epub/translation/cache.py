from __future__ import annotations

import hashlib
import json
import unicodedata

from pdf2epub.translation.base import TranslationRequest


def canonicalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return normalized.replace("\r\n", "\n").replace("\r", "\n").strip()


def source_fingerprint(text: str) -> str:
    return hashlib.sha256(canonicalize_text(text).encode("utf-8")).hexdigest()


def context_fingerprint(request: TranslationRequest) -> str:
    payload = {
        "chapter_heading": canonicalize_text(request.chapter_heading or ""),
        "previous_paragraph": canonicalize_text(request.previous_paragraph or ""),
        "next_paragraph": canonicalize_text(request.next_paragraph or ""),
        "style_instructions": canonicalize_text(request.style_instructions or ""),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def translation_cache_key(request: TranslationRequest) -> str:
    payload = {
        "normalized_source_text": canonicalize_text(request.source_text),
        "source_language": request.source_language,
        "target_language": request.target_language,
        "provider": request.provider_id,
        "model": request.model,
        "prompt_version": request.prompt_version,
        "glossary_version": request.glossary_version,
        "context_fingerprint": context_fingerprint(request),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

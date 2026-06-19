"""Reusable text translation service for REST endpoints.

This wraps the existing realtime translation engines without depending on
FastAPI or the WebSocket router, so future routes can reuse the same contract.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from server.translate.engines.base import BaseEngine

from server.schemas.memory_schema import TranslationMemoryCreate
from server.schemas.translate_schema import TextTranslateRequest, TextTranslateResponse
from server.services.glossary_service import GlossaryService
from server.services.translation_memory_service import TranslationMemoryService


_LANG_ALIASES = {
    "vi": "vie_Latn",
    "vie": "vie_Latn",
    "vie_Latn": "vie_Latn",
    "en": "eng_Latn",
    "eng": "eng_Latn",
    "eng_Latn": "eng_Latn",
    "zh": "zho_Hans",
    "zho": "zho_Hans",
    "zho_Hans": "zho_Hans",
    "ja": "jpn_Jpan",
    "jpn": "jpn_Jpan",
    "jpn_Jpan": "jpn_Jpan",
    "ko": "kor_Hang",
    "kor": "kor_Hang",
    "kor_Hang": "kor_Hang",
    "fr": "fra_Latn",
    "fra": "fra_Latn",
    "fra_Latn": "fra_Latn",
    "de": "deu_Latn",
    "deu": "deu_Latn",
    "deu_Latn": "deu_Latn",
    "es": "spa_Latn",
    "spa": "spa_Latn",
    "spa_Latn": "spa_Latn",
    "th": "tha_Thai",
    "tha": "tha_Thai",
    "tha_Thai": "tha_Thai",
}


class TranslatorService:
    def __init__(
        self,
        *,
        get_engine: Callable[[str], BaseEngine],
        get_envi_engine: Callable[[], BaseEngine],
        default_model: str,
        glossary_service: GlossaryService | None = None,
        memory_service: TranslationMemoryService | None = None,
    ) -> None:
        self._get_engine = get_engine
        self._get_envi_engine = get_envi_engine
        self._default_model = default_model
        self._glossary = glossary_service
        self._memory = memory_service

    def translate_text(self, req: TextTranslateRequest) -> TextTranslateResponse:
        source_text = req.text.strip()
        if not source_text:
            raise ValueError("text must not be empty")

        src_lang = self.normalize_lang(req.src_lang)
        tgt_lang = self.normalize_lang(req.tgt_lang)
        memory_suggestions = self._memory.search(
            source_text, src_lang=src_lang, tgt_lang=tgt_lang, limit=3
        ) if self._memory is not None else []
        glossary_terms = self._glossary.terms_for(src_lang, tgt_lang) if (req.use_glossary and self._glossary) else []

        if src_lang == tgt_lang:
            translated = source_text
        else:
            exact = self._match_exact_glossary(source_text, glossary_terms)
            if exact:
                translated = exact
            else:
                engine = self._select_engine(src_lang, tgt_lang, req.translate_model)
                translated = "".join(engine.translate_stream(source_text, src_lang, tgt_lang)).strip()
                translated = self._apply_glossary_postprocess(translated, glossary_terms)

        if self._memory is not None and src_lang != tgt_lang and translated:
            try:
                self._memory.add(TranslationMemoryCreate(
                    source_text=source_text,
                    translated_text=translated,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                ))
            except Exception:
                pass

        return TextTranslateResponse(
            source_text=source_text,
            translated_text=translated,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            memory_suggestions=memory_suggestions,
        )

    @staticmethod
    def normalize_lang(lang: str) -> str:
        key = (lang or "").strip()
        if key not in _LANG_ALIASES:
            raise ValueError(f"unsupported language code: {lang!r}")
        return _LANG_ALIASES[key]

    def _select_engine(self, src_lang: str, tgt_lang: str, model: str | None) -> BaseEngine:
        if src_lang == "eng_Latn" and tgt_lang == "vie_Latn":
            return self._get_envi_engine()

        chosen = (model or self._default_model or "").strip().lower()
        if chosen == "nllb":
            chosen = "nllb-600m"
        if chosen == "marian" and not (src_lang == "vie_Latn" and tgt_lang == "eng_Latn"):
            raise ValueError("marian currently supports only vie_Latn -> eng_Latn")
        return self._get_engine(chosen)

    @staticmethod
    def _match_exact_glossary(source_text: str, terms: list[dict]) -> str:
        normalized = source_text.casefold().strip()
        for term in terms:
            if normalized == term["source_term"].casefold().strip():
                return term["target_term"]
        return ""

    @staticmethod
    def _apply_glossary_postprocess(translated: str, terms: list[dict]) -> str:
        result = translated
        for term in terms:
            source = term["source_term"].strip()
            target = term["target_term"].strip()
            if not source or not target:
                continue
            result = re.sub(re.escape(source), target, result, flags=re.IGNORECASE)
        return result

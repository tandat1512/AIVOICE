"""MarianMT (Helsinki-NLP/opus-mt-vi-en) engine via CTranslate2.

Faster than NLLB-200 for vi→en: ~2-4x lower first-token latency because
the model is ~77M params vs 600M. Quality is lower but sufficient for
real-time streaming display.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Iterator

from .base import BaseEngine
from ..vi_preprocessor import preprocess_vi, mask_places, unmask_places, mask_glossary, unmask_glossary

_MODELS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "models"
_HF_SNAPSHOT = (
    _MODELS_DIR
    / "marian-vi-en"
    / "models--Helsinki-NLP--opus-mt-vi-en"
    / "snapshots"
    / "c8d2853e77f5fae31124d993e0b35176b1c8914e"
)
_CT2_DIR = _MODELS_DIR / "marian-vi-en-ct2"


class MarianEngine(BaseEngine):
    """Fast vi→en streaming engine backed by Helsinki-NLP/opus-mt-vi-en in CT2 int8."""

    def __init__(self, device: str = "auto") -> None:
        self._device = device
        self._translator = None
        self._tokenizer = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._translator is not None:
                return

            import ctranslate2
            from transformers import MarianTokenizer

            if not _CT2_DIR.exists():
                print("[Marian] Converting HuggingFace model to CTranslate2 int8...", flush=True)
                converter = ctranslate2.converters.TransformersConverter(str(_HF_SNAPSHOT))
                converter.convert(str(_CT2_DIR), quantization="int8")
                print("[Marian] Conversion complete.", flush=True)

            print("[Marian] Loading CTranslate2 model...", flush=True)
            self._tokenizer = MarianTokenizer.from_pretrained(str(_HF_SNAPSHOT))
            self._translator = ctranslate2.Translator(str(_CT2_DIR), device=self._device)
            print("[Marian] Model ready.", flush=True)

    @property
    def is_loaded(self) -> bool:
        return self._translator is not None

    def translate(self, text: str, src_lang: str = "vie_Latn", tgt_lang: str = "eng_Latn") -> str:
        return "".join(self.translate_stream(text, src_lang, tgt_lang))

    def translate_stream(
        self,
        text: str,
        src_lang: str = "vie_Latn",
        tgt_lang: str = "eng_Latn",
        target_prefix: str = "",
    ) -> Iterator[str]:
        """Stream translated tokens. src_lang/tgt_lang are accepted for API compat but ignored
        (model is dedicated vi→en)."""
        text = text.strip()
        if not text:
            return

        self._ensure_loaded()

        # Source-side normalization: title-case place names + fix dialect pronouns
        # so the small model keeps entities and reads "mình/tui" as first person.
        text = preprocess_vi(text)
        # Mask known place names then user glossary terms with copy-safe sentinels
        # so the model can't translate them as common words.
        text, place_map = mask_places(text)
        text, gloss_map = mask_glossary(text)
        combined_map = {**place_map, **gloss_map}

        tokens = self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(text))

        if combined_map:
            # Entities present → buffer the full output so sentinels can be restored
            # (restoration needs the whole string; streaming token-by-token would
            # split "x0x"/"g0g"). Yields the restored translation as one chunk.
            out = "".join(
                self._detok(step.token)
                for step in self._translator.generate_tokens(tokens)
                if not step.is_last and step.token not in ("</s>", "<pad>", "<unk>")
            )
            out = unmask_places(out, place_map)
            out = unmask_glossary(out, gloss_map)
            yield out
            return

        # No entities → stream token-by-token (preserves the live typing effect).
        for step in self._translator.generate_tokens(tokens):
            if step.is_last:
                break
            tok = step.token
            if tok in ["</s>", "<pad>", "<unk>"]:
                continue
            yield self._detok(tok)

    @staticmethod
    def _detok(tok: str) -> str:
        """SentencePiece token → text fragment ("▁" marks a leading space)."""
        return " " + tok[1:] if tok.startswith("▁") else tok

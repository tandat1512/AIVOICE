"""MarianMT (Helsinki-NLP/opus-mt-en-vi) engine via CTranslate2 — en→vi direction.

Mirror of marian_engine.py for the reverse direction (English → Vietnamese).
~38M params, CT2 int8, fast enough for real-time streaming display. Source is
English so the Vietnamese source-side preprocessing (preprocess_vi / place /
glossary masking) is intentionally NOT applied here.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

from .base import BaseEngine

_MODELS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "models"
_HF_DIR = _MODELS_DIR / "marian-en-vi"
_CT2_DIR = _MODELS_DIR / "marian-en-vi-ct2"


class MarianEnViEngine(BaseEngine):
    """Fast en→vi streaming engine backed by Helsinki-NLP/opus-mt-en-vi in CT2 int8."""

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

            if not (_HF_DIR / "config.json").exists():
                print("[MarianEnVi] Downloading Helsinki-NLP/opus-mt-en-vi model...", flush=True)
                from huggingface_hub import snapshot_download
                _HF_DIR.mkdir(parents=True, exist_ok=True)
                snapshot_download(
                    repo_id="Helsinki-NLP/opus-mt-en-vi",
                    local_dir=str(_HF_DIR),
                    local_dir_use_symlinks=False,
                )

            if not _CT2_DIR.exists():
                print("[MarianEnVi] Converting HuggingFace model to CTranslate2 int8...", flush=True)
                import transformers
                _orig_init = transformers.MarianMTModel.__init__
                def _tolerant_init(self_m, config, *args, **kwargs):
                    kwargs.pop("dtype", None)
                    _orig_init(self_m, config, *args, **kwargs)
                transformers.MarianMTModel.__init__ = _tolerant_init
                try:
                    converter = ctranslate2.converters.TransformersConverter(str(_HF_DIR))
                    converter.convert(str(_CT2_DIR), quantization="int8")
                finally:
                    transformers.MarianMTModel.__init__ = _orig_init
                print("[MarianEnVi] Conversion complete.", flush=True)

            print("[MarianEnVi] Loading CTranslate2 model...", flush=True)
            self._tokenizer = MarianTokenizer.from_pretrained(str(_HF_DIR))
            self._translator = ctranslate2.Translator(str(_CT2_DIR), device=self._device)
            print("[MarianEnVi] Model ready.", flush=True)

    @property
    def is_loaded(self) -> bool:
        return self._translator is not None

    def translate(self, text: str, src_lang: str = "eng_Latn", tgt_lang: str = "vie_Latn") -> str:
        return "".join(self.translate_stream(text, src_lang, tgt_lang))

    def translate_stream(
        self,
        text: str,
        src_lang: str = "eng_Latn",
        tgt_lang: str = "vie_Latn",
        target_prefix: str = "",
    ) -> Iterator[str]:
        """Stream translated tokens. src_lang/tgt_lang are accepted for API compat
        but ignored (model is dedicated en→vi)."""
        text = text.strip()
        if not text:
            return

        self._ensure_loaded()

        tokens = self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(text))

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

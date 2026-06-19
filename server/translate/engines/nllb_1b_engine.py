"""NLLB-200-distilled-1.3B engine — higher quality than 600M at ~2-4x CPU cost."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

from .base import BaseEngine
from ..vi_preprocessor import (
    preprocess_vi, mask_places, unmask_places, mask_glossary, unmask_glossary,
)

_NLLB_1B_HF  = "facebook/nllb-200-distilled-1.3B"
_NLLB_1B_DIR = Path(__file__).resolve().parents[3] / "models" / "nllb-200-distilled-1.3B-ct2"


class NLLB1BEngine(BaseEngine):
    """NLLB-200-distilled-1.3B — higher quality than 600M, ~2-4x slower on CPU."""

    # Class-level: allows only one inference at a time across all sessions.
    # Without this, phowhisper mode dispatches N sentence threads simultaneously;
    # they compete for CPU and the last thread waits N× the normal inference time.
    _INFER_LOCK = threading.Lock()

    def __init__(self, device: str = "auto") -> None:
        self._translator = None
        self._device = device
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._translator is None:
                print("[NLLB-1.3B] Loading...", flush=True)
                from ...translate_legacy import StreamingTranslator
                self._translator = StreamingTranslator(
                    device=self._device,
                    model_dir=_NLLB_1B_DIR,
                    hf_id=_NLLB_1B_HF,
                )

    @property
    def is_loaded(self) -> bool:
        return self._translator is not None

    def translate(self, text: str, src_lang: str = "vie_Latn", tgt_lang: str = "eng_Latn") -> str:
        self._ensure_loaded()
        return "".join(self.translate_stream(text, src_lang, tgt_lang))

    def translate_stream(
        self,
        text: str,
        src_lang: str = "vie_Latn",
        tgt_lang: str = "eng_Latn",
        target_prefix: str = "",
    ) -> Iterator[str]:
        self._ensure_loaded()

        place_map: dict[str, str] = {}
        gloss_map: dict[str, str] = {}
        if src_lang == "vie_Latn":
            text = preprocess_vi(text)
            text, place_map = mask_places(text)
            text, gloss_map = mask_glossary(text)
        combined_map = {**place_map, **gloss_map}

        # Serialize inference under class lock; buffer tokens so the lock is
        # released before yielding (lets the next queued sentence start while
        # this session's router processes the buffered output).
        with NLLB1BEngine._INFER_LOCK:
            tokens = list(self._translator.generate_stream(
                text, src_lang=src_lang, tgt_lang=tgt_lang, target_prefix_text=""
            ))

        if combined_map:
            out = unmask_places("".join(tokens), place_map)
            out = unmask_glossary(out, gloss_map)
            yield out
            return

        yield from tokens

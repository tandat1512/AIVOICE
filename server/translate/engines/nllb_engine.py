"""NLLB-200 engine wrapping the existing StreamingTranslator."""

from __future__ import annotations

import os
import queue
import threading
from typing import Iterator

from .base import BaseEngine
from ..vi_preprocessor import preprocess_vi, mask_places, unmask_places, mask_glossary, unmask_glossary

_SENTINEL = object()


class NLLBEngine(BaseEngine):
    """Fast-path engine backed by NLLB-200 CT2 (existing StreamingTranslator)."""

    # Serialize CPU inference across all sessions to prevent thread contention.
    # Without this, concurrent PhoWhisper segments each spawn a translate thread
    # and fight for CPU, turning 2s translations into 6-13s ones.
    _INFER_LOCK = threading.Lock()

    def __init__(self, device: str = "auto") -> None:
        self._translator = None
        # NLLB_DEVICE=cpu opts NLLB out of CUDA (frees VRAM for PhoWhisper-large
        # on the 4GB RTX 3050 Ti). Default "auto" keeps existing CUDA behavior.
        self._device = os.environ.get("NLLB_DEVICE", device)
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._translator is None:
                from ...translate_legacy import StreamingTranslator

                device = os.environ.get("NLLB_DEVICE", self._device)
                compute_type = "default"
                intra_threads = 0
                if device == "cpu":
                    compute_type = "int8"
                    intra_env = os.environ.get("NLLB_INTRA_THREADS")
                    if intra_env:
                        intra_threads = int(intra_env)

                print(
                    f"[NLLB] device={device} compute_type={compute_type} intra_threads={intra_threads}",
                    flush=True,
                )
                self._translator = StreamingTranslator(
                    device=device, compute_type=compute_type, intra_threads=intra_threads
                )

    def warmup(self) -> int:
        self._ensure_loaded()
        return self._translator.warmup()

    @property
    def is_loaded(self) -> bool:
        return self._translator is not None

    def translate(self, text: str, src_lang: str = "vie_Latn", tgt_lang: str = "eng_Latn") -> str:
        self._ensure_loaded()
        return "".join(self.translate_stream(text, src_lang, tgt_lang))

    def _stream_tokens(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        target_prefix: str,
    ) -> Iterator[str]:
        """Run generate_stream() in a producer thread under _INFER_LOCK,
        yielding tokens as they arrive. The lock is held only for the
        producer's decode loop; this generator drains the queue without
        holding the lock, so a slow consumer never blocks other sessions'
        CPU inference.
        """
        q: "queue.Queue[object]" = queue.Queue()

        def _produce() -> None:
            with NLLBEngine._INFER_LOCK:
                try:
                    for tok in self._translator.generate_stream(
                        text, src_lang=src_lang, tgt_lang=tgt_lang, target_prefix_text=target_prefix
                    ):
                        q.put(tok)
                except Exception as exc:  # noqa: BLE001 — surface to caller
                    q.put(("__error__", exc))
                finally:
                    q.put(_SENTINEL)

        threading.Thread(target=_produce, daemon=True).start()

        while True:
            item = q.get()
            if item is _SENTINEL:
                return
            if isinstance(item, tuple) and item and item[0] == "__error__":
                raise item[1]  # type: ignore[misc]
            yield item  # type: ignore[misc]

    def translate_stream(
        self,
        text: str,
        src_lang: str = "vie_Latn",
        tgt_lang: str = "eng_Latn",
        target_prefix: str = "",
    ) -> Iterator[str]:
        self._ensure_loaded()

        # Source-side normalization (Vietnamese only): fix dialect pronouns + mask
        # known place names with copy-safe sentinels so even the 600M model can't
        # translate them as common words ("Tây Ninh" → "the West").
        place_map: dict[str, str] = {}
        gloss_map: dict[str, str] = {}
        if src_lang == "vie_Latn":
            text = preprocess_vi(text)
            text, place_map = mask_places(text)
            text, gloss_map = mask_glossary(text)
        combined_map = {**place_map, **gloss_map}

        if combined_map:
            # Sentinels can span multiple yielded tokens, so unmasking needs
            # the full output text. Drain the producer queue (outside the
            # lock — see _stream_tokens) before unmasking and yielding once.
            tokens = list(self._stream_tokens(text, src_lang, tgt_lang, target_prefix))
            out = unmask_places("".join(tokens), place_map)
            out = unmask_glossary(out, gloss_map)
            yield out
            return

        # Streaming path: tokens are yielded as the producer thread decodes,
        # without holding _INFER_LOCK in this generator (see _stream_tokens).
        yield from self._stream_tokens(text, src_lang, tgt_lang, target_prefix)

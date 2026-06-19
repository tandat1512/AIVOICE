"""
Streaming Translation via CTranslate2 (NLLB-200).

Legacy module — kept so NLLBEngine and backward-compat imports work.
Original file was server/translate.py; renamed here because the new
server/translate/ package takes precedence as a Python package directory.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Iterator

import ctranslate2
from transformers import AutoTokenizer

_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
_NLLB_DIR = _MODELS_DIR / "nllb-200-distilled-600M-ct2"

class StreamingTranslator:
    """NLLB-200 based streaming translator using CTranslate2."""

    def __init__(
        self,
        device: str = "auto",
        model_dir: Path | None = None,
        hf_id: str | None = None,
        compute_type: str = "default",
        intra_threads: int = 0,
    ) -> None:
        self.device = device
        self._model_dir = model_dir if model_dir is not None else _NLLB_DIR
        self._hf_id = hf_id if hf_id is not None else "facebook/nllb-200-distilled-600M"
        self._compute_type = compute_type
        self._intra_threads = intra_threads
        self._translator = None
        self._tokenizer = None
        self._lock = threading.Lock()
        self._load_failed = False  # set on permanent error to stop retry loop

    def _convert(self) -> None:
        """Convert HF model to CTranslate2 int8 format.

        ctranslate2 4.7.x passes `dtype=torch.float32` (not `torch_dtype=`) to
        from_pretrained. transformers 4.44.x forwards unknown kwargs to the model
        constructor, but M2M100ForConditionalGeneration.__init__ rejects `dtype`.
        We patch __init__ to silently drop it for the duration of conversion.
        """
        import transformers

        os.makedirs(self._model_dir.parent, exist_ok=True)

        _orig_init = transformers.M2M100ForConditionalGeneration.__init__

        def _tolerant_init(self_m, config, *args, **kwargs):
            kwargs.pop("dtype", None)
            _orig_init(self_m, config, *args, **kwargs)

        transformers.M2M100ForConditionalGeneration.__init__ = _tolerant_init
        try:
            ctranslate2.converters.TransformersConverter(self._hf_id).convert(
                str(self._model_dir), quantization="int8"
            )
        finally:
            transformers.M2M100ForConditionalGeneration.__init__ = _orig_init

    def _load(self) -> None:
        with self._lock:
            if self._translator is not None:
                return
            if self._load_failed:
                raise RuntimeError(f"[NLLB] Model load permanently failed for {self._hf_id}")

            print(f"[NLLB] Preparing {self._hf_id}...", flush=True)
            try:
                if not self._model_dir.exists():
                    print(f"[NLLB] Converting from HuggingFace ({self._hf_id})...", flush=True)
                    self._convert()
                    print("[NLLB] Conversion complete.", flush=True)

                print("[NLLB] Loading CTranslate2 model into memory...", flush=True)
                self._tokenizer = AutoTokenizer.from_pretrained(self._hf_id)
                self._translator = ctranslate2.Translator(
                    str(self._model_dir),
                    device=self.device,
                    compute_type=self._compute_type,
                    intra_threads=self._intra_threads,
                )
                print(
                    f"[NLLB] Model ready. device={self.device} intra_threads={self._intra_threads or 'auto'}",
                    flush=True,
                )
            except Exception:
                self._load_failed = True
                raise

    def warmup(self, text: str = "xin chào", src_lang: str = "vie_Latn", tgt_lang: str = "eng_Latn") -> int:
        """Run one tiny translation after load so the first real sentence is not the outlier."""
        self._load()
        t0 = time.perf_counter()
        for _ in self.generate_stream(text, src_lang=src_lang, tgt_lang=tgt_lang):
            pass
        return round((time.perf_counter() - t0) * 1000)

    def generate_stream(self, text: str, src_lang: str = "vie_Latn", tgt_lang: str = "eng_Latn", target_prefix_text: str = "") -> Iterator[str]:
        """Yields translated text incrementally token by token."""
        text = text.strip()
        if not text:
            return

        if self._translator is None:
            self._load()

        self._tokenizer.src_lang = src_lang
        source_tokens = self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(text))

        target_prefix = [tgt_lang]
        if target_prefix_text:
            # Encode prefix with tgt_lang set so tokenizer doesn't prepend src_lang token.
            self._tokenizer.src_lang = tgt_lang
            prefix_tokens = self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(target_prefix_text))
            self._tokenizer.src_lang = src_lang
            # Strip trailing EOS and leading tgt_lang token that encode adds.
            if prefix_tokens and prefix_tokens[-1] == "</s>":
                prefix_tokens = prefix_tokens[:-1]
            if prefix_tokens and prefix_tokens[0] == tgt_lang:
                prefix_tokens = prefix_tokens[1:]
            target_prefix.extend(prefix_tokens)

        for step_result in self._translator.generate_tokens(source_tokens, target_prefix=target_prefix):
            if step_result.is_last:
                break
            tok = step_result.token

            if tok in ["<s>", "</s>", "<pad>", tgt_lang, src_lang]:
                if tok == "</s>":
                    break
                continue

            if tok.startswith("▁"):
                yield " " + tok[1:]
            else:
                yield tok

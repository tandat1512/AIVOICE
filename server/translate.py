"""
Streaming Translation via CTranslate2 (NLLB-200).

  StreamingTranslator
      Downloads and lazily loads the NLLB-200 600M model.
      Provides an async-friendly generator for token-by-token streaming translation.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Iterator

import ctranslate2
from transformers import AutoTokenizer

_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
_NLLB_DIR = _MODELS_DIR / "nllb-200-distilled-600M-ct2"

class StreamingTranslator:
    """NLLB-200 based streaming translator using CTranslate2."""

    def __init__(self, device: str = "auto") -> None:
        self.device = device
        self._translator = None
        self._tokenizer = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        with self._lock:
            if self._translator is not None:
                return

            print("[NLLB] Preparing NLLB-200 model...", flush=True)
            if not _NLLB_DIR.exists():
                print("[NLLB] Model not found. Converting from Hugging Face... This will take a few minutes...", flush=True)
                os.makedirs(_MODELS_DIR, exist_ok=True)
                # Convert the model locally
                converter = ctranslate2.converters.TransformersConverter(
                    "facebook/nllb-200-distilled-600M"
                )
                converter.convert(str(_NLLB_DIR), quantization="int8")
                print("[NLLB] Conversion complete.", flush=True)

            print("[NLLB] Loading CTranslate2 model into memory...", flush=True)
            self._tokenizer = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")
            self._translator = ctranslate2.Translator(str(_NLLB_DIR), device=self.device)
            print("[NLLB] Model ready.", flush=True)

    def generate_stream(self, text: str, src_lang: str = "vie_Latn", tgt_lang: str = "eng_Latn", target_prefix_text: str = "") -> Iterator[str]:
        """
        Yields translated text incrementally token by token.
        """
        text = text.strip()
        if not text:
            return

        # Ensure model is loaded (happens on first request)
        if self._translator is None:
            self._load()
            
        self._tokenizer.src_lang = src_lang
        source_tokens = self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(text))
        
        # NllbTokenizerFast uses the language code directly as the token string
        target_prefix = [tgt_lang]
        if target_prefix_text:
            # Tokenize the prefix text to force the model to continue from it
            prefix_tokens = self._tokenizer.convert_ids_to_tokens(self._tokenizer.encode(target_prefix_text))
            # Remove the EOS token (</s>) which is typically appended by encode
            if prefix_tokens and prefix_tokens[-1] == "</s>":
                prefix_tokens = prefix_tokens[:-1]
            # Remove the lang code if it somehow got added by encode (usually not)
            target_prefix.extend(prefix_tokens)
            
        # We yield decoded strings as they are generated.
        # generate_tokens will yield the prefix tokens first (if return_prefix=True, but by default it might not).
        # Wait! CTranslate2 generate_tokens does not yield the target_prefix by default unless we ask it to.
        # The generated tokens are the continuation.
        for step_result in self._translator.generate_tokens(source_tokens, target_prefix=target_prefix):
            if step_result.is_last:
                break
            tok = step_result.token
            
            if tok in ["<s>", "</s>", "<pad>", tgt_lang]:
                if tok == "</s>":
                    break
                continue
            
            # SentencePiece uses ' ' (U+2581) for spaces.
            if tok.startswith("\u2581"):
                yield " " + tok[1:]
            else:
                yield tok

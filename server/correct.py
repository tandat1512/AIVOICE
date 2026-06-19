"""
Contextual correction pass — a small instruction-tuned LLM rewrites
committed Vietnamese text to fix ASR homophone errors (e.g. "trân thành"
→ "chân thành") before the high-quality NLLB translation runs.

Model: Qwen/Qwen2.5-1.5B-Instruct
   - ~3 GB VRAM in fp16, ~500-1000 ms inference for typical sentences
   - Loaded lazily and silently degrades if the load fails: callers get
     the input back unchanged so the pipeline keeps working.
"""

from __future__ import annotations

import threading
from typing import Optional

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


_MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"

_SYSTEM_VI = (
    "Bạn là trợ lý sửa lỗi chính tả tiếng Việt do nhận diện giọng nói (ASR) "
    "sinh ra. Chỉ trả lời bằng câu đã sửa, không giải thích, không thêm dấu "
    "nháy hay nhãn. Giữ nguyên ý nghĩa, văn phong, và độ dài câu."
)


class Corrector:
    """Single-instance contextual corrector. Thread-safe via internal lock."""

    def __init__(self, device: Optional[str] = None) -> None:
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype  = torch.float16 if self.device == "cuda" else torch.float32
        self._ok    = False
        self._lock  = threading.Lock()
        try:
            print(f"[Correct] loading {_MODEL_NAME} on {self.device} ...", flush=True)
            self.tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
            self.model = (
                AutoModelForCausalLM.from_pretrained(_MODEL_NAME, torch_dtype=self.dtype)
                .to(self.device)
                .eval()
            )
            self._ok = True
            print("[Correct] model ready.", flush=True)
        except Exception as e:
            # Soft-fail: pipeline must keep working without correction.
            print(f"[Correct] load failed ({e}), correction disabled.", flush=True)

    @property
    def ready(self) -> bool:
        return self._ok

    @torch.inference_mode()
    def correct(self, text: str, lang: str = "vi") -> str:
        """Return a corrected version of `text` or the original on failure."""
        text = (text or "").strip()
        if not self._ok or not text or lang != "vi":
            return text

        messages = [
            {"role": "system", "content": _SYSTEM_VI},
            {"role": "user",   "content": text},
        ]
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        with self._lock:
            try:
                inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
                # Generation budget: roughly the input length + small buffer,
                # capped so a misbehaving model can't run away.
                max_new = min(max(64, int(len(text) * 1.4)), 256)
                out = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new,
                    do_sample=False,
                    num_beams=1,
                    pad_token_id=self.tokenizer.eos_token_id,
                    repetition_penalty=1.05,
                )
                new_tokens = out[0][inputs.input_ids.shape[1]:]
                result = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
            except Exception as e:
                print(f"[Correct] generate failed: {e}", flush=True)
                return text

        # Strip wrapping quotes the model sometimes adds
        if len(result) >= 2 and result[0] in '"“‘' and result[-1] in '"”’':
            result = result[1:-1].strip()

        # Sanity guard: if model returned empty or wildly different length, fall back
        if not result:
            return text
        if len(result) > len(text) * 2 + 40 or len(result) < max(8, len(text) // 3):
            return text

        return result

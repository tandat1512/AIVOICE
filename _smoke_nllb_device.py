"""Viec 2 smoke test for NLLB_DEVICE / NLLB_INTRA_THREADS env vars.

Runs Path A (no place names -> streaming path) and Path B (contains a place
name -> _INFER_LOCK + list(generate_stream) path) through NLLBEngine, and
prints the resolved device/compute_type/intra_threads (from the [NLLB] log
line in nllb_engine.py) plus first_token/total timings for each.

Usage:
    .venv/Scripts/python.exe _smoke_nllb_device.py                 # default (NLLB_DEVICE unset)
    NLLB_DEVICE=cpu NLLB_INTRA_THREADS=4 .venv/Scripts/python.exe _smoke_nllb_device.py
"""
from __future__ import annotations

import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from server.translate.engines.nllb_engine import NLLBEngine  # noqa: E402

SENTENCES = [
    ("path_a", "Xin chào, hôm nay trời rất đẹp."),
    ("path_b_place", "Tôi muốn đi từ Hà Nội đến Đà Nẵng vào ngày mai."),
]

print(f"[smoke] NLLB_DEVICE={os.environ.get('NLLB_DEVICE')!r} "
      f"NLLB_INTRA_THREADS={os.environ.get('NLLB_INTRA_THREADS')!r}", flush=True)

engine = NLLBEngine(device="auto")
engine._ensure_loaded()

for key, text in SENTENCES:
    t0 = time.monotonic()
    first_ms = None
    tokens: list[str] = []
    for tok in engine.translate_stream(text, "vie_Latn", "eng_Latn"):
        if first_ms is None:
            first_ms = (time.monotonic() - t0) * 1000
        tokens.append(tok)
    total_ms = (time.monotonic() - t0) * 1000
    out = "".join(tokens)
    print(f"[smoke] {key}: first_token={first_ms:.1f}ms total={total_ms:.1f}ms -> {out!r}", flush=True)

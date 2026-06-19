"""Viec 3: isolated CPU measurement for NLLBEngine (no PhoWhisper running).

Run with NLLB_DEVICE=cpu NLLB_INTRA_THREADS=4 set in the environment. Loads
NLLBEngine, warms up each of the 6 sentences twice (discarded), then measures
10 timed runs per sentence. Reports first_token_ms / total_ms min/avg/max,
plus RAM free before/after via psutil.

Usage:
    NLLB_DEVICE=cpu NLLB_INTRA_THREADS=4 .venv/Scripts/python.exe _measure_isolated_cpu.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import psutil  # noqa: E402

from server.translate.engines.nllb_engine import NLLBEngine  # noqa: E402

ROOT = Path(__file__).resolve().parent

SENTENCES = [
    ("s1_short", "Xin chào, hôm nay trời rất đẹp."),
    ("s2_medium", "Tôi muốn đặt một bàn cho bốn người vào lúc bảy giờ tối nay."),
    ("s3_long", "Sau khi ăn sáng xong, chúng tôi quyết định đi dạo quanh công viên gần nhà."),
    ("s4_longer", "Mặc dù trời mưa rất to nhưng anh ấy vẫn quyết định đi làm đúng giờ như mọi ngày."),
    ("s5_30w_2commas",
     "Sáng nay tôi thức dậy sớm, chuẩn bị đồ ăn sáng cho cả nhà, "
     "sau đó đưa con đi học rồi mới quay về nhà để bắt đầu công việc của mình."),
    ("s6_place_pathB", "Tôi muốn đi từ Hà Nội đến Đà Nẵng vào ngày mai."),
]

WARMUP_RUNS = 2
TIMED_RUNS = 10


def mem_free_gb() -> float:
    return psutil.virtual_memory().available / 1e9


def run_once(text: str) -> tuple[float, float]:
    t0 = time.monotonic()
    first_ms = None
    for tok in engine.translate_stream(text, "vie_Latn", "eng_Latn"):
        if first_ms is None:
            first_ms = (time.monotonic() - t0) * 1000
    total_ms = (time.monotonic() - t0) * 1000
    return first_ms if first_ms is not None else total_ms, total_ms


print(f"[isolated] NLLB_DEVICE={os.environ.get('NLLB_DEVICE')!r} "
      f"NLLB_INTRA_THREADS={os.environ.get('NLLB_INTRA_THREADS')!r}", flush=True)
print(f"[isolated] RAM free before load: {mem_free_gb():.2f} GB", flush=True)

print("[isolated] loading NLLBEngine ...", flush=True)
engine = NLLBEngine(device="auto")
engine._ensure_loaded()
print(f"[isolated] RAM free after load: {mem_free_gb():.2f} GB", flush=True)

results = {}
for key, text in SENTENCES:
    for _ in range(WARMUP_RUNS):
        run_once(text)

    firsts = []
    totals = []
    for _ in range(TIMED_RUNS):
        f, t = run_once(text)
        firsts.append(f)
        totals.append(t)

    row = {
        "n": TIMED_RUNS,
        "first_token_ms": {"min": round(min(firsts), 1), "avg": round(sum(firsts) / len(firsts), 1), "max": round(max(firsts), 1)},
        "total_ms": {"min": round(min(totals), 1), "avg": round(sum(totals) / len(totals), 1), "max": round(max(totals), 1)},
        "raw_total_ms": [round(t, 1) for t in totals],
    }
    results[key] = row
    print(f"[isolated] {key}: first_token={row['first_token_ms']} total={row['total_ms']}", flush=True)
    print(f"[isolated]   raw_total_ms={row['raw_total_ms']}", flush=True)

print(f"\n[isolated] RAM free after run: {mem_free_gb():.2f} GB", flush=True)

out_path = ROOT / "_measure_isolated_cpu.json"
out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[isolated] wrote {out_path}", flush=True)

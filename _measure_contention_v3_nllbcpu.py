"""Viec 4: NLLB-CPU + PhoWhisper-GPU contention measurement.

Run with NLLB_DEVICE=cpu NLLB_INTRA_THREADS=4 set in the environment.
PhoWhisper-large stays on GPU (device="cuda" if available), looping
transcribe(6s) continuously in a background thread while the main thread
times the same 6 sentences through NLLBEngine (warm-up 2x + 10 timed runs
each = 60 samples), all under contention.

A heartbeat thread (20ms tick) detects event-loop-style starvation, and an
in-process psutil.cpu_percent() sampler tracks system-wide CPU% throughout.

Usage:
    NLLB_DEVICE=cpu NLLB_INTRA_THREADS=4 .venv/Scripts/python.exe _measure_contention_v3_nllbcpu.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("ONNX_PROVIDER", "CPUExecutionProvider")
os.environ.setdefault("CONTEXT_DISABLED", "1")

ROOT = Path(__file__).resolve().parent

import numpy as np  # noqa: E402
import psutil  # noqa: E402

from server.translate.engines.nllb_engine import NLLBEngine  # noqa: E402

WARMUP_RUNS = 2
TIMED_RUNS = 10

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


def mem_free_gb() -> float:
    return psutil.virtual_memory().available / 1e9


print(f"[v3] NLLB_DEVICE={os.environ.get('NLLB_DEVICE')!r} "
      f"NLLB_INTRA_THREADS={os.environ.get('NLLB_INTRA_THREADS')!r}", flush=True)
print(f"[v3] RAM free before load: {mem_free_gb():.2f} GB", flush=True)

print("[v3] loading NLLBEngine ...", flush=True)
engine = NLLBEngine(device="auto")
engine._ensure_loaded()

# Warm up NLLB once each (no contention yet) -- mirrors _measure_contention.py.
for key, vi_text in SENTENCES:
    list(engine.translate_stream(vi_text, "vie_Latn", "eng_Latn"))
print("[v3] NLLB warmup done", flush=True)

print("[v3] loading PhoWhisper-large ...", flush=True)
import torch  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from server.stt_phowhisper_dual import _find_phowhisper, _BEAM_SIZE, SAMPLE_RATE  # noqa: E402

pw_path, _pw_hf = _find_phowhisper()
pw_device = "cuda" if torch.cuda.is_available() else "cpu"
pw_compute = "int8_float16" if pw_device == "cuda" else "int8"
pw_model = WhisperModel(pw_path, device=pw_device, compute_type=pw_compute)
print(f"[v3] PhoWhisper-large loaded device={pw_device} compute_type={pw_compute}", flush=True)

raw = (ROOT / "test_audio.pcm").read_bytes()
n6_bytes = SAMPLE_RATE * 6 * 2
audio6 = np.frombuffer(raw[:n6_bytes], dtype=np.int16).astype(np.float32) / 32768.0
print(f"[v3] PhoWhisper test clip: {len(audio6) / SAMPLE_RATE:.2f}s", flush=True)

_t0 = time.monotonic()
segs, _ = pw_model.transcribe(
    audio6, language="vi", beam_size=_BEAM_SIZE, word_timestamps=True,
    vad_filter=False, condition_on_previous_text=False, temperature=0.0,
    no_speech_threshold=0.5, max_new_tokens=216,
    compression_ratio_threshold=2.4, repetition_penalty=1.1,
    hallucination_silence_threshold=2.0,
)
_ = " ".join(s.text for s in segs)
print(f"[v3] PhoWhisper warmup done ({(time.monotonic() - _t0) * 1000:.0f}ms)", flush=True)

print(f"[v3] RAM free after load+warmup: {mem_free_gb():.2f} GB", flush=True)

# ── background threads ──────────────────────────────────────────────────────
hb_stop = threading.Event()
hb_gaps: list[tuple[float, float]] = []


def heartbeat() -> None:
    last = time.monotonic()
    while not hb_stop.is_set():
        time.sleep(0.02)
        now = time.monotonic()
        gap_ms = (now - last) * 1000
        if gap_ms > 25:
            hb_gaps.append((now, round(gap_ms, 1)))
        last = now


pw_stop = threading.Event()
pw_durations: list[float] = []


def pw_loop() -> None:
    while not pw_stop.is_set():
        t0 = time.monotonic()
        segs, _ = pw_model.transcribe(
            audio6, language="vi", beam_size=_BEAM_SIZE, word_timestamps=True,
            vad_filter=False, condition_on_previous_text=False, temperature=0.0,
            no_speech_threshold=0.5, max_new_tokens=216,
            compression_ratio_threshold=2.4, repetition_penalty=1.1,
            hallucination_silence_threshold=2.0,
        )
        _ = " ".join(s.text for s in segs)
        dt_ms = (time.monotonic() - t0) * 1000
        pw_durations.append(dt_ms)
        print(f"[PW-loop] transcribe {dt_ms:.0f}ms (n={len(pw_durations)})", flush=True)


cpu_stop = threading.Event()
cpu_samples: list[float] = []


def cpu_sampler() -> None:
    psutil.cpu_percent(interval=None)  # prime
    while not cpu_stop.is_set():
        cpu_samples.append(psutil.cpu_percent(interval=0.5))


hb_thread = threading.Thread(target=heartbeat, daemon=True)
pw_thread = threading.Thread(target=pw_loop, daemon=True)
cpu_thread = threading.Thread(target=cpu_sampler, daemon=True)
hb_thread.start()
pw_thread.start()
cpu_thread.start()

print("\n=== Contention: NLLB-CPU 6 sentences x (2 warmup + 10 timed) under PhoWhisper-GPU loop ===", flush=True)

results: dict[str, dict] = {}
for key, text in SENTENCES:
    for _ in range(WARMUP_RUNS):
        list(engine.translate_stream(text, "vie_Latn", "eng_Latn"))

    firsts = []
    totals = []
    for _ in range(TIMED_RUNS):
        t0 = time.monotonic()
        first_ms = None
        for tok in engine.translate_stream(text, "vie_Latn", "eng_Latn"):
            if first_ms is None:
                first_ms = (time.monotonic() - t0) * 1000
        total_ms = (time.monotonic() - t0) * 1000
        firsts.append(first_ms if first_ms is not None else total_ms)
        totals.append(total_ms)

    row = {
        "n": TIMED_RUNS,
        "first_token_ms": {"min": round(min(firsts), 1), "avg": round(sum(firsts) / len(firsts), 1), "max": round(max(firsts), 1)},
        "total_ms": {"min": round(min(totals), 1), "avg": round(sum(totals) / len(totals), 1), "max": round(max(totals), 1)},
        "raw_total_ms": [round(t, 1) for t in totals],
    }
    results[key] = row
    print(f"[v3] {key}: first_token={row['first_token_ms']} total={row['total_ms']}", flush=True)
    print(f"[v3]   raw_total_ms={row['raw_total_ms']}", flush=True)

pw_stop.set()
hb_stop.set()
cpu_stop.set()
pw_thread.join(timeout=15)
hb_thread.join(timeout=2)
cpu_thread.join(timeout=2)

print(f"\n[v3] RAM free after run: {mem_free_gb():.2f} GB", flush=True)

# ── summary ──────────────────────────────────────────────────────────────────
all_totals = [t for row in results.values() for t in row["raw_total_ms"]]
n_total = len(all_totals)
n_over_1000 = sum(1 for t in all_totals if t > 1000)
max_total = max(all_totals)

print(f"\n=== SUMMARY: total_ms > 1000ms across all {n_total} samples ===", flush=True)
print(f"  count={n_over_1000} ({100 * n_over_1000 / n_total:.1f}%)", flush=True)
print(f"  max_total_ms={max_total}", flush=True)

print(f"\n=== SUMMARY: PhoWhisper-large transcribe(6s) loop (n={len(pw_durations)}) ===", flush=True)
if pw_durations:
    print(f"  min={min(pw_durations):.0f}ms avg={sum(pw_durations)/len(pw_durations):.0f}ms max={max(pw_durations):.0f}ms", flush=True)

print(f"\n=== SUMMARY: system CPU% (n={len(cpu_samples)}) ===", flush=True)
if cpu_samples:
    print(f"  min={min(cpu_samples):.1f} avg={sum(cpu_samples)/len(cpu_samples):.1f} max={max(cpu_samples):.1f}", flush=True)

print(f"\n=== SUMMARY: heartbeat gaps (n={len(hb_gaps)}) ===", flush=True)
if hb_gaps:
    gap_vals = [g for _, g in hb_gaps]
    print(f"  count={len(gap_vals)} min={min(gap_vals):.1f}ms max={max(gap_vals):.1f}ms "
          f"gaps_over_150ms={sum(1 for g in gap_vals if g > 150)}", flush=True)
else:
    print("  (none)", flush=True)

out = {
    "results": results,
    "pw_durations_ms": pw_durations,
    "cpu_samples_pct": cpu_samples,
    "heartbeat_gaps_ms": hb_gaps,
    "n_total_samples": n_total,
    "n_over_1000ms": n_over_1000,
    "max_total_ms": max_total,
}
out_path = ROOT / "_measure_contention_v3_nllbcpu.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[v3] wrote {out_path}", flush=True)

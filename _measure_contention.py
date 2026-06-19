"""Viec 3-5 contention probe (read-only diagnostic, mirrors _measure_pipeline.py).

Loads NLLBEngine + PhoWhisper-large in ONE process (same .venv, same GPU as
production: device="auto" for NLLB, device="cuda"/int8_float16 for PhoWhisper
when available -- exactly server/stt_phowhisper_dual.py:load_model()).

Phase A (baseline): translate_stream() timings for 6 sentences (5 from
_measure_pipeline.py s1-s5, plus s6 which contains two place names -> Path B
of NLLBEngine.translate_stream, i.e. "with _INFER_LOCK: tokens = list(...)").
No PhoWhisper activity during this phase.

Phase B (contention): a background thread runs PhoWhisper-large.transcribe()
on a 6s real-audio clip in a tight loop for ~60s, while the main thread
repeatedly times the same 6 sentences. A second background thread ("heartbeat")
ticks every 20ms to detect Python/GIL-level starvation -- a rough proxy for
"would the asyncio WS receive loop miss a PCM frame deadline" (Viec 5).

Usage:
    .venv/Scripts/python.exe _measure_contention.py

Writes _measure_contention.json
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

from server.translate.engines.nllb_engine import NLLBEngine  # noqa: E402

CONTENTION_S = 60.0  # how long Phase B runs

SENTENCES = [
    ("s1_short", "Xin chào, hôm nay trời rất đẹp."),
    ("s2_medium", "Tôi muốn đặt một bàn cho bốn người vào lúc bảy giờ tối nay."),
    ("s3_long", "Sau khi ăn sáng xong, chúng tôi quyết định đi dạo quanh công viên gần nhà."),
    ("s4_longer", "Mặc dù trời mưa rất to nhưng anh ấy vẫn quyết định đi làm đúng giờ như mọi ngày."),
    ("s5_30w_2commas",
     "Sáng nay tôi thức dậy sớm, chuẩn bị đồ ăn sáng cho cả nhà, "
     "sau đó đưa con đi học rồi mới quay về nhà để bắt đầu công việc của mình."),
    # Contains 2 place names ("Hà Nội", "Đà Nẵng") -> mask_places() makes
    # combined_map non-empty -> NLLBEngine.translate_stream Path B
    # (with _INFER_LOCK: tokens = list(generate_stream(...))).
    ("s6_place_pathB", "Tôi muốn đi từ Hà Nội đến Đà Nẵng vào ngày mai."),
]


print("[contention] loading NLLBEngine (device=auto) ...", flush=True)
engine = NLLBEngine(device="auto")
engine._ensure_loaded()
print(f"[contention] NLLB translator device(requested)=auto "
      f"resolved_translator={type(engine._translator._translator).__module__}", flush=True)

# Warm up (first call pays one-time CUDA/cuDNN init cost; exclude from timings).
for key, vi_text in SENTENCES:
    list(engine.translate_stream(vi_text, "vie_Latn", "eng_Latn"))
print("[contention] NLLB warmup done", flush=True)


print("[contention] loading PhoWhisper-large ...", flush=True)
import torch  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from server.stt_phowhisper_dual import _find_phowhisper, _BEAM_SIZE, SAMPLE_RATE  # noqa: E402

pw_path, _pw_hf = _find_phowhisper()
pw_device = "cuda" if torch.cuda.is_available() else "cpu"
pw_compute = "int8_float16" if pw_device == "cuda" else "int8"
pw_model = WhisperModel(pw_path, device=pw_device, compute_type=pw_compute)
print(f"[contention] PhoWhisper-large loaded device={pw_device} compute_type={pw_compute}", flush=True)


# 6s real-audio clip from test_audio.pcm (16kHz mono int16 PCM, ~50.5s total).
raw = (ROOT / "test_audio.pcm").read_bytes()
n6_bytes = SAMPLE_RATE * 6 * 2
audio6 = np.frombuffer(raw[:n6_bytes], dtype=np.int16).astype(np.float32) / 32768.0
print(f"[contention] PhoWhisper test clip: {len(audio6) / SAMPLE_RATE:.2f}s", flush=True)

# Warm up PhoWhisper once (first call pays CUDA init cost too).
_t0 = time.monotonic()
segs, _ = pw_model.transcribe(
    audio6, language="vi", beam_size=_BEAM_SIZE, word_timestamps=True,
    vad_filter=False, condition_on_previous_text=False, temperature=0.0,
    no_speech_threshold=0.5, max_new_tokens=216,
    compression_ratio_threshold=2.4, repetition_penalty=1.1,
    hallucination_silence_threshold=2.0,
)
_ = " ".join(s.text for s in segs)
print(f"[contention] PhoWhisper warmup done ({(time.monotonic() - _t0) * 1000:.0f}ms)", flush=True)


def measure_translate(label: str) -> list[dict]:
    rows = []
    for key, vi_text in SENTENCES:
        t0 = time.monotonic()
        first_ms = None
        for tok in engine.translate_stream(vi_text, "vie_Latn", "eng_Latn"):
            if first_ms is None:
                first_ms = (time.monotonic() - t0) * 1000
        total_ms = (time.monotonic() - t0) * 1000
        rows.append({
            "phase": label, "key": key,
            "first_token_ms": round(first_ms, 1) if first_ms is not None else None,
            "total_ms": round(total_ms, 1),
            "t_wall": time.monotonic(),
        })
        print(f"[{label}] {key}: first_token={first_ms:.1f}ms total={total_ms:.1f}ms", flush=True)
    return rows


print("\n=== Phase A: baseline (no PhoWhisper activity) ===", flush=True)
baseline_rows = measure_translate("baseline")


# Heartbeat thread: ticks every 20ms; records gaps > 25ms (5ms slack).
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


# PhoWhisper loop thread: transcribe the 6s clip back-to-back for CONTENTION_S.
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


print(f"\n=== Phase B: contention (PhoWhisper-large loop, {CONTENTION_S:.0f}s) ===", flush=True)
hb_thread = threading.Thread(target=heartbeat, daemon=True)
pw_thread = threading.Thread(target=pw_loop, daemon=True)
hb_thread.start()
pw_thread.start()

contention_rows: list[dict] = []
t_start = time.monotonic()
while time.monotonic() - t_start < CONTENTION_S:
    contention_rows.extend(measure_translate("contention"))

pw_stop.set()
hb_stop.set()
pw_thread.join(timeout=10)
hb_thread.join(timeout=2)


# ── summary ──────────────────────────────────────────────────────────────────
def summarize(rows: list[dict], key: str, field: str) -> dict:
    vals = [r[field] for r in rows if r["key"] == key and r[field] is not None]
    if not vals:
        return {"n": 0, "min": None, "max": None, "avg": None}
    return {"n": len(vals), "min": round(min(vals), 1), "max": round(max(vals), 1),
            "avg": round(sum(vals) / len(vals), 1)}


print("\n=== SUMMARY: NLLB first_token_ms (baseline vs contention) ===", flush=True)
summary_rows = []
for key, _ in SENTENCES:
    b = summarize(baseline_rows, key, "first_token_ms")
    c = summarize(contention_rows, key, "first_token_ms")
    print(f"  {key:18s} baseline={b} contention={c}", flush=True)
    summary_rows.append({"key": key, "baseline_first_token": b, "contention_first_token": c})

print(f"\n=== SUMMARY: PhoWhisper-large transcribe(6s) loop ===", flush=True)
pw_summary = {
    "n": len(pw_durations),
    "min_ms": round(min(pw_durations), 0) if pw_durations else None,
    "max_ms": round(max(pw_durations), 0) if pw_durations else None,
    "avg_ms": round(sum(pw_durations) / len(pw_durations), 0) if pw_durations else None,
}
print(f"  {pw_summary}", flush=True)

print(f"\n=== SUMMARY: heartbeat gaps > 25ms during contention (n={len(hb_gaps)}) ===", flush=True)
if hb_gaps:
    gap_vals = [g for _, g in hb_gaps]
    print(f"  count={len(gap_vals)} min={min(gap_vals):.1f}ms max={max(gap_vals):.1f}ms "
          f"gaps_over_150ms={sum(1 for g in gap_vals if g > 150)}", flush=True)
else:
    print("  (none -- main-thread heartbeat stayed within 25ms tick)", flush=True)

out = {
    "baseline_rows": baseline_rows,
    "contention_rows": contention_rows,
    "pw_durations_ms": pw_durations,
    "pw_summary": pw_summary,
    "heartbeat_gaps_ms": hb_gaps,
    "summary": summary_rows,
    "pw_device": pw_device,
    "pw_compute_type": pw_compute,
}
out_path = ROOT / "_measure_contention_v2.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[contention] wrote {out_path}", flush=True)

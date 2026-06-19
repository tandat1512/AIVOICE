"""Sprint 0 benchmark for the Kokoro-82M TTS engine.

Measures first-chunk latency, total synthesis time, and real-time factor (RTF)
for 4 English sentences of increasing length. Writes:

  X:/smartgen/bench_tts_results.json   structured metrics
  X:/smartgen/bench_tts_sample.wav     first sentence as WAV (manual A/B)

Decision gate (from plan):
  PASS if first_chunk_ms < 400 ms AND rtf < 0.4 on the shortest sentence.

Run:  X:/smartgen/.venv/Scripts/python.exe X:/smartgen/bench_tts.py
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server.tts.engines.kokoro_engine import KokoroEngine  # noqa: E402


SENTENCES = [
    "Hello, how are you today?",  # 5 words
    "The quick brown fox jumps over the lazy dog in the park.",  # 12 words
    (
        "Real-time translation systems must balance latency and quality, "
        "delivering each phrase before the speaker finishes the next."
    ),  # 20 words
    (
        "Streaming text-to-speech engines convert tokens into audio chunks "
        "as soon as the upstream translation model emits them, allowing the "
        "listener to hear the first words of the translated sentence within "
        "a few hundred milliseconds while the rest of the utterance is still "
        "being synthesized in the background."
    ),  # ~50 words
]


def _system_info() -> dict:
    info = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }
    try:
        import onnxruntime as ort  # type: ignore

        info["onnxruntime"] = ort.__version__
        info["ort_providers"] = ort.get_available_providers()
    except Exception as e:  # noqa: BLE001
        info["onnxruntime_error"] = str(e)
    try:
        import torch  # type: ignore

        info["torch"] = torch.__version__
        info["torch_cuda"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
    except Exception as e:  # noqa: BLE001
        info["torch_error"] = str(e)
    return info


def _benchmark_one(engine: KokoroEngine, text: str) -> dict:
    """Run a single utterance and return latency metrics + raw audio."""
    chunks: list[bytes] = []
    t_start = time.perf_counter()
    t_first: float | None = None

    for chunk in engine.synthesize_stream(text):
        if t_first is None:
            t_first = time.perf_counter()
        chunks.append(chunk)

    t_end = time.perf_counter()
    sr = engine.sample_rate

    audio_bytes = b"".join(chunks)
    n_samples = len(audio_bytes) // 2  # Int16 = 2 bytes
    audio_seconds = n_samples / sr if sr else 0.0
    total_ms = (t_end - t_start) * 1000.0
    first_chunk_ms = ((t_first or t_end) - t_start) * 1000.0
    rtf = (total_ms / 1000.0) / audio_seconds if audio_seconds > 0 else float("inf")

    return {
        "text": text,
        "words": len(text.split()),
        "first_chunk_ms": round(first_chunk_ms, 1),
        "total_ms": round(total_ms, 1),
        "audio_seconds": round(audio_seconds, 3),
        "sample_rate": sr,
        "rtf": round(rtf, 3),
        "_audio_bytes": audio_bytes,  # popped before JSON serialization
    }


def _pcm_to_wav(pcm: bytes, sample_rate: int, dest: Path) -> None:
    arr = np.frombuffer(pcm, dtype=np.int16)
    sf.write(str(dest), arr, sample_rate, subtype="PCM_16")


def main() -> int:
    print("=" * 78)
    print("Sprint 0 — Kokoro-82M TTS Benchmark")
    print("=" * 78)
    info = _system_info()
    for k, v in info.items():
        print(f"  {k}: {v}")
    print()

    engine = KokoroEngine()

    print("Loading model + voices (may download ~330 MB on first run) ...")
    t0 = time.perf_counter()
    engine.warmup()
    warmup_s = time.perf_counter() - t0
    print(f"  warmup: {warmup_s * 1000:.0f} ms\n")

    results: list[dict] = []
    sample_wav_written = False
    for i, sentence in enumerate(SENTENCES, 1):
        print(f"[{i}/{len(SENTENCES)}] {len(sentence.split())} words: {sentence[:60]}...")
        res = _benchmark_one(engine, sentence)
        if not sample_wav_written:
            _pcm_to_wav(res["_audio_bytes"], res["sample_rate"], ROOT / "bench_tts_sample.wav")
            sample_wav_written = True
            print(f"  -> wrote bench_tts_sample.wav ({len(res['_audio_bytes'])} bytes pcm)")
        # Strip raw audio before serialization
        res.pop("_audio_bytes", None)
        results.append(res)
        print(
            f"  first_chunk_ms={res['first_chunk_ms']}  total_ms={res['total_ms']}  "
            f"audio_s={res['audio_seconds']}  rtf={res['rtf']}"
        )

    print()
    print("=" * 78)
    print("Summary table")
    print("=" * 78)
    print(f"{'words':>6} | {'first_ms':>9} | {'total_ms':>9} | {'audio_s':>8} | {'rtf':>6}")
    print("-" * 78)
    for r in results:
        print(
            f"{r['words']:>6} | {r['first_chunk_ms']:>9.1f} | {r['total_ms']:>9.1f} | "
            f"{r['audio_seconds']:>8.3f} | {r['rtf']:>6.3f}"
        )

    # Decision gate (per Sprint 0 plan):
    shortest = results[0]
    gate_first = shortest["first_chunk_ms"] < 400.0
    gate_rtf = shortest["rtf"] < 0.4
    overall_pass = gate_first and gate_rtf

    print()
    print("=" * 78)
    print("Decision gate (shortest sentence)")
    print("=" * 78)
    print(f"  first_chunk_ms < 400 ?  {gate_first}  (got {shortest['first_chunk_ms']:.1f})")
    print(f"  rtf < 0.4            ?  {gate_rtf}  (got {shortest['rtf']:.3f})")
    print(f"  OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    if not overall_pass:
        print()
        print("RECOMMENDATION:")
        if "CUDAExecutionProvider" not in info.get("ort_providers", []):
            print("  • Install onnxruntime-gpu (replace CPU onnxruntime):")
            print("    pip uninstall -y onnxruntime")
            print("    pip install onnxruntime-gpu")
            print("  • Re-run bench_tts.py and check ort_providers list.")
        else:
            print("  • GPU provider present but latency still high — try:")
            print("    - shorter input phrasing per dispatch")
            print("    - alternative engine: piper-tts (CPU, smaller, ~50ms first chunk)")

    out = ROOT / "bench_tts_results.json"
    payload = {
        "system_info": info,
        "warmup_ms": round(warmup_s * 1000, 1),
        "results": results,
        "gate": {
            "first_chunk_ms_lt_400": gate_first,
            "rtf_lt_0_4": gate_rtf,
            "overall_pass": overall_pass,
        },
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote: {out}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())

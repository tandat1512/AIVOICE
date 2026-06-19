"""Việc 4: measure SEGMENTER=v1 vs v2 — mid-clause cut rate and lock latency.

Builds a synthetic Vietnamese audio timeline with three kinds of pauses
(mid-clause ~400-600ms, sentence-boundary ~700-800ms) plus one continuous
(no-pause) utterance >_MAX_SPEECH_S long containing clause conjunctions, then
streams it through StreamingASR in real time and records every is_final
commit (timestamp + silence_ms + text).

Usage (run from AIVOICE/):
    .venv/Scripts/python.exe _measure_segmenter.py v1
    .venv/Scripts/python.exe _measure_segmenter.py v2

Each run writes _measure_<mode>.json. Run both, then compare with
_measure_compare.py.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODE = sys.argv[1] if len(sys.argv) > 1 else "v1"
assert MODE in ("v1", "v2"), "usage: _measure_segmenter.py v1|v2"

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
if MODE == "v2":
    os.environ["SEGMENTER"] = "v2"

from server import stt_phowhisper_dual as mod
from server.stt_sherpa import SAMPLE_RATE

ROOT       = Path(__file__).resolve().parent
CACHE_DIR  = ROOT / "_measure_cache"
CACHE_DIR.mkdir(exist_ok=True)


def tts_pcm(text: str, key: str) -> np.ndarray:
    mp3_path = CACHE_DIR / f"{key}.mp3"
    if not mp3_path.exists():
        from gtts import gTTS
        gTTS(text=text, lang="vi").save(str(mp3_path))
    import librosa
    audio, _ = librosa.load(str(mp3_path), sr=SAMPLE_RATE, mono=True)
    # gTTS pads each clip with its own lead/trail silence; trim it so the
    # silence durations we splice in below are the actual VAD-visible pauses.
    trimmed, _ = librosa.effects.trim(audio, top_db=25)
    return trimmed.astype(np.float32)


def silence(ms: int) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * ms / 1000), dtype=np.float32)


# ── build the test timeline ─────────────────────────────────────────────────
# Three "real sentences", each split into two clauses by a mid-clause pause
# (400-600ms — should NOT lock in v2), followed by a sentence-boundary pause
# (700-800ms — should lock in both). Then one continuous (no-pause) utterance
# with clause conjunctions, longer than _MAX_SPEECH_S (default 6s).
FRAGMENTS = [
    ("s1a", "hôm nay trời rất đẹp"),
    ("s1b", "nên tôi muốn đi dạo"),
    ("s2a", "buổi sáng tôi ăn phở"),
    ("s2b", "rồi tôi đi làm luôn"),
    ("s3a", "cuối tuần tôi sẽ về quê"),
    ("s3b", "để thăm ông bà"),
    ("s4", "tôi thức dậy sớm và tôi đi tập thể dục rồi tôi ăn sáng "
           "nhưng tôi quên mang theo ô nên khi ra đường thì trời bắt đầu mưa to"),
]
print(f"[measure:{MODE}] synthesizing {len(FRAGMENTS)} fragments via gTTS ...", flush=True)
clips = {key: tts_pcm(text, key) for key, text in FRAGMENTS}
for key, a in clips.items():
    print(f"  {key}: {len(a) / SAMPLE_RATE:.2f}s", flush=True)

timeline = [
    ("s1a", clips["s1a"]),
    ("pause_mid_1", silence(450)),
    ("s1b", clips["s1b"]),
    ("pause_boundary_1", silence(800)),
    ("s2a", clips["s2a"]),
    ("pause_mid_2", silence(500)),
    ("s2b", clips["s2b"]),
    ("pause_boundary_2", silence(750)),
    ("s3a", clips["s3a"]),
    ("pause_mid_3", silence(480)),
    ("s3b", clips["s3b"]),
    ("pause_boundary_3", silence(800)),
    ("s4", clips["s4"]),
    ("pause_boundary_4", silence(800)),
]
audio = np.concatenate([a for _, a in timeline]).astype(np.float32)

# Sample offset where each pause STARTS == where speech ends (a candidate
# segment-lock point).
markers: dict[str, float] = {}
offset = 0
for label, a in timeline:
    if label.startswith("pause"):
        markers[label] = offset / SAMPLE_RATE
    offset += len(a)

print(f"[measure:{MODE}] total audio: {len(audio) / SAMPLE_RATE:.2f}s", flush=True)
print(f"[measure:{MODE}] markers (s): "
      f"{ {k: round(v, 3) for k, v in markers.items()} }", flush=True)

# ── stream through StreamingASR in real time ───────────────────────────────
events: list[tuple[float, int, str]] = []
t_start = [0.0]


def on_update(committed, interim, silence_ms=0, is_final=False, final_text="", *rest):
    if is_final:
        events.append((time.monotonic() - t_start[0], silence_ms, final_text))
        print(f"[measure:{MODE}] COMMIT t={events[-1][0]:.3f}s "
              f"silence_ms={silence_ms} text={final_text!r}", flush=True)


print(f"[measure:{MODE}] loading models ...", flush=True)
model_path = mod.prepare_model()
model = mod.load_model(model_path)
asr = mod.StreamingASR(on_update, model, "vi")

CHUNK_MS = 250
chunk_n = int(SAMPLE_RATE * CHUNK_MS / 1000)

print(f"[measure:{MODE}] streaming in real time ...", flush=True)
t_start[0] = time.monotonic()
for i in range(0, len(audio), chunk_n):
    asr.feed_pcm(audio[i:i + chunk_n])
    time.sleep(CHUNK_MS / 1000)

# Drain the trailing pause's lock trigger (up to ~lock_trigger + margin).
time.sleep(1.5)
asr.stop()

result = {
    "mode": MODE,
    "sample_rate": SAMPLE_RATE,
    "total_audio_s": len(audio) / SAMPLE_RATE,
    "markers_s": markers,
    "events": [{"t": t, "silence_ms": sm, "text": txt} for t, sm, txt in events],
}
out_path = ROOT / f"_measure_{MODE}.json"
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[measure:{MODE}] wrote {out_path}", flush=True)

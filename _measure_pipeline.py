"""Step 4 for stream-translate-tts-pipeline plan.

Drives StreamingTranslationRouter._dispatch_final directly (bypassing STT) with
5 fixed Vietnamese sentences, including the ~30-word/2-comma sentence from
addendum 5. Records, per sentence:

  - first_audio_ms (segment-lock -> first Kokoro PCM chunk), from the router's
    own "latency" telemetry event.
  - t_nllb_first_token: time of the first trans_stream_c token (NLLB decode start).
  - t_handoff: time of the first tts_start event (NLLB cụm -> Kokoro dispatch).
  - cụm_count: number of distinct TTS utterances dispatched (chunk_id-N pieces,
    across all clauses if _split_clauses fired).
  - per-cụm word counts (to check addendum 5's "no <3-word fragment" criterion).
  - total audio duration (sum of PCM bytes / sample_rate / 2).

Usage (run from X:/smartgen):
    .venv/Scripts/python.exe _measure_pipeline.py [before|after]

Writes _measure_pipeline_<label>.json (label defaults to "after").
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
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

from server.translate.engines.nllb_engine import NLLBEngine  # noqa: E402
from server.translate.streaming_router import StreamingTranslationRouter  # noqa: E402
from server.tts.dispatcher import TTSDispatcher  # noqa: E402
from server.tts.engines.kokoro_engine import KokoroEngine  # noqa: E402

LABEL = sys.argv[1] if len(sys.argv) > 1 else "after"

# Same s1-s4 as Steps 0/1; s5 is the ~30-word/2-comma sentence (addendum 5).
SENTENCES = [
    ("s1_short", "Xin chào, hôm nay trời rất đẹp."),
    ("s2_medium", "Tôi muốn đặt một bàn cho bốn người vào lúc bảy giờ tối nay."),
    ("s3_long", "Sau khi ăn sáng xong, chúng tôi quyết định đi dạo quanh công viên gần nhà."),
    ("s4_longer", "Mặc dù trời mưa rất to nhưng anh ấy vẫn quyết định đi làm đúng giờ như mọi ngày."),
    ("s5_30w_2commas",
     "Sáng nay tôi thức dậy sớm, chuẩn bị đồ ăn sáng cho cả nhà, "
     "sau đó đưa con đi học rồi mới quay về nhà để bắt đầu công việc của mình."),
]

IDLE_TIMEOUT_S = 3.0  # stop draining a sentence's events after this much silence

print("[pipeline] loading NLLBEngine ...", flush=True)
engine = NLLBEngine(device="auto")
engine._ensure_loaded()

print("[pipeline] loading KokoroEngine ...", flush=True)
tts_engine = KokoroEngine()
tts_engine.warmup()

dispatcher = TTSDispatcher(tts_engine)

loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

results = []

for key, vi_text in SENTENCES:
    print(f"\n[pipeline] === {key} ({len(vi_text.split())} words) === {vi_text!r}", flush=True)

    router = StreamingTranslationRouter(engine, tts_dispatcher=dispatcher, tts_voice="af_sarah", wait_final=True)
    send_q: "queue.Queue[object]" = queue.Queue()

    t0 = time.monotonic()
    router._dispatch_final(vi_text, "vi", "en", loop, send_q, seg_id="", speaker=0)

    events: list[tuple[float, dict]] = []
    pcm_bytes_by_utterance: dict[str, int] = {}
    t_first_pcm: float | None = None
    while True:
        try:
            item = send_q.get(timeout=IDLE_TIMEOUT_S)
        except queue.Empty:
            break
        t = time.monotonic() - t0
        if isinstance(item, (bytes, bytearray)):
            # Binary PCM chunk -- attribute to whichever utterance most recently
            # got a tts_start without a matching tts_end yet.
            if t_first_pcm is None:
                t_first_pcm = t
            uid = pcm_bytes_by_utterance.setdefault("__current__", "")
            pcm_bytes_by_utterance[uid] = pcm_bytes_by_utterance.get(uid, 0) + len(item)
            continue
        events.append((t, item))
        if item.get("type") == "tts_start":
            pcm_bytes_by_utterance["__current__"] = item["utterance_id"]
            pcm_bytes_by_utterance.setdefault(item["utterance_id"], 0)

    pcm_bytes_by_utterance.pop("__current__", None)

    # ── Extract telemetry ────────────────────────────────────────────────────
    trans_tokens = [(t, e) for t, e in events if e.get("type") == "trans_stream_c"]
    tts_starts = [(t, e) for t, e in events if e.get("type") == "tts_start"]
    tts_ends = [(t, e) for t, e in events if e.get("type") == "tts_end"]
    latency_events = [(t, e) for t, e in events if e.get("type") == "latency"]
    translation_updates = [(t, e) for t, e in events if e.get("type") == "translation_update"]

    t_nllb_first_token = trans_tokens[0][0] * 1000 if trans_tokens else None
    t_handoff = tts_starts[0][0] * 1000 if tts_starts else None

    first_audio_events = [(t, e) for t, e in latency_events if "first_audio_ms" in e]
    first_audio_ms = first_audio_events[0][1]["first_audio_ms"] if first_audio_events else None

    # t_first_pcm_ms: time of the very first PCM byte received, relative to t0
    # (call to _dispatch_final). Computed from raw binary chunks, so it works
    # whether or not the router emits an on_first_chunk "latency" event --
    # this is the metric used for before/after comparison.
    t_first_pcm_ms = t_first_pcm * 1000 if t_first_pcm is not None else None
    t_kokoro_first_pcm = first_audio_events[0][0] * 1000 if first_audio_events else t_first_pcm_ms

    sample_rate = tts_engine.sample_rate
    total_audio_bytes = sum(pcm_bytes_by_utterance.values())
    total_audio_s = total_audio_bytes / sample_rate / 2  # Int16 = 2 bytes/sample

    cum_durations_s = {
        uid: nbytes / sample_rate / 2 for uid, nbytes in pcm_bytes_by_utterance.items()
    }

    print(f"[pipeline]   t_nllb_first_token={t_nllb_first_token}ms "
          f"t_handoff={t_handoff}ms t_kokoro_first_pcm={t_kokoro_first_pcm}ms "
          f"first_audio_ms={first_audio_ms} t_first_pcm_ms={t_first_pcm_ms}", flush=True)
    print(f"[pipeline]   tts_starts={len(tts_starts)} tts_ends={len(tts_ends)} "
          f"total_audio_s={total_audio_s:.3f}", flush=True)
    for t, e in tts_starts:
        print(f"[pipeline]     tts_start t={t*1000:.1f}ms utterance_id={e['utterance_id']}", flush=True)
    for uid, dur in cum_durations_s.items():
        print(f"[pipeline]     utterance {uid}: audio_dur={dur:.3f}s", flush=True)

    results.append({
        "key": key,
        "text": vi_text,
        "n_words": len(vi_text.split()),
        "first_audio_ms": first_audio_ms,
        "t_first_pcm_ms": t_first_pcm_ms,
        "t_nllb_first_token_ms": t_nllb_first_token,
        "t_handoff_ms": t_handoff,
        "t_kokoro_first_pcm_ms": t_kokoro_first_pcm,
        "n_tts_starts": len(tts_starts),
        "n_tts_ends": len(tts_ends),
        "tts_utterance_ids": [e["utterance_id"] for _, e in tts_starts],
        "utterance_audio_s": cum_durations_s,
        "total_audio_s": total_audio_s,
        "translate_ms": next((e.get("translate_ms") for _, e in latency_events if "translate_ms" in e), None),
    })

out_path = ROOT / f"_measure_pipeline_{LABEL}.json"
out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[pipeline] wrote {out_path}", flush=True)

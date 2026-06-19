"""Step 1 verification for stream-translate-tts-pipeline plan.

Verifies NLLBEngine.translate_stream (queue+thread refactor) end-to-end:

  (a) Tokens still arrive incrementally (spread out in time), same as raw
      CT2 generate_tokens confirmed in Step 0.
  (b) _INFER_LOCK is released as soon as CT2 decode finishes, NOT held while
      the consumer drains the queue. Demonstrated by running a deliberately
      SLOW consumer (sleep between next() calls) and probing the lock from a
      second thread -- the probe should acquire the lock long before the slow
      consumer finishes iterating.

Usage (run from X:/smartgen):
    .venv/Scripts/python.exe _measure_step1_nllb_engine.py

Writes _measure_step1_nllb_engine.json with results.
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

ROOT = Path(__file__).resolve().parent

from server.translate.engines.nllb_engine import NLLBEngine  # noqa: E402

# Same 5 sentences as Step 0 (no place/glossary terms -> non-masked path).
SENTENCES = [
    ("s1_short", "Xin chào, hôm nay trời rất đẹp."),
    ("s2_medium", "Tôi muốn đặt một bàn cho bốn người vào lúc bảy giờ tối nay."),
    ("s3_long", "Sau khi ăn sáng xong, chúng tôi quyết định đi dạo quanh công viên gần nhà."),
    ("s4_longer", "Mặc dù trời mưa rất to nhưng anh ấy vẫn quyết định đi làm đúng giờ như mọi ngày."),
    ("s5_30w_2commas",
     "Sáng nay tôi thức dậy sớm, chuẩn bị đồ ăn sáng cho cả nhà, "
     "sau đó đưa con đi học rồi mới quay về nhà để bắt đầu công việc của mình."),
]

print("[step1] loading NLLBEngine ...", flush=True)
engine = NLLBEngine(device="auto")
engine._ensure_loaded()

results = {"part_a_incremental": [], "part_b_lock_probe": None}

# --- Part (a): incremental arrival through NLLBEngine.translate_stream ---
print("\n[step1] === Part (a): incremental arrival via NLLBEngine.translate_stream ===", flush=True)
for key, text in SENTENCES:
    print(f"\n[step1] === {key} ({len(text.split())} words) === {text!r}", flush=True)
    tokens: list[str] = []
    times: list[float] = []
    t_start = time.monotonic()
    for tok in engine.translate_stream(text, src_lang="vie_Latn", tgt_lang="eng_Latn"):
        now = time.monotonic()
        tokens.append(tok)
        times.append(now - t_start)
    t_total = time.monotonic() - t_start

    deltas = [times[i] - times[i - 1] for i in range(1, len(times))]
    out_text = "".join(tokens)
    print(f"[step1]   -> {out_text!r}", flush=True)
    print(f"[step1]   tokens={len(tokens)} total={t_total*1000:.1f}ms "
          f"first_token={times[0]*1000:.1f}ms last_token={times[-1]*1000:.1f}ms", flush=True)
    if deltas:
        avg_d = sum(deltas) / len(deltas)
        max_d = max(deltas)
        print(f"[step1]   inter-token deltas: avg={avg_d*1000:.2f}ms max={max_d*1000:.2f}ms "
              f"min={min(deltas)*1000:.2f}ms", flush=True)
    print("[step1]   per-token (ms from start): " +
          ", ".join(f"{t*1000:.1f}" for t in times), flush=True)

    results["part_a_incremental"].append({
        "key": key,
        "text": text,
        "out_text": out_text,
        "n_tokens": len(tokens),
        "total_ms": t_total * 1000,
        "token_times_ms": [t * 1000 for t in times],
    })

# --- Part (b): lock-release-independent-of-consumer-pace probe ---
print("\n[step1] === Part (b): _INFER_LOCK release vs slow consumer ===", flush=True)
PROBE_KEY, PROBE_TEXT = SENTENCES[2]  # s3_long
SLOW_SLEEP_S = 0.05  # 50ms artificial delay per token in the consumer

probe_result: dict[str, float] = {}


def _probe_lock(t_start: float) -> None:
    """Poll _INFER_LOCK.acquire(blocking=False) until it succeeds; record elapsed time."""
    while True:
        got = NLLBEngine._INFER_LOCK.acquire(blocking=False)
        if got:
            probe_result["lock_free_at_ms"] = (time.monotonic() - t_start) * 1000
            NLLBEngine._INFER_LOCK.release()
            return
        time.sleep(0.001)


print(f"[step1] sentence={PROBE_TEXT!r} slow_consumer_sleep={SLOW_SLEEP_S*1000:.0f}ms/token", flush=True)

t_start = time.monotonic()
probe_thread = threading.Thread(target=_probe_lock, args=(t_start,), daemon=True)

n_tokens = 0
first_token_ms = None
last_token_ms = None
gen = engine.translate_stream(PROBE_TEXT, src_lang="vie_Latn", tgt_lang="eng_Latn")
for tok in gen:
    now_ms = (time.monotonic() - t_start) * 1000
    if n_tokens == 0:
        first_token_ms = now_ms
        # Start the lock probe right after the first token is received --
        # by this point the producer thread should already hold the lock.
        probe_thread.start()
    n_tokens += 1
    last_token_ms = now_ms
    time.sleep(SLOW_SLEEP_S)  # simulate slow consumer (e.g. WS send + cụm logic)

consumer_done_ms = (time.monotonic() - t_start) * 1000
probe_thread.join(timeout=5)

lock_free_at_ms = probe_result.get("lock_free_at_ms")
print(f"[step1]   n_tokens={n_tokens} first_token={first_token_ms:.1f}ms "
      f"last_token={last_token_ms:.1f}ms consumer_done={consumer_done_ms:.1f}ms", flush=True)
print(f"[step1]   lock_free_at={lock_free_at_ms:.1f}ms "
      f"(consumer_done - lock_free = {consumer_done_ms - lock_free_at_ms:.1f}ms slack)", flush=True)

lock_released_before_consumer_done = lock_free_at_ms is not None and lock_free_at_ms < consumer_done_ms
print(f"[step1]   PASS: lock released before slow consumer finished = "
      f"{lock_released_before_consumer_done}", flush=True)

results["part_b_lock_probe"] = {
    "sentence": PROBE_TEXT,
    "slow_sleep_ms": SLOW_SLEEP_S * 1000,
    "n_tokens": n_tokens,
    "first_token_ms": first_token_ms,
    "last_token_ms": last_token_ms,
    "consumer_done_ms": consumer_done_ms,
    "lock_free_at_ms": lock_free_at_ms,
    "lock_released_before_consumer_done": lock_released_before_consumer_done,
}

out_path = ROOT / "_measure_step1_nllb_engine.json"
out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[step1] wrote {out_path}", flush=True)

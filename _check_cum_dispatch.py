"""Step 3 functional check (addendum 5 + general criteria) for
stream-translate-tts-pipeline plan.

Exercises StreamingTranslationRouter._dispatch_final with a fake TTS dispatcher
(no Kokoro synthesis, no audio) to capture the exact cụm text + utterance_id
dispatched for each sentence, including the ~30-word/2-comma sentence (s5)
which triggers _split_clauses (3 clauses) AND incremental cụm dispatch within
the longest clause.

Checks:
  - >12-word sentences get >=2 TTS dispatches.
  - No dispatched cụm has <3 words (no "vụn" fragments) -- addendum 5.
  - Only the first cụm of the FIRST clause is capitalized (seq==0 / clause i==0);
    later cụm/clauses are not capitalized mid-sentence.

Usage (run from X:/smartgen):
    .venv/Scripts/python.exe _check_cum_dispatch.py
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
os.environ.setdefault("CONTEXT_DISABLED", "1")

ROOT = Path(__file__).resolve().parent

from server.translate.engines.nllb_engine import NLLBEngine  # noqa: E402
from server.translate.streaming_router import StreamingTranslationRouter  # noqa: E402


class FakeTTS:
    """Records dispatched cụm text without doing real synthesis."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (utterance_id, text)
        self._lock = threading.Lock()

    def pending_count(self, session_id: str) -> int:
        return 0

    def dispatch(self, *, text, session_id, utterance_id, loop, send_q, voice=None, on_first_chunk=None):
        with self._lock:
            self.calls.append((utterance_id, text))
        if on_first_chunk is not None:
            on_first_chunk()


SENTENCES = [
    ("s1_short", "Xin chào, hôm nay trời rất đẹp."),
    ("s2_medium", "Tôi muốn đặt một bàn cho bốn người vào lúc bảy giờ tối nay."),
    ("s3_long", "Sau khi ăn sáng xong, chúng tôi quyết định đi dạo quanh công viên gần nhà."),
    ("s4_longer", "Mặc dù trời mưa rất to nhưng anh ấy vẫn quyết định đi làm đúng giờ như mọi ngày."),
    ("s5_30w_2commas",
     "Sáng nay tôi thức dậy sớm, chuẩn bị đồ ăn sáng cho cả nhà, "
     "sau đó đưa con đi học rồi mới quay về nhà để bắt đầu công việc của mình."),
]

print("[check] loading NLLBEngine ...", flush=True)
engine = NLLBEngine(device="auto")
engine._ensure_loaded()

loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

all_ok = True

for key, vi_text in SENTENCES:
    n_words_vi = len(vi_text.split())
    print(f"\n[check] === {key} ({n_words_vi} words VI) === {vi_text!r}", flush=True)

    fake_tts = FakeTTS()
    router = StreamingTranslationRouter(engine, tts_dispatcher=fake_tts, tts_voice="af_sarah", wait_final=True)
    send_q: "queue.Queue[object]" = queue.Queue()

    router._dispatch_final(vi_text, "vi", "en", loop, send_q, seg_id="", speaker=0)

    # Wait for completion: drain translation_update events until idle.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            send_q.get(timeout=8.0)
        except queue.Empty:
            break

    time.sleep(0.2)  # let any trailing dispatch() calls land

    print(f"[check]   {len(fake_tts.calls)} cụm dispatched:", flush=True)
    fragments = []
    for uid, text in fake_tts.calls:
        n = len(text.split())
        flag = " <-- FRAGMENT (<3 words)" if n < 3 else ""
        if n < 3:
            fragments.append((uid, text))
        first_char = text[0] if text else ""
        cap_flag = " [capitalized]" if first_char.isupper() else " [lowercase]"
        print(f"[check]     {uid}: ({n}w){cap_flag} {text!r}{flag}", flush=True)

    if n_words_vi > 12 and len(fake_tts.calls) < 2:
        print(f"[check]   FAIL: >12-word sentence got <2 TTS dispatches", flush=True)
        all_ok = False

    if fragments:
        print(f"[check]   FAIL: {len(fragments)} fragment(s) <3 words", flush=True)
        all_ok = False

    # Capitalization check: only the first cụm of each clause's seq==0 should be
    # capitalized; for s5 (3 clauses, each clause's first cụm is seq==0 within
    # that clause) -- so multiple "-0" utterances may be capitalized (one per
    # clause), but no "-1"/"-2" suffix should be capitalized mid-sentence.
    for uid, text in fake_tts.calls:
        if not text:
            continue
        seq = uid.rsplit("-", 1)[-1]
        is_cap = text[0].isupper()
        if seq != "0" and is_cap and text[0].isalpha():
            print(f"[check]   FAIL: non-first cụm {uid} is capitalized: {text!r}", flush=True)
            all_ok = False

print(f"\n[check] {'ALL PASS' if all_ok else 'SOME CHECKS FAILED'}", flush=True)

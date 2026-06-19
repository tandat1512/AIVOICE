"""Step 0 (gate) for stream-translate-tts-pipeline plan.

Confirms whether ctranslate2.Translator.generate_tokens (wrapped by
StreamingTranslator.generate_stream) yields tokens incrementally — i.e. spread
out in time as the model decodes — or whether the whole sequence is produced
in one batch and handed back near-instantly.

This bypasses NLLBEngine entirely (no masking, no queue/lock changes) — it
calls server.translate_legacy.StreamingTranslator.generate_stream directly,
which is the raw CT2 generator.

Usage (run from X:/smartgen):
    .venv/Scripts/python.exe _measure_ct2_stream.py

Writes _measure_ct2_stream.json with per-sentence token timestamps.
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

ROOT = Path(__file__).resolve().parent

from server.translate_legacy import StreamingTranslator  # noqa: E402

# 5 sample sentences, increasing length, no place/glossary terms (raw CT2 test).
# #5 doubles as the addendum-5 prep sentence: ~28 words, 2 commas.
SENTENCES = [
    ("s1_short", "Xin chào, hôm nay trời rất đẹp."),
    ("s2_medium", "Tôi muốn đặt một bàn cho bốn người vào lúc bảy giờ tối nay."),
    ("s3_long", "Sau khi ăn sáng xong, chúng tôi quyết định đi dạo quanh công viên gần nhà."),
    ("s4_longer", "Mặc dù trời mưa rất to nhưng anh ấy vẫn quyết định đi làm đúng giờ như mọi ngày."),
    ("s5_30w_2commas",
     "Sáng nay tôi thức dậy sớm, chuẩn bị đồ ăn sáng cho cả nhà, "
     "sau đó đưa con đi học rồi mới quay về nhà để bắt đầu công việc của mình."),
]

print("[step0] loading StreamingTranslator (NLLB-200 distilled 600M, CT2) ...", flush=True)
translator = StreamingTranslator(device="auto")

results = []
for key, text in SENTENCES:
    print(f"\n[step0] === {key} ({len(text.split())} words) === {text!r}", flush=True)
    tokens: list[str] = []
    times: list[float] = []
    t_start = time.monotonic()
    for tok in translator.generate_stream(text, src_lang="vie_Latn", tgt_lang="eng_Latn"):
        now = time.monotonic()
        tokens.append(tok)
        times.append(now - t_start)
    t_total = time.monotonic() - t_start

    deltas = [times[i] - times[i - 1] for i in range(1, len(times))]
    out_text = "".join(tokens)
    print(f"[step0]   -> {out_text!r}", flush=True)
    print(f"[step0]   tokens={len(tokens)} total={t_total*1000:.1f}ms "
          f"first_token={times[0]*1000:.1f}ms last_token={times[-1]*1000:.1f}ms", flush=True)
    if deltas:
        avg_d = sum(deltas) / len(deltas)
        max_d = max(deltas)
        print(f"[step0]   inter-token deltas: avg={avg_d*1000:.2f}ms max={max_d*1000:.2f}ms "
              f"min={min(deltas)*1000:.2f}ms", flush=True)
    print("[step0]   per-token (ms from start): " +
          ", ".join(f"{t*1000:.1f}" for t in times), flush=True)

    results.append({
        "key": key,
        "text": text,
        "out_text": out_text,
        "n_tokens": len(tokens),
        "total_ms": t_total * 1000,
        "token_times_ms": [t * 1000 for t in times],
        "tokens": tokens,
    })

out_path = ROOT / "_measure_ct2_stream.json"
out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[step0] wrote {out_path}", flush=True)

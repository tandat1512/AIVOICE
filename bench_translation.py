"""Translation speed benchmark: NLLB-200 vs MarianMT.

Measures first-token latency and tokens/sec for both engines on a
fixed set of Vietnamese test sentences. Run from the project root:

    python bench_translation.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent / "server"))

TEST_SENTENCES = [
    "tôi muốn đặt một cái phòng cho hai người",
    "anh ơi cho tôi hỏi giờ này có xe buýt không",
    "hôm nay thời tiết đẹp quá tôi muốn đi dạo",
    "chị có thể giúp tôi tìm đường đến bệnh viện không",
    "sản phẩm này có bảo hành bao lâu và giá bao nhiêu",
    "tôi cần đặt vé máy bay từ hà nội đi thành phố hồ chí minh vào ngày mười lăm tháng này",
]


def bench_engine(name: str, engine, sentences: list[str]) -> dict:
    results = []
    for sent in sentences:
        t0 = time.perf_counter()
        first_token_ms = None
        tokens = []
        for tok in engine.translate_stream(sent, "vie_Latn", "eng_Latn"):
            elapsed = (time.perf_counter() - t0) * 1000
            if first_token_ms is None:
                first_token_ms = elapsed
            tokens.append(tok)
        total_ms = (time.perf_counter() - t0) * 1000
        translation = "".join(tokens).strip()
        tps = len(tokens) / (total_ms / 1000) if total_ms > 0 else 0
        results.append({
            "sent": sent[:50],
            "translation": translation[:60],
            "first_token_ms": round(first_token_ms or 0),
            "total_ms": round(total_ms),
            "tokens": len(tokens),
            "tok_per_sec": round(tps, 1),
        })

    avg_first = sum(r["first_token_ms"] for r in results) / len(results)
    avg_total = sum(r["total_ms"] for r in results) / len(results)
    avg_tps = sum(r["tok_per_sec"] for r in results) / len(results)

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    for r in results:
        print(f"  [{r['first_token_ms']:4d}ms 1st | {r['total_ms']:5d}ms total | {r['tok_per_sec']:5.1f} tok/s]")
        print(f"    VI: {r['sent']}")
        print(f"    EN: {r['translation']}")
    print(f"\n  AVG first-token: {avg_first:.0f}ms | AVG total: {avg_total:.0f}ms | AVG tok/s: {avg_tps:.1f}")

    return {"avg_first_ms": avg_first, "avg_total_ms": avg_total, "avg_tps": avg_tps}


def main():
    print("Loading engines (first load converts/caches models)...\n")

    # ── NLLB-200 ────────────────────────────────────────────────────────────────
    print("[1/2] Loading NLLB-200 distilled 600M...")
    t0 = time.perf_counter()
    from translate_legacy import StreamingTranslator
    nllb = StreamingTranslator(device="cpu")
    # warm-up (forces lazy load)
    _ = list(nllb.generate_stream("xin chào", "vie_Latn", "eng_Latn"))
    nllb_load = (time.perf_counter() - t0) * 1000
    print(f"    loaded in {nllb_load:.0f}ms")

    class NLLBWrapper:
        def translate_stream(self, text, src, tgt):
            return nllb.generate_stream(text, src_lang=src, tgt_lang=tgt)

    nllb_stats = bench_engine("NLLB-200 distilled 600M (CT2 int8)", NLLBWrapper(), TEST_SENTENCES)

    # ── MarianMT ─────────────────────────────────────────────────────────────────
    print("\n[2/2] Loading MarianMT opus-mt-vi-en...")
    t0 = time.perf_counter()
    from translate.engines.marian_engine import MarianEngine
    marian = MarianEngine(device="cpu")
    _ = list(marian.translate_stream("xin chào"))
    marian_load = (time.perf_counter() - t0) * 1000
    print(f"    loaded in {marian_load:.0f}ms")

    marian_stats = bench_engine("MarianMT opus-mt-vi-en (CT2 int8)", marian, TEST_SENTENCES)

    # ── Summary ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  COMPARISON SUMMARY")
    print(f"{'='*60}")
    speedup_first = nllb_stats["avg_first_ms"] / max(marian_stats["avg_first_ms"], 1)
    speedup_tps = marian_stats["avg_tps"] / max(nllb_stats["avg_tps"], 1)
    print(f"  First-token:  NLLB {nllb_stats['avg_first_ms']:.0f}ms  vs  Marian {marian_stats['avg_first_ms']:.0f}ms  ({speedup_first:.1f}x faster)")
    print(f"  Throughput:   NLLB {nllb_stats['avg_tps']:.1f} tok/s  vs  Marian {marian_stats['avg_tps']:.1f} tok/s  ({speedup_tps:.1f}x faster)")

    rec = "MarianMT" if marian_stats["avg_first_ms"] < nllb_stats["avg_first_ms"] * 0.7 else "NLLB-200"
    print(f"\n  RECOMMENDATION: {rec} (lower first-token latency wins for streaming UX)")
    print(f"  To switch, change engine in server/main.py:")
    print(f"    from translate.engines.marian_engine import MarianEngine")
    print(f"    engine = MarianEngine(device='auto')")


if __name__ == "__main__":
    main()

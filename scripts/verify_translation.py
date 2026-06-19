"""Translation accuracy + latency verification harness.

Runs a fixed Vietnamese test set (including the real failure cases observed in
production logs) through the available MT engines, checks entity/pronoun
assertions, and prints a side-by-side comparison with per-engine latency.

Use this before switching the default TRANSLATE_BACKEND — it makes the
accuracy/latency trade-off explicit instead of guessed.

Usage (from repo root):
    python -m scripts.verify_translation            # Marian only (no download)
    python -m scripts.verify_translation --nllb     # also test NLLB-600M
                                                     # (first run downloads ~2.4GB)
"""

from __future__ import annotations

import argparse
import sys
import time

# Vietnamese console output is UTF-8; reconfigure so diacritics don't crash on cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from server.translate.vi_preprocessor import preprocess_vi


# Each case: raw Vietnamese, substrings that MUST appear (case-insensitive) in the
# English output, and substrings that MUST NOT appear (the observed wrong words).
_TEST_SET: tuple[dict, ...] = (
    {"vi": "mình là juli",
     "must": ["juli"], "must_not": ["everyone"]},
    {"vi": "mình tên là nguyễn tấn lợi",
     "must": [], "must_not": []},
    {"vi": "mình đến từ gia lai",
     "must": ["gia lai"], "must_not": ["future"]},
    {"vi": "em ở tây ninh",
     "must": ["tây ninh"], "must_not": ["ocean"]},
    {"vi": "mình đến từ bình dương",
     "must": ["bình dương"], "must_not": []},
    {"vi": "đến từ thành phố hồ chí minh",
     "must": ["chí minh"], "must_not": []},
    {"vi": "mình sinh năm hai lẻ hai",
     "must": ["born", "2002"], "must_not": []},
    {"vi": "tôi có hai mươi ba người bạn",
     "must": ["23"], "must_not": []},
    {"vi": "tui ở vũng tàu",
     "must": ["vũng tàu"], "must_not": []},
    {"vi": "hello mọi người mình là đại đến từ nha trang",
     "must": ["nha trang"], "must_not": []},
    {"vi": "anh hai ơi anh khỏe không",
     "must": [], "must_not": []},
    # ── Glossary masking test cases ──────────────────────────────────────────
    # These verify that mask_glossary/unmask_glossary preserves proper nouns.
    {"vi": "gửi về cho duy nhé",
     "must": ["Duy"], "must_not": ["reader", "the Duy"]},
    {"vi": "tải zalo về đi",
     "must": ["Zalo"], "must_not": []},
    {"vi": "cô ấy nhắn tin qua zalo cho duy",
     "must": ["Zalo", "Duy"], "must_not": ["reader"]},
    {"vi": "câu chuyện về duyên âm rất huyền bí",
     "must": ["Duyên Âm"], "must_not": []},
)


def _check(english: str, case: dict) -> tuple[bool, list[str]]:
    low = english.lower()
    problems: list[str] = []
    for token in case["must"]:
        if token.lower() not in low:
            problems.append(f"missing '{token}'")
    for token in case["must_not"]:
        if token.lower() in low:
            problems.append(f"has wrong '{token}'")
    return (not problems), problems


def _run_engine(name: str, engine) -> None:
    print(f"\n{'='*78}\n  ENGINE: {name}\n{'='*78}")
    passed = 0
    total_ms = 0.0
    for case in _TEST_SET:
        vi = case["vi"]
        t0 = time.monotonic()
        english = "".join(engine.translate_stream(vi, "vie_Latn", "eng_Latn")).strip()
        ms = (time.monotonic() - t0) * 1000
        total_ms += ms
        ok, problems = _check(english, case)
        passed += ok
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {ms:6.0f}ms  vi: {vi}")
        print(f"           preproc: {preprocess_vi(vi)}")
        print(f"           en:      {english}")
        if problems:
            print(f"           ⚠ {', '.join(problems)}")
    n = len(_TEST_SET)
    print(f"\n  {name}: {passed}/{n} passed · avg {total_ms / n:.0f}ms/sentence")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nllb", action="store_true", help="also test NLLB-600M (downloads on first run)")
    ap.add_argument("--marian", action="store_true", help="test Marian (default if no engine flag given)")
    args = ap.parse_args()

    run_marian = args.marian or not args.nllb
    run_nllb = args.nllb

    if run_marian:
        from server.translate.engines.marian_engine import MarianEngine
        _run_engine("Marian opus-mt-vi-en (77M)", MarianEngine())

    if run_nllb:
        from server.translate.engines.nllb_engine import NLLBEngine
        _run_engine("NLLB-200 distilled (600M)", NLLBEngine())


if __name__ == "__main__":
    main()

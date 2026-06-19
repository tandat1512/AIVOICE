"""Spoken Vietnamese numbers → digits, for the MT source text.

STT emits numbers as words ("hai mươi ba"); small MT models then mangle them
("two and two"). Converting to digits ("23") before translation fixes this.

False-positive safety is the hard part — many number words are also common
non-numeric words ("không"=not, "năm"=year/name, "ba"=father, "tư"=think,
"mốt"=day-after-tomorrow). Two guards keep conversion safe:

  1. Only convert a run of 2+ adjacent number words (a lone "năm"/"không"/"ba"
     is never touched — that is where the false friends live).
  2. The run must contain a structural word (mười/mươi/trăm/nghìn/lẻ/lăm/tư/mốt);
     a bare digit pair like "hai ba" (e.g. the street "Hai Bà") is left alone.

Plus a dedicated idiom for 2000s birth years: "hai lẻ X" → "200X" (the
conversational form of 2002–2009), applied before the general pass.
"""

from __future__ import annotations

import re
import unicodedata

# Base digits (0-9) and "mười" (10).
_DIGITS: dict[str, int] = {
    "không": 0, "một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5,
    "sáu": 6, "bảy": 7, "tám": 8, "chín": 9, "mười": 10,
}
# Compound-position specials (valid after mười/mươi).
_SPECIAL: dict[str, int] = {"lăm": 5, "tư": 4, "mốt": 1}
# Scale words.
_SCALES: dict[str, int] = {
    "trăm": 100, "nghìn": 1000, "ngàn": 1000, "triệu": 1_000_000,
    "tỷ": 1_000_000_000, "tỉ": 1_000_000_000,
}
_TENS = "mươi"          # "hai mươi" → 2*10
_ZERO_FILL = {"lẻ", "linh"}

# Words that signal a real number (not a bare digit pair). A run without any of
# these is too ambiguous (names, kinship) and is skipped.
_STRUCTURAL = {"mười", "mươi", "trăm", "nghìn", "ngàn", "triệu", "tỷ", "tỉ",
               "lẻ", "linh", "lăm", "tư", "mốt"}

_ALL_NUM_WORDS = set(_DIGITS) | set(_SPECIAL) | set(_SCALES) | {_TENS} | _ZERO_FILL

_NUM = "|".join(sorted(_ALL_NUM_WORDS, key=len, reverse=True))
# A run of 2+ number words separated by single spaces.
_RUN_RE = re.compile(rf"\b(?:{_NUM})(?:\s+(?:{_NUM}))+\b", re.IGNORECASE)
# 2000s birth-year idiom: "hai lẻ X" / "hai linh X".
_YEAR_200X_RE = re.compile(
    r"\bhai\s+(?:lẻ|linh)\s+(không|một|hai|ba|bốn|năm|sáu|bảy|tám|chín)\b",
    re.IGNORECASE,
)


def _run_to_int(tokens: list[str]) -> int | None:
    """Parse a list of lowercase Vietnamese number words to an int, or None."""
    result = 0       # completed scale groups (≥ nghìn)
    current = 0      # current group < 1000
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        if t in _ZERO_FILL:            # "lẻ/linh" → zero tens, skip
            i += 1
            continue
        if t in _SCALES and t != "trăm":
            scale = _SCALES[t]
            result += (current or 1) * scale
            current = 0
            i += 1
            continue
        if t in _DIGITS:
            d = _DIGITS[t]
            nxt = tokens[i + 1] if i + 1 < n else None
            if t == "mười":            # 10, optionally + unit
                current += 10
                i += 1
                continue
            if nxt == "trăm":
                current += d * 100
                i += 2
                continue
            if nxt == _TENS:           # "hai mươi" → 20 (+ optional unit)
                current += d * 10
                i += 2
                continue
            if nxt in _ZERO_FILL:      # "hai lẻ …" → d is the hundreds
                current += d * 100
                i += 1
                continue
            current += d               # bare unit
            i += 1
            continue
        if t in _SPECIAL:              # lăm/tư/mốt as trailing unit
            current += _SPECIAL[t]
            i += 1
            continue
        return None                    # non-number token — shouldn't happen
    return result + current


def _convert_run(m: re.Match) -> str:
    tokens = m.group(0).lower().split()
    if not any(tok in _STRUCTURAL for tok in tokens):
        return m.group(0)              # bare digit pair → leave alone
    value = _run_to_int(tokens)
    return str(value) if value is not None else m.group(0)


def convert_spoken_numbers(text: str) -> str:
    """Replace spoken Vietnamese number runs with digit strings. Conservative:
    only multi-word runs containing a structural number word are converted."""
    if not text:
        return text
    text = unicodedata.normalize("NFC", text)
    text = _YEAR_200X_RE.sub(lambda m: "200" + str(_DIGITS[m.group(1).lower()]), text)
    text = _RUN_RE.sub(_convert_run, text)
    return text

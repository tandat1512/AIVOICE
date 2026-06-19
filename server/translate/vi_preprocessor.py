"""Vietnamese source-side preprocessing before translation.

Deterministic, model-agnostic normalization that fixes the most common failure
modes of small vi→en MT models on conversational speech:

  1. Proper-noun casing — STT emits lowercase ("gia lai"); MT then translates it
     as common words ("the future"). Title-casing known place names makes the
     model treat them as named entities and keep them intact.
  2. Southern-dialect pronouns — "mình / tui" used as first person are read by
     standard-corpus MT as "oneself / everyone". Normalizing the clear cases to
     "tôi" yields correct "I / my" output.

Applied at the engine boundary for src=Vietnamese only. No latency cost.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .vi_numbers import convert_spoken_numbers

# ── Place names (63 provinces + major cities / common districts) ───────────────
# Canonical Title-Case forms. Matched case-insensitively against the source text
# and rewritten to the canonical form so the MT model keeps them as entities.
_PLACE_NAMES: tuple[str, ...] = (
    # Direct-controlled cities
    "Hà Nội", "Hồ Chí Minh", "Hải Phòng", "Đà Nẵng", "Cần Thơ",
    # Provinces
    "An Giang", "Bà Rịa Vũng Tàu", "Bắc Giang", "Bắc Kạn", "Bạc Liêu",
    "Bắc Ninh", "Bến Tre", "Bình Định", "Bình Dương", "Bình Phước",
    "Bình Thuận", "Cà Mau", "Cao Bằng", "Đắk Lắk", "Đắk Nông",
    "Điện Biên", "Đồng Nai", "Đồng Tháp", "Gia Lai", "Hà Giang",
    "Hà Nam", "Hà Tĩnh", "Hải Dương", "Hậu Giang", "Hòa Bình",
    "Hưng Yên", "Khánh Hòa", "Kiên Giang", "Kon Tum", "Lai Châu",
    "Lâm Đồng", "Lạng Sơn", "Lào Cai", "Long An", "Nam Định",
    "Nghệ An", "Ninh Bình", "Ninh Thuận", "Phú Thọ", "Phú Yên",
    "Quảng Bình", "Quảng Nam", "Quảng Ngãi", "Quảng Ninh", "Quảng Trị",
    "Sóc Trăng", "Sơn La", "Tây Ninh", "Thái Bình", "Thái Nguyên",
    "Thanh Hóa", "Thừa Thiên Huế", "Tiền Giang", "Trà Vinh", "Tuyên Quang",
    "Vĩnh Long", "Vĩnh Phúc", "Yên Bái",
    # Common shorter forms / cities frequently spoken
    "Vũng Tàu", "Huế", "Nha Trang", "Đà Lạt", "Buôn Ma Thuột",
    "Sài Gòn", "Biên Hòa", "Thủ Đức",
)

# Build one alternation, longest first, so "Thành Phố Hồ Chí Minh" / "Hồ Chí Minh"
# match before a bare substring, and multi-word names match as a unit.
_PLACES_SORTED = sorted(_PLACE_NAMES, key=lambda s: -len(s))
_PLACE_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _PLACES_SORTED) + r")\b",
    re.IGNORECASE,
)
_PLACE_CANON = {p.lower(): p for p in _PLACE_NAMES}

# ── Southern-dialect first-person pronoun normalization ────────────────────────
# Only rewrite "mình" when it is clearly the subject (followed by a verb/marker
# that makes it first-person), never the bare word (which can mean "we/each other").
_MINH_FOLLOWERS = (
    "là", "tên", "đến", "ở", "sinh", "năm", "thích", "muốn", "có",
    "đang", "sẽ", "đã", "cũng", "không", "chưa", "vẫn", "rất",
)
_MINH_RE = re.compile(
    r"\bmình\b(?=\s+(?:" + "|".join(_MINH_FOLLOWERS) + r")\b)",
    re.IGNORECASE,
)
# "tui" is unambiguously first-person "tôi" in Southern speech.
_TUI_RE = re.compile(r"\btui\b", re.IGNORECASE)

# ── Homophone / context disambiguation ────────────────────────────────────────
# "kiếm" before search-goal verbs means "to find/look for", not "sword".
# Normalizing to "tìm" removes the homophone ambiguity for the MT model.
_KIEM_SEARCH_RE = re.compile(
    r"\bkiếm\b(?=\s+(?:bắt|thấy|được|ra|cho|về|lại)\b)",
    re.IGNORECASE,
)
# "dằn" before tableware means "slam/bang" — stronger verb is clearer for MT.
_DAN_DISH_RE = re.compile(r"\bdằn\b(?=\s+(?:mâm|chén|dĩa|bát|tô)\b)", re.IGNORECASE)


def _fix_places(text: str) -> str:
    return _PLACE_RE.sub(lambda m: _PLACE_CANON[m.group(0).lower()], text)


def _fix_pronouns(text: str) -> str:
    text = _MINH_RE.sub("tôi", text)
    text = _TUI_RE.sub("tôi", text)
    return text


def _fix_homophones(text: str) -> str:
    text = _KIEM_SEARCH_RE.sub("tìm", text)
    text = _DAN_DISH_RE.sub("đập", text)
    return text


def preprocess_vi(text: str) -> str:
    """Normalize Vietnamese source text before MT. Idempotent and safe to call
    on every chunk. Returns the input unchanged if empty."""
    if not text or not text.strip():
        return text
    text = unicodedata.normalize("NFC", text)
    text = _fix_places(text)
    text = _fix_pronouns(text)
    text = _fix_homophones(text)
    text = convert_spoken_numbers(text)
    return text


# ── Entity masking (do-not-translate protection) ───────────────────────────────
# Even after title-casing, a weak MT model still translates place names as common
# words ("Tây Ninh" → "Western Europe"). The robust fix is the production-MT
# technique: replace each known entity with a sentinel the model copies verbatim,
# translate, then restore. Sentinel format "x{i}x" was verified to round-trip
# through the Marian/CT2 decoder unchanged (unlike numbers, which get comma-grouped).

def _sentinel(i: int) -> str:
    return f"x{i}x"


def _gloss_sentinel(i: int) -> str:
    return f"g{i}g"


# ── Glossary masking (user-configurable proper nouns) ─────────────────────────
# Loaded from <repo_root>/glossary.txt at import time. Format: lowercase_vi = Canonical
# Multi-word entries are matched before single-word ones (longest first).
_GLOSSARY_FILE = Path(__file__).resolve().parents[2] / "glossary.txt"
_GLOSSARY: dict[str, str] = {}
_GLOSSARY_RE: re.Pattern | None = None


def _load_glossary(path: Path) -> None:
    global _GLOSSARY, _GLOSSARY_RE
    entries: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                k = key.strip().lower()
                v = val.strip()
                if k and v:
                    entries[k] = v
    except FileNotFoundError:
        return
    if not entries:
        return
    _GLOSSARY = entries
    sorted_keys = sorted(_GLOSSARY.keys(), key=lambda s: -len(s))
    _GLOSSARY_RE = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in sorted_keys) + r")\b",
        re.IGNORECASE,
    )


_load_glossary(_GLOSSARY_FILE)


def mask_glossary(text: str) -> tuple[str, dict[str, str]]:
    """Replace user-configured glossary terms with copy-safe sentinels (g0g, g1g, …).

    Returns (masked_text, mapping) where mapping maps each sentinel back to its
    canonical form. The same term reuses one sentinel. Sentinels don't conflict
    with mask_places (which uses x0x, x1x, …)."""
    if _GLOSSARY_RE is None:
        return text, {}
    mapping: dict[str, str] = {}
    term_to_sentinel: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        canon = _GLOSSARY[m.group(0).lower()]
        sentinel = term_to_sentinel.get(canon)
        if sentinel is None:
            sentinel = _gloss_sentinel(len(term_to_sentinel))
            term_to_sentinel[canon] = sentinel
            mapping[sentinel] = canon
        return sentinel

    masked = _GLOSSARY_RE.sub(repl, text)
    return masked, mapping


def unmask_glossary(text: str, mapping: dict[str, str]) -> str:
    """Restore sentinels produced by mask_glossary back to canonical forms."""
    if not mapping:
        return text
    for sentinel, canon in mapping.items():
        text = re.sub(rf"\b{re.escape(sentinel)}\b", canon, text, flags=re.IGNORECASE)
    return text


def mask_places(text: str) -> tuple[str, dict[str, str]]:
    """Replace known place names with copy-safe sentinels.

    Returns (masked_text, mapping) where mapping maps each sentinel back to its
    canonical place name. The same name reuses one sentinel. Match the canonical
    Title-Case names produced by preprocess_vi (and any-case raw input)."""
    mapping: dict[str, str] = {}
    name_to_sentinel: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        canon = _PLACE_CANON[m.group(0).lower()]
        sentinel = name_to_sentinel.get(canon)
        if sentinel is None:
            sentinel = _sentinel(len(name_to_sentinel))
            name_to_sentinel[canon] = sentinel
            mapping[sentinel] = canon
        return sentinel

    masked = _PLACE_RE.sub(repl, text)
    return masked, mapping


def unmask_places(text: str, mapping: dict[str, str]) -> str:
    """Restore sentinels produced by mask_places back to canonical place names."""
    if not mapping:
        return text
    for sentinel, canon in mapping.items():
        text = re.sub(rf"\b{re.escape(sentinel)}\b", canon, text, flags=re.IGNORECASE)
    return text

"""Rule-based Vietnamese punctuation restorer for STT committed text."""

from __future__ import annotations

import re
import unicodedata

# Words that typically end a statement when they are the last word of a committed chunk
_STATEMENT_ENDERS = frozenset([
    # Conversational closers
    "thôi", "xong", "rồi", "nha", "nhé", "nghen", "nhen",
    "vậy", "đó", "hết", "đây", "à", "ừ", "ừa", "ơ",
    # Multi-word closers
    "vậy thôi", "thôi nha", "thôi nhé", "rồi đó", "vậy đó", "như vậy",
    # Narrative / storytelling endings common in podcasts
    # (single-word enders only fire at ≥3 words, reducing false positives)
    "nè", "luôn", "lắm", "cơ",
    "này", "ấy", "nhau",
])

# Words that typically end a question
_QUESTION_ENDERS = frozenset([
    "không", "hả", "chứ", "phải không", "đúng không",
    "vậy hả", "hay không", "được không", "hả không",
])

# Words that introduce a new clause — insert ',' before them
_CLAUSE_STARTERS = [
    "tuy nhiên", "cho nên", "vì vậy", "vả lại", "thế nhưng",
    "bởi vì", "nhưng mà", "nhưng", "tuy", "dù", "mà",
]

_SENTENCE_END = frozenset([".", "!", "?", "…", "。", "！", "？"])


def _strip_accents_lower(text: str) -> str:
    """Lowercase + strip Vietnamese diacritics to ASCII for matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    # đ/Đ do not decompose via NFKD; map explicitly
    stripped = stripped.replace("đ", "d").replace("Đ", "d")
    return stripped.lower()


# Pre-computed ASCII forms — avoids repeated _strip_accents_lower calls in hot loops
_Q_MULTI = frozenset(_strip_accents_lower(q) for q in _QUESTION_ENDERS if " " in q)
_Q_SINGLE = frozenset(_strip_accents_lower(q) for q in _QUESTION_ENDERS if " " not in q)
_S_MULTI = frozenset(_strip_accents_lower(s) for s in _STATEMENT_ENDERS if " " in s)
_S_SINGLE = frozenset(_strip_accents_lower(s) for s in _STATEMENT_ENDERS if " " not in s)
_Q_ALL = _Q_MULTI | _Q_SINGLE
_S_ALL = _S_MULTI | _S_SINGLE


class VietnamesePunctuator:
    """Inserts commas and periods into raw Vietnamese STT text."""

    def punctuate(self, delta: str, is_commit_boundary: bool = False, short_pause: bool = False) -> str:
        """Return delta with punctuation inserted.

        Args:
            delta: New committed text to punctuate.
            is_commit_boundary: True when silence was long enough to end a sentence.
            short_pause: True when silence was short (breath/phrase break) — appends ','.
        """
        text = delta.strip()
        if not text:
            return ""

        # Already ends with punctuation — don't add more
        if text[-1] in _SENTENCE_END:
            return text

        # Insert commas before clause-starters in the middle of text
        text = self._insert_clause_commas(text)

        if is_commit_boundary:
            text = self._add_sentence_end(text)
        elif short_pause and text[-1] not in _SENTENCE_END and text[-1] != ",":
            text = text + ","

        return text

    def has_sentence_end(self, text: str) -> bool:
        """Return True if text ends with a real sentence-ender.

        Single-word enders are only accepted when the text has ≥3 words, preventing
        false positives on mid-utterance pauses after "không" (negation) or "đây"
        (deictic). Multi-word phrase enders ("phải không") match at ≥2 words.
        """
        words = text.strip().split()
        if len(words) < 2:
            return False
        tail_2 = _strip_accents_lower(" ".join(words[-2:]))
        if tail_2 in _Q_MULTI or tail_2 in _S_MULTI:
            return True
        if len(words) >= 3:
            tail_1 = _strip_accents_lower(words[-1])
            if tail_1 in _Q_SINGLE or tail_1 in _S_SINGLE:
                return True
        return False

    # ── Private ──────────────────────────────────────────────────────────────

    def _insert_clause_commas(self, text: str) -> str:
        for starter in _CLAUSE_STARTERS:
            # e.g. "học xong nhưng chưa về" → "học xong, nhưng chưa về"
            pattern = r"(?<=[^\s,\.!\?])\s+(" + re.escape(starter) + r")\b"
            text = re.sub(pattern, r", \1", text, flags=re.IGNORECASE)
        return text

    def _add_sentence_end(self, text: str) -> str:
        """Append '.' or '?'. Only called after has_sentence_end() returned True."""
        words = text.split()
        if not words:
            return text
        tail_2 = _strip_accents_lower(" ".join(words[-2:])) if len(words) >= 2 else ""
        tail_1 = _strip_accents_lower(words[-1])
        if tail_2 in _Q_ALL or tail_1 in _Q_ALL:
            return text + "?"
        if tail_2 in _S_ALL or tail_1 in _S_ALL:
            return text + "."
        return text + "."

"""Vietnamese profanity filter — replaces strong profanity before translation/TTS."""

from __future__ import annotations

import re

# Common Vietnamese profanity abbreviations and explicit forms.
_VI_PROFANITY_RE = re.compile(
    r'\b(đụ\s*mẹ|đ\.?\s*m\.?|đcm|cc\b|vl\b|đéo|đ\s+mẹ)\b',
    re.IGNORECASE,
)


def filter_profanity(text: str) -> str:
    """Replace Vietnamese profanity with neutral filler before translation."""
    return _VI_PROFANITY_RE.sub('...', text)

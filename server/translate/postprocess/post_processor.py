"""Tầng E: Post-Processor — capitalization, punctuation, number formatting."""

from __future__ import annotations

import re


class PostProcessor:
    """Cleans up translated text for display."""

    def process(self, text: str, tgt_lang: str = "en", capitalize: bool = True) -> str:
        if not text:
            return ""

        result = text.strip()

        # Capitalize first character
        if capitalize and result:
            result = result[0].upper() + result[1:]

        if tgt_lang == "en":
            result = self._fix_english(result)

        return result

    def _fix_english(self, text: str) -> str:
        # Standalone lowercase 'i' → 'I'
        text = re.sub(r"\bi\b", "I", text)
        # Ensure space after commas/periods when followed by a letter
        text = re.sub(r"([.,!?])([A-Za-z])", r"\1 \2", text)
        return text

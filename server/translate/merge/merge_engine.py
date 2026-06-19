"""Tầng D: Merge Engine — reconciles fast-path and quality-path translations."""

from __future__ import annotations

import difflib
from typing import Literal

MergeDecision = Literal["replace", "partial", "keep_fast"]


class MergeEngine:
    """Merges fast-path and quality-path translation outputs using SequenceMatcher."""

    def compute_overlap(self, fast_text: str, quality_text: str) -> float:
        """Return overlap ratio 0.0–1.0 between two translation strings."""
        fast_words = fast_text.lower().split()
        quality_words = quality_text.lower().split()
        if not fast_words and not quality_words:
            return 1.0
        if not fast_words or not quality_words:
            return 0.0
        matcher = difflib.SequenceMatcher(None, fast_words, quality_words, autojunk=False)
        return matcher.ratio()

    def merge(self, fast_text: str, quality_text: str) -> tuple[str, MergeDecision]:
        """Merge fast and quality translations.

        Returns (merged_text, decision) where decision is one of:
          'replace'    — quality used in full (overlap > 0.7)
          'partial'    — common prefix kept, quality suffix appended (overlap 0.4–0.7)
          'keep_fast'  — fast kept unchanged (overlap < 0.4)
        """
        overlap = self.compute_overlap(fast_text, quality_text)

        if overlap > 0.7:
            return quality_text, "replace"

        if overlap >= 0.4:
            merged = self._partial_merge(fast_text, quality_text)
            return merged, "partial"

        return fast_text, "keep_fast"

    def _partial_merge(self, fast_text: str, quality_text: str) -> str:
        fast_words = fast_text.split()
        quality_words = quality_text.split()
        matcher = difflib.SequenceMatcher(None, fast_words, quality_words, autojunk=False)

        # Find the longest common prefix using matching blocks
        common_end_fast = 0
        common_end_quality = 0
        for block in matcher.get_matching_blocks():
            if block.a == common_end_fast and block.b == common_end_quality:
                common_end_fast = block.a + block.size
                common_end_quality = block.b + block.size
            else:
                break

        common_prefix = fast_words[:common_end_fast]
        quality_remainder = quality_words[common_end_quality:]
        merged = common_prefix + quality_remainder
        return " ".join(merged) if merged else quality_text

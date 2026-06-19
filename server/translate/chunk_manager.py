"""Tầng B: Chunk Manager — boundary detection and dispatch policy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

DispatchPath = Literal["fast_only", "both", "quality_only", "skip"]

# Vietnamese words that indicate an incomplete phrase when trailing
_VI_INCOMPLETE_TRAIL = frozenset([
    # Prepositions
    "của", "với", "ở", "tại", "từ", "cho", "đến", "về", "trong", "ngoài",
    "trên", "dưới", "sau", "trước", "giữa", "qua", "theo", "bằng",
    # Subordinate connectors
    "mà", "rằng", "để", "vì", "khi", "nếu", "tuy", "dù", "nhưng", "và",
    "hoặc", "hay", "thì", "là", "như", "hơn", "nhất",
    # Articles/quantifiers that need following noun
    "một", "các", "những", "mọi", "mỗi", "nhiều", "ít",
])


@dataclass
class TranslationChunk:
    chunk_id: str
    text: str
    ready_to_translate: bool
    dispatch_path: DispatchPath
    context_chunks: list[str] = field(default_factory=list)  # preceding chunk_ids for context


class TranslationUnitDetector:
    """Rule-based detection of whether a text segment is ready to translate."""

    def is_translatable_boundary(self, text: str, lang: str = "vi") -> bool:
        """Return True if text ends at a translatable boundary."""
        stripped = text.strip()
        if not stripped:
            return False

        # Sentence-ending punctuation is always a good boundary
        if stripped[-1] in (".", "!", "?", "…", "。", "！", "？"):
            return True

        if lang == "vi":
            return self._check_vi_boundary(stripped)

        # For other languages, default to translatable if non-empty
        return len(stripped.split()) >= 2

    def _check_vi_boundary(self, text: str) -> bool:
        words = text.lower().split()
        if not words:
            return False

        last_word = words[-1].rstrip(".,!?")

        # Trailing incomplete marker → not ready
        if last_word in _VI_INCOMPLETE_TRAIL:
            return False

        # Very short text (single word) → wait for more context
        if len(words) == 1:
            return False

        # Two+ words and no incomplete trailer → translatable
        return True


class DispatchPolicy:
    """Decides which translation path to use for a chunk."""

    def decide(
        self,
        confidence: float,
        is_complex: bool = False,
        is_urgent: bool = True,
    ) -> DispatchPath:
        """Return dispatch path based on confidence, complexity and urgency."""
        if confidence >= 0.9 and not is_complex and is_urgent:
            return "fast_only"
        if confidence >= 0.9 and not is_complex and not is_urgent:
            return "both"
        if confidence >= 0.9 and is_complex and is_urgent:
            return "both"
        if confidence >= 0.9 and is_complex and not is_urgent:
            return "quality_only"
        if confidence < 0.7 and is_urgent:
            return "both"
        # Low confidence, not urgent → skip until more certain
        return "skip"


class ChunkManager:
    """Builds TranslationChunk objects from incoming text segments."""

    def __init__(self) -> None:
        self._detector = TranslationUnitDetector()
        self._policy = DispatchPolicy()

    def make_chunk(
        self,
        text: str,
        lang: str = "vi",
        confidence: float = 0.85,
        is_urgent: bool = True,
        preceding_chunk_ids: list[str] | None = None,
    ) -> TranslationChunk:
        ready = self._detector.is_translatable_boundary(text, lang)
        # Simple heuristic: treat idioms/very long words as complex
        is_complex = any(len(w) > 12 for w in text.split())
        path = self._policy.decide(confidence, is_complex, is_urgent) if ready else "skip"

        return TranslationChunk(
            chunk_id=str(uuid.uuid4())[:8],
            text=text,
            ready_to_translate=ready,
            dispatch_path=path,
            context_chunks=preceding_chunk_ids or [],
        )

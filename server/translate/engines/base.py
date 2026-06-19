"""Abstract base class for translation engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


class BaseEngine(ABC):
    """Abstract translation engine interface."""

    @abstractmethod
    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """Translate text, returning the full translation string."""

    @abstractmethod
    def translate_stream(
        self, text: str, src_lang: str, tgt_lang: str, target_prefix: str = ""
    ) -> Iterator[str]:
        """Translate text, yielding tokens incrementally."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Whether the underlying model is loaded into memory."""

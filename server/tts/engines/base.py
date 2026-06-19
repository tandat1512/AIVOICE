"""BaseTTSEngine — abstract interface for streaming text-to-speech engines.

Engines emit Int16 PCM audio chunks (mono, little-endian). The default
sample rate is 24000 Hz which matches Kokoro-82M's native output.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


SAMPLE_RATE = 24000


class BaseTTSEngine(ABC):
    """Streaming TTS contract.

    Implementations MUST be safe to call from multiple threads after warmup().
    synthesize_stream yields chunks as soon as they are ready so that downstream
    consumers (WebSocket forwarders) can stream audio with low latency.
    """

    sample_rate: int = SAMPLE_RATE

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """True once model weights are resident in memory and warm."""

    @abstractmethod
    def warmup(self) -> None:
        """Load weights + run a dummy synthesis so the first real call is fast."""

    @abstractmethod
    def list_voices(self) -> list[str]:
        """Return the set of voice IDs the engine accepts."""

    @abstractmethod
    def synthesize_stream(self, text: str, voice: str) -> Iterator[bytes]:
        """Yield Int16-PCM mono audio chunks at self.sample_rate.

        Implementations should yield the first chunk as early as possible to
        minimize perceived latency, even if the rest of the utterance is still
        being generated.
        """

    def synthesize(self, text: str, voice: str) -> bytes:
        """Convenience: collect a full utterance into a single bytes buffer."""
        return b"".join(self.synthesize_stream(text, voice))

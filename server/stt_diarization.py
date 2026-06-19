"""Lightweight online speaker diarization for the streaming STT pipeline.

Uses sherpa-onnx's SpeakerEmbeddingExtractor (already a project dependency) to
turn each committed speech segment into a speaker embedding, then assigns a
speaker index by online cosine clustering against running centroids.

Design goals
------------
* **Never break the pipeline.** If sherpa-onnx has no speaker-embedding support,
  or no model is present, the diarizer silently disables itself and every
  segment is attributed to speaker 0 — identical to the pre-diarization behavior.
* **100% local.** No auto-download. The model is looked up on disk only:
    - env ``DIARIZE_MODEL`` (explicit path), or
    - the first ``*.onnx`` under ``models/speaker-embedding/``.
  Disable entirely with ``DIARIZE=0``.

Model
-----
Any sherpa-onnx speaker-embedding ONNX works (3D-Speaker / WeSpeaker). Speaker
embeddings are largely language-agnostic, so a zh/en model identifies VI speakers
fine. Drop one into ``models/speaker-embedding/`` to enable.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

_MODELS_DIR = Path(__file__).resolve().parent.parent / "models" / "speaker-embedding"

# Two segments with cosine similarity >= this are treated as the same speaker.
_SAME_SPEAKER_COS = float(os.environ.get("DIARIZE_THRESHOLD", "0.65"))
# Below this much audio (seconds) an embedding is unreliable — reuse last speaker.
_MIN_SEG_S = 0.6
_MAX_SPEAKERS = 3   # matches the UI's 3 speaker colors; extra voices fold into nearest


def _find_model() -> Optional[str]:
    explicit = os.environ.get("DIARIZE_MODEL", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    if _MODELS_DIR.is_dir():
        for p in sorted(_MODELS_DIR.glob("*.onnx")):
            return str(p)
    return None


class SpeakerDiarizer:
    """Online speaker clustering. Thread-safe; one instance per process is fine.

    ``assign(samples, sample_rate)`` returns a 0-based speaker index, or 0 when
    diarization is unavailable.
    """

    def __init__(self) -> None:
        self._enabled = False
        self._extractor = None
        self._lock = threading.Lock()
        self._centroids: list[np.ndarray] = []   # L2-normalized running means
        self._counts: list[int] = []
        self._last_speaker = 0

        if os.environ.get("DIARIZE", "1") == "0":
            return
        model = _find_model()
        if not model:
            return
        try:
            import sherpa_onnx  # noqa: PLC0415 — optional, lazy

            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=model,
                num_threads=1,
                provider=os.environ.get("ONNX_PROVIDER_SPK", "cpu"),
            )
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            self._enabled = True
            print(f"[Diarize] speaker embeddings enabled: {Path(model).name}", flush=True)
        except Exception as exc:  # noqa: BLE001 — any failure → disabled, never crash
            print(f"[Diarize] disabled ({exc})", flush=True)
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def reset(self) -> None:
        """Forget learned speakers (call on a new session)."""
        with self._lock:
            self._centroids.clear()
            self._counts.clear()
            self._last_speaker = 0

    def _embed(self, samples: np.ndarray, sample_rate: int) -> Optional[np.ndarray]:
        try:
            stream = self._extractor.create_stream()
            stream.accept_waveform(sample_rate=sample_rate, waveform=samples)
            stream.input_finished()
            if not self._extractor.is_ready(stream):
                return None
            emb = np.asarray(self._extractor.compute(stream), dtype=np.float32)
            n = np.linalg.norm(emb)
            return emb / n if n > 1e-9 else None
        except Exception:  # noqa: BLE001 — bad frame → no attribution
            return None

    def assign(self, samples: np.ndarray, sample_rate: int = 16000) -> int:
        """Return a speaker index (0-based) for this segment's audio."""
        if not self._enabled:
            return 0
        if samples is None or len(samples) < int(sample_rate * _MIN_SEG_S):
            return self._last_speaker
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        emb = self._embed(samples, sample_rate)
        if emb is None:
            return self._last_speaker

        with self._lock:
            if not self._centroids:
                self._centroids.append(emb)
                self._counts.append(1)
                self._last_speaker = 0
                return 0

            sims = [float(np.dot(emb, c)) for c in self._centroids]
            best = int(np.argmax(sims))
            if sims[best] >= _SAME_SPEAKER_COS or len(self._centroids) >= _MAX_SPEAKERS:
                # Update the matched centroid with a running mean, then renormalize.
                k = self._counts[best] + 1
                mixed = self._centroids[best] * (self._counts[best] / k) + emb * (1.0 / k)
                nrm = np.linalg.norm(mixed)
                self._centroids[best] = mixed / nrm if nrm > 1e-9 else self._centroids[best]
                self._counts[best] = k
                self._last_speaker = best
                return best

            # New, sufficiently-distinct speaker.
            self._centroids.append(emb)
            self._counts.append(1)
            self._last_speaker = len(self._centroids) - 1
            return self._last_speaker


_singleton: Optional[SpeakerDiarizer] = None
_singleton_lock = threading.Lock()


def get_diarizer() -> SpeakerDiarizer:
    """Process-wide singleton (the embedding model loads once)."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SpeakerDiarizer()
    return _singleton

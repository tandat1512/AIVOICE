"""Kokoro-82M ONNX TTS engine.

Wraps thewh1teagle/kokoro-onnx (Apache 2.0). Downloads model + voices on
first use into X:/smartgen/models/kokoro/. Default voice is af_sarah
(female, American). Native sample rate is 24000 Hz.

Streaming strategy
------------------
kokoro-onnx exposes Kokoro.create_stream which is an async generator yielding
(float32_chunk, sample_rate) tuples. We drive it from a background thread
using a private event loop, push Int16-converted bytes into a queue, and
let the public synthesize_stream iterator drain that queue. This keeps the
engine's public API synchronous while preserving early-chunk emission.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import re
import threading
import urllib.request
from pathlib import Path
from typing import Iterator

import numpy as np

from .base import BaseTTSEngine

# phonemizer's espeak backend logs "words count mismatch" at WARNING level for
# every TTS synthesis when espeak tokenisation differs from input word count.
# This is expected behaviour with Kokoro — suppress it.
logging.getLogger("phonemizer").setLevel(logging.ERROR)


_STREAM_MAX_WORDS = 12  # split longer utterances into clauses so the first audio
                        # chunk emits sooner (lower perceived latency, no audio lost)


def _split_for_streaming(text: str, max_words: int = _STREAM_MAX_WORDS) -> list[str]:
    """Split text into clause-sized pieces on punctuation, capped at max_words.

    Short sentences (<= max_words) pass through whole — only long ones are split,
    preferring natural comma/period boundaries so prosody stays reasonable.
    """
    text = text.strip()
    if not text:
        return []
    if len(text.split()) <= max_words:
        return [text]
    parts = re.split(r"(?<=[.!?,;:])\s+", text)
    pieces: list[str] = []
    cur: list[str] = []
    cw = 0
    for part in parts:
        w = len(part.split())
        if cw + w > max_words and cur:
            pieces.append(" ".join(cur))
            cur, cw = [], 0
        cur.append(part)
        cw += w
    if cur:
        pieces.append(" ".join(cur))
    # Any piece still too long (no punctuation) — hard-split by word count.
    out: list[str] = []
    for pc in pieces:
        ws = pc.split()
        if len(ws) <= max_words + 4:
            out.append(pc)
        else:
            for i in range(0, len(ws), max_words):
                out.append(" ".join(ws[i:i + max_words]))
    return out or [text]


_MODELS_DIR = Path(__file__).resolve().parents[3] / "models" / "kokoro"
_MODEL_FILENAME = "kokoro-v1.0.onnx"
_VOICES_FILENAME = "voices-v1.0.bin"
_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/"
    "download/model-files-v1.0/" + _MODEL_FILENAME
)
_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/"
    "download/model-files-v1.0/" + _VOICES_FILENAME
)

DEFAULT_VOICE = "af_sarah"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"[Kokoro] downloading {url} -> {dest} ...", flush=True)
    with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def _ensure_assets() -> tuple[str, str]:
    """Return (model_path, voices_path), downloading if missing."""
    model_path = _MODELS_DIR / _MODEL_FILENAME
    voices_path = _MODELS_DIR / _VOICES_FILENAME
    if not model_path.exists():
        _download(_MODEL_URL, model_path)
    if not voices_path.exists():
        _download(_VOICES_URL, voices_path)
    return str(model_path), str(voices_path)


def _float_to_int16_bytes(samples: np.ndarray) -> bytes:
    """Convert float32 audio [-1, 1] to little-endian Int16 PCM bytes."""
    if samples.dtype != np.float32:
        samples = samples.astype(np.float32)
    np.clip(samples, -1.0, 1.0, out=samples)
    return (samples * 32767.0).astype(np.int16).tobytes()


def _ascii_espeak_config():
    """espeak-ng opens its data files through the ANSI code page, so a non-ASCII
    data path (e.g. a non-ASCII OneDrive folder name) fails to load and espeak
    falls back to a bogus compiled-in path, hard-crashing TTS. If the bundled
    espeak-ng-data path is not ASCII, mirror it to an ASCII cache dir and point
    Kokoro at the copy."""
    import shutil
    import espeakng_loader
    from kokoro_onnx.config import EspeakConfig

    data_path = espeakng_loader.get_data_path()
    try:
        data_path.encode("ascii")
        return None
    except UnicodeEncodeError:
        pass

    cache = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "smartgen" / "espeak-ng-data"
    if not (cache / "phontab").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(data_path, cache, dirs_exist_ok=True)
    return EspeakConfig(data_path=str(cache))


# Cap Kokoro's ONNX Runtime CPU threads so synthesis can't saturate all cores
# and starve the NLLB-orchestration / STT threads (which balloons translate
# latency to tens of seconds and backs up TTS by minutes). Tunable via env.
_KOKORO_THREADS = max(1, int(os.environ.get("KOKORO_THREADS", "4")))


class KokoroEngine(BaseTTSEngine):
    """Kokoro-82M ONNX TTS — CPU or CUDA via onnxruntime."""

    def __init__(self, voice: str = DEFAULT_VOICE) -> None:
        self._default_voice = voice
        self._kokoro = None
        self._sample_rate: int = 24000
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._kokoro is not None

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._kokoro is not None:
                return
            import onnxruntime as _ort
            from kokoro_onnx import Kokoro

            model_path, voices_path = _ensure_assets()
            print(f"[Kokoro] loading {model_path} (intra_op_threads={_KOKORO_THREADS})", flush=True)
            # kokoro_onnx builds its InferenceSession with no SessionOptions, so
            # patch the constructor for the duration of the load to inject a
            # thread-capped one.
            _orig_sess = _ort.InferenceSession
            def _capped_sess(*a, **kw):
                so = _ort.SessionOptions()
                so.intra_op_num_threads = _KOKORO_THREADS
                so.inter_op_num_threads = 1
                kw.setdefault("sess_options", so)
                return _orig_sess(*a, **kw)
            _ort.InferenceSession = _capped_sess
            try:
                self._kokoro = Kokoro(model_path, voices_path, espeak_config=_ascii_espeak_config())
            finally:
                _ort.InferenceSession = _orig_sess

    def warmup(self) -> None:
        self._ensure_loaded()
        # Tiny utterance primes JIT + ORT session graph; discarded.
        for _ in self.synthesize_stream("Hello.", self._default_voice):
            break

    def list_voices(self) -> list[str]:
        self._ensure_loaded()
        return list(self._kokoro.get_voices())

    def synthesize_stream(self, text: str, voice: str | None = None) -> Iterator[bytes]:
        self._ensure_loaded()
        voice = voice or self._default_voice
        pieces = _split_for_streaming(text)
        sentinel = object()
        q: "queue.Queue[object]" = queue.Queue(maxsize=64)

        def runner() -> None:
            async def pump() -> None:
                try:
                    # Synthesize clause pieces in order; emit each as it completes
                    # so the first audio reaches the client without waiting for the
                    # whole utterance.
                    for piece in pieces:
                        async for samples, sr in self._kokoro.create_stream(piece, voice):
                            if not isinstance(samples, np.ndarray):
                                samples = np.asarray(samples, dtype=np.float32)
                            self._sample_rate = int(sr)
                            q.put(_float_to_int16_bytes(samples))
                except Exception as e:  # noqa: BLE001 — surface to caller
                    q.put(("__error__", e))
                finally:
                    q.put(sentinel)

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(pump())
            finally:
                loop.close()

        threading.Thread(target=runner, daemon=True).start()

        while True:
            item = q.get()
            if item is sentinel:
                return
            if isinstance(item, tuple) and item and item[0] == "__error__":
                raise item[1]  # type: ignore[misc]
            yield item  # type: ignore[misc]

    @property
    def sample_rate(self) -> int:  # type: ignore[override]
        return self._sample_rate

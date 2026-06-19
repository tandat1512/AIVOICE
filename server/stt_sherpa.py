"""
Streaming Vietnamese ASR via sherpa-onnx OfflineRecognizer + chunk-commit.

Model: sherpa-onnx-zipformer-vi-30M-int8-2026-02-09

Stable-display rules (3 layers):
  1. MIN_BUF_S=1.0 s  — need >=1 s audio before first display (prevents
                        English hallucinations on very short clips).
  2. Strict monotonic — word count must strictly INCREASE to update display.
  3. Stable-prefix    — when interim already has >=2 words, new result must
                        share the same first word (blocks large oscillations
                        where model completely re-interprets earlier audio).

Commit: every CHUNK_S=2 s of speech, or on silence. Fresh re-encode at commit
time for maximum accuracy (independent of interim display state).
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

SAMPLE_RATE   = 16000
TICK_S        = 0.15   # re-encode every 150 ms for interim display
MIN_BUF_S     = 1.0    # need >=1 s before first display (stability)
CHUNK_S       = 2.0    # commit and reset every 2 s of speech
SILENCE_TICKS = 4      # N × TICK_S silence → early commit (~600 ms)
SILENCE_RMS   = 0.005

_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
_MODEL_NAME = "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09"
_HF_REPO    = "csukuangfj2/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09"

# Vietnamese diacritics — result must contain at least one to be shown
_VI_RE = re.compile(
    r"[àáảãạăắặằẳẵâấậầẩẫèéẻẽẹêếệềểễìíỉĩịòóỏõọôốộồổỗơớợờởỡùúủũụưứựừửữỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẮẶẰẲẴÂẤẬẦẨẪÈÉẺẼẸÊẾỆỀỂỄÌÍỈĨỊÒÓỎÕỌÔỐỘỒỔỖƠỚỢỜỞỠÙÚỦŨỤƯỨỰỪỬỮỲÝỶỸỴĐ]"
)


# ── model file discovery ──────────────────────────────────────────────────────

def find_onnx_files(d: Path) -> dict[str, str]:
    def _pick(*globs: str) -> str:
        for g in globs:
            found = sorted(d.glob(g))
            if found:
                return str(found[0])
        raise FileNotFoundError(f"No ONNX file matching {globs} in {d}")

    if not (d / "tokens.txt").exists():
        raise FileNotFoundError(f"tokens.txt not found in {d}")

    return {
        "encoder": _pick("encoder*.int8.onnx", "encoder*.onnx"),
        "decoder": _pick("decoder*.int8.onnx", "decoder*.onnx"),
        "joiner":  _pick("joiner*.int8.onnx",  "joiner*.onnx"),
        "tokens":  str(d / "tokens.txt"),
    }


# ── model helpers ─────────────────────────────────────────────────────────────

def prepare_model(model_name: str = _MODEL_NAME) -> str:
    dest = _MODELS_DIR / model_name
    if dest.exists():
        try:
            find_onnx_files(dest)
            return str(dest)
        except FileNotFoundError:
            pass

    hf_repo = _HF_REPO if model_name == _MODEL_NAME else model_name
    print(f"[Sherpa] downloading {hf_repo} -> {dest} ...", flush=True)
    from huggingface_hub import snapshot_download
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=hf_repo, local_dir=str(dest), local_dir_use_symlinks=False)
    print("[Sherpa] download complete.", flush=True)
    return str(dest)


def _ascii_path(p: str) -> str:
    """sherpa-onnx's bundled onnxruntime can't load a model from a non-ASCII
    path on Windows (it passes the path as a narrow/UTF-8 string, so a folder
    like "Tài liệu" yields a corrupt model and decode raises
    "invalid unordered_map<K, T> key"). Fall back to the Windows 8.3 short
    path, which is pure ASCII."""
    import os
    if os.name != "nt" or p.isascii():
        return p
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024) and buf.value.isascii():
        return buf.value
    return p


def load_model(model_path: str, **_kwargs):
    import sherpa_onnx
    d = Path(_ascii_path(str(model_path)))
    files = find_onnx_files(d)
    print(f"[Sherpa] loading {d.name} ...", flush=True)
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder         = files["encoder"],
        decoder         = files["decoder"],
        joiner          = files["joiner"],
        tokens          = files["tokens"],
        num_threads     = 4,
        sample_rate     = SAMPLE_RATE,
        feature_dim     = 80,
        decoding_method = "greedy_search",
    )
    print("[Sherpa] model ready.", flush=True)
    return rec


# ── StreamingASR ──────────────────────────────────────────────────────────────

class StreamingASR:
    """
    Chunk-commit ASR with stable-prefix interim display.

    Words shown in interim NEVER disappear — only new words append to the right.
    Commit uses a fresh re-encode for maximum accuracy (independent of interim).
    """

    def __init__(
        self,
        on_update: Callable[[str, str], None],
        model,
        language: Optional[str] = None,
    ):
        self.on_update     = on_update
        self._rec          = model
        self.language      = language or "vi"
        self._committed    = ""
        self._last_text    = ""
        self._buf: np.ndarray = np.zeros(0, dtype=np.float32)
        self._prev_n       = 0
        self._silent_ticks = 0
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ── public API ────────────────────────────────────────────────────────────

    def feed_pcm(self, pcm: np.ndarray) -> None:
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        with self._lock:
            self._buf = np.concatenate([self._buf, pcm])

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def set_committed(self, text: str) -> None:
        with self._lock:
            self._committed = text

    def finalize(self) -> str:
        with self._lock:
            audio = self._buf.copy()
        if len(audio) >= int(SAMPLE_RATE * MIN_BUF_S):
            text = self._transcribe(audio)
            if text:
                with self._lock:
                    self._committed = (self._committed + " " + text).strip()
                self.on_update(self._committed, "")
        return self._committed

    # ── internal loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(TICK_S)
            try:
                self._tick()
            except Exception as e:
                print(f"[Sherpa] tick error: {e}", flush=True)

    def _tick(self) -> None:
        with self._lock:
            n     = len(self._buf)
            audio = self._buf.copy() if n > 0 else None

        if audio is None:
            return

        # ── Chunk full → commit ───────────────────────────────────────────────
        if n >= int(SAMPLE_RATE * CHUNK_S):
            self._commit(audio)
            return

        # ── Silence gate → early commit ───────────────────────────────────────
        tail = audio[-int(SAMPLE_RATE * 0.3):] if n > int(SAMPLE_RATE * 0.3) else audio
        rms  = float(np.sqrt(np.mean(tail ** 2)))
        if rms < SILENCE_RMS:
            self._silent_ticks += 1
            if self._silent_ticks >= SILENCE_TICKS:
                # Even if no interim text was generated (e.g. very short phrase < MIN_BUF_S),
                # always try to transcribe it before discarding.
                # If Sherpa returns empty for noise/silence, _commit safely clears it.
                silence_ms = int(self._silent_ticks * TICK_S * 1000)
                if n >= int(SAMPLE_RATE * 0.3):
                    self._commit(audio, silence_ms=silence_ms)
                else:
                    with self._lock:
                        self._buf = np.zeros(0, dtype=np.float32)
                    self._prev_n = 0
            return
        self._silent_ticks = 0

        # ── Wait for minimum buffer ───────────────────────────────────────────
        if n < int(SAMPLE_RATE * MIN_BUF_S):
            return

        # ── Throttle: skip if not enough new audio ────────────────────────────
        new_s = (n - self._prev_n) / SAMPLE_RATE
        if new_s < TICK_S * 0.5 and self._last_text:
            return
        self._prev_n = n

        # ── Encode ────────────────────────────────────────────────────────────
        t0   = time.monotonic()
        text = self._transcribe(audio)
        ms   = (time.monotonic() - t0) * 1000

        if not text:
            return

        # ── Layer 1: Vietnamese-only filter ───────────────────────────────────
        if not _VI_RE.search(text):
            return   # English / noise hallucination — skip

        new_words = text.split()
        old_words = self._last_text.split() if self._last_text else []
        new_wc    = len(new_words)
        old_wc    = len(old_words)

        # ── Layer 2: Strict monotonic — must add words ────────────────────────
        if new_wc <= old_wc:
            return

        # ── Layer 3: Stable-prefix — first word must not change ───────────────
        # Once we've shown ≥1 word, the leading word is locked.
        # This blocks: "thôi" (1w) → "không bao giờ" (4w, different start).
        if old_wc >= 1 and new_words[0] != old_words[0]:
            return

        # ── Accept ────────────────────────────────────────────────────────────
        self._last_text = text
        with self._lock:
            committed = self._committed
        print(f"[Sherpa] {ms:.0f}ms buf={n/SAMPLE_RATE:.2f}s -> {repr(text[:60])}", flush=True)
        self.on_update(committed, text)

    def _transcribe(self, audio: np.ndarray) -> str:
        stream = self._rec.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio.astype(np.float32))
        self._rec.decode_stream(stream)
        return stream.result.text.strip().lower()

    def _commit(self, audio: np.ndarray, silence_ms: int = 0) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)
        self._prev_n       = 0
        self._silent_ticks = 0
        last_interim       = self._last_text   # save before clearing
        self._last_text    = ""

        text = ""
        if len(audio) >= int(SAMPLE_RATE * MIN_BUF_S):
            text = self._transcribe(audio)
            if text and not _VI_RE.search(text):
                text = ""

        # Fresh re-encode failed (too short / noise): fall back to last rolling
        # interim so the words already on screen are preserved in committed state.
        if not text and last_interim and _VI_RE.search(last_interim):
            text = last_interim

        if text:
            with self._lock:
                self._committed = (self._committed + " " + text).strip()
                committed = self._committed
            print(f"[Sherpa] commit: {repr(committed[-80:])}", flush=True)
            self.on_update(committed, "", silence_ms)
        else:
            with self._lock:
                committed = self._committed
            self.on_update(committed, "", silence_ms)

"""
Streaming English ASR via faster-whisper CTranslate2 — single-pass turbo.

Model: whisper-large-v3-turbo (CT2 int8 ~1.5-1.8GB VRAM on GPU).
Single pass only — no fast/slow split, no correction-vs-final. Used for the
en->vi Meet mode; committed text is dispatched straight to translate/TTS via
the router's legacy committed-delta path (wait_final=False).

API (drop-in, same shape as stt_whisper.py):
  StreamingASR(on_update, model, language)
  .feed_pcm(np.ndarray  float32 @ 16 kHz)
  .stop()
  .set_committed(text)
  .finalize() -> str

on_update(committed, interim, stt_ms=...) — stt_ms is the last transcribe
call's wall time in ms, threaded through to [SEG] stt_ms.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

SAMPLE_RATE   = 16000
TICK_S        = 0.40   # re-encode every 400 ms
MIN_BUF_S     = 1.0    # need >=1 s before first display (stability)
CHUNK_S       = 2.5    # commit and reset after this many seconds
SILENCE_TICKS = 4      # N × TICK_S of low-RMS before early commit (~1.6 s)
SILENCE_RMS   = 0.005

_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
_MODEL_NAME = "deepdml/faster-whisper-large-v3-turbo-ct2"
_LOCAL_NAME = "faster-whisper-large-v3-turbo-ct2"


# ── model helpers ─────────────────────────────────────────────────────────────

def prepare_model(model_name: str = _MODEL_NAME) -> str:
    local = _MODELS_DIR / _LOCAL_NAME
    if local.exists() and (local / "model.bin").exists():
        return str(local)

    print(f"[WhisperEn] downloading {model_name} -> {local} ...", flush=True)
    from huggingface_hub import snapshot_download
    local.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_name, local_dir=str(local), local_dir_use_symlinks=False)
    print("[WhisperEn] download complete.", flush=True)
    return str(local)


def load_model(model_path: str, **_kwargs):
    from faster_whisper import WhisperModel
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"
    compute_type = "int8_float16" if device == "cuda" else "int8"
    print(f"[WhisperEn] loading {Path(model_path).name} on {device} ({compute_type}) ...", flush=True)
    try:
        model = WhisperModel(model_path, device=device, compute_type=compute_type)
    except Exception as e:
        if device != "cpu":
            print(f"[WhisperEn] GPU failed ({e}), retrying on CPU ...", flush=True)
            model = WhisperModel(model_path, device="cpu", compute_type="int8")
            device = "cpu"
        else:
            raise
    model._aivoice_device = device   # read by [CFG] logging
    print("[WhisperEn] model ready.", flush=True)
    return model


# ── StreamingASR ──────────────────────────────────────────────────────────────

class StreamingASR:
    """
    Sliding-window single-pass ASR using faster-whisper (CTranslate2),
    English only — no Vietnamese-script filter, no correction pass.

    on_update(committed, interim, stt_ms) contract:
      committed — accumulated committed text (all past utterances)
      interim   — growing text for current utterance (re-encoded every TICK_S)
      stt_ms    — wall time (ms) of the transcribe() call behind this update
    """

    def __init__(
        self,
        on_update: Callable[..., None],
        model,
        language: Optional[str] = None,
    ):
        self.on_update    = on_update
        self._model       = model
        self.language     = language or "en"
        self._committed   = ""
        self._last_text   = ""
        self._last_stt_ms = 0
        self._buf: np.ndarray = np.zeros(0, dtype=np.float32)
        self._prev_n      = 0
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
            t0   = time.monotonic()
            text = self._transcribe(audio)
            self._last_stt_ms = round((time.monotonic() - t0) * 1000)
            if text:
                with self._lock:
                    self._committed = (self._committed + " " + text).strip()
                self.on_update(self._committed, "", stt_ms=self._last_stt_ms)
        return self._committed

    # ── internal loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(TICK_S)
            try:
                self._tick()
            except Exception as e:
                print(f"[WhisperEn] tick error: {e}", flush=True)

    def _tick(self) -> None:
        with self._lock:
            n     = len(self._buf)
            audio = self._buf.copy() if n > 0 else None

        if audio is None:
            return

        if n >= int(SAMPLE_RATE * CHUNK_S):
            t0   = time.monotonic()
            text = self._transcribe(audio)
            ms   = (time.monotonic() - t0) * 1000
            if text:
                self._last_text   = text
                self._last_stt_ms = round(ms)
            self._commit()
            return

        tail = audio[-int(SAMPLE_RATE * 0.4):] if n > int(SAMPLE_RATE * 0.4) else audio
        rms  = float(np.sqrt(np.mean(tail ** 2)))
        if rms < SILENCE_RMS:
            self._silent_ticks += 1
            if self._silent_ticks >= SILENCE_TICKS:
                if self._last_text:
                    self._commit()
                else:
                    with self._lock:
                        self._buf = np.zeros(0, dtype=np.float32)
                    self._prev_n = 0
            return
        self._silent_ticks = 0

        new_s = (n - self._prev_n) / SAMPLE_RATE
        if new_s < TICK_S * 0.4 and self._last_text:
            return
        self._prev_n = n

        if n < int(SAMPLE_RATE * MIN_BUF_S):
            return

        t0   = time.monotonic()
        text = self._transcribe(audio)
        ms   = (time.monotonic() - t0) * 1000

        if not text:
            return

        new_words = text.split()
        old_words = self._last_text.split() if self._last_text else []
        new_wc    = len(new_words)
        old_wc    = len(old_words)

        if new_wc <= old_wc:
            return   # must grow

        if old_wc >= 1 and new_words[0] != old_words[0]:
            return   # first word changed — oscillation, skip

        if text != self._last_text:
            self._last_text   = text
            self._last_stt_ms = round(ms)
            with self._lock:
                committed = self._committed
            print(f"[WhisperEn] {ms:.0f}ms buf={n/SAMPLE_RATE:.2f}s -> {repr(text[:60])}", flush=True)
            self.on_update(committed, text, stt_ms=self._last_stt_ms)

    def _transcribe(self, audio: np.ndarray) -> str:
        buf_s    = len(audio) / SAMPLE_RATE
        max_new  = max(20, int(buf_s * 36))
        segs, _  = self._model.transcribe(
            audio,
            language                  = self.language,
            beam_size                 = 1,
            vad_filter                = True,
            condition_on_previous_text = False,
            word_timestamps           = False,
            temperature               = 0.0,
            no_speech_threshold       = 0.6,
            max_new_tokens            = max_new,
        )
        return " ".join(s.text.strip() for s in segs).strip()

    def _commit(self) -> None:
        text   = self._last_text
        stt_ms = self._last_stt_ms
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)
        self._prev_n       = 0
        self._last_text    = ""
        self._silent_ticks = 0
        if text:
            with self._lock:
                self._committed = (self._committed + " " + text).strip()
                committed = self._committed
            print(f"[WhisperEn] commit: {repr(committed[-80:])}", flush=True)
            self.on_update(committed, "", stt_ms=stt_ms)
        else:
            with self._lock:
                committed = self._committed
            self.on_update(committed, "", stt_ms=stt_ms)

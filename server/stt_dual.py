"""
Dual-Path Streaming ASR:
  Fast path   — Zipformer 30M (sherpa-onnx)  — real-time word-by-word display
  Verify path — EraX / Whisper Large CT2     — batch correction after each commit

Architecture:
  User speaks → Sherpa 30M shows words immediately (chunk-commit every 2 s)
             → EraX runs on the same audio chunk in background (~25-350 ms)
             → If EraX result differs and looks better → replace committed text

Why Whisper as verify (not RNNT):
  Whisper was designed for batch transcription with 5-30 s context.
  Running it on short interim chunks (1-2 s) hurts accuracy.
  But on completed utterances (2-5 s after Sherpa commits) it has enough
  context and outperforms the 30M RNNT model significantly.

Verify model priority:
  1. models/EraX-WoW-Turbo-V1.1-CT2/   — already downloaded (recommended)
  2. Any other CTranslate2 Whisper model in models/ with model.bin
"""
from __future__ import annotations

import re
import threading
import unicodedata
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .stt_sherpa import (
    SAMPLE_RATE,
    StreamingASR as _FastASR,
    prepare_model as _fast_prepare,
    load_model as _fast_load,
)

_MODELS_DIR   = Path(__file__).resolve().parent.parent / "models"
_MAX_AUDIO_S  = 30.0   # hard-cap audio buffer

# Supported verify models (CTranslate2 format required for faster-whisper).
# Note: openai/whisper-large-v3 is PyTorch format — use Systran/faster-whisper-large-v3.
_VERIFY_MODELS: dict[str, str] = {
    # local_dir_name        : huggingface_repo (CTranslate2 pre-converted)
    "whisper-large-v3"          : "Systran/faster-whisper-large-v3",        # OpenAI Whisper Large v3 (~3.1 GB)
    "whisper-large-v2"          : "Systran/faster-whisper-large-v2",
    "whisper-medium"            : "Systran/faster-whisper-medium",
    "EraX-WoW-Turbo-V1.1-CT2"  : "erax-ai/EraX-WoW-Turbo-V1.1-CT2",
}

_VI_DIACRITIC = re.compile(
    r"[àáảãạăắặằẳẵâấậầẩẫèéẻẽẹêếệềểễìíỉĩịòóỏõọôốộồổỗơớợờởỡùúủũụưứựừửữỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẮẶẰẲẴÂẤẬẦẨẪÈÉẺẼẸÊẾỆỀỂỄÌÍỈĨỊÒÓỎÕỌÔỐỘỒỔỖƠỚỢỜỞỠÙÚỦŨỤƯỨỰỪỬỮỲÝỶỸỴĐ]"
)


def _normalise(text: str) -> str:
    t = unicodedata.normalize("NFC", text.strip().lower())
    return re.sub(r"[.!?,;:\s]+$", "", t)


# ── model helpers ─────────────────────────────────────────────────────────────

def _find_verify_dir() -> tuple[str, str]:
    """Return (local_model_path, hf_repo) for the best available Whisper verify model.

    Checks VERIFY_MODEL env var first, then known models in priority order.
    VERIFY_MODEL accepts: local dir name OR HuggingFace repo (e.g. 'Systran/faster-whisper-large-v3').
    """
    import os

    # Explicit override via env var
    env_model = os.environ.get("VERIFY_MODEL", "").strip()
    if env_model:
        # Check if it's a known short name
        for local_name, hf_repo in _VERIFY_MODELS.items():
            if env_model in (local_name, hf_repo):
                dest = _MODELS_DIR / local_name
                return str(dest), hf_repo
        # Treat as HuggingFace repo, local dir = last segment
        local_name = env_model.split("/")[-1]
        dest = _MODELS_DIR / local_name
        return str(dest), env_model

    # Auto-detect: prefer EraX (Vietnamese-tuned), then any other CT2 model
    for local_name, hf_repo in _VERIFY_MODELS.items():
        d = _MODELS_DIR / local_name
        if d.exists() and (d / "model.bin").exists():
            print(f"[Dual] verify model: {local_name} (local)", flush=True)
            return str(d), hf_repo

    # Fallback: any Whisper CT2 model on disk (vocabulary.json is Whisper-specific)
    for d in _MODELS_DIR.iterdir():
        if d.is_dir() and (d / "model.bin").exists() and (d / "vocabulary.json").exists():
            print(f"[Dual] verify model: {d.name} (auto-detected local)", flush=True)
            return str(d), ""

    # Default download target = EraX
    first_name, first_repo = next(iter(_VERIFY_MODELS.items()))
    return str(_MODELS_DIR / first_name), first_repo


def prepare_model(model_name: str = "") -> str:
    fast_path = _fast_prepare()

    verify_path, verify_hf = _find_verify_dir()

    if not Path(verify_path).exists() or not (Path(verify_path) / "model.bin").exists():
        if not verify_hf:
            raise RuntimeError(
                f"No Whisper CT2 verify model found in {_MODELS_DIR}. "
                f"Download EraX: huggingface_hub.snapshot_download('{_ERAX_HF_REPO}', "
                f"local_dir='models/{_ERAX_DIR}')"
            )
        print(f"[Dual] downloading verify model {verify_hf} ...", flush=True)
        from huggingface_hub import snapshot_download
        Path(verify_path).mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=verify_hf, local_dir=verify_path, local_dir_use_symlinks=False)
        print("[Dual] verify model download complete.", flush=True)

    return f"{fast_path}|{verify_path}"


def load_model(model_path: str, **_kwargs) -> tuple:
    """Load fast (sherpa-onnx) + verify (Whisper CT2) models."""
    from faster_whisper import WhisperModel
    import torch

    fast_path, verify_path = model_path.split("|", 1)

    print("[Dual] loading fast model (Sherpa 30M) ...", flush=True)
    fast_rec = _fast_load(fast_path)

    vname = Path(verify_path).name
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"
    compute_type = "int8_float16" if device == "cuda" else "int8"
    print(f"[Dual] loading verify model ({vname}) on {device} ...", flush=True)
    try:
        verify_model = WhisperModel(verify_path, device=device, compute_type=compute_type)
    except Exception as e:
        if device != "cpu":
            print(f"[Dual] GPU failed ({e}), retrying CPU ...", flush=True)
            verify_model = WhisperModel(verify_path, device="cpu", compute_type="int8")
        else:
            raise

    print("[Dual] both models ready.", flush=True)
    return (fast_rec, verify_model)


# ── verify helpers ────────────────────────────────────────────────────────────

def _run_verify(whisper_model, audio: np.ndarray, language: str = "vi") -> str:
    """Batch-transcribe an utterance chunk with Whisper. Returns clean text."""
    buf_s   = len(audio) / SAMPLE_RATE
    max_new = max(20, int(buf_s * 36))
    segs, _ = whisper_model.transcribe(
        audio,
        language                   = language,
        beam_size                  = 1,
        vad_filter                 = True,
        condition_on_previous_text = False,
        word_timestamps            = False,
        temperature                = 0.0,
        no_speech_threshold        = 0.6,
        max_new_tokens             = max_new,
    )
    return " ".join(s.text.strip() for s in segs).strip()


def _should_apply(fast: str, verify: str) -> bool:
    """Return True if Whisper result is meaningfully better than Sherpa result."""
    if not verify:
        return False
    if not _VI_DIACRITIC.search(verify):
        return False   # Whisper produced English / noise — reject
    return _normalise(verify) != _normalise(fast)


# ── StreamingASR ──────────────────────────────────────────────────────────────

class StreamingASR:
    """
    Dual-path ASR:
      • Sherpa 30M  — chunk-commit every 2 s  — drives live word-by-word display
      • EraX Whisper — batch on committed audio — corrects when more accurate

    on_update(committed, interim) contract: same as stt_sherpa.StreamingASR.
    """

    def __init__(
        self,
        on_update: Callable[[str, str], None],
        model: tuple,
        language: Optional[str] = None,
    ):
        fast_rec, verify_model = model
        self._on_update   = on_update
        self._verify      = verify_model
        self._language    = language or "vi"
        self._committed   = ""
        self._audio_buf: np.ndarray = np.zeros(0, dtype=np.float32)
        self._lock        = threading.Lock()
        self._executor    = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verify")
        self._pending: Future | None = None

        self._fast = _FastASR(
            on_update = self._on_fast_update,
            model     = fast_rec,
            language  = language,
        )

    # ── public API ────────────────────────────────────────────────────────────

    def feed_pcm(self, pcm: np.ndarray) -> None:
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        self._fast.feed_pcm(pcm)
        with self._lock:
            self._audio_buf = np.concatenate([self._audio_buf, pcm])
            cap = int(SAMPLE_RATE * _MAX_AUDIO_S)
            if len(self._audio_buf) > cap:
                self._audio_buf = self._audio_buf[-cap:]

    def stop(self) -> None:
        self._fast.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def set_committed(self, text: str) -> None:
        with self._lock:
            self._committed = text
        self._fast.set_committed(text)

    def finalize(self) -> str:
        return self._fast.finalize()

    # ── fast-path callback ────────────────────────────────────────────────────

    def _on_fast_update(self, fast_committed: str, interim: str, silence_ms: int = 0) -> None:
        with self._lock:
            prev = self._committed

        if fast_committed != prev:
            prefix   = prev if fast_committed.startswith(prev) else ""
            fast_utt = fast_committed[len(prefix):].strip() if prefix else fast_committed

            with self._lock:
                self._committed = fast_committed
                audio_snap      = self._audio_buf.copy()
                self._audio_buf = np.zeros(0, dtype=np.float32)

            # Launch Whisper verify on the committed audio chunk
            if fast_utt and len(audio_snap) >= int(SAMPLE_RATE * 0.5):
                self._launch_verify(fast_committed, prefix, audio_snap, fast_utt)

        with self._lock:
            current = self._committed
        self._on_update(current, interim, silence_ms)

    # ── Whisper verify pass ───────────────────────────────────────────────────

    def _launch_verify(
        self,
        full_fast: str,
        prefix: str,
        audio: np.ndarray,
        fast_utt: str,
    ) -> None:
        if self._pending and not self._pending.done():
            print(f"[Dual] verify busy — skip: {repr(fast_utt[:40])}", flush=True)
            return

        def _run() -> None:
            try:
                verify_utt = _run_verify(self._verify, audio, self._language)

                if not _should_apply(fast_utt, verify_utt):
                    return

                corrected = (prefix + " " + verify_utt).strip() if prefix else verify_utt

                with self._lock:
                    if self._committed != full_fast:
                        return   # session moved on — discard stale correction
                    self._committed = corrected

                self._fast.set_committed(corrected)
                print(
                    f"[Dual] Whisper correction: {repr(fast_utt[:50])} -> {repr(verify_utt[:50])}",
                    flush=True,
                )
                self._on_update(corrected, "")
            except Exception as e:
                print(f"[Dual] verify error: {e}", flush=True)

        self._pending = self._executor.submit(_run)

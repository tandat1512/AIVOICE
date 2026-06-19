"""
Streaming + Correction Dual ASR
================================

Goal: behave like the zipformer (Sherpa) streaming model — solid text appears
in real-time WHILE speaking — but with higher accuracy via an asynchronous
PhoWhisper correction pass after each pause.

Layer 1  Demucs          vocals/music separation (optional, DEMUCS=1)
Layer 2  Silero VAD       32ms frames, threshold 0.3 (low to catch "nghe", "không")
Layer 3  Sherpa 30M       streams the segment every 300ms, committing stable words
                          as SOLID text immediately (last few words stay gray)
Layer 4  Silence trigger  VAD silence > 500ms ends the segment (full commit)
Layer 5  PhoWhisper-large async verify of the just-committed segment; if it
                          disagrees, the committed segment is corrected in place

Design principles:
  • Sherpa drives the real-time display → user sees solid text as they speak
  • PhoWhisper is a background editor → corrects committed words only on a real
    disagreement; never blocks the UI, never freezes on a slow/hung transcribe
  • Fail gracefully:
      - PhoWhisper timeout (PHOWHISPER_TIMEOUT_S, default 15) → keep Sherpa text
      - Demucs timeout (5s) → skip, use raw audio
      - overlap < 40% → keep Sherpa, do not force-replace

Environment variables:
  DEMUCS=1                   enable Demucs vocals separation (default off)
  DOMAIN_HINT=chứng_khoán    domain context for PhoWhisper initial_prompt
  PHOWHISPER_TIMEOUT_S=15    max seconds to wait for PhoWhisper (default 15)
  SEGMENTER=v2               enable the v2 segmenter (default v1, see below)
  LONG_PAUSE_MS=600          v2: silence (ms) required to LOCK a segment

SEGMENTER=v2 (default off — v1 behavior is unchanged when unset):
  v1 locks (is_final=True, drives translate+TTS) on ANY VAD pause >=
  _SILENCE_TRIGGER_MS (~400ms), including normal mid-clause breaths. v2 adds:
    - Hold/merge: a pause in [_SILENCE_TRIGGER_MS, LONG_PAUSE_MS) does not
      lock the segment. If speech resumes within the window, it merges into
      the same segment. Only a pause >= LONG_PAUSE_MS locks.
    - Smart force-cut: when a continuous (no-pause) utterance exceeds
      _MAX_SPEECH_S, cut at the last clause conjunction (và/nhưng/thì/rồi/
      vì/nên/mà/để) instead of mid-clause; the audio after the conjunction
      carries forward into the next segment.
"""
from __future__ import annotations

import contextlib
import io
import os
import threading
import time
import unicodedata
import re
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .audio_filter import AudioFilter
from .stt_sherpa import (
    SAMPLE_RATE,
    MIN_BUF_S,
    _MODELS_DIR,
    prepare_model as _sherpa_prepare,
    load_model as _sherpa_load,
)

# ── tuneable constants ─────────────────────────────────────────────────────────

_PHOWHISPER_DIR    = "phowhisper-large"
_PHOWHISPER_HF     = "vinai/PhoWhisper-large"

_VAD_FRAME         = 512    # samples — 32ms @ 16kHz (Silero minimum)
_VAD_THRESHOLD     = 0.30   # low threshold: catches "nghe", "không" sentence starts
_SILENCE_TRIGGER_MS = 400   # ms silence to end a segment (lower = faster, more chunks)
_SHERPA_EMIT_S     = 0.30   # s  — Sherpa interim update interval
_STABLE_TAIL       = 2      # words kept gray (unstable); everything before is committed solid
_MIN_WORD_PROB     = 0.30   # reject PhoWhisper words below this probability
_BEAM_SIZE         = 5      # PhoWhisper beam size (accuracy vs speed)
_OVERLAP_REJECT    = 0.40   # < this → keep Sherpa (PhoWhisper likely hallucinated)
_CTX_SENTENCES     = 0      # prevent whisper loop hallucination (only use DOMAIN_HINT)
_MAX_SPEECH_S      = float(os.environ.get("MAX_SPEECH_S", "6.0"))
                            # force-commit after this many seconds (default 6s; YouTube needs longer windows)
_DEMUCS_TIMEOUT_S  = 5.0    # seconds before abandoning Demucs
_LONG_PAUSE_MS     = int(os.environ.get("LONG_PAUSE_MS", "600"))
                            # silence_ms value that signals a sentence end to the router;
                            # v2 also uses this as the hold->lock silence threshold.
_PW_TIMEOUT_S      = float(os.environ.get("PHOWHISPER_TIMEOUT_S", "15"))
_USE_DEMUCS        = os.environ.get("DEMUCS", "0") == "1"
_DOMAIN_HINT       = os.environ.get("DOMAIN_HINT", "").strip()
_SEGMENTER_V2      = os.environ.get("SEGMENTER", "v1").strip().lower() == "v2"

# v2 force-cut: clause-initial conjunctions used to split a >_MAX_SPEECH_S
# continuous utterance at a clause boundary instead of mid-clause.
_FORCE_CUT_CONJUNCTIONS = frozenset({
    "và", "nhưng", "thì", "rồi", "vì", "nên", "mà", "để",
})

_VI_RE = re.compile(
    r"[àáảãạăắặằẳẵâấậầẩẫèéẻẽẹêếệềểễìíỉĩịòóỏõọôốộồổỗơớợờởỡùúủũụưứựừửữỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẮẶẰẲẴÂẤẬẦẨẪÈÉẺẼẸÊẾỆỀỂỄÌÍỈĨỊÒÓỎÕỌÔỐỘỒỔỖƠỚỢỜỞỠÙÚỦŨỤƯỨỰỪỬỮỲÝỶỸỴĐ]"
)


# ── text helpers ───────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip().lower())


def _strip_punct(text: str) -> str:
    return re.sub(
        r"[^\w\sàáảãạăắặằẳẵâấậầẩẫèéẻẽẹêếệềểễìíỉĩịòóỏõọôốộồổỗơớợờởỡùúủũụưứựừửữỳýỷỹỵđ]",
        "", text
    )


def _is_vi(text: str) -> bool:
    return bool(_VI_RE.search(text))


def _word_overlap(a: str, b: str) -> float:
    """SequenceMatcher ratio on word lists (0.0 – 1.0)."""
    aw = _strip_punct(_normalise(a)).split()
    bw = _strip_punct(_normalise(b)).split()
    if not aw and not bw:
        return 1.0
    if not aw or not bw:
        return 0.0
    return SequenceMatcher(None, aw, bw).ratio()


def _is_hallucination(text: str, repeat_threshold: float = 0.70) -> bool:
    """Return True if text looks like noise hallucination (e.g. 'thấy thấy thấy thấy').
    Requires ≥3 words and ≥repeat_threshold fraction sharing the same token."""
    words = _strip_punct(_normalise(text)).split()
    if len(words) < 3:
        return False
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return max(counts.values()) / len(words) >= repeat_threshold


def _patch_sherpa(sherpa: str, phowhisper: str) -> str:
    """Sherpa-backbone merge: accept PhoWhisper word substitutions, reject hallucinated insertions."""
    sw_orig = sherpa.split()
    pw_orig = phowhisper.split()

    sw_cmp = [_strip_punct(_normalise(w)) for w in sw_orig]
    pw_cmp = [_strip_punct(_normalise(w)) for w in pw_orig]

    result = []

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, sw_cmp, pw_cmp).get_opcodes():
        if tag == "equal":
            result.extend(pw_orig[j1:j2])
        elif tag == "replace":
            sherpa_len = i2 - i1
            pw_len = j2 - j1
            if pw_len > sherpa_len + 3:  # PhoWhisper expansion too large — hallucination
                result.extend(sw_orig[i1:i2])
            elif sherpa_len > pw_len + 5:  # PhoWhisper truncated — keep Sherpa
                result.extend(sw_orig[i1:i2])
            else:
                result.extend(pw_orig[j1:j2])
        elif tag == "insert":
            pass  # Sherpa is backbone — reject PhoWhisper-only insertions (hallucinations)
        elif tag == "delete":
            result.extend(sw_orig[i1:i2])
    return " ".join(result).strip()


# ── model helpers ──────────────────────────────────────────────────────────────

def _find_phowhisper() -> tuple[str, str]:
    local = _MODELS_DIR / _PHOWHISPER_DIR
    if local.exists() and (local / "model.bin").exists():
        return str(local), _PHOWHISPER_HF
    for d in sorted(_MODELS_DIR.iterdir()):
        if d.is_dir() and "phowhisper" in d.name.lower() and (d / "model.bin").exists():
            print(f"[PHDual] PhoWhisper found: {d.name}", flush=True)
            return str(d), _PHOWHISPER_HF
    return str(local), _PHOWHISPER_HF


def prepare_model(model_name: str = "") -> str:
    fast_path = _sherpa_prepare()
    pw_path, pw_hf = _find_phowhisper()
    if not (Path(pw_path) / "model.bin").exists():
        print(f"[PHDual] downloading PhoWhisper-large from {pw_hf} ...", flush=True)
        from huggingface_hub import snapshot_download
        Path(pw_path).mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=pw_hf, local_dir=pw_path, local_dir_use_symlinks=False)
        print("[PHDual] download complete.", flush=True)
    return f"{fast_path}|{pw_path}"


def load_model(model_path: str, **_) -> tuple:
    """Returns (sherpa_recognizer, whisper_model)."""
    import torch
    from faster_whisper import WhisperModel

    fast_path, pw_path = model_path.split("|", 1)
    print("[PHDual] loading Sherpa 30M ...", flush=True)
    fast_rec = _sherpa_load(fast_path)

    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"
    compute = "int8_float16" if device == "cuda" else "int8"
    vname = Path(pw_path).name
    print(f"[PHDual] loading {vname} on {device} ...", flush=True)
    try:
        pw_model = WhisperModel(pw_path, device=device, compute_type=compute)
    except Exception as e:
        if device != "cpu":
            print(f"[PHDual] GPU failed ({e}), retrying CPU ...", flush=True)
            pw_model = WhisperModel(pw_path, device="cpu", compute_type="int8")
        else:
            raise
    print("[PHDual] both models ready.", flush=True)
    if _USE_DEMUCS:
        _preload_demucs()
    return (fast_rec, pw_model)


# ── Silero VAD ─────────────────────────────────────────────────────────────────

_silero_vad_lock  = threading.Lock()
_silero_vad_model = None


def _get_silero_vad():
    """Lazily load Silero VAD and immediately probe it.

    Uses a pure-torch probe (no numpy bridge) so NumPy 2.x ABI mismatches
    are caught at load time rather than crashing every 32ms tick.
    Returns model or None on any failure.
    """
    global _silero_vad_model
    if _silero_vad_model is not None:
        return _silero_vad_model
    with _silero_vad_lock:
        if _silero_vad_model is not None:
            return _silero_vad_model
        try:
            import torch
            model, _ = torch.hub.load(
                "snakers4/silero-vad", "silero_vad",
                force_reload=False, verbose=False,
            )
            model.eval()
            # Probe: silent frame using pure torch (no numpy bridge).
            # If torch↔numpy interop is broken, this catches it here.
            with torch.no_grad():
                model(torch.zeros(_VAD_FRAME), SAMPLE_RATE)
            _silero_vad_model = model
            print("[PHDual] Silero VAD loaded and verified.", flush=True)
        except Exception as e:
            print(f"[PHDual] Silero VAD unavailable ({e}), using RMS fallback.", flush=True)
            _silero_vad_model = False   # sentinel
    return _silero_vad_model if _silero_vad_model is not False else None


# ── Demucs vocals separation ───────────────────────────────────────────────────

_demucs_lock  = threading.Lock()
_demucs_model = None


def _preload_demucs() -> None:
    """Pre-load Demucs in background so it's ready when needed."""
    t = threading.Thread(target=_get_demucs_model, daemon=True)
    t.start()


def _get_demucs_model():
    global _demucs_model
    if _demucs_model is not None:
        return _demucs_model
    with _demucs_lock:
        if _demucs_model is not None:
            return _demucs_model
        try:
            from demucs.pretrained import get_model  # type: ignore
            m = get_model("htdemucs_ft")
            m.eval()
            _demucs_model = m
            print("[PHDual] Demucs htdemucs_ft ready.", flush=True)
        except Exception as e:
            print(f"[PHDual] Demucs unavailable: {e}", flush=True)
            _demucs_model = False
    return _demucs_model if _demucs_model is not False else None


def _apply_demucs_safe(audio: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Separate vocals. Returns vocals-only mono audio at *sr*.
    Falls back to original audio if Demucs is unavailable or times out.
    """
    model = _get_demucs_model()
    if model is None:
        return audio
    exec_ = ThreadPoolExecutor(max_workers=1)
    try:
        f = exec_.submit(_demucs_worker, audio, sr, model)
        return f.result(timeout=_DEMUCS_TIMEOUT_S)
    except (FutureTimeout, Exception) as e:
        print(f"[PHDual] Demucs skipped ({type(e).__name__}), using raw audio.", flush=True)
        return audio
    finally:
        exec_.shutdown(wait=False)


def _demucs_worker(audio: np.ndarray, sr: int, model) -> np.ndarray:
    import torch
    import torchaudio.transforms as T

    sr_target = 44_100
    up   = T.Resample(sr, sr_target)
    down = T.Resample(sr_target, sr)

    t = torch.from_numpy(audio.astype(np.float32)).unsqueeze(0)
    t = up(t).unsqueeze(0).repeat(1, 2, 1)   # (1, 2, T) stereo

    from demucs.apply import apply_model  # type: ignore
    with torch.no_grad():
        sources = apply_model(model, t, device="cpu", progress=False)[0]

    stem_idx = list(model.sources).index("vocals") if "vocals" in model.sources else -1
    if stem_idx < 0:
        return audio
    vocals = sources[stem_idx].mean(dim=0)   # stereo → mono
    return down(vocals.unsqueeze(0)).squeeze(0).numpy().astype(np.float32)


# ── PhoWhisper transcription ───────────────────────────────────────────────────

def _transcribe_phowhisper(
    model,
    audio: np.ndarray,
    language: str = "vi",
    context_prompt: str = "",
) -> tuple[str, float]:
    """
    Returns (text, avg_word_probability).
    context_prompt: previous sentences (improves accuracy by ~15%).
    """
    buf_s   = len(audio) / SAMPLE_RATE
    max_new = min(256, max(30, int(buf_s * 36)))

    # Redirect stdout while iterating: torio's lazy FFmpeg search prints failure
    # messages (Loading FFmpeg6 / Failed to load ...) on the first call per session.
    # These are harmless — we never use FFmpeg — but clutter the log.
    _sink = io.StringIO()
    with contextlib.redirect_stdout(_sink):
        segs, _ = model.transcribe(
            audio,
            language                       = language,
            beam_size                      = _BEAM_SIZE,
            word_timestamps                = True,
            vad_filter                     = True,
            condition_on_previous_text     = bool(context_prompt),
            initial_prompt                 = context_prompt or None,
            temperature                    = 0.0,
            no_speech_threshold            = 0.5,
            max_new_tokens                 = max_new,
            compression_ratio_threshold    = 2.4,
            # ── anti-hallucination ──
            repetition_penalty             = 1.1,
            hallucination_silence_threshold = 2.0,
        )
        raw_segs = list(segs)  # materialize generator inside redirect scope

    words: list[str]  = []
    probs: list[float] = []
    for seg in raw_segs:
        if seg.no_speech_prob > 0.5:
            continue
        if seg.words:
            for w in seg.words:
                raw_word = unicodedata.normalize("NFC", w.word.strip())
                clean = _strip_punct(raw_word.lower())
                if clean and float(w.probability) >= _MIN_WORD_PROB:
                    words.append(raw_word)
                    probs.append(float(w.probability))
        else:
            toks_raw = unicodedata.normalize("NFC", seg.text.strip()).split()
            words.extend(toks_raw)
            probs.extend([0.60] * len(toks_raw))

    text     = " ".join(words).strip()
    avg_prob = float(np.mean(probs)) if probs else 0.0
    return text, avg_prob


# ── StreamingASR ──────────────────────────────────────────────────────────────

class StreamingASR:
    """
    Streaming-first dual ASR (Sherpa display + PhoWhisper correction).

    on_update(committed, interim, silence_ms, is_final, final_text) contract:
      - committed:   solid text. Grows in real-time from Sherpa; may be *revised*
                     when PhoWhisper refines a finished segment. DISPLAY only.
      - interim:     trailing unstable Sherpa words (gray). Changes/disappears.
      - silence_ms:  >= _LONG_PAUSE_MS signals a sentence boundary to the router.
      - is_final:    True once per Sherpa-committed segment (Sherpa-fast). This is
                     the event that drives translation + TTS — fired as soon as
                     Sherpa commits the sentence, for low latency.
      - final_text:  the Sherpa text for *that segment only* (what to translate and
                     speak). Empty unless is_final is True.

    PhoWhisper runs asynchronously after each commit and refines the on-screen
    transcript via a DISPLAY-ONLY update (is_final=False) — it never re-speaks
    already-spoken audio.
    """

    def __init__(
        self,
        on_update: Callable[..., None],
        model: tuple,
        language: Optional[str] = None,
    ) -> None:
        self._on_update    = on_update
        self._fast_rec     = model[0]
        self._whisper      = model[1]
        self._language     = language or "vi"

        # ── committed-text bookkeeping ───────────────────────────────────────
        # _committed       : full solid text shown to the user
        # _seg_base        : committed text BEFORE the current in-progress segment
        # _seg_sherpa      : current segment's committed (Sherpa) words
        # _sherpa_interim  : trailing unstable words (gray)
        self._committed: str      = ""
        self._seg_base: str       = ""
        self._seg_sherpa: str     = ""
        self._sherpa_interim: str = ""
        self._context_sents: list[str] = []

        self._filter = AudioFilter()

        # Raw PCM buffer — used only for VAD (not passed through AudioFilter so
        # the noise gate cannot zero out frames and fool Silero into seeing silence)
        self._raw_buf: np.ndarray = np.zeros(0, dtype=np.float32)
        # Filtered audio buffer — kept aligned with raw so Sherpa/PhoWhisper could
        # use it; currently we feed raw PCM (both models handle 16kHz natively).
        self._audio_buf: np.ndarray = np.zeros(0, dtype=np.float32)
        # Speech-segment buffer (accumulates raw audio between VAD start/end)
        self._speech_buf: np.ndarray = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()

        # VAD state
        self._vad_model    = _get_silero_vad()
        if self._vad_model is not None:
            try:
                self._vad_model.reset_states()
            except Exception:
                pass
        self._vad_state    = "silence"   # "silence" | "speech"
        self._silence_frames = 0
        _silence_trigger_frames = int(_SILENCE_TRIGGER_MS / 1000 * SAMPLE_RATE / _VAD_FRAME)
        self._silence_trigger  = max(1, _silence_trigger_frames)
        # v2 only: extra hold beyond _silence_trigger before locking the segment
        # (SEGMENTER=v2 "hold window" — see _tick). Defaults from _LONG_PAUSE_MS.
        _lock_trigger_frames = int(_LONG_PAUSE_MS / 1000 * SAMPLE_RATE / _VAD_FRAME)
        self._lock_trigger = max(self._silence_trigger, _lock_trigger_frames)
        self._holding = False
        self._last_audio_time: float = time.monotonic()

        # Sherpa fast-path
        self._last_sherpa_emit = 0.0

        # PhoWhisper correction executor — 1 worker, latest-segment-wins
        self._pw_executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="phowhisper"
        )
        self._pw_pending: Future | None = None

        # Stable id per committed segment — links the Sherpa "speak" event to the
        # later PhoWhisper "correct" event so the router can re-translate that exact
        # translation chunk in place.
        self._seg_counter: int = 0

        # Speaker diarization (optional; no-op if no embedding model present).
        # _seg_speaker maps seg_id -> speaker index so the later PhoWhisper
        # correction for that segment keeps the same speaker label.
        from .stt_diarization import get_diarizer
        self._diarizer = get_diarizer()
        self._diarizer.reset()
        self._seg_speaker: dict[str, int] = {}

        self._stop = threading.Event()
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    # ── public API ─────────────────────────────────────────────────────────────

    def set_silence_ms(self, ms: int) -> None:
        """Configure the end-of-segment silence trigger (VAD endpoint), in ms.

        Drives how long a pause must last before the current speech segment is
        committed — exposed to the UI as the 'Độ trễ ngắt câu (VAD)' control.
        """
        try:
            ms = int(ms)
        except (TypeError, ValueError):
            return
        ms = max(150, min(2000, ms))
        frames = int(ms / 1000 * SAMPLE_RATE / _VAD_FRAME)
        with self._lock:
            self._silence_trigger = max(1, frames)
            self._lock_trigger = max(self._lock_trigger, self._silence_trigger)

    def set_lock_ms(self, ms: int) -> None:
        """SEGMENTER=v2 only: configure the hold->lock silence threshold (ms).

        A pause >= silence_trigger (set_silence_ms) but < this value enters a
        "hold" — the segment is not finalized yet and merges with any speech
        that resumes within the window. A pause >= this value locks the
        segment (is_final=True). Always clamped to >= the silence_trigger value.
        """
        try:
            ms = int(ms)
        except (TypeError, ValueError):
            return
        ms = max(150, min(3000, ms))
        frames = int(ms / 1000 * SAMPLE_RATE / _VAD_FRAME)
        with self._lock:
            self._lock_trigger = max(self._silence_trigger, frames)

    def feed_pcm(self, pcm: np.ndarray) -> None:
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        filtered = self._filter.process(pcm)
        self._last_audio_time = time.monotonic()
        cap = int(SAMPLE_RATE * _MAX_SPEECH_S)
        with self._lock:
            self._raw_buf = np.concatenate([self._raw_buf, pcm])
            if len(self._raw_buf) > cap:
                self._raw_buf = self._raw_buf[-cap:]
            self._audio_buf = np.concatenate([self._audio_buf, filtered])
            if len(self._audio_buf) > cap:
                self._audio_buf = self._audio_buf[-cap:]

    def stop(self) -> None:
        self._stop.set()
        self._tick_thread.join(timeout=2.0)
        self._pw_executor.shutdown(wait=False, cancel_futures=True)

    def set_committed(self, text: str) -> None:
        with self._lock:
            self._committed = text
            self._seg_base  = text
            self._seg_sherpa = ""

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        self._language = value or "vi"

    def finalize(self) -> str:
        """Transcribe any remaining audio and append it to committed."""
        with self._lock:
            audio = self._speech_buf.copy() if len(self._speech_buf) > 0 else self._raw_buf.copy()
            self._speech_buf = np.zeros(0, dtype=np.float32)
            self._raw_buf    = np.zeros(0, dtype=np.float32)
            seg_base   = self._seg_base
            seg_sherpa = self._seg_sherpa
        if len(audio) >= int(SAMPLE_RATE * MIN_BUF_S):
            try:
                pw_text, avg = _transcribe_phowhisper(
                    self._whisper, audio, self._language, self._build_context()
                )
                if pw_text and _is_vi(pw_text):
                    if seg_sherpa:
                        merged, _ = self._merge(seg_sherpa, pw_text, avg)
                    else:
                        merged = pw_text
                    if merged:
                        with self._lock:
                            self._committed = (seg_base + " " + merged).strip() if seg_base else merged
                            self._seg_base   = self._committed
                            self._seg_sherpa = ""
            except Exception as e:
                print(f"[PHDual] finalize error: {e}", flush=True)
        with self._lock:
            return self._committed

    # ── tick loop ──────────────────────────────────────────────────────────────

    def _tick_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.032)   # ~32ms tick — 1 VAD frame
            try:
                self._tick()
            except Exception as e:
                print(f"[PHDual] tick error: {e}", flush=True)

    def _tick(self) -> None:
        # Drain all available VAD frames. VAD runs on raw PCM (_raw_buf) so the
        # AudioFilter noise gate cannot zero out frames and make Silero see
        # permanent silence. The filtered buffer is kept consumed in lockstep.
        while True:
            with self._lock:
                if len(self._raw_buf) < _VAD_FRAME:
                    break
                raw_frame = self._raw_buf[:_VAD_FRAME].copy()
                self._raw_buf = self._raw_buf[_VAD_FRAME:]
                if len(self._audio_buf) >= _VAD_FRAME:
                    self._audio_buf = self._audio_buf[_VAD_FRAME:]

            # ── Layer 2: Silero VAD (on raw audio) ───────────────────────────
            if self._vad_model is not None:
                is_speech = self._vad_probability(raw_frame) >= _VAD_THRESHOLD
            else:
                rms = float(np.sqrt(np.mean(raw_frame ** 2)))
                is_speech = rms > 0.008

            if is_speech:
                self._silence_frames = 0
                if self._vad_state == "silence":
                    self._vad_state = "speech"
                    with self._lock:
                        self._speech_buf = np.zeros(0, dtype=np.float32)
                    print("[PHDual] speech started.", flush=True)
                elif self._holding:
                    self._holding = False
                    print("[PHDual] hold resolved -> merge (speech resumed).", flush=True)
                with self._lock:
                    self._speech_buf = np.concatenate([self._speech_buf, raw_frame])
            else:
                if self._vad_state == "speech":
                    with self._lock:
                        self._speech_buf = np.concatenate([self._speech_buf, raw_frame])
                    self._silence_frames += 1

                    # ── v2: enter "hold" at silence_trigger — do not lock yet ─
                    if _SEGMENTER_V2 and not self._holding and self._silence_frames >= self._silence_trigger:
                        self._holding = True
                        print("[PHDual] hold started (pause >= silence_trigger).", flush=True)

                    # ── Layer 4: lock threshold → end segment ────────────────
                    # v1: locks at _silence_trigger. v2: locks at _lock_trigger
                    # (the hold/merge window above keeps the buffer live in
                    # between, so resumed speech merges instead of cutting).
                    lock_threshold = self._lock_trigger if _SEGMENTER_V2 else self._silence_trigger
                    if self._silence_frames >= lock_threshold:
                        self._vad_state      = "silence"
                        self._silence_frames = 0
                        self._holding        = False
                        try:
                            self._vad_model.reset_states()
                        except Exception:
                            pass
                        with self._lock:
                            speech_snap      = self._speech_buf.copy()
                            self._speech_buf = np.zeros(0, dtype=np.float32)
                        self._commit_segment(speech_snap, is_sentence_end=True)
                        print("[PHDual] silence trigger -> commit + PhoWhisper.", flush=True)

            # ── Layer 3: Sherpa progressive streaming during speech ──────────
            if self._vad_state == "speech":
                now = time.monotonic()
                if now - self._last_sherpa_emit >= _SHERPA_EMIT_S:
                    self._last_sherpa_emit = now
                    with self._lock:
                        sp = self._speech_buf.copy()
                    if len(sp) >= int(SAMPLE_RATE * MIN_BUF_S):
                        self._update_sherpa_interim(sp)

                # Force-commit if the segment runs too long without a pause
                with self._lock:
                    sp_len = len(self._speech_buf)
                if sp_len >= int(SAMPLE_RATE * _MAX_SPEECH_S):
                    if _SEGMENTER_V2:
                        with self._lock:
                            sp = self._speech_buf.copy()
                        before, after = self._split_at_conjunction(sp)
                        if len(after) > 0:
                            # Cut at the last clause conjunction; the conjunction
                            # and remaining audio carry forward as the same
                            # ongoing segment (vad_state stays "speech"). Reset
                            # the silence counter so trailing silence absorbed
                            # into `before` doesn't spuriously lock `after`.
                            with self._lock:
                                self._speech_buf = after
                            self._silence_frames = 0
                            self._holding        = False
                            self._commit_segment(before, is_sentence_end=False)
                            print(f"[PHDual] force-commit at {_MAX_SPEECH_S}s (split at conjunction).", flush=True)
                        else:
                            self._vad_state      = "silence"
                            self._silence_frames = 0
                            self._holding        = False
                            with self._lock:
                                speech_snap      = self._speech_buf.copy()
                                self._speech_buf = np.zeros(0, dtype=np.float32)
                            self._commit_segment(speech_snap, is_sentence_end=False)
                            print(f"[PHDual] force-commit at {_MAX_SPEECH_S}s (no conjunction, hard cut).", flush=True)
                    else:
                        self._vad_state      = "silence"
                        self._silence_frames = 0
                        with self._lock:
                            speech_snap      = self._speech_buf.copy()
                            self._speech_buf = np.zeros(0, dtype=np.float32)
                        self._commit_segment(speech_snap, is_sentence_end=False)
                        print(f"[PHDual] force-commit at {_MAX_SPEECH_S}s.", flush=True)

        # Virtual silence: in speech state but no audio for 500ms → end segment
        if self._vad_state == "speech" and time.monotonic() - self._last_audio_time >= 0.500:
            self._vad_state = "silence"
            self._silence_frames = 0
            self._holding = False
            try:
                self._vad_model.reset_states()
            except Exception:
                pass
            with self._lock:
                speech_snap      = self._speech_buf.copy()
                self._speech_buf = np.zeros(0, dtype=np.float32)
            self._commit_segment(speech_snap, is_sentence_end=True)
            print("[PHDual] virtual silence (500ms no audio) -> commit.", flush=True)

    def _vad_probability(self, frame: np.ndarray) -> float:
        """Silero VAD inference — avoids torch.from_numpy to bypass NumPy ABI issues."""
        import torch
        try:
            t = torch.FloatTensor(frame.tolist())   # no numpy bridge — NumPy 2.x safe
            with torch.no_grad():
                result = self._vad_model(t, SAMPLE_RATE)
            if isinstance(result, torch.Tensor):
                return float(result.item())
            if isinstance(result, (tuple, list)) and len(result) >= 1:
                r = result[0]
                return float(r.item() if hasattr(r, "item") else r)
            return float(result)
        except Exception as e:
            self._vad_model = None
            print(f"[PHDual] Silero VAD failed ({e}), switching to RMS fallback.", flush=True)
            return 0.0

    # ── Sherpa decode helpers ────────────────────────────────────────────────

    def _decode_sherpa(self, audio: np.ndarray) -> str:
        """Decode an audio segment with Sherpa 30M. Returns lowercase text or ''."""
        try:
            stream = self._fast_rec.create_stream()
            stream.accept_waveform(SAMPLE_RATE, audio)
            self._fast_rec.decode_stream(stream)
            return stream.result.text.strip().lower()
        except Exception as e:
            print(f"[PHDual] Sherpa decode error: {e}", flush=True)
            return ""

    def _update_sherpa_interim(self, audio: np.ndarray) -> None:
        """Decode the growing segment; commit stable words, keep the tail gray.

        This is what makes the display feel like the zipformer model: solid text
        appears in real-time, with only the last few (unstable) words shown gray.
        """
        text = self._decode_sherpa(audio)
        if not text or not _is_vi(text):
            return
        words = text.split()
        if len(words) > _STABLE_TAIL:
            stable = words[:-_STABLE_TAIL]
            tail   = words[-_STABLE_TAIL:]
        else:
            stable = []
            tail   = words
        new_seg_sherpa = " ".join(stable)

        with self._lock:
            # Sherpa re-decodes the whole segment each call; only grow (never shrink)
            # the committed portion to avoid flicker from minor prefix re-rankings.
            if len(new_seg_sherpa) >= len(self._seg_sherpa):
                self._seg_sherpa = new_seg_sherpa
            self._committed = (self._seg_base + " " + self._seg_sherpa).strip() if self._seg_sherpa else self._seg_base
            self._sherpa_interim = " ".join(tail)
            c = self._committed
            i = self._sherpa_interim
        self._on_update(c, i, 0, False, "")

    def _split_at_conjunction(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """SEGMENTER=v2 force-cut: find the last clause conjunction in `audio`
        and split the buffer just before it, so the current segment ends at a
        clause boundary instead of mid-clause. The conjunction and everything
        after it carries forward into the next segment.

        Returns (before, after); `after` is empty if no usable conjunction was
        found, signalling the caller to fall back to the v1 hard cut.
        """
        text = self._decode_sherpa(audio)
        words = _strip_punct(_normalise(text)).split()
        if len(words) < 2:
            return audio, np.zeros(0, dtype=np.float32)

        cut_idx = None
        for i in range(len(words) - 1, 0, -1):
            if words[i] in _FORCE_CUT_CONJUNCTIONS:
                cut_idx = i
                break
        if cut_idx is None:
            return audio, np.zeros(0, dtype=np.float32)

        # Approximate: assumes uniform word duration, so the cut may land
        # tens-to-hundreds of ms off the true clause boundary. Acceptable for
        # this fallback path (still better than v1's blind mid-buffer cut).
        cut_sample = int(len(audio) * cut_idx / len(words))
        if cut_sample < int(SAMPLE_RATE * MIN_BUF_S):
            return audio, np.zeros(0, dtype=np.float32)

        return audio[:cut_sample], audio[cut_sample:]

    # ── segment commit (Layer 4) ─────────────────────────────────────────────

    def _commit_segment(self, speech_snap: np.ndarray, is_sentence_end: bool) -> None:
        """Finalize the current segment: commit the full Sherpa text as solid,
        advance the segment base, then kick off the async PhoWhisper correction."""
        segment_ms = round(len(speech_snap) / SAMPLE_RATE * 1000)
        t0_commit = time.monotonic()
        final_text = ""
        if len(speech_snap) >= int(SAMPLE_RATE * MIN_BUF_S):
            final_text = self._decode_sherpa(speech_snap)

        with self._lock:
            if final_text and _is_vi(final_text) and len(final_text) >= len(self._seg_sherpa):
                self._seg_sherpa = final_text
            seg_base_snap   = self._seg_base
            seg_sherpa_snap = self._seg_sherpa
            self._committed = (seg_base_snap + " " + seg_sherpa_snap).strip() if seg_sherpa_snap else seg_base_snap
            self._sherpa_interim = ""
            c = self._committed
            # Advance the base so the next segment accumulates on top of this one.
            self._seg_base   = self._committed
            self._seg_sherpa = ""

        if not seg_sherpa_snap:
            # Nothing was committed for this segment — just refresh the display.
            self._on_update(c, "", 0, False, "")
            return

        sherpa_ms = round((time.monotonic() - t0_commit) * 1000)
        print(
            f"[PHDual] commit seg_ms={segment_ms} sherpa_ms={sherpa_ms} "
            f"sentence_end={is_sentence_end} text={seg_sherpa_snap[:60]!r}",
            flush=True,
        )

        silence_ms = _LONG_PAUSE_MS if is_sentence_end else 0
        self._seg_counter += 1
        seg_id = f"s{self._seg_counter}"
        # Attribute this segment to a speaker (0 when diarization is unavailable).
        speaker = self._diarizer.assign(speech_snap, SAMPLE_RATE)
        self._seg_speaker[seg_id] = speaker
        # Sherpa-fast: speak THIS committed sentence immediately (low latency).
        # final_text = the Sherpa text for this segment only (one sentence).
        self._on_update(c, "", silence_ms, True, seg_sherpa_snap, seg_id, "", speaker)

        # PhoWhisper runs in the background to refine the on-screen transcript and
        # re-translate this segment in place (display only) — never re-speaks audio.
        if len(speech_snap) >= int(SAMPLE_RATE * MIN_BUF_S):
            self._submit_correction(speech_snap, seg_base_snap, seg_sherpa_snap, silence_ms, seg_id)

    # ── PhoWhisper correction (Layer 5) ──────────────────────────────────────

    def _submit_correction(
        self,
        audio: np.ndarray,
        seg_base: str,
        seg_sherpa: str,
        silence_ms: int,
        seg_id: str,
    ) -> None:
        """Queue an async PhoWhisper refine of a just-committed segment.

        The worker emits one DISPLAY-ONLY correction for this segment (PhoWhisper
        verdict) carrying *seg_id*, so the router can re-translate that exact chunk
        in place. Never re-speaks. The single-worker executor refines in order.
        """
        context = self._build_context()
        self._pw_pending = self._pw_executor.submit(
            self._run_correction, audio.copy(), seg_base, seg_sherpa, context, silence_ms, seg_id
        )

    def _transcribe_with_timeout(
        self, audio: np.ndarray, context: str, timeout_s: float
    ) -> tuple[str, float] | None:
        """Run PhoWhisper transcribe under a hard wall-clock timeout so a slow or
        hung decode can never freeze the correction path. Returns None on timeout."""
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(
                _transcribe_phowhisper, self._whisper, audio, self._language, context
            )
            return fut.result(timeout=timeout_s)
        except FutureTimeout:
            print("[PHDual] PhoWhisper timeout, keeping Sherpa.", flush=True)
            return None
        except Exception as e:
            print(f"[PHDual] PhoWhisper transcribe error: {e}", flush=True)
            return None
        finally:
            ex.shutdown(wait=False)

    def _run_correction(
        self,
        audio: np.ndarray,
        seg_base: str,
        seg_sherpa: str,
        context: str,
        silence_ms: int,
        seg_id: str,
    ) -> None:
        """Layer 5: PhoWhisper verify, then emit this segment's single is_final.

        Always emits a final (PhoWhisper verdict, or Sherpa fallback on timeout /
        disagreement) so every committed segment is translated + spoken once.
        """
        t0_pw = time.monotonic()
        if _USE_DEMUCS:
            audio = _apply_demucs_safe(audio, SAMPLE_RATE)

        result = self._transcribe_with_timeout(audio, context, _PW_TIMEOUT_S)
        pw_ms = round((time.monotonic() - t0_pw) * 1000)

        if result is None:
            final_seg = seg_sherpa   # timeout/failure → keep Sherpa
            print(f"[PHDual] correction seg={seg_id} transcribe_ms={pw_ms} → timeout/keep_sherpa", flush=True)
        else:
            pw_text, avg_prob = result
            corrected, decision = self._merge(seg_sherpa, pw_text, avg_prob)
            final_seg = corrected if corrected else seg_sherpa
            changed = _normalise(final_seg) != _normalise(seg_sherpa)
            print(
                f"[PHDual] correction seg={seg_id} transcribe_ms={pw_ms} avg_prob={avg_prob:.2f} "
                f"decision={decision} changed={changed} | sherpa={seg_sherpa[:40]!r} "
                f"pw={pw_text[:40]!r} -> {final_seg[:40]!r}",
                flush=True,
            )

        # Update rolling context
        if _CTX_SENTENCES > 0 and final_seg:
            self._context_sents.append(final_seg)
            if len(self._context_sents) > _CTX_SENTENCES:
                self._context_sents.pop(0)

        self._emit_final(seg_base, seg_sherpa, final_seg, silence_ms, seg_id)

    def _emit_final(
        self, seg_base: str, seg_sherpa: str, final_seg: str, silence_ms: int, seg_id: str
    ) -> None:
        """Refine the on-screen transcript with PhoWhisper's verdict — DISPLAY ONLY.

        Sherpa already spoke this segment (Sherpa-fast), so this never re-speaks.
        It splices *final_seg* in place of the Sherpa text inside the committed
        display, but only when the committed still starts with the original
        "base + sherpa" prefix; otherwise a later segment moved things and we skip
        to avoid corrupting the transcript. Emitted with is_final=False and the
        segment's *seg_id* + corrected text so the router updates the VI display
        AND re-translates that exact chunk in place — without dispatching TTS.
        """
        if not final_seg or _is_hallucination(final_seg):
            # Empty or repetitive garbage ("thấy thấy thấy") — leave Sherpa text.
            if final_seg:
                print(f"[PHDual] dropped hallucination: {final_seg[:40]!r}", flush=True)
            return
        prefix = (seg_base + " " + seg_sherpa).strip() if seg_base else seg_sherpa
        with self._lock:
            cur = self._committed
            if not cur.startswith(prefix):
                return   # later segment moved the prefix — skip to avoid corruption
            later = cur[len(prefix):].strip()   # words from later segment(s)
            corrected_prefix = (seg_base + " " + final_seg).strip() if seg_base else final_seg
            self._committed = (corrected_prefix + " " + later).strip() if later else corrected_prefix
            if not later:
                # No newer segment yet — the corrected text becomes the base.
                self._seg_base = corrected_prefix
                self._seg_sherpa = ""
            c = self._committed
            i = self._sherpa_interim
        # display correction (is_final=False) + re-translate this chunk — NO re-speak
        speaker = self._seg_speaker.get(seg_id, 0)
        self._on_update(c, i, silence_ms, False, "", seg_id, final_seg, speaker)

    # ── merge engine ─────────────────────────────────────────────────────────

    def _merge(
        self,
        sherpa: str,
        phowhisper: str,
        pw_avg_prob: float,
    ) -> tuple[str, str]:
        """Confirmatory merge. Sherpa is the base; PhoWhisper patches wrong/missing
        words only. Rejects PhoWhisper hallucinations and non-Vietnamese output.
        Returns (result_text, decision_label)."""
        if not phowhisper and not sherpa:
            return "", "both-empty"

        if not phowhisper:
            if sherpa and _is_vi(sherpa) and not _is_hallucination(sherpa):
                return sherpa, "sherpa(pw-empty)"
            return "", "pw-empty->reject"

        if not _is_vi(phowhisper):
            if sherpa and _is_vi(sherpa) and not _is_hallucination(sherpa):
                return sherpa, "sherpa(pw-noVI)"
            return "", "pw-noVI->reject"

        if not sherpa:
            pw_len = len(_normalise(phowhisper).split())
            if pw_len > 3:
                return "", f"reject(pw-from-noise:{pw_len}w)"
            return phowhisper, "pw-only(no-sherpa)"

        sw = _normalise(sherpa).split()
        pw = _normalise(phowhisper).split()

        # Length hallucination safeguard: PhoWhisper ballooning vs Sherpa = noise loop.
        if len(sw) > 0 and len(pw) > len(sw) + 6 and len(pw) > len(sw) * 1.5:
            return sherpa, f"sherpa(pw-len={len(pw)}vs{len(sw)})"

        overlap = _word_overlap(sherpa, phowhisper)
        # Short segments are unreliable for PhoWhisper — raise rejection bar.
        min_overlap = 0.65 if len(sw) < 5 else _OVERLAP_REJECT
        if overlap < min_overlap:
            return sherpa, f"sherpa(low-overlap={overlap:.2f},min={min_overlap:.2f})"

        result = _patch_sherpa(sherpa, phowhisper)
        return result, f"patched(overlap={overlap:.2f})"

    # ── context builder ────────────────────────────────────────────────────────

    def _build_context(self) -> str:
        """Build PhoWhisper initial_prompt: punctuation hint + DOMAIN_HINT + last N sentences."""
        parts: list[str] = ["Đây là một câu hoàn chỉnh, có dấu phẩy và dấu chấm."]
        if _DOMAIN_HINT:
            parts.append(_DOMAIN_HINT)
        if _CTX_SENTENCES > 0:
            parts.extend(self._context_sents[-_CTX_SENTENCES:])
        return " ".join(parts)

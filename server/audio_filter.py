"""
Multi-stage voice enhancement filter for Vietnamese STT.

Pipeline (stateful — keep one instance per streaming session):
  1. DC offset removal
  2. Butterworth bandpass 80-7500 Hz, 4th-order (IIR, stateful)
  3. Adaptive RMS noise gate (learns noise floor from silent frames)
  4. RMS normalization to -20 dBFS
  5. Tanh soft limiter at 0.85

Why stateful IIR instead of per-chunk FIR:
  sosfilt with saved zi gives phase-continuous output across chunks —
  no click/discontinuity at chunk boundaries that would confuse the
  Whisper encoder's log-mel frontend.
"""
from __future__ import annotations

from collections import deque

import numpy as np
from scipy import signal

SAMPLE_RATE = 16_000

_BP_LO    = 80      # Hz  — removes low-frequency rumble / HVAC
_BP_HI    = 7_500   # Hz  — removes high-frequency hiss above speech range
_BP_ORDER = 4

# Gate: a frame whose RMS exceeds _SPEECH_RMS_FLOOR is never silenced
_SPEECH_RMS_FLOOR = 0.015
# Noise gate multiplier: threshold = noise_floor × N
_GATE_MULT = 4.0
# Hard floor prevents gating everything at startup before estimate builds up
_GATE_ABS_MIN = 0.003
# Target RMS after normalization (-20 dBFS ≈ 0.100)
_TARGET_RMS = 0.100
# Soft limiter knee
_TANH_KNEE = 0.85


class AudioFilter:
    """
    Five-stage voice enhancement filter.

    Usage::

        filt = AudioFilter()
        for chunk in pcm_chunks:
            clean = filt.process(chunk)   # float32, same length
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self._sr = sample_rate
        sos = signal.butter(
            _BP_ORDER, [_BP_LO, _BP_HI], "bandpass", fs=sample_rate, output="sos"
        )
        self._sos = sos
        # Zero initial conditions; filter settles within ~5 ms (1 period at 80 Hz)
        self._zi = np.zeros((sos.shape[0], 2), dtype=np.float64)
        # Circular buffer of per-frame RMS values observed during silence
        self._noise_history: deque[float] = deque(maxlen=120)  # ~18 s at 150 ms/frame
        self._noise_floor = 0.004

    # ── public API ─────────────────────────────────────────────────────────────

    def process(self, pcm: np.ndarray) -> np.ndarray:
        """Return filtered float32 audio of the same length as *pcm*."""
        if len(pcm) == 0:
            return np.zeros(0, dtype=np.float32)

        audio = pcm.astype(np.float64)

        # Stage 1 — DC offset (removes microphone bias / USB-adapter ground hum)
        audio -= audio.mean()

        # Stage 2 — Bandpass filter (stateful: preserves phase across chunks)
        audio, self._zi = signal.sosfilt(self._sos, audio, zi=self._zi)

        rms = float(np.sqrt(np.mean(audio ** 2)))

        # Stage 3 — Adaptive noise gate
        #   Silent frames (rms < threshold) feed the noise-floor estimator.
        #   The gate itself fires when rms is below noise_floor × multiplier.
        if rms < _SPEECH_RMS_FLOOR:
            self._noise_history.append(rms)
            if len(self._noise_history) >= 5:
                # 10th-percentile smooths over occasional low-energy speech frames
                self._noise_floor = float(
                    np.percentile(list(self._noise_history), 10)
                )
        gate_threshold = max(self._noise_floor * _GATE_MULT, _GATE_ABS_MIN)
        if rms < gate_threshold:
            # Silence frame — return zeros (Whisper VAD will ignore it)
            return np.zeros(len(audio), dtype=np.float32)

        # Stage 4 — RMS normalization to -20 dBFS
        if rms > 1e-9:
            audio = audio * (_TARGET_RMS / rms)

        # Stage 5 — Tanh soft limiter (preserves waveform shape, avoids hard clips)
        audio = np.tanh(audio / _TANH_KNEE) * _TANH_KNEE

        return audio.astype(np.float32)

    def reset(self) -> None:
        """Reset filter state (call between unrelated audio sessions)."""
        self._zi = np.zeros((self._sos.shape[0], 2), dtype=np.float64)
        self._noise_history.clear()
        self._noise_floor = 0.004

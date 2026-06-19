"""Phase 1 baseline: offline STT + diarization measurement on the cached clips."""
import time
from pathlib import Path

import numpy as np
from faster_whisper.audio import decode_audio

from server.stt_sherpa import prepare_model, load_model, SAMPLE_RATE
from server.stt_diarization import get_diarizer

CACHE = Path("_measure_cache")
CLIPS = ["s1a", "s1b", "s2a", "s2b", "s3a", "s3b", "s4"]


def _load(name):
    return decode_audio(str(CACHE / (name + ".mp3")), sampling_rate=SAMPLE_RATE).astype(np.float32)


def main():
    print("[baseline] loading Sherpa 30M ...", flush=True)
    rec = load_model(prepare_model())
    diar = get_diarizer()
    print("[baseline] diarization enabled =", diar.enabled, "\n", flush=True)

    print("{:6} {:>6} {:>10} {:>4}  text".format("clip", "dur_s", "decode_ms", "spk"))
    print("-" * 90)
    for name in CLIPS:
        audio = _load(name)
        dur = len(audio) / SAMPLE_RATE
        t0 = time.monotonic()
        stream = rec.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio)
        rec.decode_stream(stream)
        text = stream.result.text.strip().lower()
        decode_ms = (time.monotonic() - t0) * 1000
        spk = diar.assign(audio, SAMPLE_RATE)
        print("{:6} {:6.2f} {:10.0f} {:4}  {!r}".format(name, dur, decode_ms, spk, text[:60]))


if __name__ == "__main__":
    main()

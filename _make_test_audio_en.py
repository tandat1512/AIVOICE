"""Generate a continuous English meeting-style monologue as 16kHz int16 PCM
for GD1 verification (en STT -> NLLB en->vi)."""
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from gtts import gTTS

SAMPLE_RATE = 16000

TEXT = (
    "Good morning everyone, thanks for joining today's meeting. "
    "Let's start with a quick update on the project timeline. "
    "The development team has finished the first milestone ahead of schedule. "
    "However, we still need to review the budget for the next quarter. "
    "I think we should schedule a follow up call with the design team next week. "
    "Does anyone have questions before we move to the next topic?"
)

mp3_path = Path("_measure_cache/en_meeting.mp3")
mp3_path.parent.mkdir(exist_ok=True)
if not mp3_path.exists():
    gTTS(text=TEXT, lang="en").save(str(mp3_path))
    print(f"saved {mp3_path}")

audio, sr = sf.read(str(mp3_path), dtype="float32", always_2d=False)
if audio.ndim > 1:
    audio = audio.mean(axis=1)
print(f"loaded: {len(audio)/sr:.2f}s @ {sr}Hz")

if sr != SAMPLE_RATE:
    from math import gcd
    g = gcd(SAMPLE_RATE, sr)
    audio = resample_poly(audio, SAMPLE_RATE // g, sr // g)
print(f"resampled: {len(audio)/SAMPLE_RATE:.2f}s @ {SAMPLE_RATE}Hz")

pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
with open("test_audio_en.pcm", "wb") as f:
    f.write(pcm16.tobytes())
print("wrote test_audio_en.pcm")

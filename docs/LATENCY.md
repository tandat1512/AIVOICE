# Latency Profile — smartgen VI→EN streaming pipeline

## Measured baseline (2026-06-02, Windows 11, GTX 1650 4GB, CPU-only TTS)

All timings are wall-clock from the perspective of the server. Client network RTT (~1ms loopback) is excluded.

### Per-stage breakdown

| Stage | Mechanism | Measured latency | Notes |
|---|---|---|---|
| STT interim update | Sherpa-ONNX Zipformer 30M int8 | 80–150 ms/word | Rolling update every ~100ms |
| STT commit (sentence end) | Long silence ≥ 600ms or punctuation heuristic | 0ms overhead | Triggered by pause detection |
| Translation (vi→en) | MarianMT Helsinki CT2 int8 greedy | 30–80 ms / 10-word sentence | First token ~20ms after input; streaming |
| TTS synthesis (first chunk) | Kokoro-82M ONNX, CPU | **517 ms** (5-word phrase) | GPU with cuDNN 9: ~80–150ms |
| Audio scheduling (browser) | Web Audio API `source.start(startTime)` | <5 ms | `_nextPlayTime + 0.020s` cushion |

### End-to-end path (CPU mode, no phrase dispatch)

```
t=0      Vietnamese speech ends (STT silence trigger fires)
t=80ms   STT commits last words → router receives committed text
t=110ms  Translation starts (MarianMT CT2)
t=180ms  Translation done (70ms for ~10-word sentence)
t=180ms  TTS dispatch fires (Kokoro synthesis begins in thread pool)
t=697ms  First PCM chunk arrives at browser (517ms TTS inference)
t=717ms  Audio playback starts (+20ms Web Audio buffer cushion)
──────────────────────────────────────────────────────────
Total:   ~717ms speech-end → first English audio
```

### End-to-end path (CPU mode, with phrase dispatch at 5 words)

```
t=0      Vietnamese speech ends
t=80ms   STT commits → router
t=110ms  Translation starts
t=155ms  5 translated words accumulated → phrase TTS dispatch fires immediately
t=225ms  Full translation done (70ms remaining)
t=225ms  Remainder TTS dispatch fires (words 6–N)
t=672ms  Phrase audio plays (+517ms after phrase dispatch at t=155ms)
t=742ms  Remainder audio continues seamlessly after phrase ends
──────────────────────────────────────────────────────────
Total:   ~672ms speech-end → first English audio  (45ms saved vs no-phrase)
```

### Decision gate results (Sprint 0)

| Metric | Gate | Measured (CPU) | Status |
|---|---|---|---|
| First-chunk latency | < 400ms | 517ms | FAIL — accepted (within 2-3s target) |
| RTF (real-time factor) | < 0.4 | 0.35 | PASS |
| End-to-end (speech→audio) | < 2.0s | ~717ms | PASS |

## GPU acceleration path

Installing **cuDNN 9** for CUDA 12.x enables `CUDAExecutionProvider` for Kokoro:

```powershell
# Enable GPU TTS after cuDNN 9 install:
$env:ONNX_PROVIDER = "CUDAExecutionProvider"
.\run.ps1 serve
```

Expected GPU latency on GTX 1650 (4GB):
- TTS first chunk: ~80–150ms (vs 517ms CPU)
- End-to-end: ~350–500ms speech-end → first English audio
- With phrase dispatch: ~280–420ms

## Reading latency from the debug panel

Open the debug panel (Debug ▼ button). After each translated sentence you will see:

```
[TR_PAR] translate=68ms  words=12  [phrase]  u=a3f2c1b4
[TTS]    start u=a3f2c1b4_p voice=af_heart sr=24000
[TTS]    first audio chunk latency: 523ms
[TTS]    end u=a3f2c1b4_p chunks=4
[TTS]    start u=a3f2c1b4 voice=af_heart sr=24000
[TTS]    end u=a3f2c1b4 chunks=2
```

- `translate=68ms` — time MarianMT spent generating all tokens
- `words=12` — source Vietnamese word count
- `[phrase]` — phrase-level early dispatch fired (≥5 translated words dispatched before full sentence)
- `TTS: 523ms` in the header — first audio chunk latency from `tts_start` signal

## Bottleneck analysis

On CPU, the dominant bottleneck is **Kokoro TTS synthesis** (517ms for 5 words). MarianMT translation is fast (30–80ms). STT commit latency is driven by Sherpa's silence detection threshold (600ms).

Tuning options ranked by impact:

1. **Install cuDNN 9** — drops TTS from 517ms to ~100ms. Largest single improvement.
2. **Phrase-level dispatch** — implemented in Sprint 3. Saves ~45ms on CPU; ~30ms on GPU.
3. **Lower STT silence threshold** — `_LONG_PAUSE_MS = 600` in `streaming_router.py`. Reducing to 400ms saves 200ms at the cost of more false sentence boundaries.
4. **MarianMT beam search** — already greedy (beam=1). No further tuning available without quality loss.

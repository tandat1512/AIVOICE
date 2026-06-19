# SmartGen Performance Benchmarks

## Hardware & Software Configuration

| Item | Value |
|------|-------|
| OS | Windows 11 Pro 26200 |
| CPU | (measured on typical dev machine) |
| GPU | NVIDIA GTX 1650 4GB (TU117, CUDA 12.1) |
| RAM | 16 GB DDR4 |
| Python | 3.11 |
| ONNX Runtime | 1.18+ |
| STT Backend | Sherpa-ONNX Zipformer 30M int8 |
| Translation | MarianMT Helsinki VI→EN CTranslate2 int8 |
| TTS | Kokoro-82M ONNX (CPUExecutionProvider) |

---

## Per-Stage Latency (CPU TTS mode)

Measured 2026-06-02 using `bench_tts.py` and server debug logs.

| Stage | P50 | P95 | Notes |
|-------|-----|-----|-------|
| STT interim update | 80 ms | 150 ms | Per word, streaming |
| STT sentence commit | 600 ms | 900 ms | Silence threshold trigger |
| Translation (VI→EN) | 45 ms | 80 ms | 10-word sentence, greedy |
| TTS first chunk (CPU) | 517 ms | 720 ms | 5-word phrase, Kokoro-82M |
| TTS first chunk (GPU*) | ~100 ms | ~180 ms | *Estimated with cuDNN 9 |
| Audio scheduling | <5 ms | <10 ms | Web Audio API |
| **End-to-end (speech → audio)** | **720 ms** | **1 050 ms** | CPU mode, phrase dispatch |

\* GPU estimates based on Kokoro-82M RTF published benchmarks. Actual results require cuDNN 9 installation.

---

## TTS Latency by Utterance Length (`bench_tts.py`)

| Utterance length | First chunk | Full synthesis | RTF |
|-----------------|-------------|----------------|-----|
| 5 words | 517 ms | 520 ms | 0.35 |
| 10 words | 480 ms | 890 ms | 0.31 |
| 20 words | 460 ms | 1 650 ms | 0.28 |
| 50 words | 420 ms | 3 800 ms | 0.25 |

Longer utterances have lower RTF because ONNX model JIT overhead is amortized.

---

## Memory Usage

| Point in time | RSS (server process) |
|---------------|----------------------|
| After startup (models loaded) | ~1.4 GB |
| After 5 min continuous use | ~1.45 GB |
| After 30 min continuous use | ~1.50 GB |

RSS growth over 30 min: **<100 MB** — within the 200 MB budget from the project spec.

---

## How to Reproduce

### TTS benchmark

```bash
# From project root with venv active:
python bench_tts.py
# Results written to bench_tts_results.json
```

### Translation throughput

```bash
python bench_translation.py
```

### End-to-end stress test (30 min)

```bash
# Simulates 1 Vietnamese sentence every 4 seconds for 30 minutes
python evaluate_pipeline.py --duration 1800 --interval 4
```

Monitor server memory during the test:

```python
import psutil, time
proc = psutil.Process(PID)   # replace PID with server PID
while True:
    print(f"RSS: {proc.memory_info().rss / 1e6:.0f} MB")
    time.sleep(30)
```

---

## Phrase-Level Dispatch Savings

With `_PHRASE_DISPATCH_TOKENS = 5` (Sprint 3):

| Scenario | First audio latency | vs. no dispatch |
|----------|---------------------|-----------------|
| Short sentence (≤5 words) | 720 ms | — (no phrase dispatch) |
| Medium sentence (10 words) | ~630 ms | −90 ms |
| Long sentence (20+ words) | ~600 ms | −120 ms |

---

## CPU vs GPU Summary

| Metric | CPU | GPU (cuDNN 9) |
|--------|-----|---------------|
| TTS first chunk | 517 ms | ~100 ms |
| End-to-end p50 | 720 ms | ~300 ms |
| End-to-end p95 | 1 050 ms | ~450 ms |
| VRAM usage | 0 (system RAM) | ~900 MB |

To enable GPU TTS:

```powershell
$env:ONNX_PROVIDER = "CUDAExecutionProvider"
.\run.ps1 serve
```

Requires cuDNN 9 for CUDA 12.x installed system-wide.

# SmartGen Models & Libraries Reference

This document provides a comprehensive list of the pre-trained models and core Python libraries required to run and develop the SmartGen translation pipeline. 

If you are cloning this repository on a fresh machine or server, the `setup.bat` or `setup.sh` scripts will attempt to auto-download most of these. However, if you are working offline, running a Docker build without internet, or continuing development, this guide tells you exactly what files go where.

## Directory Structure

All models should be placed inside the `models/` directory at the root of the project.

```text
models/
├── kokoro/
│   ├── kokoro-v1.0.onnx
│   └── voices.bin
├── marian-vi-en-ct2/
│   ├── model.bin
│   └── shared_vocabulary.txt
├── nllb-200-distilled-600M-ct2/      (Optional, for higher quality translation)
│   ├── model.bin
│   └── shared_vocabulary.txt
├── phowhisper-large/                 (Faster-whisper format)
│   ├── model.bin
│   └── vocabulary.txt
└── sherpa-onnx-zipformer-vi-30M-int8-2026-02-09/
    ├── encoder-epoch-99-avg-1.int8.onnx
    ├── decoder-epoch-99-avg-1.onnx
    ├── joiner-epoch-99-avg-1.int8.onnx
    └── tokens.txt
```

*(Note: The exact filenames inside some CTranslate2 and Faster-Whisper directories might vary slightly depending on the export, but the directory names must match what the scripts expect).*

## 1. Speech-to-Text (STT) Models

### Sherpa-ONNX Zipformer (Vietnamese)
- **Role**: Provides ultra-fast, real-time interim transcription.
- **Source**: [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) releases or HuggingFace.
- **Path**: `models/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09`
- **Library**: `sherpa-onnx`

### PhoWhisper (Vietnamese)
- **Role**: Provides high-accuracy batch verification and correction (Dual-layer STT).
- **Source**: [VinAIResearch/PhoWhisper](https://huggingface.co/VinAIResearch/PhoWhisper-large) (Converted to CTranslate2/Faster-Whisper format).
- **Path**: `models/phowhisper-large` (or `base`/`small` depending on your `.env` config).
- **Library**: `faster-whisper`

### Silero VAD
- **Role**: Voice Activity Detection to segment speech and prevent hallucination loops.
- **Source**: [snakers4/silero-vad](https://github.com/snakers4/silero-vad).
- **Path**: Usually auto-downloaded by PyTorch Hub to `~/.cache/torch/hub/snakers4_silero-vad_master` or loaded via ONNX.
- **Library**: `onnxruntime`, `torch`

## 2. Translation Models (VI → EN)

### MarianMT (Helsinki-NLP)
- **Role**: Primary, lightning-fast translation engine.
- **Source**: [Helsinki-NLP/opus-mt-vi-en](https://huggingface.co/Helsinki-NLP/opus-mt-vi-en). We use a CTranslate2 int8 quantized version for speed.
- **Path**: `models/marian-vi-en-ct2`
- **Library**: `ctranslate2`, `transformers`

### NLLB-200 (Optional)
- **Role**: Higher quality translation alternative.
- **Source**: [facebook/nllb-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M).
- **Path**: `models/nllb-200-distilled-600M-ct2`
- **Library**: `ctranslate2`

*(You can use `scripts/convert_nllb.py` to generate the CTranslate2 format from the HuggingFace weights).*

## 3. Text-to-Speech (TTS) Models

### Kokoro-82M
- **Role**: Fast, natural-sounding English speech synthesis.
- **Source**: [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M).
- **Path**: `models/kokoro/kokoro-v1.0.onnx` and `models/kokoro/voices.bin`.
- **Library**: `kokoro-onnx`, `soundfile`

## Core Python Libraries for Developers

If you are continuing development, familiarize yourself with these key libraries:
- `FastAPI` & `websockets`: For the real-time server and streaming chunks.
- `sherpa-onnx`: For the Zipformer STT engine.
- `faster-whisper`: The CTranslate2 backend for PhoWhisper.
- `ctranslate2`: Highly optimized inference engine used for translation.
- `kokoro-onnx`: ONNX wrapper for the Kokoro TTS model.
- `onnxruntime`: Used for GPU acceleration across multiple models (TTS, VAD).

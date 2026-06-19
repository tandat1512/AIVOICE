# smartgen — realtime streaming translate + TTS (no paid APIs)

Replicates the pipeline from the design diagram, but **100% open-source / local** —
no Deepgram, no cloud STT, no translation API, no cloud TTS.

```text
   ┌──────────────┐  PCM 16k   ┌────────────────────────────┐  words   ┌────────────────────────┐  cụm   ┌──────────────────┐  PCM
   │ Microphone   │ ─────────▶ │ Dual-layer STT             │ ───────▶ │ StreamingTranslation    │ ─────▶ │ Kokoro-82M TTS   │ ─────▶ Web UI
   │ (browser)    │  WebSocket │ Sherpa 30M + PhoWhisper    │          │ Router (NLLB-200 600M) │        │ (ONNX, streamed) │  audio
   └──────────────┘            │ Real-time + Verify         │          └────────────────────────┘        └──────────────────┘
                               └────────────────────────────┘                    │
                                                                                   ▼
                                                                          Delta JSON ──▶ Web UI (text)
```

The pipeline stages, mapped to code:

| Stage                                 | Code                                       |
|----------------------------------------|--------------------------------------------|
| 1. Microphone — PCM 16 kHz             | `web/smartgen/*` + `web/worklets/pcm-worklet.js` |
| 2. STT streaming                       | `server/stt_phowhisper_dual.py` / `stt_sherpa.py` |
| 3. Streaming translation (NLLB-200)    | `server/translate/streaming_router.py`, `server/translate/engines/nllb_engine.py` |
| 4. Realtime TTS (Kokoro-82M, ONNX)     | `server/tts/dispatcher.py`, `server/tts/engines/kokoro_engine.py` |
| 5. Delta renderer + audio playback     | `server/main.py` (WebSocket gateway), `web/smartgen/*` |

## The Dual-Layer STT Architecture

We implemented a sophisticated dual-layer speech recognition pipeline to achieve both **zero-latency real-time preview** and **maximum accuracy**:

1. **Layer 1: Sherpa-ONNX Zipformer 30M**: A blazing-fast streaming model that gives instant real-time transcription (interim) with <100ms latency.
2. **Layer 2: PhoWhisper Large**: A highly accurate batch model that verifies and corrects the Sherpa transcript at natural silence boundaries. It patches missing/incorrect words while keeping Sherpa as the timing backbone.
3. **Anti-Hallucination Safeguards**: The pipeline includes multiple heuristics (Length safeguards, context isolation, overlap rejection) to completely eliminate Whisper's notorious "hallucination loops" during background noise.

## Requirements

- Windows 10/11
- NVIDIA GPU + CUDA-capable driver (≥ 6 GB VRAM recommended for PhoWhisper-large; fall back to medium/small if needed).
- Python 3.10 or 3.11
- A modern browser (Chrome / Edge / Firefox)

## Setup & Models

For a complete breakdown of all AI models, file paths, and core libraries used in this repository, please refer to **[MODELS.md](MODELS.md)**.

```powershell
.\run.ps1 setup
```

This creates `.venv`, installs PyTorch with CUDA 12.1 wheels, then the rest of the requirements (faster-whisper, transformers, FastAPI, uvicorn, ...).

First run will automatically download:
- Sherpa-ONNX Zipformer 30M
- PhoWhisper Large
- MarianMT (Helsinki-NLP/opus-mt-vi-en) translation models

## Run

```powershell
.\run.ps1 serve
```

Then open <http://localhost:8000>, pick source/target languages, click **Start mic**, allow microphone access, and start speaking. You should see:
- **Transcript** pane filling in word-by-word with instant preview and auto-correction.
- **Translation** pane updating in lockstep, with translated audio played back as it's generated.

## Realtime Translation + TTS Pipeline

Once the dual-layer STT commits a Vietnamese sentence (or clause), the
`StreamingTranslationRouter` (`server/translate/streaming_router.py`) translates
it with **NLLB-200-distilled-600M** (CTranslate2, `server/translate/engines/nllb_engine.py`)
and streams the result to **Kokoro-82M** (ONNX, `server/tts/engines/kokoro_engine.py`)
for text-to-speech — both translation and speech synthesis start before the full
sentence has finished decoding:

- **Token-streaming translation**: NLLB tokens are decoded incrementally via
  CTranslate2's `generate_tokens`, off the shared inference lock (producer
  thread + queue), so the lock is held only for the time it takes to start
  decoding, not the whole sentence.
- **Cụm-based incremental TTS dispatch**: as English tokens arrive, the router
  splits the growing translation into "cụm" (clause-sized chunks, ~7-11 words,
  preferring `,;:` boundaries) and dispatches each cụm to Kokoro as soon as it's
  ready via `TTSDispatcher` (`server/tts/dispatcher.py`), instead of waiting for
  the entire sentence. A small holdback (`_TAIL_HOLDBACK_WORDS`) keeps the final
  remainder of each clause from becoming a 1-2 word fragment.
- **Per-session serial TTS worker**: `TTSDispatcher` runs one Kokoro synthesis at
  a time per session and streams PCM chunks back over the WebSocket as they're
  produced.
- **Entity/glossary masking**: place names and glossary terms are masked before
  translation and restored afterwards (`server/translate/postprocess/`), so NLLB
  doesn't mistranslate proper nouns.

Key environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `TRANSLATE_BACKEND` | `nllb-600m` | Translation engine: `nllb-600m`, `nllb-1b`, `marian`, `marian-envi` |
| `CONTEXT_DISABLED` | `1` | When `1` (default), no cross-sentence context is fed to NLLB — only glossary masking is active |
| `SEGMENTER` | (v1) | `v2` enables the alternate clause segmenter in `chunk_manager.py` |
| `ONNX_PROVIDER` | `CPUExecutionProvider` | Kokoro ONNX execution provider (`CUDAExecutionProvider` for GPU, when available) |

> Kokoro currently runs on CPU; CPU synthesis dominates first-audio latency for
> longer sentences (~85-90%). GPU execution (`CUDAExecutionProvider`) is the next
> performance lever once the required `cublas`/`cuDNN` runtime DLLs are available.

## Text Translate API

SmartGen also exposes a REST endpoint for direct text translation. It reuses the
same local translation engines as the realtime voice pipeline and does not change
the WebSocket flow.

```http
POST /api/translate/text
Content-Type: application/json
```

```json
{
  "text": "Xin chào, tôi muốn đặt phòng",
  "src_lang": "vie_Latn",
  "tgt_lang": "eng_Latn",
  "translate_model": "nllb-600m"
}
```

Response:

```json
{
  "source_text": "Xin chào, tôi muốn đặt phòng",
  "translated_text": "Hello, I want to book a room",
  "src_lang": "vie_Latn",
  "tgt_lang": "eng_Latn",
  "memory_suggestions": []
}
```

The web UI includes a **Text** view with source/target language selectors, model
selection through Settings, and a backend-connected Translate button.

## Currency Convert API

Currency conversion is available through a REST endpoint and a **Currency** tab
in the web UI.

```http
GET /api/currency/convert?amount=100&from=USD&to=VND
```

```json
{
  "amount": 100,
  "from_currency": "USD",
  "to_currency": "VND",
  "rate": 25400,
  "converted": 2540000,
  "source": "frankfurter",
  "updated_at": "2026-06-10T00:00:00+00:00"
}
```

The service uses `open.er-api.com` latest exchange rates as the primary source,
falls back to Frankfurter, caches rates in memory, and finally falls back to a
small static rate table if external APIs are down.
It also exposes currency detection for text:

```http
GET /api/currency/detect?text=Ramen%20980円%20and%20coffee%20$4
```

## Image Translate API

Image translation accepts an uploaded image, runs OCR, translates extracted
text with the local translation engine, and detects currency amounts in the OCR
text.

```http
POST /api/translate/image
Content-Type: multipart/form-data
```

Fields:

- `file`: image file
- `src_lang`: source language code, e.g. `vie_Latn`
- `tgt_lang`: target language code, e.g. `eng_Latn`
- `translate_model`: optional translation model id
- `ocr_engine`: optional, `auto`, `google`, `paddle`, `tesseract`, or `none`
- `ocr_lang`: optional OCR language override

Response:

```json
{
  "extracted_text": "Ramen 980円",
  "translated_text": "Ramen 980 yen",
  "blocks": [
    { "text": "Ramen", "translation": "Ramen", "bbox": [10, 20, 80, 40], "confidence": 0.96 }
  ],
  "detected_currency": [
    { "text": "980円", "amount": 980, "currency": "JPY", "start": 6, "end": 10 }
  ],
  "ocr_status": "ok",
  "ocr_engine": "paddle",
  "ocr_lang": "japan"
}
```

OCR dependencies are optional. `OCR_ENGINE=auto` tries Google Vision first only
when Google credentials are configured, then PaddleOCR, then Tesseract, then
returns `ocr_status: "unavailable"` with a clear error message.

Optional PaddleOCR install:

```powershell
.\run.ps1 setup-ocr
```

For GPU, install `paddlepaddle-gpu` matching your CUDA version from Paddle's
official install matrix, then install `paddleocr`.

Optional Google Vision install for Google-Translate-like OCR quality:

```powershell
.\run.ps1 setup-google-ocr
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\service-account.json"
$env:OCR_ENGINE="google"
.\run.ps1 serve
```

Google Vision is a cloud OCR backend and may incur Google Cloud costs. The app
does not hard-code or store API keys; it uses the standard
`GOOGLE_APPLICATION_CREDENTIALS` environment variable. To keep `auto` mode local
unless credentials are present, leave `OCR_ENGINE=auto`. To force cloud OCR from
the UI, choose `Google Vision` in the OCR engine selector.

If you see `PaddleOCR unavailable: No module named 'paddleocr'` and
`Tesseract dependency missing: No module named 'PIL'`, OCR dependencies have not
been installed in `.venv` yet. Run `.\run.ps1 setup-ocr`, then restart
`.\run.ps1 serve`.

The OCR adapter runs PaddleOCR on `OCR_DEVICE=cpu` with MKLDNN disabled by
default to avoid oneDNN runtime errors seen on some Windows Paddle builds.
For faster local OCR, PaddleOCR uses `OCR_PADDLE_PROFILE=fast` by default,
which selects a lighter PP-OCR mobile profile. Use `OCR_PADDLE_PROFILE=balanced`
or `OCR_PADDLE_PROFILE=accurate` when quality matters more than speed, or set
`OCR_PADDLE_VERSION` directly, for example `PP-OCRv3`, `PP-OCRv5`, or
`PP-OCRv6`. Set `OCR_WARMUP=1` to preload PaddleOCR in the background at server
startup so the first image request is faster.
Raster images are preprocessed by default (`OCR_PREPROCESS=1`) with RGB
normalization, light upscaling, contrast, and sharpening before OCR. Tune with
`OCR_SCALE`, `OCR_MIN_SIDE`, and `OCR_MAX_SIDE`, or set `OCR_PREPROCESS=0` to
compare raw PaddleOCR output. For Vietnamese screenshots, some OCR engines may
still lose accents; upload the original high-resolution crop instead of a full
desktop screenshot for best results.

Image Translate returns OCR blocks by default but skips per-block translation to
keep latency low. Set `IMAGE_TRANSLATE_BLOCKS=1` if you need translated overlay
text for every OCR block.

## Audio File Translate API

Audio file translation accepts an uploaded recording, transcribes it with the
existing faster-whisper STT backend, translates each segment, and returns a
bilingual timeline.

```http
POST /api/translate/audio-file
Content-Type: multipart/form-data
```

Fields:

- `file`: audio file (`wav`, `mp3`, `m4a`, `flac`, `ogg`, `webm`, `aac`)
- `src_lang`: source language code
- `tgt_lang`: target language code
- `translate_model`: optional translation model id

Response:

```json
{
  "segments": [
    {
      "start": 0.0,
      "end": 3.2,
      "text": "Xin chào",
      "translation": "Hello"
    }
  ],
  "full_text": "Xin chào",
  "full_translation": "Hello",
  "stt_status": "ok"
}
```

If the faster-whisper model or ffmpeg runtime is missing, the endpoint returns
`stt_status: "unavailable"` with a clear error message.

## Travel Assistant API

Travel Assistant combines OCR or raw text input, translation, currency
detection, and currency conversion. It is useful for menus, receipts, and signs.

```http
POST /api/travel/assist
Content-Type: multipart/form-data
```

Fields:

- `file`: optional image file
- `text`: optional raw text if no image is uploaded
- `src_lang`: source language code, e.g. `jpn_Jpan`
- `target_language`: target language code, e.g. `vie_Latn`
- `home_currency`: currency to convert prices into, default `VND`
- `translate_model`: optional translation model id
- `ocr_engine`: optional OCR backend selector
- `ocr_lang`: optional OCR language override

Response:

```json
{
  "items": [
    {
      "original": "ラーメン 980円",
      "translation": "Ramen 980 yên",
      "price": {
        "amount": 980,
        "currency": "JPY",
        "converted_amount": 160000,
        "converted_currency": "VND",
        "rate": 163.2,
        "source": "open_er_api"
      },
      "note": "Đã phát hiện giá tiền và quy đổi sang tiền tệ nhà."
    }
  ],
  "summary": "Đã phân tích 1 dòng và phát hiện 1 mục có giá tiền."
}
```

## Glossary API

Glossary entries are stored in SQLite at `data/glossary.db` and are applied by
`TranslatorService` when `use_glossary` is true.

```http
GET /api/glossary
POST /api/glossary
PUT /api/glossary/{id}
DELETE /api/glossary/{id}
```

```json
{
  "source_term": "prompt",
  "target_term": "câu lệnh",
  "src_lang": "eng_Latn",
  "tgt_lang": "vie_Latn",
  "note": "Dùng trong AI"
}
```

## Translation Memory API

Translation Memory is stored in SQLite at `data/translation_memory.db`. It uses
string similarity for v1 and can later be replaced by embeddings.

```http
GET /api/memory/search?q=...
POST /api/memory
```

Text/Image/Audio/Travel translations save pairs automatically through the shared
translation service. Text Translate responses include `memory_suggestions`.

## Export API

```http
POST /api/export
Content-Type: application/json
```

Supported formats: `txt`, `json`, `srt`, and optional `docx`.

```json
{
  "format": "srt",
  "title": "SmartGen Audio",
  "segments": [
    { "start": 0.0, "end": 3.2, "text": "Xin chào", "translation": "Hello" }
  ]
}
```

`docx` export requires the optional dependency:

```powershell
pip install python-docx
```

## How the streaming logic works

1. Browser captures the mic with `getUserMedia`, an `AudioWorklet` downsamples to 16 kHz Int16 PCM and forwards binary frames over WebSocket.
2. Server appends each frame to a rolling buffer.
3. Silero VAD (Voice Activity Detection) monitors the audio stream.
4. **Fast-path**: While speaking, Sherpa emits real-time interim transcripts every 300ms.
5. **Silence trigger**: When the user pauses (500ms silence), the chunk is sent to a background PhoWhisper worker for verification.
6. **Merge Engine**: PhoWhisper's output is compared with Sherpa's via SequenceMatcher. If valid, PhoWhisper's corrections are patched into the committed transcript.
7. **Translation**: each committed sentence/clause is sent to `StreamingTranslationRouter`, which streams NLLB-200 tokens incrementally and emits `translation_update` / `trans_stream_c` WebSocket events as the English text grows.
8. **TTS**: as soon as a cụm (clause-sized chunk) of the translation is ready, it's dispatched to Kokoro-82M; `tts_start` / binary PCM frames / `tts_end` events stream the resulting audio to the browser, which plays it back as it arrives.
9. The UI renders the transcript and translation deltas using a diffing algorithm without screen flashes, and plays translated audio in order per utterance.

## Files

```text
server/
  main.py                       # FastAPI app, WebSocket gateway, REST routes wiring
  stt_phowhisper_dual.py        # Dual-layer STT engine (Sherpa + PhoWhisper + Silero VAD)
  stt_sherpa.py                 # Standalone Sherpa fast-path engine
  translate/
    streaming_router.py         # StreamingTranslationRouter: NLLB streaming + cụm TTS dispatch
    chunk_manager.py             # Sentence/clause segmentation (v1/v2)
    vi_preprocessor.py, vi_numbers.py, punctuation.py
    engines/                     # nllb_engine.py, nllb_1b_engine.py, marian_engine.py, ...
    postprocess/                 # post_processor.py, profanity_filter.py (entity/glossary masking)
  tts/
    dispatcher.py                # TTSDispatcher: per-session serial TTS worker
    engines/kokoro_engine.py      # Kokoro-82M ONNX TTS engine
  routes/                        # text_translate, image_translate, audio_translate, currency, travel
  schemas/                       # Pydantic request/response schemas
  services/                      # translator_service, ocr_service, currency_service, ...
web/
  smartgen/                      # SmartGen React UI (vendored React/Babel, no build step)
    SmartGen.html, app.jsx, screens.jsx, backend.js, main.jsx, ui.jsx, orb.jsx, styles.css
  index.html, app.js, style.css  # legacy 2-pane UI
  worklets/pcm-worklet.js        # 48k/44.1k -> 16k Int16 downsampler
requirements.txt
run.ps1
```

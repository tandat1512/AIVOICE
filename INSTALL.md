# SmartGen — Installation Guide

Real-time Vietnamese→English speech translation with TTS audio output.
Works standalone in the browser or as a Chrome overlay on Google Meet.

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | None (CPU mode) | NVIDIA 4–8 GB VRAM (RTX 3050+) |
| RAM | 8 GB | 16 GB |
| Disk | 5 GB (models) | 10 GB |
| OS | Windows 10/11, Ubuntu 22.04+ | Windows 11, Ubuntu 22.04 |
| Browser | Chrome 95+ | Chrome latest |

GPU is optional. CPU mode works but TTS latency is ~517 ms vs ~100 ms with GPU.

---

## Software Requirements

- **Python 3.10 or 3.11** — [python.org](https://python.org)
- **Git** — [git-scm.com](https://git-scm.com)
- **Google Chrome 95+**
- **NVIDIA CUDA 12.x + cuDNN 9** *(optional, for GPU TTS)*

---

## Windows Installation

### Step 1 — Clone the repository

```powershell
git clone https://github.com/your-org/smartgen.git
cd smartgen
```

### Step 2 — Run the setup script

```powershell
.\setup.bat
```

The script will:
- Check for Python 3.10+
- Create a `.venv` virtual environment
- Install PyTorch (CPU) and all project dependencies
- Copy `.env.example` → `.env`

For **GPU TTS** after installing cuDNN 9, edit `.env`:

```
ONNX_PROVIDER=CUDAExecutionProvider
```

Then reinstall PyTorch with CUDA:

```powershell
.venv\Scripts\pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/cu121
```

### Step 3 — Download models

Models are downloaded automatically on first server start. They are cached in `models/` (~2–3 GB). Ensure you have an internet connection for the first run.

To pre-download manually:

```powershell
.venv\Scripts\python -c "from server.stt_sherpa import prepare_model; prepare_model()"
.venv\Scripts\python -c "from server.translate.engines.marian_engine import MarianEngine; MarianEngine()"
```

### Step 4 — Start the server

```powershell
.\run.ps1 serve
```

Or directly:

```powershell
.venv\Scripts\python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### Step 5 — Verify the server is running

Open a browser and navigate to:

```
http://localhost:8000/api/health
```

Expected response:

```json
{"stt": "ok", "translate": "ok", "tts": "ok", "version": "0.1.0", "uptime_s": 12}
```

If any subsystem shows `"loading"`, wait 10–20 seconds for models to finish loading, then refresh.

### Step 6 — Open the web app

Navigate to `http://localhost:8000` to use the translation pipeline directly in the browser.

---

## Linux / macOS Installation

### Step 1 — Clone and setup

```bash
git clone https://github.com/your-org/smartgen.git
cd smartgen
bash setup.sh
```

### Step 2 — Start the server

```bash
.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

---

## Chrome Extension (Google Meet Overlay)

### Load the extension in Developer Mode

1. Open Chrome and navigate to `chrome://extensions`
2. Enable **Developer mode** (toggle in top-right)
3. Click **Load unpacked**
4. Select the `extension/` folder inside the smartgen project directory
5. The SmartGen icon appears in the Chrome toolbar

### Using the extension on Google Meet

1. Join or start a Google Meet call at `meet.google.com`
2. A floating **SmartGen** panel appears in the top-right corner
3. Select audio source:
   - **Mic** — captures your microphone (Vietnamese speaker)
   - **Tab Audio** — captures Meet's audio (prompts a share-dialog; select the Meet tab)
4. Click **▶ Start** to begin translation
5. Vietnamese speech is transcribed (VI panel) and translated to English (EN panel)
6. English audio plays through your speakers

### Extension settings (popup)

Click the SmartGen icon in the toolbar to open settings:

- **Server URL** — default `ws://localhost:8000/ws`; change if the server runs on a different host/port
- **Test** — verifies the server is reachable
- **Voice** — TTS voice (populated from the server)
- **Volume** — output volume for English audio

---

## GPU TTS (faster audio, requires cuDNN 9)

Install cuDNN 9 from NVIDIA's website for your CUDA 12.x version, then:

```powershell
# Windows
$env:ONNX_PROVIDER = "CUDAExecutionProvider"
.\run.ps1 serve
```

```bash
# Linux
ONNX_PROVIDER=CUDAExecutionProvider .venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Or set `ONNX_PROVIDER=CUDAExecutionProvider` in your `.env` file for permanent GPU mode.

Expected improvement: TTS first-chunk latency drops from ~517 ms to ~100 ms.

---

## Docker (optional)

```bash
# CPU mode
docker compose up

# GPU mode (requires NVIDIA Container Toolkit)
# Uncomment the 'deploy' section in docker-compose.yml first, then:
docker compose up
```

First run downloads models into the `./models` volume.

---

## STT Backend Selection

Set `STT_BACKEND` in `.env`:

| Value | Description | Latency |
|-------|-------------|---------|
| `sherpa` (default) | Zipformer 30M streaming | 80–150 ms/word |
| `dual` | 30M streaming + Whisper verify pass | 80–150 ms interim, accurate final |
| `phowhisper` | Highest accuracy dual pipeline | ~3 s (better for noisy calls) |

---

## Known Limitations

- **Mic permissions**: Chrome prompts for microphone access on first use — click Allow.
- **Tab audio UX**: `getDisplayMedia` shows a system dialog asking which tab to share. Select the Meet tab. This is a browser security requirement.
- **Windows CRLF**: Git may warn about line ending conversion on Windows — this is harmless.
- **CPU TTS latency**: First audio chunk takes ~517 ms on CPU. Install cuDNN 9 for ~100 ms.
- **Model download**: First server start may take 5–10 minutes to download ~2 GB of models.
- **macOS**: Untested. Should work but audio device names may differ.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/api/health` shows `"loading"` | Models still downloading | Wait 10–20 s and refresh |
| Server crashes on startup (no traceback) | cuDNN missing + CUDAExecutionProvider | Set `ONNX_PROVIDER=CPUExecutionProvider` in `.env` |
| No audio in browser | AudioContext suspended | Click anywhere on the page first |
| Extension panel not showing on Meet | Extension not loaded or URL mismatch | Reload the extension at `chrome://extensions` |
| `tts: "loading"` forever | Kokoro model downloading (~500 MB) | Check server console for download progress |

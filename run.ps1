# One-shot bootstrap + run for the smartgen realtime translate pipeline.
# Usage:
#   .\run.ps1 setup     # create venv, install torch (CUDA 12.1) + deps
#   .\run.ps1 setup-ocr # install optional PaddleOCR OCR deps into .venv
#   .\run.ps1 setup-google-ocr # install optional Google Cloud Vision OCR client
#   .\run.ps1 serve     # launch the FastAPI server on 0.0.0.0:8000

param([Parameter(Position=0)][string]$cmd = "serve")

$ErrorActionPreference = "Stop"
$root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv  = Join-Path $root ".venv"
$py    = Join-Path $venv "Scripts\python.exe"

function Setup {
    if (Test-Path $venv) {
        Write-Host "[setup] removing existing venv..."
        Remove-Item -Recurse -Force $venv
    }
    Write-Host "[setup] creating venv..."
    py -3.11 -m venv $venv
    & $py -m pip install --upgrade pip
    Write-Host "[setup] installing torch (CUDA 12.1)..."
    & $py -m pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/cu121
    Write-Host "[setup] installing project deps..."
    & $py -m pip install -r (Join-Path $root "requirements.txt")
    Write-Host "[setup] done. Run: .\run.ps1 serve"
}

function SetupOcr {
    if (-not (Test-Path $py)) { throw "venv missing - run: .\run.ps1 setup" }
    Write-Host "[setup-ocr] installing optional OCR deps (PaddleOCR CPU + Pillow)..."
    & $py -m pip install --upgrade pillow pytesseract paddleocr paddlepaddle
    Write-Host "[setup-ocr] done. For GPU Paddle, replace paddlepaddle with paddlepaddle-gpu matching your CUDA version."
}

function SetupGoogleOcr {
    if (-not (Test-Path $py)) { throw "venv missing - run: .\run.ps1 setup" }
    Write-Host "[setup-google-ocr] installing optional Google Cloud Vision client..."
    & $py -m pip install --upgrade google-cloud-vision
    Write-Host "[setup-google-ocr] done. Set GOOGLE_APPLICATION_CREDENTIALS to your service-account JSON file before serving."
}

function Serve {
    if (-not (Test-Path $py)) { throw "venv missing - run: .\run.ps1 setup" }
    Set-Location $root

    # ── Load .env if present ─────────────────────────────────────────────────
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
                $k = $Matches[1].Trim(); $v = $Matches[2].Trim()
                if (-not [System.Environment]::GetEnvironmentVariable($k)) {
                    [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
                }
            }
        }
    }

    $env:PYTHONUNBUFFERED     = "1"
    $env:PYTHONUTF8           = "1"
    $env:KMP_DUPLICATE_LIB_OK = "TRUE"
    if (-not $env:STT_BACKEND)       { $env:STT_BACKEND       = "phowhisper" }
    if (-not $env:TRANSLATE_BACKEND) { $env:TRANSLATE_BACKEND  = "nllb-600m" }
    if (-not $env:NLLB_DEVICE)       { $env:NLLB_DEVICE        = "cpu" }
    if (-not $env:NLLB_INTRA_THREADS){ $env:NLLB_INTRA_THREADS = "6" }
    if (-not $env:DEBUG_LOG)         { $env:DEBUG_LOG          = "1" }
    if (-not $env:MAX_SPEECH_S)      { $env:MAX_SPEECH_S       = "6.0" }
    # NLLB on CPU (int8) frees the GPU for PhoWhisper and avoids CUDA contention
    # between the two models — measured fix for slow translation in Studio mode.
    if (-not $env:NLLB_DEVICE)        { $env:NLLB_DEVICE        = "cpu" }
    if (-not $env:NLLB_INTRA_THREADS) { $env:NLLB_INTRA_THREADS = "6" }
    # Suppress torio FFmpeg extension search noise (FFmpeg not installed — expected)
    $env:NO_FFMPEG = "1"

    Write-Host "[serve] STT=$env:STT_BACKEND  TRANSLATE=$env:TRANSLATE_BACKEND  NLLB_DEVICE=$env:NLLB_DEVICE  NLLB_INTRA_THREADS=$env:NLLB_INTRA_THREADS  DEBUG_LOG=$env:DEBUG_LOG  MAX_SPEECH_S=$env:MAX_SPEECH_S"
    & $py -m uvicorn server.main:app --host 0.0.0.0 --port 8000
}

switch ($cmd) {
    "setup" { Setup }
    "setup-ocr" { SetupOcr }
    "setup-google-ocr" { SetupGoogleOcr }
    "serve" { Serve }
    default { Write-Host "usage: .\run.ps1 [setup|setup-ocr|setup-google-ocr|serve]" }
}

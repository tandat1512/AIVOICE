"""
FastAPI WebSocket gateway.

Wire protocol:
    client -> server
        binary : raw Int16 PCM mono @ 16000 Hz (any chunk size)
        text   : JSON {"type": "config", "src": "vi", "tgt": "en"}
                      {"type": "stop"}

    server -> client (JSON)
        {"type": "word",    "word": "Chào", "translation": "Hello", "final": true}
        {"type": "interim", "text": "...",  "translation": "..."}
        {"type": "commit",  "text": "...",  "translation": "..."}
        {"type": "info",    "msg":  "..."}
        {"type": "error",   "msg":  "..."}
        {"type": "sync",    "committed": "...", "interim": "..."}
        {"type": "trans_stream_c", "token": "..."}
        {"type": "trans_stream_i", "token": "..."}
        {"type": "clear_trans_i"}

Pipeline:
    PCM 16 kHz
      -> StreamingASR (sherpa-onnx Zipformer 30M, ~80-150 ms/word)
        [dual mode: + Whisper CT2 verify pass after each commit]
      -> StreamingTranslationRouter (NLLB-200 fast path, ~30-80ms/chunk)

Backends (STT_BACKEND env var):
    "sherpa"     (default) — Zipformer 30M, sliding-window RNNT, ~80-200 ms/update
    "dual"                 — 30M real-time display + Whisper CT2 verify pass
    "whisper"              — faster-whisper CT2 (EraX-WoW-Turbo or any CT2 model)
    "phowhisper"           — 6-layer accuracy-first dual (Silero VAD + Sherpa interim +
                             PhoWhisper-large verify + merge engine). Word-by-word commit,
                             never deletes. Accept ~3s latency for high accuracy.
                             Env: DEMUCS=1 (vocals separation, optional, slow)
                                  DOMAIN_HINT="..." (initial prompt context)
                                  PHOWHISPER_TIMEOUT_S=15 (max verify wait)
"""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import threading
import uuid
from pathlib import Path

import time as _time_module

multiprocessing.freeze_support()
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

_START_TIME = _time_module.monotonic()

import numpy as np
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

_STT_BACKEND = os.environ.get("STT_BACKEND", "phowhisper").lower()
_DEBUG_WS    = os.environ.get("DEBUG_WS", "0") == "1"

from .debug_log import dlog, is_enabled as _debug_enabled, olog, obs_enabled

if _debug_enabled():
    # Surface StreamingTranslationRouter's per-chunk telemetry (translate_ms,
    # cụm dispatch order) on stdout. These use logging.info(), which is silent
    # by default under uvicorn's logging config.
    _router_logger = logging.getLogger("server.translate.streaming_router")
    _router_logger.setLevel(logging.INFO)
    _router_handler = logging.StreamHandler()
    _router_handler.setFormatter(logging.Formatter("%(message)s"))
    _router_logger.addHandler(_router_handler)
    _router_logger.propagate = False

from .translate import StreamingTranslationRouter
from .translate.engines.base import BaseEngine
from .translate.engines.marian_engine import MarianEngine
from .translate.engines.nllb_engine import NLLBEngine
from .tts.engines.kokoro_engine import KokoroEngine, DEFAULT_VOICE
from .tts.dispatcher import TTSDispatcher
from .routes.audio_translate import create_audio_translate_router
from .routes.currency import create_currency_router
from .routes.export import create_export_router
from .routes.glossary import create_glossary_router
from .routes.image_translate import create_image_translate_router
from .routes.memory import create_memory_router
from .routes.text_translate import create_text_translate_router
from .routes.travel import create_travel_router
from .routes.youtube_dub import create_youtube_dub_router
from .services.audio_file_service import AudioFileService
from .services.currency_service import CurrencyService
from .services.export_service import ExportService
from .services.glossary_service import GlossaryService
from .services.ocr_service import OcrService
from .services.translation_memory_service import TranslationMemoryService
from .services.travel_service import TravelService
from .services.translator_service import TranslatorService

# Translation engine backend: "nllb-600m" (default) | "marian" (77M, fast) | "nllb-1.3b" (1.3B).
# Legacy "nllb" maps to "nllb-600m" for backward compat.
_TRANSLATE_BACKEND = os.environ.get("TRANSLATE_BACKEND", "nllb-600m").lower()
if _TRANSLATE_BACKEND == "nllb":
    _TRANSLATE_BACKEND = "nllb-600m"

_TRANSLATE_MODELS = {
    "marian": {
        "id": "marian", "name": "Marian opus-mt-vi-en (77M)",
        "speed": "fast", "quality": "good",
    },
    "nllb-600m": {
        "id": "nllb-600m", "name": "NLLB-200 distilled (600M)",
        "speed": "medium", "quality": "better",
    },
    "nllb-1.3b": {
        "id": "nllb-1.3b", "name": "NLLB-200 distilled (1.3B)",
        "speed": "slow", "quality": "best",
    },
}

# kokoro-onnx auto-detection of onnxruntime-gpu is broken (checks for a package
# named "onnxruntime-gpu" but onnxruntime is the import name). Default to CPU
# because attempting CUDAExecutionProvider when cuDNN is absent crashes the
# onnxruntime session (not a graceful fallback). Set ONNX_PROVIDER=CUDAExecutionProvider
# in the environment after installing cuDNN 9 to enable GPU TTS.
os.environ.setdefault("ONNX_PROVIDER", "CPUExecutionProvider")

HERE = Path(__file__).resolve().parent
WEB  = HERE.parent / "web"

_models: dict[str, object] = {}       # backend name -> loaded model (cached singleton)
_engine_pool: dict[str, BaseEngine] = {}   # translate model key -> engine instance
_tts_engine: KokoroEngine | None = None
_tts_dispatcher: TTSDispatcher | None = None
_perf_sampler_stop: threading.Event | None = None
_perf_sampler_thread: threading.Thread | None = None
_tts_error: str = ""
_model_lock       = threading.Lock()
_engine_pool_lock = threading.Lock()
_tts_lock         = threading.Lock()


def _backend_modules(backend: str):
    """Return (StreamingASR, prepare_model, load_model) for a backend name."""
    if backend == "dual":
        from .stt_dual import StreamingASR, prepare_model, load_model
    elif backend == "whisper":
        from .stt_whisper import StreamingASR, prepare_model, load_model
    elif backend == "whisper_en":
        from .stt_whisper_en import StreamingASR, prepare_model, load_model
    elif backend == "phowhisper":
        from .stt_phowhisper_dual import StreamingASR, prepare_model, load_model
    else:
        from .stt_sherpa import StreamingASR, prepare_model, load_model
    return StreamingASR, prepare_model, load_model


# Backends that keep their model resident on the GPU. The 4GB card only fits
# one of these at a time, so switching between them (e.g. vi <-> en Meet mode)
# unloads whichever one is currently cached before loading the new one.
_GPU_STT_BACKENDS = {"phowhisper", "dual", "whisper", "whisper_en"}


def _unload_model_locked(backend: str) -> None:
    """Drop a cached model and free its VRAM. Caller must hold _model_lock."""
    model = _models.pop(backend, None)
    if model is None:
        return
    del model
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    print(f"[Model] unloaded {backend}", flush=True)


def _get_or_load_model(backend: str = ""):
    """Load+cache the model for *backend* (defaults to the configured backend).

    Cached per backend so reconnecting (or switching backends) never re-pays the
    multi-second model load. PhoWhisper-large (~1.5 GB) in particular must be
    loaded exactly once for the process lifetime.

    Switching between GPU-resident STT backends (_GPU_STT_BACKENDS) unloads the
    previously-cached one first, so only one such model is resident at a time.
    """
    backend = (backend or _STT_BACKEND).lower()
    with _model_lock:
        if backend not in _models:
            if backend in _GPU_STT_BACKENDS:
                for other in [b for b in _models if b != backend and b in _GPU_STT_BACKENDS]:
                    _unload_model_locked(other)
            _, prepare_model, load_model = _backend_modules(backend)
            path = prepare_model()
            _models[backend] = load_model(path)
    return _models[backend]


def _get_engine(name: str = "") -> BaseEngine:
    """Return (lazy-load + cache) the translation engine for *name*.

    Falls back to _TRANSLATE_BACKEND when name is empty or unknown.
    """
    key = name.lower() if name else _TRANSLATE_BACKEND
    if key == "nllb":          # legacy alias
        key = "nllb-600m"
    if key not in _TRANSLATE_MODELS:
        key = _TRANSLATE_BACKEND
    with _engine_pool_lock:
        if key not in _engine_pool:
            if key == "nllb-1.3b":
                from .translate.engines.nllb_1b_engine import NLLB1BEngine
                print("[Translate] loading nllb-1.3b (first request)", flush=True)
                _engine_pool[key] = NLLB1BEngine()
            elif key == "nllb-600m":
                print("[Translate] loading nllb-600m", flush=True)
                _engine_pool[key] = NLLBEngine()
            else:
                print("[Translate] loading marian", flush=True)
                _engine_pool[key] = MarianEngine()
    return _engine_pool[key]


def _get_envi_engine() -> BaseEngine:
    """Lazy-load + cache the en→vi engine (Marian opus-mt-en-vi).

    Selected by translation direction (src=en, tgt=vi), not by the user-facing
    translate_model picker, so it lives outside _TRANSLATE_MODELS. Reuses the
    shared engine pool/lock under a reserved key.
    """
    key = "marian-en-vi"
    with _engine_pool_lock:
        if key not in _engine_pool:
            from .translate.engines.marian_envi_engine import MarianEnViEngine
            print("[Translate] loading marian en-vi", flush=True)
            _engine_pool[key] = MarianEnViEngine()
    return _engine_pool[key]


def _get_or_load_tts() -> TTSDispatcher:
    """Load Kokoro TTS engine + dispatcher (singleton across WS sessions)."""
    global _tts_engine, _tts_dispatcher, _tts_error
    with _tts_lock:
        if _tts_dispatcher is None:
            try:
                _tts_engine = KokoroEngine()
                _tts_engine.warmup()
                _tts_dispatcher = TTSDispatcher(_tts_engine)
                _tts_error = ""
            except Exception as exc:
                _tts_engine = None
                _tts_dispatcher = None
                _tts_error = str(exc)
                raise
    return _tts_dispatcher


def _try_get_or_load_tts() -> TTSDispatcher | None:
    """Best-effort TTS loader. Voice translation must keep working without TTS."""
    try:
        return _get_or_load_tts()
    except Exception as exc:  # noqa: BLE001 - keep server and WebSocket alive.
        print(f"[TTS] disabled: {exc}", flush=True)
        return None


app = FastAPI(title="smartgen realtime translate")

_glossary_service = GlossaryService()
_memory_service = TranslationMemoryService()
_translator_service = TranslatorService(
    get_engine=_get_engine,
    get_envi_engine=_get_envi_engine,
    default_model=_TRANSLATE_BACKEND,
    glossary_service=_glossary_service,
    memory_service=_memory_service,
)
_currency_service = CurrencyService()
_ocr_service = OcrService()
_audio_file_service = AudioFileService(get_whisper_model=lambda: _get_or_load_model("whisper"))
_export_service = ExportService()
_travel_service = TravelService(
    translator_service=_translator_service,
    currency_service=_currency_service,
)
app.include_router(create_text_translate_router(_translator_service))
app.include_router(create_youtube_dub_router(_get_engine))
app.include_router(create_currency_router(_currency_service))
app.include_router(create_glossary_router(_glossary_service))
app.include_router(create_memory_router(_memory_service))
app.include_router(create_export_router(_export_service))
app.include_router(create_image_translate_router(
    ocr_service=_ocr_service,
    translator_service=_translator_service,
    currency_service=_currency_service,
))
app.include_router(create_audio_translate_router(
    audio_service=_audio_file_service,
    translator_service=_translator_service,
))
app.include_router(create_travel_router(
    travel_service=_travel_service,
    ocr_service=_ocr_service,
))


def _warmup_translation() -> None:
    """Prime the default translation engine's CTranslate2 JIT cache with a dummy call."""
    engine = _get_engine()
    if isinstance(engine, NLLBEngine):
        warmup_ms = engine.warmup()
        print(f"[NLLB] warmup done in {warmup_ms}ms", flush=True)
        return

    t0 = _time_module.perf_counter()
    for _ in engine.translate_stream("xin chào", "vie_Latn", "eng_Latn"):
        pass
    warmup_ms = round((_time_module.perf_counter() - t0) * 1000)
    print(f"[Translate] warmup done in {warmup_ms}ms (backend={_TRANSLATE_BACKEND})", flush=True)
    if _TRANSLATE_BACKEND.startswith("nllb"):
        # Dedicated NLLB warmup marker (mirrors the [NLLB] device=... boot line)
        # so the one-time cold-decode outlier is paid here, not on first request.
        print(f"[NLLB] warmup done (backend={_TRANSLATE_BACKEND})", flush=True)


def _warmup_engine(key: str) -> None:
    """Warm up a translation engine by key if its CT2 dir already exists on disk."""
    from pathlib import Path as _P
    models_dir = HERE.parent / "models"
    ct2_dirs = {
        "nllb-600m": models_dir / "nllb-200-distilled-600M-ct2",
        "nllb-1.3b": models_dir / "nllb-200-distilled-1.3B-ct2",
    }
    ct2_dir = ct2_dirs.get(key)
    if ct2_dir and not ct2_dir.exists():
        return   # not downloaded yet — skip, don't trigger download
    engine = _get_engine(key)
    for _ in engine.translate_stream("xin chào", "vie_Latn", "eng_Latn"):
        pass
    print(f"[Translate] background warmup done ({key})", flush=True)


def _start_perf_sampler() -> None:
    """Log CPU and free RAM every 500ms when DEBUG_LOG=1."""
    global _perf_sampler_stop, _perf_sampler_thread
    if not _debug_enabled() or _perf_sampler_thread is not None:
        return

    stop = threading.Event()
    _perf_sampler_stop = stop

    def _sample() -> None:
        try:
            import psutil
        except Exception as e:
            print(f"[PERF] sampler disabled: {e}", flush=True)
            return

        proc = psutil.Process()
        proc.cpu_percent(None)
        psutil.cpu_percent(None)
        while not stop.wait(0.5):
            vm = psutil.virtual_memory()
            dlog(
                "PERF",
                "sample",
                cpu_pct=round(psutil.cpu_percent(None), 1),
                proc_cpu_pct=round(proc.cpu_percent(None), 1),
                ram_free_mb=round(vm.available / 1024 / 1024),
            )

    _perf_sampler_thread = threading.Thread(target=_sample, name="perf_sampler", daemon=True)
    _perf_sampler_thread.start()


@app.on_event("startup")
async def _warm() -> None:
    _start_perf_sampler()
    await asyncio.to_thread(_warmup_translation)
    # Pre-warm non-default NLLB models in background so the first session that
    # selects them doesn't pay the 8-15 s model-load latency.
    for _key in ("nllb-600m", "nllb-1.3b"):
        if _key != _TRANSLATE_BACKEND:
            asyncio.get_event_loop().run_in_executor(None, _warmup_engine, _key)
    # Preload the configured STT backend so the first WS connection is instant
    # instead of paying the model load (PhoWhisper-large ~1.5 GB = 12-19 s).
    await asyncio.to_thread(_get_or_load_model, _STT_BACKEND)
    # TTS load is heavy (~330 MB model download on first run) — keep async
    if os.environ.get("TTS_WARMUP", "1") != "0":
        await asyncio.to_thread(_try_get_or_load_tts)
    if os.environ.get("OCR_WARMUP", "0").strip().lower() in {"1", "true", "yes"}:
        asyncio.get_event_loop().run_in_executor(None, _ocr_service.warmup)


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _tts_dispatcher
    if _perf_sampler_stop is not None:
        _perf_sampler_stop.set()
    if _tts_dispatcher is not None:
        _tts_dispatcher.shutdown()


@app.websocket("/ws/stt")
async def ws_stt_endpoint(sock: WebSocket) -> None:
    """Lightweight STT-only WebSocket for the YouTube dub aligner.

    Runs the fast Sherpa transducer on incoming 16 kHz Int16 PCM and streams back
    {"type":"stt","committed":...,"interim":...} only. No translation, no TTS, so
    it stays cheap. The dub player matches this rough text against the YouTube
    transcript (/api/youtube/align) to anchor position, then dubs from the
    transcript. ?lang=vi|en picks the recognizer language (needs a matching Sherpa
    model on disk; defaults to the configured sherpa model).
    """
    await sock.accept()
    loop = asyncio.get_running_loop()
    out_q: asyncio.Queue = asyncio.Queue()

    def on_update(committed, interim="", *_a, **_k):
        try:
            loop.call_soon_threadsafe(
                out_q.put_nowait, {"type": "stt", "committed": committed, "interim": interim}
            )
        except Exception:
            pass

    try:
        from .stt_sherpa import StreamingASR as _SherpaASR
        model = await asyncio.to_thread(_get_or_load_model, "sherpa")
        asr = _SherpaASR(on_update, model, "vi")
    except Exception as e:  # noqa: BLE001
        try:
            await sock.send_text(json.dumps({"type": "error", "msg": f"STT load: {e}"}))
        except Exception:
            pass
        return

    async def _sender() -> None:
        try:
            while True:
                msg = await out_q.get()
                await sock.send_text(json.dumps(msg))
        except Exception:
            pass

    send_task = asyncio.create_task(_sender())
    try:
        await sock.send_text(json.dumps({"type": "info", "msg": "stt_ready"}))
        while True:
            m = await sock.receive()
            if m.get("type") == "websocket.disconnect":
                break
            b = m.get("bytes")
            if b:
                pcm = np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0
                asr.feed_pcm(pcm)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"[WS/stt] {e}", flush=True)
    finally:
        send_task.cancel()
        try:
            asr.stop()
        except Exception:
            pass

app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(WEB / "smartgen" / "SmartGen.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/api/health")
async def health_check():
    """Return subsystem status for extension connectivity check."""
    stt_ok       = len(_models) > 0
    translate_ok = bool(_engine_pool)
    tts_ok       = _tts_dispatcher is not None

    status = {
        "stt":       "ok" if stt_ok       else "loading",
        "translate": "ok" if translate_ok else "loading",
        "tts":       "ok" if tts_ok       else ("unavailable" if _tts_error else "loading"),
        "version":   "0.1.0",
        "uptime_s":  round(_time_module.monotonic() - _START_TIME),
    }
    if _tts_error:
        status["tts_error"] = _tts_error

    all_ok = stt_ok and translate_ok
    return Response(
        content=json.dumps(status),
        media_type="application/json",
        status_code=200 if all_ok else 503,
    )


@app.get("/api/tts/voices")
async def list_tts_voices():
    """Return available TTS voices and the default selection."""
    try:
        dispatcher = _get_or_load_tts()
        voices = _tts_engine.list_voices() if _tts_engine else []
    except Exception as exc:  # noqa: BLE001 — surface in JSON
        return {"voices": [], "default": "", "error": str(exc)}
    return {
        "voices": [{"id": v, "name": v, "lang": "en"} for v in voices],
        "default": DEFAULT_VOICE,
        "sample_rate": _tts_engine.sample_rate if _tts_engine else 24000,
    }


@app.post("/api/tts/say")
async def tts_say(req: Request):
    """Synthesize one line of text → raw Int16 PCM (used by the UI 'replay' button).

    Body: {"text": "...", "voice": "af_heart"}. Unknown/empty voice → DEFAULT_VOICE.
    Response: application/octet-stream, with X-Sample-Rate header.
    """
    try:
        body = await req.json()
    except Exception:
        return Response(status_code=400)
    text = (body.get("text") or "").strip()
    voice = (body.get("voice") or "").strip()
    if not text:
        return Response(status_code=400)

    try:
        _get_or_load_tts()  # ensure Kokoro engine is loaded
    except Exception as exc:  # noqa: BLE001 - tell the client TTS is unavailable.
        return Response(content=str(exc), status_code=503)
    engine = _tts_engine
    if engine is None:
        return Response(status_code=503)

    try:
        valid = set(engine.list_voices())
    except Exception:
        valid = set()
    chosen = voice if voice in valid else DEFAULT_VOICE

    def _synth() -> bytes:
        return b"".join(engine.synthesize_stream(text, chosen))

    try:
        pcm = await asyncio.to_thread(_synth)
    except Exception as exc:  # noqa: BLE001 — surface as 500
        return Response(content=str(exc), status_code=500)

    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(engine.sample_rate), "Cache-Control": "no-store"},
    )


def _serveable_backends() -> set:
    """STT backends whose model files are present on disk, so a session may load
    them on demand. Mirrors the availability logic in /api/models (list_models)
    so the UI's STT model picker is actually honored, without allowing a backend
    whose (possibly multi-GB) model has not been downloaded yet."""
    models_dir = HERE.parent / "models"
    def _has(*parts: str) -> bool:
        return models_dir.joinpath(*parts).exists()
    backends = set()
    fast_ok = _has("sherpa-onnx-zipformer-vi-30M-int8-2026-02-09", "tokens.txt")
    gipformer_ok = _has("gipformer-65M-rnnt", "tokens.txt")
    erax_ok = _has("EraX-WoW-Turbo-V1.1-CT2", "model.bin")
    if fast_ok or gipformer_ok:
        backends.add("sherpa")
    if fast_ok and erax_ok:
        backends.add("dual")
    if erax_ok:
        backends.add("whisper")
    if fast_ok and any(_has(d, "model.bin") for d in ("phowhisper-large", "phowhisper-medium")):
        backends.add("phowhisper")
    return backends

@app.get("/api/models")
async def list_models():
    """Return available STT models and current active backend."""
    from pathlib import Path as _P
    models_dir = HERE.parent / "models"

    available = []

    fast_ok = (_P(models_dir) / "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09" / "tokens.txt").exists()
    zzasdf_ok = (_P(models_dir) / "sherpa-onnx-zipformer-vi-2025-04-20" / "tokens.txt").exists()
    gipformer_ok = (_P(models_dir) / "gipformer-65M-rnnt" / "tokens.txt").exists()
    erax_ok = (_P(models_dir) / "EraX-WoW-Turbo-V1.1-CT2" / "model.bin").exists()

    if fast_ok:
        available.append({
            "id":      "sherpa",
            "name":    "Zipformer 30M (streaming)",
            "desc":    "hynt/VLSP-2025 · 6k hrs · streaming native · ~80-150 ms/word",
            "backend": "sherpa",
            "model":   "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09",
        })

    if fast_ok and erax_ok:
        available.append({
            "id":      "dual",
            "name":    "Dual: 30M + EraX Whisper ★",
            "desc":    "30M streaming display · EraX Whisper verify pass · better accuracy than 30M alone",
            "backend": "dual",
            "model":   "dual",
        })

    if gipformer_ok and not fast_ok:
        available.append({
            "id":      "gipformer",
            "name":    "Gipformer 65M (streaming)",
            "desc":    "g-group-ai-lab · best WER on Vietnamese benchmarks · streaming native",
            "backend": "sherpa",
            "model":   "gipformer-65M-rnnt",
        })

    if erax_ok:
        available.append({
            "id":      "erax",
            "name":    "EraX-WoW-Turbo V1.1 (Whisper)",
            "desc":    "erax-ai · Whisper Large-v3 Turbo · 8 giong Viet · ~350 ms/30s",
            "backend": "whisper",
            "model":   "erax-ai/EraX-WoW-Turbo-V1.1-CT2",
        })

    phowhisper_ok = any(
        ((_P(models_dir) / d) / "model.bin").exists()
        for d in ["phowhisper-large", "phowhisper-medium"]
    )
    if phowhisper_ok and fast_ok:
        demucs_hint = " · DEMUCS=1 cho YouTube"
        available.append({
            "id":      "phowhisper",
            "name":    "Accuracy: Sherpa + PhoWhisper ★★★",
            "desc":    (
                "6-layer pipeline · Silero VAD · Sherpa interim · PhoWhisper verify "
                "· merge engine · ~3s latency · highest accuracy" + demucs_hint
            ),
            "backend": "phowhisper",
            "model":   "phowhisper",
        })

    return {
        "available": available,
        "active": {
            "backend": _STT_BACKEND,
            "model":   os.environ.get("STT_MODEL", "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09"),
        },
    }


@app.get("/api/translate/models")
async def list_translate_models():
    """Return available translation models and server default."""
    return {
        "models":  list(_TRANSLATE_MODELS.values()),
        "default": _TRANSLATE_BACKEND,
    }


@app.websocket("/ws")
async def ws_endpoint(sock: WebSocket) -> None:
    await sock.accept()
    loop   = asyncio.get_running_loop()
    # send_q carries either dict (JSON event) or bytes (TTS audio chunk)
    send_q: asyncio.Queue = asyncio.Queue()

    src = "vi"
    tgt = "en"
    _sid = uuid.uuid4().hex[:8]   # unique session id for log correlation

    tts_dispatcher = await asyncio.to_thread(_try_get_or_load_tts)

    # engine + router are built after the config message is parsed so per-session
    # translate_model selection works. The closure binds lazily — only invoked
    # once the ASR starts, after router is assigned.
    engine: BaseEngine | None = None
    router: StreamingTranslationRouter | None = None
    asr = None
    res_task: asyncio.Task | None = None
    _stt_update_t: list[float] = [0.0]   # mutable cell for closure

    def on_stt_update(
        committed: str,
        interim: str,
        silence_ms: int = 0,
        is_final: bool = False,
        final_text: str = "",
        seg_id: str = "",
        correction: str = "",
        speaker: int = 0,
        stt_ms: "int | str" = "n/a",
    ) -> None:
        now = _time_module.monotonic()
        if _stt_update_t[0]:
            interval_ms = round((now - _stt_update_t[0]) * 1000)
        else:
            interval_ms = 0
        _stt_update_t[0] = now
        dlog("STT", "update", sid=_sid,
             committed_len=len(committed), interim_len=len(interim),
             is_final=is_final, seg_id=seg_id or "-",
             interval_ms=interval_ms)
        router.on_stt_update(
            committed, interim, loop, send_q, src, tgt,
            silence_ms=silence_ms, is_final=is_final, final_text=final_text,
            seg_id=seg_id, correction=correction, speaker=speaker,
            stt_ms=stt_ms,
        )

    # ── WebSocket sender (handles JSON events + binary audio chunks) ─────────

    async def sender() -> None:
        while True:
            msg = await send_q.get()
            if isinstance(msg, (bytes, bytearray)):
                await sock.send_bytes(msg)
                continue
            if _DEBUG_WS:
                t = msg.get("type", "?")
                if t == "word":
                    print(f"  [WS->] WORD  '{msg.get('word','')}' | tr='{msg.get('translation','')[:30]}'", flush=True)
                elif t == "sync":
                    print(f"  [WS->] SYNC c='{msg.get('committed','')[-40:]}' | i='{msg.get('interim','')[:60]}'", flush=True)
                else:
                    print(f"  [WS->] {t}", flush=True)
            await sock.send_text(json.dumps(msg, ensure_ascii=False))

    sender_task = asyncio.create_task(sender())

    _last_pcm_t: list[float] = [0.0]   # mutable cell for gap detector closure
    _pcm_chunk_count: list[int] = [0]

    try:
        try:
            first_msg = await asyncio.wait_for(sock.receive(), timeout=10.0)
        except TimeoutError:
            await sock.send_text(json.dumps({
                "type": "error",
                "msg": "WebSocket config timeout",
            }))
            return
        session_backend = _STT_BACKEND
        translate_model = ""
        voice = ""
        vad_ms = 0
        lock_ms = 0
        if "text" in first_msg and first_msg["text"]:
            try:
                cfg = json.loads(first_msg["text"])
                if cfg.get("type") == "config":
                    src = cfg.get("src", src)
                    tgt = cfg.get("tgt", tgt)
                    if cfg.get("backend"):
                        requested = cfg["backend"]
                        # Only honor a client backend override the server can
                        # actually serve (the configured backend, or one already
                        # loaded). Otherwise a stale UI can force a heavy
                        # unconfigured model (e.g. PhoWhisper-large) whose multi-GB
                        # download runs under the global model lock and jams every
                        # other session. Fall back to the configured backend.
                        if requested == _STT_BACKEND or requested in _models or requested in _serveable_backends():
                            session_backend = requested
                        elif requested:
                            print(f"[WS] backend '{requested}' unavailable; using '{_STT_BACKEND}'", flush=True)
                    translate_model = cfg.get("translate_model", "")
                    voice = cfg.get("voice", "") or ""
                    vad_ms = int(cfg.get("vad", 0) or 0)
                    lock_ms = int(cfg.get("lock_ms", 0) or 0)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        engine = _get_engine(translate_model)
        effective_model = translate_model or _TRANSLATE_BACKEND
        print(f"[Translate] session uses {effective_model}", flush=True)
        dlog("WS", "session_config", sid=_sid,
             backend=session_backend, src=src, tgt=tgt,
             translate=effective_model, voice=voice or DEFAULT_VOICE, vad_ms=vad_ms)
        olog("CFG", sid=_sid, backend=session_backend, src=src, tgt=tgt,
             translate_model=effective_model, voice=voice or DEFAULT_VOICE,
             nllb_device=os.environ.get("NLLB_DEVICE", "auto"))

        if session_backend == "whisper_en":
            try:
                import torch as _torch_chk
                _stt_dev = "cuda" if _torch_chk.cuda.is_available() else "cpu"
            except Exception:
                _stt_dev = "cpu"
            _mt_name = "NLLB" if effective_model.startswith("nllb") else "Marian"
            olog("CFG", sid=_sid, stt="whisper-large-v3-turbo", stt_dev=_stt_dev,
                 mt=_mt_name, mt_dev=os.environ.get("NLLB_DEVICE", "auto"),
                 tts="Piper-vi (GD2)")

        await sock.send_text(json.dumps({"type": "info", "msg": "loading STT model..."}))

        # PhoWhisper uses wait-final dispatch (translate + TTS only on confirmed
        # segments) so already-spoken audio is never re-spoken. Streaming backends
        # keep the legacy committed-delta dispatch.
        router = StreamingTranslationRouter(
            engine=engine,
            tts_dispatcher=tts_dispatcher,
            tts_voice=voice or DEFAULT_VOICE,
            wait_final=(session_backend == "phowhisper"),
            sid=_sid,
        )

        if obs_enabled():
            import psutil as _res_psutil
            import subprocess as _res_subprocess

            _res_proc = _res_psutil.Process()
            _res_proc.cpu_percent(None)
            _res_psutil.cpu_percent(None)

            def _vram_mb() -> str:
                try:
                    out = _res_subprocess.run(
                        ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                         "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=1,
                    )
                    used, total = out.stdout.strip().split(",")
                    return f"{used.strip()}/{total.strip()}"
                except Exception:
                    return "n/a"

            async def _res_logger() -> None:
                while True:
                    await asyncio.sleep(2.0)
                    tts_qdepth = tts_dispatcher.pending_count(router._session_id) if tts_dispatcher else 0
                    vm = _res_psutil.virtual_memory()
                    vram = await asyncio.to_thread(_vram_mb)
                    olog("RES", sid=_sid,
                         t=_time_module.strftime("%H:%M:%S"),
                         cpu=round(_res_psutil.cpu_percent(None), 1),
                         ram_free=round(vm.available / (1024 ** 3), 1),
                         vram=vram,
                         tts_qdepth=tts_qdepth,
                         translate_active=router.active_translations())

            res_task = asyncio.create_task(_res_logger())

        try:
            # Cached per backend — first connection pays the load, the rest are
            # instant (no more 12-19 s reload of PhoWhisper-large per connection).
            ASR, _, _ = _backend_modules(session_backend)
            model = await asyncio.to_thread(_get_or_load_model, session_backend)
            asr   = ASR(on_stt_update, model, src)
            # Apply the UI's VAD endpoint setting if the backend supports it.
            if vad_ms and hasattr(asr, "set_silence_ms"):
                asr.set_silence_ms(vad_ms)
            # SEGMENTER=v2: apply the UI's hold->lock threshold if supported.
            if lock_ms and hasattr(asr, "set_lock_ms"):
                asr.set_lock_ms(lock_ms)
        except Exception as e:
            await sock.send_text(json.dumps({"type": "error", "msg": f"STT init: {e}"}))
            return

        await sock.send_text(json.dumps({
            "type":    "info",
            "msg":     "ready",
            "backend": session_backend,
        }))

        while True:
            msg = await sock.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                pcm = np.frombuffer(msg["bytes"], dtype=np.int16)
                if pcm.size:
                    now_t = _time_module.monotonic()
                    if _last_pcm_t[0] > 0:
                        gap_ms = round((now_t - _last_pcm_t[0]) * 1000)
                        if gap_ms > 150:
                            dlog("WS", "pcm_gap_warn", sid=_sid,
                                 gap_ms=gap_ms, chunks_so_far=_pcm_chunk_count[0])
                    _last_pcm_t[0] = now_t
                    _pcm_chunk_count[0] += 1
                    asr.feed_pcm(pcm.astype(np.float32) / 32768.0)
            elif "text" in msg and msg["text"]:
                try:
                    ctrl = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if ctrl.get("type") == "config":
                    src = ctrl.get("src", src)
                    tgt = ctrl.get("tgt", tgt)
                    if asr is not None:
                        asr.language = src
                    if ctrl.get("voice") and router is not None:
                        router.set_voice(ctrl["voice"])
                    if ctrl.get("vad") and asr is not None and hasattr(asr, "set_silence_ms"):
                        try:
                            asr.set_silence_ms(int(ctrl["vad"]))
                        except (ValueError, TypeError):
                            pass
                    if ctrl.get("lock_ms") and asr is not None and hasattr(asr, "set_lock_ms"):
                        try:
                            asr.set_lock_ms(int(ctrl["lock_ms"]))
                        except (ValueError, TypeError):
                            pass
                    await sock.send_text(json.dumps(
                        {"type": "info", "msg": f"lang {src}→{tgt}"}
                    ))
                elif ctrl.get("type") == "stop":
                    break

    except WebSocketDisconnect:
        pass
    finally:
        if router is not None:
            router.reset()

        if asr is not None:
            try:
                await asyncio.to_thread(asr.finalize)
            except Exception:
                pass
            asr.stop()
        if res_task is not None:
            res_task.cancel()
        sender_task.cancel()

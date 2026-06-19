"""YouTube real-time dubbing backend (STT-aligned).

Flow (the player drives it):
  1. GET  /api/youtube/transcript  - fetch + sentence-merge captions, cache them.
  2. Client captures the YouTube tab audio and streams it to /ws (stt_only) to get
     fast, rough STT text in real time.
  3. POST /api/youtube/align - fuzzy-match the rolling STT text against the cached
     transcript to find WHERE in the video we are (drift-proof position anchor).
  4. POST /api/youtube/translate - NLLB-translate the matched *transcript* sentence
     (accurate text, not the rough STT).
  5. POST /api/youtube/tts - Vietnamese VITS speaks it. Upcoming sentences are
     prepared ahead using transcript timestamps, so playback stays real-time.

STT is only a position anchor; the dubbed text always comes from the transcript.
"""
from __future__ import annotations

import ctypes
import os
import re
import threading
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")
_VI_TTS_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "vits-piper-vi_VN-vais1000-medium"
_SENT_END = re.compile(r"[.!?][\")’”]?\s*$")
_WORD_RE = re.compile(r"[a-z0-9]+")

_vi_tts = None
_vi_tts_lock = threading.Lock()
_TRANSCRIPT_CACHE: dict = {}   # video_id -> merged snippets


def _extract_id(s: str):
    s = (s or "").strip()
    m = _ID_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    return None


def _merge_snippets(snips):
    """Merge caption fragments into sentence units (accuracy + better-timed clips)."""
    out = []
    cur = None
    for i, s in enumerate(snips):
        if cur is None:
            cur = {"start": s["start"], "end": s["start"] + s["dur"], "text": s["text"]}
        else:
            cur["text"] = (cur["text"] + " " + s["text"]).strip()
            cur["end"] = s["start"] + s["dur"]
        nxt = snips[i + 1] if i + 1 < len(snips) else None
        gap = (nxt["start"] - cur["end"]) if nxt else 99.0
        dur = cur["end"] - cur["start"]
        if _SENT_END.search(cur["text"]) or dur >= 6.0 or len(cur["text"]) > 180 or gap > 0.7:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return [
        {"start": round(c["start"], 3), "dur": round(c["end"] - c["start"], 3), "text": c["text"].strip()}
        for c in out if c["text"].strip()
    ]


def _toks(s: str):
    return _WORD_RE.findall((s or "").lower())


def _overlap(a_set, b_list):
    """Fraction of the candidate sentence's words covered by the STT word set."""
    if not b_list:
        return 0.0
    hit = sum(1 for w in b_list if w in a_set)
    return hit / len(b_list)


def _align(snippets, stt_text, after_index):
    """Find the transcript sentence index best matching the recent STT text,
    searching a forward window from after_index. Returns (index, score)."""
    stt = set(_toks(stt_text)[-16:])
    if not stt:
        return after_index, 0.0
    lo = max(0, after_index)
    hi = min(len(snippets), after_index + 6)
    best_i, best_adj, best_raw = after_index, 0.0, 0.0
    for i in range(lo, hi):
        raw = _overlap(stt, _toks(snippets[i]["text"]))
        adj = raw - 0.04 * (i - lo)   # proximity bias: prefer the nearest forward match
        if adj > best_adj:
            best_adj, best_i, best_raw = adj, i, raw
    return best_i, round(best_raw, 3)


def _short(p: str) -> str:
    """8.3 short path - sherpa-onnx cannot load non-ASCII paths on Windows."""
    p = os.path.abspath(p)
    if os.name != "nt" or p.isascii():
        return p
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024) and buf.value.isascii():
        return buf.value
    return p


def _get_vi_tts():
    global _vi_tts
    if _vi_tts is not None:
        return _vi_tts
    with _vi_tts_lock:
        if _vi_tts is None:
            import sherpa_onnx
            base = _short(str(_VI_TTS_DIR))
            cfg = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=base + os.sep + "vi_VN-vais1000-medium.onnx",
                        tokens=base + os.sep + "tokens.txt",
                        data_dir=base + os.sep + "espeak-ng-data",
                    ),
                    num_threads=2,
                    provider="cpu",
                )
            )
            _vi_tts = sherpa_onnx.OfflineTts(cfg)
            print("[YTDub] Vietnamese VITS TTS ready.", flush=True)
    return _vi_tts


class _TtsReq(BaseModel):
    text: str
    speed: float = 1.0


class _TrReq(BaseModel):
    text: str
    src_lang: str = "eng_Latn"
    tgt_lang: str = "vie_Latn"


class _AlignReq(BaseModel):
    video_id: str
    stt_text: str
    after_index: int = -1


def create_youtube_dub_router(get_engine=None) -> APIRouter:
    router = APIRouter(prefix="/api/youtube", tags=["youtube"])

    @router.get("/transcript")
    def transcript(id: str = Query(...), src: str = Query("")):
        vid = _extract_id(id)
        if not vid:
            return JSONResponse({"error": "invalid YouTube id/url"}, status_code=400)
        try:
            import truststore
            truststore.inject_into_ssl()
        except Exception:
            pass
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": f"youtube_transcript_api missing: {e}"}, status_code=500)

        api = YouTubeTranscriptApi()
        try:
            tl = api.list(vid)
            available = [
                {"code": t.language_code, "generated": t.is_generated, "name": t.language}
                for t in tl
            ]
            pick = None
            if src:
                for t in tl:
                    if t.language_code == src or t.language_code.split("-")[0] == src:
                        pick = t
                        break
            if pick is None:
                manual = [t for t in tl if not t.is_generated]
                pick = (manual or list(tl))[0]
            fetched = pick.fetch()
            raw = [
                {"start": round(s.start, 3), "dur": round(s.duration, 3),
                 "text": s.text.replace("\n", " ").strip()}
                for s in fetched
                if s.text and s.text.strip()
            ]
            merged = _merge_snippets(raw)
            _TRANSCRIPT_CACHE[vid] = merged
            return {
                "video_id": vid, "lang": pick.language_code,
                "generated": pick.is_generated, "available": available,
                "count": len(merged), "raw_count": len(raw), "snippets": merged,
            }
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": f"transcript fetch failed: {e}"}, status_code=502)

    @router.post("/align")
    def align(req: _AlignReq):
        snippets = _TRANSCRIPT_CACHE.get(req.video_id)
        if not snippets:
            return JSONResponse({"error": "transcript not loaded for this video"}, status_code=409)
        idx, score = _align(snippets, req.stt_text, max(0, req.after_index))
        return {"index": idx, "score": score, "advanced": idx > req.after_index,
                "text": snippets[idx]["text"], "start": snippets[idx]["start"], "dur": snippets[idx]["dur"]}

    @router.post("/translate")
    def translate(req: _TrReq):
        text = (req.text or "").strip()
        if not text or get_engine is None:
            return {"translated_text": ""}
        try:
            eng = get_engine("nllb-600m")
            out = "".join(eng.translate_stream(text, req.src_lang, req.tgt_lang)).strip()
            return {"translated_text": out}
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": f"translate failed: {e}"}, status_code=500)

    @router.post("/tts")
    def vi_tts(req: _TtsReq):
        text = (req.text or "").strip()
        if not text:
            return Response(content=b"", media_type="application/octet-stream",
                            headers={"X-Sample-Rate": "22050"})
        try:
            tts = _get_vi_tts()
            audio = tts.generate(text, sid=0, speed=max(0.5, min(2.0, req.speed)))
            pcm = (np.asarray(audio.samples, dtype=np.float32) * 32767.0).astype(np.int16).tobytes()
            return Response(content=pcm, media_type="application/octet-stream",
                            headers={"X-Sample-Rate": str(audio.sample_rate), "Cache-Control": "no-store"})
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": f"vi tts failed: {e}"}, status_code=500)

    return router
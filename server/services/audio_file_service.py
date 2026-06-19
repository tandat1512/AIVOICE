"""Audio file transcription service for non-realtime translation."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AudioTranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class AudioTranscriptResult:
    segments: list[AudioTranscriptSegment]
    full_text: str
    status: str = "ok"
    error: str | None = None


class AudioFileService:
    def __init__(self, *, get_whisper_model: Callable[[], object]) -> None:
        self._get_whisper_model = get_whisper_model

    def transcribe(self, audio_bytes: bytes, filename: str = "", language: str = "vi") -> AudioTranscriptResult:
        if not audio_bytes:
            raise ValueError("audio file is empty")

        suffix = Path(filename or "audio.wav").suffix.lower() or ".wav"
        if suffix not in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".aac"}:
            raise ValueError("unsupported audio file type")

        tmp_path = ""
        try:
            model = self._get_whisper_model()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            whisper_lang = self._to_whisper_lang(language)
            raw_segments, _info = model.transcribe(tmp_path, language=whisper_lang, vad_filter=True)
            segments: list[AudioTranscriptSegment] = []
            for seg in raw_segments:
                text = (getattr(seg, "text", "") or "").strip()
                if not text:
                    continue
                segments.append(AudioTranscriptSegment(
                    start=float(getattr(seg, "start", 0.0) or 0.0),
                    end=float(getattr(seg, "end", 0.0) or 0.0),
                    text=text,
                ))
            return AudioTranscriptResult(
                segments=segments,
                full_text=" ".join(seg.text for seg in segments).strip(),
                status="ok",
            )
        except Exception as exc:
            return AudioTranscriptResult(
                segments=[],
                full_text="",
                status="unavailable",
                error=f"Audio transcription failed: {exc}. Check faster-whisper model and ffmpeg availability.",
            )
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    @staticmethod
    def _to_whisper_lang(lang: str) -> str:
        normalized = (lang or "vi").strip()
        return {
            "vie_Latn": "vi",
            "vi": "vi",
            "eng_Latn": "en",
            "en": "en",
            "jpn_Jpan": "ja",
            "ja": "ja",
            "kor_Hang": "ko",
            "ko": "ko",
            "zho_Hans": "zh",
            "zh": "zh",
            "fra_Latn": "fr",
            "fr": "fr",
        }.get(normalized, normalized[:2])

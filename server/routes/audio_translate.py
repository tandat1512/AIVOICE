"""Audio file translation route."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.schemas.translate_schema import (
    AudioFileTranslateResponse,
    AudioTranslateSegment,
    TextTranslateRequest,
)
from server.services.audio_file_service import AudioFileService
from server.services.translator_service import TranslatorService


def create_audio_translate_router(
    *,
    audio_service: AudioFileService,
    translator_service: TranslatorService,
) -> APIRouter:
    router = APIRouter(prefix="/api/translate", tags=["translate"])

    @router.post("/audio-file", response_model=AudioFileTranslateResponse, response_model_exclude_none=True)
    async def translate_audio_file(
        file: UploadFile = File(...),
        src_lang: str = Form("vie_Latn"),
        tgt_lang: str = Form("eng_Latn"),
        translate_model: str = Form(""),
    ) -> AudioFileTranslateResponse:
        content_type = (file.content_type or "").lower()
        if content_type and not (content_type.startswith("audio/") or content_type in {"video/webm", "application/octet-stream"}):
            raise HTTPException(status_code=400, detail="file must be an audio file")

        audio_bytes = await file.read()
        transcript = await asyncio.to_thread(audio_service.transcribe, audio_bytes, file.filename or "", src_lang)
        if not transcript.full_text:
            return AudioFileTranslateResponse(
                segments=[],
                full_text="",
                full_translation="",
                stt_status=transcript.status,
                error=transcript.error or "No speech detected in audio file.",
            )

        output_segments: list[AudioTranslateSegment] = []
        translations: list[str] = []
        for seg in transcript.segments:
            try:
                req = TextTranslateRequest(
                    text=seg.text,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    translate_model=translate_model or None,
                )
                translated = await asyncio.to_thread(translator_service.translate_text, req)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"translation failed: {exc}") from exc

            translations.append(translated.translated_text)
            output_segments.append(AudioTranslateSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                translation=translated.translated_text,
            ))

        return AudioFileTranslateResponse(
            segments=output_segments,
            full_text=transcript.full_text,
            full_translation=" ".join(translations).strip(),
            stt_status=transcript.status,
            error=transcript.error,
        )

    return router

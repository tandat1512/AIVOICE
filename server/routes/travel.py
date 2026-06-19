"""Travel assistant route."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.schemas.translate_schema import TravelAssistResponse
from server.services.ocr_service import OcrService
from server.services.travel_service import TravelService


def create_travel_router(*, travel_service: TravelService, ocr_service: OcrService) -> APIRouter:
    router = APIRouter(prefix="/api/travel", tags=["travel"])

    @router.post("/assist", response_model=TravelAssistResponse, response_model_exclude_none=True)
    async def travel_assist(
        file: UploadFile | None = File(default=None),
        text: str = Form(""),
        src_lang: str = Form("jpn_Jpan"),
        target_language: str = Form("vie_Latn"),
        home_currency: str = Form("VND"),
        translate_model: str = Form(""),
        ocr_engine: str = Form(""),
        ocr_lang: str = Form(""),
    ) -> dict:
        source_text = (text or "").strip()
        ocr_status = None
        ocr_engine_used = None
        ocr_lang_used = None
        ocr_error = None

        if file is not None and file.filename:
            content_type = (file.content_type or "").lower()
            if content_type and not content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="file must be an image")
            image_bytes = await file.read()
            ocr = await asyncio.to_thread(
                ocr_service.extract_text,
                image_bytes,
                file.filename or "",
                engine=ocr_engine or None,
                lang=ocr_lang or src_lang,
            )
            ocr_status = ocr.status
            ocr_engine_used = ocr.engine
            ocr_lang_used = ocr.lang
            ocr_error = ocr.error
            source_text = ocr.text or source_text

        try:
            result = await asyncio.to_thread(
                travel_service.assist,
                text=source_text,
                src_lang=src_lang,
                target_language=target_language,
                home_currency=home_currency,
                translate_model=translate_model or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"travel assistant failed: {exc}") from exc

        result["ocr_status"] = ocr_status
        result["ocr_engine"] = ocr_engine_used
        result["ocr_lang"] = ocr_lang_used
        result["error"] = ocr_error
        return result

    return router

"""Image translation route with OCR + translation + currency detection."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.schemas.translate_schema import ImageTranslateResponse, TextTranslateRequest
from server.services.currency_service import CurrencyService
from server.services.ocr_service import OcrService
from server.services.translator_service import TranslatorService


def create_image_translate_router(
    *,
    ocr_service: OcrService,
    translator_service: TranslatorService,
    currency_service: CurrencyService,
) -> APIRouter:
    router = APIRouter(prefix="/api/translate", tags=["translate"])

    @router.post("/image", response_model=ImageTranslateResponse, response_model_exclude_none=True)
    async def translate_image(
        file: UploadFile = File(...),
        src_lang: str = Form("vie_Latn"),
        tgt_lang: str = Form("eng_Latn"),
        translate_model: str = Form(""),
        ocr_engine: str = Form(""),
        ocr_lang: str = Form(""),
        translate_blocks: bool = Form(False),
    ) -> ImageTranslateResponse:
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
        if not ocr.text:
            return ImageTranslateResponse(
                extracted_text="",
                translated_text="",
                blocks=[],
                detected_currency=[],
                ocr_status=ocr.status,
                ocr_engine=ocr.engine,
                ocr_lang=ocr.lang,
                error=ocr.error or "No text detected in image.",
            )

        try:
            req = TextTranslateRequest(
                text=ocr.text,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                translate_model=translate_model or None,
            )
            translated = await asyncio.to_thread(translator_service.translate_text, req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface model/runtime failures clearly.
            raise HTTPException(status_code=500, detail=f"translation failed: {exc}") from exc

        should_translate_blocks = translate_blocks or os.environ.get("IMAGE_TRANSLATE_BLOCKS", "0").strip().lower() in {"1", "true", "yes"}
        blocks = []
        for block in ocr.blocks:
            block_copy = dict(block)
            block_text = (block_copy.get("text") or "").strip()
            if should_translate_blocks and block_text:
                try:
                    block_req = TextTranslateRequest(
                        text=block_text,
                        src_lang=src_lang,
                        tgt_lang=tgt_lang,
                        translate_model=translate_model or None,
                    )
                    block_translated = await asyncio.to_thread(translator_service.translate_text, block_req)
                    block_copy["translation"] = block_translated.translated_text
                except Exception:
                    block_copy["translation"] = ""
            blocks.append(block_copy)

        detected = await asyncio.to_thread(currency_service.detect_currency_amounts, ocr.text)
        return ImageTranslateResponse(
            extracted_text=ocr.text,
            translated_text=translated.translated_text,
            blocks=blocks,
            detected_currency=[item.model_dump() for item in detected],
            ocr_status=ocr.status,
            ocr_engine=ocr.engine,
            ocr_lang=ocr.lang,
            error=ocr.error,
        )

    return router

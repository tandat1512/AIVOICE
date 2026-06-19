"""Text translation REST route."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from server.schemas.translate_schema import TextTranslateRequest, TextTranslateResponse
from server.services.translator_service import TranslatorService


def create_text_translate_router(service: TranslatorService) -> APIRouter:
    router = APIRouter(prefix="/api/translate", tags=["translate"])

    @router.post("/text", response_model=TextTranslateResponse, response_model_exclude_none=True)
    async def translate_text(req: TextTranslateRequest) -> TextTranslateResponse:
        try:
            return await asyncio.to_thread(service.translate_text, req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface model/runtime failures clearly.
            raise HTTPException(status_code=500, detail=f"translation failed: {exc}") from exc

    return router


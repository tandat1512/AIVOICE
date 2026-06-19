"""Translation memory routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from server.schemas.memory_schema import TranslationMemoryCreate, TranslationMemoryItem
from server.services.translation_memory_service import TranslationMemoryService


def create_memory_router(service: TranslationMemoryService) -> APIRouter:
    router = APIRouter(prefix="/api/memory", tags=["memory"])

    @router.get("/search", response_model=list[TranslationMemoryItem])
    async def search_memory(
        q: str = Query(..., min_length=1, max_length=12000),
        src_lang: str = Query("", max_length=16),
        tgt_lang: str = Query("", max_length=16),
        limit: int = Query(5, ge=1, le=20),
    ) -> list[dict]:
        return await asyncio.to_thread(service.search, q, src_lang=src_lang, tgt_lang=tgt_lang, limit=limit)

    @router.post("", response_model=TranslationMemoryItem)
    async def add_memory(item: TranslationMemoryCreate) -> dict:
        try:
            return await asyncio.to_thread(service.add, item)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router

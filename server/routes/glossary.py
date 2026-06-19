"""Glossary CRUD routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from server.schemas.glossary_schema import GlossaryItem, GlossaryItemCreate, GlossaryItemUpdate
from server.services.glossary_service import GlossaryService


def create_glossary_router(service: GlossaryService) -> APIRouter:
    router = APIRouter(prefix="/api/glossary", tags=["glossary"])

    @router.get("", response_model=list[GlossaryItem])
    async def list_glossary() -> list[dict]:
        return await asyncio.to_thread(service.list_items)

    @router.post("", response_model=GlossaryItem)
    async def create_glossary_item(item: GlossaryItemCreate) -> dict:
        return await asyncio.to_thread(service.create_item, item)

    @router.put("/{item_id}", response_model=GlossaryItem)
    async def update_glossary_item(item_id: int, patch: GlossaryItemUpdate) -> dict:
        try:
            return await asyncio.to_thread(service.update_item, item_id, patch)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/{item_id}")
    async def delete_glossary_item(item_id: int) -> dict:
        try:
            await asyncio.to_thread(service.delete_item, item_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True}

    return router

"""Currency conversion routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from server.schemas.currency_schema import CurrencyConversionResponse, DetectedCurrencyAmount
from server.services.currency_service import CurrencyService


def create_currency_router(service: CurrencyService) -> APIRouter:
    router = APIRouter(prefix="/api/currency", tags=["currency"])

    @router.get("/convert", response_model=CurrencyConversionResponse)
    async def convert_currency(
        amount: float = Query(..., ge=0),
        from_currency: str = Query(..., alias="from", min_length=3, max_length=3),
        to_currency: str = Query(..., alias="to", min_length=3, max_length=3),
    ) -> dict:
        try:
            return await asyncio.to_thread(service.convert, amount, from_currency, to_currency)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - return clear API failure.
            raise HTTPException(status_code=503, detail=f"currency conversion failed: {exc}") from exc

    @router.get("/detect", response_model=list[DetectedCurrencyAmount])
    async def detect_currency(text: str = Query(..., min_length=1, max_length=12000)) -> list[DetectedCurrencyAmount]:
        return await asyncio.to_thread(service.detect_currency_amounts, text)

    return router

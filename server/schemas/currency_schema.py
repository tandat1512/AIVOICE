"""Schemas for currency conversion endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CurrencyConversionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    amount: float
    from_currency: str = Field(alias="from")
    to_currency: str = Field(alias="to")
    rate: float
    converted: float
    source: str
    updated_at: str


class DetectedCurrencyAmount(BaseModel):
    text: str
    amount: float
    currency: str
    start: int
    end: int

"""Schemas for translation memory."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranslationMemoryCreate(BaseModel):
    source_text: str = Field(..., min_length=1, max_length=12000)
    translated_text: str = Field(..., min_length=1, max_length=12000)
    src_lang: str = Field("vie_Latn", min_length=2, max_length=16)
    tgt_lang: str = Field("eng_Latn", min_length=2, max_length=16)


class TranslationMemoryItem(BaseModel):
    id: int
    source_text: str
    translated_text: str
    src_lang: str
    tgt_lang: str
    created_at: str
    score: float | None = None

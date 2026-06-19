"""Schemas for glossary CRUD."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GlossaryItemCreate(BaseModel):
    source_term: str = Field(..., min_length=1, max_length=200)
    target_term: str = Field(..., min_length=1, max_length=200)
    src_lang: str = Field("eng_Latn", min_length=2, max_length=16)
    tgt_lang: str = Field("vie_Latn", min_length=2, max_length=16)
    note: str = Field("", max_length=500)


class GlossaryItemUpdate(BaseModel):
    source_term: str | None = Field(default=None, min_length=1, max_length=200)
    target_term: str | None = Field(default=None, min_length=1, max_length=200)
    src_lang: str | None = Field(default=None, min_length=2, max_length=16)
    tgt_lang: str | None = Field(default=None, min_length=2, max_length=16)
    note: str | None = Field(default=None, max_length=500)


class GlossaryItem(BaseModel):
    id: int
    source_term: str
    target_term: str
    src_lang: str
    tgt_lang: str
    note: str = ""
    created_at: str

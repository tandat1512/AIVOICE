"""Schemas for translation REST endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TextTranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=12000)
    src_lang: str = Field("vie_Latn", min_length=2, max_length=16)
    tgt_lang: str = Field("eng_Latn", min_length=2, max_length=16)
    translate_model: str | None = Field(default=None, max_length=32)
    use_glossary: bool = True


class TextTranslateResponse(BaseModel):
    source_text: str
    translated_text: str
    src_lang: str
    tgt_lang: str
    memory_suggestions: list[dict] = []


class OcrBlock(BaseModel):
    text: str
    translation: str | None = None
    bbox: list[int] | None = None
    confidence: float | None = None


class ImageTranslateResponse(BaseModel):
    extracted_text: str
    translated_text: str
    blocks: list[OcrBlock] = []
    detected_currency: list[dict] = []
    ocr_status: str = "ok"
    ocr_engine: str = ""
    ocr_lang: str = ""
    error: str | None = None


class AudioTranslateSegment(BaseModel):
    start: float
    end: float
    text: str
    translation: str


class AudioFileTranslateResponse(BaseModel):
    segments: list[AudioTranslateSegment]
    full_text: str
    full_translation: str
    stt_status: str = "ok"
    error: str | None = None


class TravelPrice(BaseModel):
    amount: float
    currency: str
    converted_amount: float
    converted_currency: str
    rate: float
    source: str


class TravelAssistItem(BaseModel):
    original: str
    translation: str
    price: TravelPrice | None = None
    note: str | None = None


class TravelAssistResponse(BaseModel):
    items: list[TravelAssistItem]
    summary: str
    source_text: str
    ocr_status: str | None = None
    ocr_engine: str | None = None
    ocr_lang: str | None = None
    error: str | None = None

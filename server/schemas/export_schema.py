"""Schemas for export endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ExportFormat = Literal["txt", "json", "srt", "docx"]


class ExportSegment(BaseModel):
    start: float = 0.0
    end: float = 0.0
    text: str = ""
    translation: str = ""


class ExportRequest(BaseModel):
    format: ExportFormat
    title: str = Field("SmartGen Export", max_length=120)
    source_text: str = ""
    translated_text: str = ""
    segments: list[ExportSegment] = []

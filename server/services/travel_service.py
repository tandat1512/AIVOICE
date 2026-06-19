"""Travel assistant orchestration service."""

from __future__ import annotations

from server.schemas.translate_schema import TextTranslateRequest
from server.services.currency_service import CurrencyService
from server.services.translator_service import TranslatorService


class TravelService:
    def __init__(
        self,
        *,
        translator_service: TranslatorService,
        currency_service: CurrencyService,
    ) -> None:
        self._translator = translator_service
        self._currency = currency_service

    def assist(
        self,
        *,
        text: str,
        src_lang: str,
        target_language: str,
        home_currency: str,
        translate_model: str | None = None,
    ) -> dict:
        source_text = (text or "").strip()
        if not source_text:
            return {
                "items": [],
                "summary": "Không tìm thấy nội dung để phân tích.",
                "source_text": "",
            }

        lines = [line.strip() for line in source_text.splitlines() if line.strip()]
        if not lines:
            lines = [source_text]

        items = []
        for line in lines[:40]:
            translation = self._translator.translate_text(TextTranslateRequest(
                text=line,
                src_lang=src_lang,
                tgt_lang=target_language,
                translate_model=translate_model,
            )).translated_text

            price = None
            detected = self._currency.detect_currency_amounts(line)
            if detected:
                first = detected[0]
                try:
                    converted = self._currency.convert(first.amount, first.currency, home_currency)
                    price = {
                        "amount": first.amount,
                        "currency": first.currency,
                        "converted_amount": converted["converted"],
                        "converted_currency": converted["to_currency"],
                        "rate": converted["rate"],
                        "source": converted["source"],
                    }
                except Exception:
                    price = None

            items.append({
                "original": line,
                "translation": translation,
                "price": price,
                "note": self._make_note(line, price),
            })

        summary = self._summarize(items)
        return {
            "items": items,
            "summary": summary,
            "source_text": source_text,
        }

    @staticmethod
    def _make_note(line: str, price: dict | None) -> str | None:
        lowered = line.lower()
        if price:
            return "Đã phát hiện giá tiền và quy đổi sang tiền tệ nhà."
        if any(word in lowered for word in ("menu", "ramen", "coffee", "cafe", "restaurant")):
            return "Nội dung có vẻ liên quan đến ăn uống/nhà hàng."
        return None

    @staticmethod
    def _summarize(items: list[dict]) -> str:
        if not items:
            return "Không có mục nào để hiển thị."
        priced = sum(1 for item in items if item.get("price"))
        if priced:
            return f"Đã phân tích {len(items)} dòng và phát hiện {priced} mục có giá tiền."
        return f"Đã phân tích {len(items)} dòng văn bản du lịch."

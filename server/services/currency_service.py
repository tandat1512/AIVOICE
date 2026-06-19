"""Currency conversion with cache, public API lookup, and local fallback rates."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from server.schemas.currency_schema import DetectedCurrencyAmount


_FALLBACK_TO_USD = {
    "USD": 1.0,
    "VND": 25400.0,
    "EUR": 0.92,
    "JPY": 157.0,
    "KRW": 1380.0,
    "CNY": 7.25,
    "GBP": 0.79,
    "AUD": 1.52,
    "CAD": 1.37,
    "SGD": 1.35,
    "THB": 36.5,
}

_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
    "￥": "JPY",
    "円": "JPY",
    "₩": "KRW",
    "£": "GBP",
    "₫": "VND",
}

_CODE_RE = r"USD|VND|EUR|JPY|KRW|CNY|GBP|AUD|CAD|SGD|THB"


class CurrencyService:
    def __init__(self, ttl_s: int = 900) -> None:
        self._ttl_s = ttl_s
        self._cache: dict[tuple[str, str], tuple[float, float, str, str]] = {}

    def convert(self, amount: float, from_currency: str, to_currency: str) -> dict:
        src = self._normalize_code(from_currency)
        tgt = self._normalize_code(to_currency)
        if amount < 0:
            raise ValueError("amount must be >= 0")

        rate, source, updated_at = self._get_rate(src, tgt)
        converted = amount * rate
        return {
            "amount": amount,
            "from_currency": src,
            "to_currency": tgt,
            "rate": rate,
            "converted": converted,
            "source": source,
            "updated_at": updated_at,
        }

    def detect_currency_amounts(self, text: str) -> list[DetectedCurrencyAmount]:
        items: list[DetectedCurrencyAmount] = []
        if not text:
            return items

        symbol_pattern = "|".join(re.escape(s) for s in sorted(_SYMBOLS, key=len, reverse=True))
        patterns = [
            rf"(?P<symbol>{symbol_pattern})\s*(?P<amount>\d+(?:[,.]\d+)*)",
            rf"(?P<amount>\d+(?:[,.]\d+)*)\s*(?P<symbol>{symbol_pattern})",
            rf"(?P<amount>\d+(?:[,.]\d+)*)\s*(?P<code>{_CODE_RE})\b",
            rf"\b(?P<code>{_CODE_RE})\s*(?P<amount>\d+(?:[,.]\d+)*)",
            r"(?P<amount>\d+(?:[,.]\d+)*)\s*(?P<yen>yen|yên)\b",
        ]

        seen: set[tuple[int, int]] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                span = match.span()
                if span in seen:
                    continue
                amount = self._parse_amount(match.group("amount"))
                code = match.groupdict().get("code")
                symbol = match.groupdict().get("symbol")
                if symbol:
                    currency = _SYMBOLS[symbol]
                elif code:
                    currency = self._normalize_code(code)
                else:
                    currency = "JPY"
                seen.add(span)
                items.append(DetectedCurrencyAmount(
                    text=match.group(0),
                    amount=amount,
                    currency=currency,
                    start=span[0],
                    end=span[1],
                ))
        return sorted(items, key=lambda item: item.start)

    def _get_rate(self, src: str, tgt: str) -> tuple[float, str, str]:
        if src == tgt:
            return 1.0, "identity", datetime.now(timezone.utc).isoformat()

        key = (src, tgt)
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[1] < self._ttl_s:
            return cached[0], cached[2], cached[3]

        try:
            rate, updated_at = self._fetch_open_er(src, tgt)
            source = "open_er_api"
        except Exception:
            try:
                rate, updated_at = self._fetch_frankfurter(src, tgt)
                source = "frankfurter"
            except Exception:
                rate = self._fallback_rate(src, tgt)
                source = "fallback_static"
                updated_at = datetime.now(timezone.utc).isoformat()

        self._cache[key] = (rate, now, source, updated_at)
        return rate, source, updated_at

    @staticmethod
    def _fetch_open_er(src: str, tgt: str) -> tuple[float, str]:
        url = f"https://open.er-api.com/v6/latest/{urllib.parse.quote(src)}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("result") != "success":
            raise ValueError(data.get("error-type") or "open exchange rate API failed")
        rate = float(data["rates"][tgt])
        if rate <= 0:
            raise ValueError("invalid exchange rate")
        updated_at = data.get("time_last_update_utc") or datetime.now(timezone.utc).isoformat()
        return rate, updated_at

    @staticmethod
    def _fetch_frankfurter(src: str, tgt: str) -> tuple[float, str]:
        params = urllib.parse.urlencode({"from": src, "to": tgt})
        url = f"https://api.frankfurter.app/latest?{params}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rate = float(data["rates"][tgt])
        if rate <= 0:
            raise ValueError("invalid exchange rate")
        return rate, data.get("date") or datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _fallback_rate(src: str, tgt: str) -> float:
        if src not in _FALLBACK_TO_USD or tgt not in _FALLBACK_TO_USD:
            raise ValueError(f"unsupported currency pair: {src}->{tgt}")
        return _FALLBACK_TO_USD[tgt] / _FALLBACK_TO_USD[src]

    @staticmethod
    def _normalize_code(code: str) -> str:
        normalized = (code or "").strip().upper()
        if normalized not in _FALLBACK_TO_USD:
            raise ValueError(f"unsupported currency: {code!r}")
        return normalized

    @staticmethod
    def _parse_amount(raw: str) -> float:
        value = raw.strip()
        if "," in value and "." in value:
            value = value.replace(",", "")
        elif "," in value:
            value = value.replace(",", ".")
        return float(value)

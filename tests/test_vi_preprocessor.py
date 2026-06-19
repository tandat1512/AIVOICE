"""Unit tests for Vietnamese source preprocessing + entity masking.

Pure-function tests — no model load, fast. Cover the real failure cases observed
in production logs (place names mistranslated, dialect pronouns misread).
"""

from __future__ import annotations

from server.translate.vi_preprocessor import (
    preprocess_vi,
    mask_places,
    unmask_places,
)


# ── Place-name title-casing ────────────────────────────────────────────────────

def test_place_names_are_title_cased():
    assert preprocess_vi("mình đến từ gia lai") == "tôi đến từ Gia Lai"
    assert preprocess_vi("em ở tây ninh") == "em ở Tây Ninh"
    assert preprocess_vi("đến từ bình dương") == "đến từ Bình Dương"


def test_multiword_city_title_cased():
    assert preprocess_vi("thành phố hồ chí minh") == "thành phố Hồ Chí Minh"


# ── Dialect pronoun normalization ──────────────────────────────────────────────

def test_minh_as_subject_becomes_toi():
    assert preprocess_vi("mình là juli") == "tôi là juli"
    assert preprocess_vi("mình sinh năm 2002") == "tôi sinh năm 2002"
    assert preprocess_vi("mình đến từ đâu") == "tôi đến từ đâu"


def test_tui_becomes_toi():
    assert preprocess_vi("tui ở vũng tàu").startswith("tôi ở")


def test_bare_minh_not_touched():
    # "mình" not followed by a first-person marker keeps its reciprocal meaning.
    assert preprocess_vi("mình với nhau") == "mình với nhau"


def test_non_place_words_untouched():
    assert preprocess_vi("chụp tấm ảnh") == "chụp tấm ảnh"


# ── Entity masking round-trip ──────────────────────────────────────────────────

def test_mask_produces_copy_safe_sentinels():
    masked, mapping = mask_places("tôi đến từ Gia Lai và Tây Ninh")
    assert "x0x" in masked and "x1x" in masked
    assert mapping == {"x0x": "Gia Lai", "x1x": "Tây Ninh"}


def test_unmask_restores_names():
    _, mapping = mask_places("đến từ Gia Lai")
    assert unmask_places("I am from x0x", mapping) == "I am from Gia Lai"


def test_repeated_name_reuses_one_sentinel():
    masked, mapping = mask_places("Gia Lai Gia Lai")
    assert len(mapping) == 1
    assert masked == "x0x x0x"


def test_no_entities_yields_empty_mapping():
    # Empty mapping is the signal the engine uses to keep token streaming on.
    _, mapping = mask_places("xin chào mọi người")
    assert mapping == {}


def test_unmask_is_case_insensitive():
    # The decoder may emit the sentinel uppercased; restoration must still match.
    assert unmask_places("from X0X", {"x0x": "Huế"}) == "from Huế"

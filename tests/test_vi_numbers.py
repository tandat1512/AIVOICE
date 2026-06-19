"""Unit tests for spoken Vietnamese number → digit conversion.

Covers correct conversions AND the false-positive guards (the hard part):
number words that double as everyday words must survive untouched.
"""

from __future__ import annotations

from server.translate.vi_numbers import convert_spoken_numbers as c


# ── Correct conversions ────────────────────────────────────────────────────────

def test_tens_and_units():
    assert c("hai mươi ba") == "23"
    assert c("mười lăm") == "15"
    assert c("ba mươi tư") == "34"
    assert c("hai mươi mốt") == "21"
    assert c("năm mươi") == "50"


def test_hundreds_and_thousands():
    assert c("một trăm lẻ năm") == "105"
    assert c("hai trăm") == "200"
    assert c("một nghìn") == "1000"


def test_year_2000s_idiom():
    assert c("sinh năm hai lẻ hai") == "sinh năm 2002"
    assert c("hai lẻ năm") == "2005"
    assert c("hai linh chín") == "2009"


def test_conversion_inside_sentence():
    assert c("tôi sinh năm hai lẻ hai") == "tôi sinh năm 2002"
    assert c("có hai mươi ba người") == "có 23 người"


# ── False-positive guards (must NOT convert) ───────────────────────────────────

def test_negation_khong_untouched():
    # "không" as negation/question particle, not zero.
    assert c("anh khỏe không") == "anh khỏe không"


def test_lone_number_words_untouched():
    assert c("ba tao nói") == "ba tao nói"        # ba = father
    assert c("năm nay") == "năm nay"              # năm = year
    assert c("anh hai ơi") == "anh hai ơi"        # hai = kinship


def test_bare_digit_pair_untouched():
    # No structural word → too ambiguous (e.g. the name "Hai Ba"); left alone.
    assert c("hai ba") == "hai ba"


def test_false_friend_words_untouched():
    assert c("tư duy") == "tư duy"                # tư = think, not 4
    assert c("riêng tư") == "riêng tư"


def test_empty_and_plain():
    assert c("") == ""
    assert c("xin chào") == "xin chào"

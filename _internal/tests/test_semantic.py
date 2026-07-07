# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_semantic.py
PURPOSE: 의미(형태) 검증 골든 — _value_shape 분류 + _semantic_ok 가 '채워졌지만 형태가
         틀린' 잘못된 치유를 잡되, 정상적 변동(급여에 '무료/협의' 섞임)은 오탐하지 않음.
DEPENDENCY: 표준 라이브러리만(values/guards 의 순수 함수 직접 호출, 네트워크/LLM 무관).
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import values
import guards


def _schema(**fields):
    """{name: example} → schema 유사 객체(.fields[name]['example'])."""
    return types.SimpleNamespace(
        fields={n: {"example": ex} for n, ex in fields.items()})


def _rows(field, values):
    return [{field: v} for v in values]


def test_value_shape_classes():
    assert values._value_shape("https://x.com/a") == "url"
    assert values._value_shape("2026-07-02") == "date"
    assert values._value_shape("07월 04일") == "date"
    assert values._value_shape("3일 전") == "date"
    assert values._value_shape("12,000") == "num"
    assert values._value_shape("12:34") == "num"
    assert values._value_shape("삼성 코엑스 행사") == "text"
    assert values._value_shape("") == "empty"


def test_wrong_healing_flagged():
    # 가격(num) 칸이 전부 날짜로 채워짐 → 잘못된 치유
    sc = _schema(가격="12,000")
    ok, bad = guards._semantic_ok(_rows("가격", ["2026-07-01"] * 4), sc)
    assert not ok and bad and bad[0][0] == "가격"


def test_url_field_all_text_flagged():
    sc = _schema(링크="https://site.com/1")
    ok, bad = guards._semantic_ok(_rows("링크", ["제목1", "제목2", "제목3"]), sc)
    assert not ok and bad[0][0] == "링크"


def test_legit_variation_not_flagged():
    # 급여(num) 에 '무료/협의' 섞여도 숫자가 충분(≥20%)하면 통과 — 오탐 방지
    sc = _schema(급여="12,000")
    ok, bad = guards._semantic_ok(
        _rows("급여", ["12,000", "무료", "협의", "3,000", "5,000"]), sc)
    assert ok and not bad


def test_text_example_never_flagged():
    # 형태가 약한(text) 필드는 값이 숫자여도 판정 보류
    sc = _schema(제목="삼성 행사")
    ok, _ = guards._semantic_ok(_rows("제목", ["1", "2", "3"]), sc)
    assert ok


def test_small_sample_not_flagged():
    # 표본 3개 미만 → 판정 보류(성급한 거부 방지)
    sc = _schema(가격="12,000")
    ok, _ = guards._semantic_ok(_rows("가격", ["2026-07-01", "2026-07-02"]), sc)
    assert ok


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

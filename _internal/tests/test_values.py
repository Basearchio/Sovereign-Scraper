# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_values.py
PURPOSE: (v5.0 co-split) 값 의미 분류 leaf(values.py) 골든 + leaf 경계 강제.
         engine·cli 가 공유하는 값 판별(링크/가격/날짜/형태)이 한곳에서 결정적으로 동작하고,
         values.py 가 상위 모듈(engine/cli/…)을 import 하지 않음을 소스 스캔으로 확인.
DEPENDENCY: 표준 라이브러리만.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import values


def test_looks_url_absolute_only():
    assert values.looks_url("https://x.com/a") is True
    assert values.looks_url("//x.com/a") is True
    assert values.looks_url("/p/1") is False        # 상대경로는 URL 로 안 봄(특성화된 동작)
    assert values.looks_url("제목1") is False


def test_is_real_href():
    assert values.is_real_href("https://x.com") is True
    assert values.is_real_href("#") is False
    assert values.is_real_href("javascript:;") is False
    assert values.is_real_href("") is False


def test_url_key_strips_scheme_and_query():
    assert values._url_key("https://x.com/v/BV1?") == "x.com/v/BV1"
    assert values._url_key("http://x.com/v/BV1") == values._url_key("//x.com/v/BV1")


def test_looks_price():
    assert values._looks_price("25,800원") is True
    assert values._looks_price("15,980") is True
    assert values._looks_price("제목") is False


def test_value_shape_classes():
    assert values._value_shape("https://x.com/a") == "url"
    assert values._value_shape("2026-07-02") == "date"
    assert values._value_shape("3일 전") == "date"
    assert values._value_shape("12,000") == "num"
    assert values._value_shape("삼성 코엑스 행사") == "text"
    assert values._value_shape("") == "empty"


def test_values_is_leaf():
    # 경계: values.py 는 상위 모듈을 import 하지 않는다(순환 차단, 테스트로 강제).
    src = open(values.__file__, encoding="utf-8").read()
    forbidden = ("engine", "cli", "chain", "llm_locators", "core", "crawlers", "runlog")
    for mod in forbidden:
        assert not re.search(rf"^\s*(import|from)\s+{mod}\b", src, re.M), \
            f"values.py 가 상위 모듈 '{mod}' 를 import 함 — leaf 위반"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

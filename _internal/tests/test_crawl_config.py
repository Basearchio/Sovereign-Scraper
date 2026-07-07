# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_crawl_config.py
PURPOSE: crawl_config 계약 — 기본 저장/로드 방식을 .env 에서 읽고, 값이 없거나 잘못되면 안전한
         폴백(append/auto). start.py 가 쓰고 cli 가 읽는 '기준값'의 형식을 못박는다.
DEPENDENCY: 표준 라이브러리만(tempdir .env, 실제 .env 무접촉 — path 인자로 격리).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crawl_config as cc


def _env(d, text):
    p = os.path.join(d, ".env")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def test_reads_configured_values():
    with tempfile.TemporaryDirectory() as d:
        p = _env(d, "DEFAULT_SAVE_MODE=overwrite\nDEFAULT_LOAD_METHOD=save_as\n")
        assert cc.default_save_mode(p) == "overwrite"
        assert cc.default_load_method(p) == "save_as"


def test_missing_falls_back():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "nope.env")
        assert cc.default_save_mode(p) == "append"
        assert cc.default_load_method(p) == "auto"


def test_invalid_value_falls_back():
    with tempfile.TemporaryDirectory() as d:
        p = _env(d, "DEFAULT_SAVE_MODE=garbage\nDEFAULT_LOAD_METHOD=weird\n")
        assert cc.default_save_mode(p) == "append"     # 잘못된 값 → 폴백
        assert cc.default_load_method(p) == "auto"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_interactive_setup.py
PURPOSE: 대화형 시작 안내(cli._interactive_setup) 계약 — 로드 방식(save_as)·저장 방식을 '처음부터'
         고르게 하고 args 에 반영, 주소를 마지막에 받는다. Enter(기본)는 args 를 안 건드려 기존 레시피의
         방식을 덮지 않는다.
DEPENDENCY: 표준 라이브러리만(builtins.input 을 가짜 답변으로 교체).
"""
import argparse
import builtins
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli
import crawl_config as cc


def _run_setup(answers):
    args = argparse.Namespace(chrome=False, mode=None)
    it = iter(answers)
    old = builtins.input
    builtins.input = lambda *a, **k: next(it)
    try:
        target = cli._interactive_setup(args)
    finally:
        builtins.input = old
    return target, args


def _run_rediscover(answers):
    """실재하는 레시피 파일이 있을 때 _maybe_rediscover 가 답변열에 어떻게 반응하는지."""
    fd, p = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    it = iter(answers)
    old = builtins.input
    builtins.input = lambda *a, **k: next(it)
    try:
        return cli._maybe_rediscover(p)
    finally:
        builtins.input = old
        os.remove(p)


def test_rediscover_enter_uses_existing():
    assert _run_rediscover([""]) is False        # Enter = 기존 레시피 재현


def test_rediscover_r_resets():
    assert _run_rediscover(["r"]) is True         # r = 초기화 후 새로 학습


def test_rediscover_unrecognized_reprompts_not_silent_default():
    # ★핵심: 'ㄱ'(IME 로 r 대신 들어온 글자)을 조용히 '기존 사용'으로 흘리지 않고 다시 묻는다.
    assert _run_rediscover(["ㄱ", "r"]) is True    # 재질문 후 r → 초기화
    assert _run_rediscover(["ㄱ", "x", ""]) is False  # 계속 재질문하다 Enter → 기존


def test_rediscover_no_recipe_returns_false_without_asking():
    assert cli._maybe_rediscover("nonexistent_zzz.csv") is False   # 레시피 없으면 묻지 않음


def test_setup_save_as_and_overwrite():
    target, args = _run_setup(["2", "3", "http://x"])   # save_as, 덮어쓰기, 주소
    assert target == "http://x"
    assert args.chrome is True
    assert args.mode == "overwrite"


def test_setup_history_mode():
    target, args = _run_setup(["1", "1", "http://y"])   # auto, 추가하기(중복허용)
    assert target == "http://y" and args.chrome is False and args.mode == "history"


def test_setup_enter_applies_configured_default():
    # Enter/Enter → '설정된 기본값'을 일관되게 적용(더 이상 None 아님).
    target, args = _run_setup(["", "", "http://z"])
    assert target == "http://z"
    assert args.mode == cc.default_save_mode()                    # 설정 기본 저장 방식 적용
    assert args.chrome is (cc.default_load_method() == "save_as")  # 설정 기본 로드 방식 적용


def test_maybe_rediscover_skips_when_no_recipe():
    # 레시피 없음 → 묻지 않고 False(놀람 없음 — cli 가 예시를 물어봄)
    assert cli._maybe_rediscover("") is False
    assert cli._maybe_rediscover(os.path.join(tempfile.gettempdir(), "zz_nope_xyz.csv")) is False


def test_maybe_rediscover_arms_on_relearn():
    import builtins
    with tempfile.TemporaryDirectory() as d:
        rp = os.path.join(d, "r.csv")
        open(rp, "w").close()                          # '이미 학습된 레시피' 존재를 흉내
        old = builtins.input
        try:
            builtins.input = lambda *a, **k: "r"        # 초기화 선택 → 재학습
            assert cli._maybe_rediscover(rp) is True
            builtins.input = lambda *a, **k: ""         # Enter → 기존 재현
            assert cli._maybe_rediscover(rp) is False
        finally:
            builtins.input = old


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

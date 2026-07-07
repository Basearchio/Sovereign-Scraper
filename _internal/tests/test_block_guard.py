# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_block_guard.py
PURPOSE: '성공 = 원한 필드를 실제로 가져왔는가' 기준의 결정적 가드 —
         _coverage_ok(원한 필드 절반 미만이면 실패), _looks_like_block(차단/인증 마커 도배 감지),
         llm_locators.looks_like_real_records(극소수 결과 최후 백스톱, LLM 페이크).
DEPENDENCY: 표준 라이브러리 + services.llm_service(ask 페이크). 네트워크/모델 불필요.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli
import services.llm_service as svc
import llm_locators


def test_coverage_ok_defines_success_by_requested_fields():
    assert cli._coverage_ok(3, 1) is False     # 제목·내용·시간 중 1개만 → 구멍투성이 = 실패
    assert cli._coverage_ok(3, 2) is True       # 3개 중 2개 → 절반 이상 = 성공권
    assert cli._coverage_ok(4, 1) is False
    assert cli._coverage_ok(2, 1) is True        # 2개 중 1개 = 절반 → 통과(마커/백스톱이 마저 거름)
    assert cli._coverage_ok(1, 1) is True
    assert cli._coverage_ok(3, 0) is False       # 하나도 못 잡음


def test_looks_like_block_detects_verify_dump():
    rows = [{"내용": "验证通过"}, {"내용": None}]     # baidu auto 케이스: 값이 인증 텍스트
    assert cli._looks_like_block(rows, ["내용"]) is True


def test_looks_like_block_passes_real_content():
    rows = [{"제목": "葡萄牙VS克罗地亚", "시간": "17:33"},
            {"제목": "感觉巴西人能处", "시간": "17:38"}]
    assert cli._looks_like_block(rows, ["제목", "시간"]) is False


def test_looks_like_real_records_llm_classify():
    old = svc.ask
    try:
        svc.ask = lambda *a, **k: "BLOCK"
        assert llm_locators.looks_like_real_records([{"t": "验证"}], ["t"]) is False
        svc.ask = lambda *a, **k: "REAL"
        assert llm_locators.looks_like_real_records([{"t": "실제 글"}], ["t"]) is True
        svc.ask = lambda *a, **k: "글쎄"
        assert llm_locators.looks_like_real_records([{"t": "x"}], ["t"]) is None   # 불명확→None
    finally:
        svc.ask = old
    assert llm_locators.looks_like_real_records([], ["t"]) is None                 # 빈 결과→None


def test_llm_confirms_real_fails_open():
    # LLM 이 명시적으로 BLOCK 일 때만 거짓, 나머지(None/True)는 통과(정상 데이터 안 막음)
    old = svc.ask
    try:
        svc.ask = lambda *a, **k: "BLOCK"
        assert cli._llm_confirms_real([{"t": "验证"}], ["t"]) is False
        svc.ask = lambda *a, **k: "REAL"
        assert cli._llm_confirms_real([{"t": "글"}], ["t"]) is True
    finally:
        svc.ask = old


def test_guards_does_not_import_cli_or_engine():
    # 경계: guards.py 는 values(leaf)+llm_locators 에만 의존하고 cli/engine 을 import 하지 않는다.
    import re
    import guards
    src = open(guards.__file__, encoding="utf-8").read()
    for mod in ("cli", "engine", "chain", "crawlers"):
        assert not re.search(rf"^\s*(import|from)\s+{mod}\b", src, re.M), \
            f"guards.py 가 '{mod}' 를 import 함 — 경계 위반"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

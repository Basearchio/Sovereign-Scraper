# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_locate_golden.py
PURPOSE: by-example 역설계의 '행동' 골든 — 사용자가 '서로 다른 레코드'에서 온 값을 섞어 입력하면
         (버그 #9: YouTube 서로 다른 영상의 제목·채널) 조용히 엉뚱한 매칭을 하지 않고 '예시값 불일치'로
         감지해 안내하는지를 결정적으로 못박는다. 같은 레코드 값이면 정상 매칭(양성 대조).
DEPENDENCY: lxml. 네트워크/LLM 불필요(결정적 구조 매칭 경로).

[검증된 주요 사이트 및 케이스]
- mixed-rows: 값이 한 반복 레코드에 모여 있지 않으면 _MIXED_ROWS_TAG 로 어떤 값이 어긋났는지 안내.

[테스트/운영 교훈]
- '실패는 조용히 넘기지 말고 사용자가 고치게' — 잘못 입력을 억지 매칭하면 잘못된 스키마가 학습된다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html as H
import engine
import locators
from locators import locate_by_example

# 3개의 반복 레코드(영상 카드처럼). 각 카드에 제목/채널이 짝지어 있음.
_LIST = """<html><body><ul>
<li><a>제목A</a><span>채널가</span></li>
<li><a>제목B</a><span>채널나</span></li>
<li><a>제목C</a><span>채널다</span></li>
</ul></body></html>"""


def test_by_example_same_record_succeeds():
    """[역할] 양성 대조 — '같은 한 항목'의 값들(제목A+채널가)이면 정상 매칭."""
    dom = H.fromstring(_LIST)
    rec, sig, matched, err = locate_by_example(dom, ["제목A", "채널가"])
    assert err is None and rec is not None
    # 두 값 모두 그 레코드 안에서 노드로 잡혀야 함
    assert all(m[1] is not None for m in matched)


def test_by_example_mixed_records_detected():
    """[역할] ★버그#9 회귀가드 — 서로 다른 레코드의 값(제목A+채널나)은 '예시값 불일치'로 감지."""
    dom = H.fromstring(_LIST)
    rec, sig, matched, err = locate_by_example(dom, ["제목A", "채널나"])
    assert rec is None
    assert err and err.startswith(locators._MIXED_ROWS_TAG), f"불일치 감지 실패(err={err!r})"
    # 어긋난 값이 무엇인지 사용자에게 짚어줘야 함
    assert "채널나" in err


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

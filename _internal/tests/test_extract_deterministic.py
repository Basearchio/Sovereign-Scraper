# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_extract_deterministic.py
PURPOSE: 결정적(비-LLM) 추출 경로가 리팩터로 안 깨졌는지 고정. LLM 모듈을 옮겨도
         '반복 레코드 탐지 + by-example 결정적 매칭'은 그대로여야 한다는 회귀 기준.
DEPENDENCY: lxml. 네트워크/LLM/브라우저 불필요(작은 인라인 HTML 만 사용).

[검증된 주요 사이트 및 케이스]
- 저장 HTML 대신 최소 반복 리스트(li[a,span] 3개)로 구조를 대표. saramin/incruit 류의
  '정적 목록 → 결정적 매칭'과 동일 계약(앵커=첫 값, href/텍스트 매칭)을 압축 재현.

[테스트/운영 교훈]
- LLM 은 '결정적 매칭 실패 시에만' 타는 폴백 → 이 결정적 경로가 살아 있어야 LLM 호출이
  최소화된다(성능/비용). 이 테스트가 그 1차 방어선을 고정한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html as H
import engine
import locators

# 최소 반복 리스트: 카드 3개(제목 링크 + 가격). 실제 목록 페이지의 압축판.
# href 는 절대 URL — looks_url() 이 상대경로('/p/1')는 URL 로 안 보기 때문(특성화된 동작).
_HTML = (
    "<html><body><ul>"
    '<li class="card"><a href="https://ex.com/p/1" class="t">사과</a><span class="price">1,000원</span></li>'
    '<li class="card"><a href="https://ex.com/p/2" class="t">바나나</a><span class="price">2,000원</span></li>'
    '<li class="card"><a href="https://ex.com/p/3" class="t">체리</a><span class="price">3,000원</span></li>'
    "</ul></body></html>"
)


def _dom():
    return H.fromstring(_HTML)


def test_find_repeating_rows():
    """[역할] 반복 레코드 3개(li)와 구조 시그니처를 고정(MDR 탐지 계약)."""
    rows, sig = engine.find_repeating_rows(_dom())
    assert len(rows) == 3
    assert rows[0].tag == "li"
    assert sig == "li[a,span]", f"sig 변경 감지: {sig!r}"


def test_locate_by_example_matches_title_and_price():
    """[역할] 앵커(첫 값) 기반 결정적 매칭 — 제목=<a>, 가격=<span> 로 정확히 잡음."""
    rec, sig, matched, err = locators.locate_by_example(_dom(), ["사과", "1,000원"])
    assert err is None
    assert rec is not None
    assert len(matched) == 2
    vals = [m[0] for m in matched]
    tags = [m[1].tag for m in matched]      # (value, node, name, attr)
    assert vals == ["사과", "1,000원"]
    assert tags == ["a", "span"]


def test_locate_by_example_href_on_link_field():
    """[역할] 절대 URL 값을 주면 href 속성으로 매칭되는 계약 고정(attr=='href')."""
    url = "https://ex.com/p/1"
    rec, sig, matched, err = locators.locate_by_example(_dom(), ["사과", url])
    assert err is None
    link = [m for m in matched if m[0] == url]   # (value, node, name, attr)
    assert link and link[0][3] == "href"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

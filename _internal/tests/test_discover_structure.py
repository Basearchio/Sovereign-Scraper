# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_discover_structure.py
PURPOSE: 자동 재학습의 최후 폴백 llm_locators.discover_structure 계약 — 저장 HTML(dom)에서
         '기존 필드명'을 키로 LLM 매핑 → 그 이름 그대로 노드를 도출(이름 보존). 반복 없음/이름 없음은
         우아하게 (None, err). LLM 은 페이크로 대체(네트워크/모델 불필요).
DEPENDENCY: lxml(파싱) + services.llm_service(ask_json 을 테스트에서 가짜로 교체).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lxml import html

import services.llm_service as svc
import llm_locators

_HTML = """
<ul class="list">
  <li class="card"><a href="/1"><span class="t">제목A</span></a><span class="p">1,000원</span></li>
  <li class="card"><a href="/2"><span class="t">제목B</span></a><span class="p">2,000원</span></li>
  <li class="card"><a href="/3"><span class="t">제목C</span></a><span class="p">3,000원</span></li>
  <li class="card"><a href="/4"><span class="t">제목D</span></a><span class="p">4,000원</span></li>
</ul>
"""


def test_discover_structure_preserves_field_names():
    dom = html.fromstring(_HTML)
    old = svc.ask_json
    # LLM 은 첫 레코드(제목A/1,000원) 값을 돌려준다고 가정
    svc.ask_json = lambda *a, **k: [{"name": "제목", "value": "제목A"},
                                    {"name": "가격", "value": "1,000원"}]
    try:
        rec, sig, sel, err = llm_locators.discover_structure(
            dom, ["제목", "가격"], {"제목": "제목X", "가격": "9,999원"})
    finally:
        svc.ask_json = old
    assert err is None and rec is not None
    assert [n for n, _ in sel] == ["제목", "가격"]        # 이름 보존(순서까지)
    nodes = dict(sel)
    assert nodes["제목"] is not None and "제목A" in nodes["제목"].text_content()
    assert nodes["가격"] is not None and "1,000" in nodes["가격"].text_content()


def test_discover_structure_no_repeating_rows():
    dom = html.fromstring("<div><p>단일 문단</p></div>")
    rec, sig, sel, err = llm_locators.discover_structure(dom, ["제목"], {})
    assert rec is None and err


def test_discover_structure_empty_field_names():
    dom = html.fromstring(_HTML)
    rec, sig, sel, err = llm_locators.discover_structure(dom, [], {})
    assert rec is None and err       # 이름이 없으면 보존할 것도 없음 → 즉시 실패


def test_discover_structure_llm_values_absent_in_html():
    dom = html.fromstring(_HTML)
    old = svc.ask_json
    svc.ask_json = lambda *a, **k: [{"name": "제목", "value": "존재하지않는값ZZZ"}]
    try:
        rec, sig, sel, err = llm_locators.discover_structure(dom, ["제목"], {})
    finally:
        svc.ask_json = old
    assert rec is None and err        # HTML 에서 못 찾으면 채택 안 함(오채택 방지)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

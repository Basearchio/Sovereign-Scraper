# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_improvement_brief.py
PURPOSE: llm_locators.improvement_brief 계약 — full-HTML 재학습으로만 뚫린 케이스에 대해 '왜 값싼
         휴리스틱이 놓쳤고 어떻게 고칠지'를 개발자(Claude)용 브리핑으로 만든다. findings/engine_hint 가
         프롬프트에 반영되고, findings 가 비면 None. LLM 은 페이크.
DEPENDENCY: llm_locators + services.llm_service(ask 페이크). 네트워크/모델 불필요.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.llm_service as svc
import llm_locators


def test_improvement_brief_reflects_findings_and_hint():
    captured = {}

    def fake_ask(prompt, **k):
        captured["p"] = prompt
        return "- 이유: class 가 price 가 아니라 cost\n- 단서: ₩ 접두\n- 제안: FIELD_DEFS 매처 확장"

    old = svc.ask
    svc.ask = fake_ask
    try:
        brief = llm_locators.improvement_brief(
            "<li class='card'><span class='cost'>₩12,000</span></li>",
            [("가격", "₩12,000", "span.cost, path=[['span',0]]")],
            engine_hint="구조경로=None, 휴리스틱 매처=미스")
    finally:
        svc.ask = old
    assert brief and "제안" in brief
    # findings·engine_hint·HTML 이 프롬프트에 실려 브리핑이 근거를 갖는다
    assert "가격" in captured["p"] and "₩12,000" in captured["p"] and "cost" in captured["p"]
    assert "구조경로=None" in captured["p"]
    assert "<li" in captured["p"]
    # 마무리에 '적용 후 기록 후 삭제(resolve)' 라이프사이클 지시가 붙는다
    assert "resolve" in brief and "삭제" in brief


def test_improvement_brief_none_when_no_findings():
    assert llm_locators.improvement_brief("<li></li>", []) is None


def test_improvement_brief_none_when_llm_blank():
    old = svc.ask
    svc.ask = lambda *a, **k: "   "
    try:
        assert llm_locators.improvement_brief("<li/>", [("가격", "1,000", "span")]) is None
    finally:
        svc.ask = old


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

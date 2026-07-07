# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_learning_heal.py
PURPOSE: (v5.0, slice 3c) 학습 단계에서 값싼 방법으로도 못 잡은 '요청 필드'를 LLM(discover_structure)
         으로 마지막 회복 + heal_knowledge 저널 기록. AUTO_HEAL OFF 면 LLM 0(값싼까지만),
         ON 이면 rec 자손인 회복 노드만 채택하고 '왜 놓쳤나'를 저널에 남긴다. LLM/디스크는 페이크.
DEPENDENCY: 표준 라이브러리 + lxml. 네트워크/모델/실제 파일쓰기 없음(record 페이크).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html
import autoheal
import heal_knowledge


def _rec():
    dom = lxml.html.fromstring('<div class="rec"><p class="a">TEXT</p><span class="b">MISS</span></div>')
    return dom, dom  # 여기선 dom==rec


def _patch(auto_on, discover, captured):
    autoheal._auto_heal_enabled = lambda: auto_on
    autoheal._discover_impl = discover
    autoheal.improvement_brief = lambda *a, **k: "개선 브리핑"
    heal_knowledge.record = lambda cue, path=None: captured.append(cue)


def test_off_gate_no_llm_no_journal():
    dom, rec = _rec()
    cap = []
    old = (autoheal._auto_heal_enabled, autoheal._discover_impl, autoheal.improvement_brief, heal_knowledge.record)
    _patch(False, lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM 호출되면 안 됨")), cap)
    try:
        out = autoheal._heal_missing_at_learning("http://x", dom, rec, [("MISS", False)], ["제목"])
    finally:
        (autoheal._auto_heal_enabled, autoheal._discover_impl, autoheal.improvement_brief, heal_knowledge.record) = old
    assert out == [] and cap == []          # OFF → 회복 없음, 저널 기록 없음


def test_on_recovers_node_inside_rec_and_journals():
    dom, rec = _rec()
    span = rec.find(".//span")
    cap = []
    fake = lambda d, names, ex: (rec, "sig", [(names[0], span)], None)
    old = (autoheal._auto_heal_enabled, autoheal._discover_impl, autoheal.improvement_brief, heal_knowledge.record)
    _patch(True, fake, cap)
    try:
        out = autoheal._heal_missing_at_learning("http://x", dom, rec, [("MISS", False)], ["제목"])
    finally:
        (autoheal._auto_heal_enabled, autoheal._discover_impl, autoheal.improvement_brief, heal_knowledge.record) = old
    assert len(out) == 1 and out[0][1] is span and out[0][3] == "MISS"   # 회복됨
    assert len(cap) == 1 and cap[0]["source"] == "learning_miss"          # 저널 기록됨
    assert cap[0]["fields"][0]["recovered"] is True
    assert cap[0]["fix_prompt"] == "개선 브리핑"


def test_on_node_outside_rec_not_recovered_but_journaled():
    dom, rec = _rec()
    outside = lxml.html.fromstring("<a href='/z'>딴 것</a>")   # rec 자손 아님
    cap = []
    fake = lambda d, names, ex: (rec, "sig", [(names[0], outside)], None)
    old = (autoheal._auto_heal_enabled, autoheal._discover_impl, autoheal.improvement_brief, heal_knowledge.record)
    _patch(True, fake, cap)
    try:
        out = autoheal._heal_missing_at_learning("http://x", dom, rec, [("http://x/z", True)], ["제목"])
    finally:
        (autoheal._auto_heal_enabled, autoheal._discover_impl, autoheal.improvement_brief, heal_knowledge.record) = old
    assert out == []                                     # rec 밖 → 미채택(침범 방지)
    assert len(cap) == 1 and cap[0]["fields"][0]["recovered"] is False    # 그래도 저널엔 미해결로 남김


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

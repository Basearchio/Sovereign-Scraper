# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_heal_knowledge.py
PURPOSE: 실패 진단 저널(heal_knowledge)의 계약 — 큐 축적/조회, (site,field,path) 중복은 최신 교체,
         진단 필드(tried/why/context) 원형 보존, 사이트 우선 정렬, 그리고 leaf 경계(상위 import 금지).
DEPENDENCY: 표준 라이브러리만(tempdir 로 실제 recipes/_heal_hints.json 을 건드리지 않음).
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import heal_knowledge as hk


def test_record_then_read_roundtrip_with_diagnostics():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "hints.json")
        cue = {"field": "가격", "site": "incruit", "example": "12,000원",
               "tag": "span", "class_token": "price", "shape": "num",
               "path": [["div", 0], ["span", 1]], "source": "full_llm",
               "tried": ["structural_path", "heuristic", "relocate"],
               "why": "text cue mismatch(₩ prefix)", "context": "<span>₩12,000</span>"}
        hk.record(cue, path=p)
        got = hk.all_hints(path=p)
        assert len(got) == 1
        # 진단 필드가 원형 그대로 보존되어야 '왜 못 찾았나'를 사람이 읽을 수 있다
        assert got[0]["why"] == "text cue mismatch(₩ prefix)"
        assert got[0]["tried"] == ["structural_path", "heuristic", "relocate"]
        assert got[0]["source"] == "full_llm"


def test_dedup_same_site_field_path_keeps_latest():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "hints.json")
        base = {"field": "가격", "site": "incruit", "path": [["span", 1]]}
        hk.record({**base, "example": "1,000"}, path=p)
        hk.record({**base, "example": "9,999"}, path=p)   # 같은 (site,field,path) → 교체
        got = hk.all_hints(path=p)
        assert len(got) == 1 and got[0]["example"] == "9,999"


def test_hints_for_prefers_same_site():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "hints.json")
        hk.record({"field": "가격", "site": "albamon", "path": [["a", 0]]}, path=p)
        hk.record({"field": "가격", "site": "incruit", "path": [["b", 0]]}, path=p)
        hk.record({"field": "제목", "site": "incruit", "path": [["c", 0]]}, path=p)
        out = hk.hints_for("가격", site="incruit", path=p)
        assert [c["site"] for c in out][0] == "incruit"      # 사이트 일치 우선
        assert all(c["field"] == "가격" for c in out)          # 필드 필터
        assert len(out) == 2                                  # 크로스사이트도 폴백 포함


def test_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        assert hk.all_hints(path=os.path.join(d, "nope.json")) == []
        assert hk.hints_for("가격", path=os.path.join(d, "nope.json")) == []


def test_resolve_records_then_removes_from_active():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "hints.json")
        rp = os.path.join(d, "resolved.json")
        cue = {"field": "가격", "site": "incruit", "path": [["span", 1]], "fix_prompt": "..."}
        hk.record(cue, path=p)
        n = hk.resolve(cue, note="FIELD_DEFS['가격'] 매처에 ₩ 접두 인정", path=p, resolved_path=rp)
        assert n == 1
        assert hk.all_hints(path=p) == []          # 활성 저널에서 삭제(미해결만 남김)
        log = hk.all_hints(path=rp)
        assert len(log) == 1                        # 이력엔 기록 보존
        assert log[0]["resolved_note"].startswith("FIELD_DEFS") and log[0]["resolved_at"]


def test_resolve_no_match_returns_zero():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "hints.json")
        hk.record({"field": "가격", "site": "incruit", "path": [["a", 0]]}, path=p)
        assert hk.resolve({"field": "없음", "site": "x", "path": []}, path=p) == 0
        assert len(hk.all_hints(path=p)) == 1       # 매치 없으면 활성 저널 불변


def test_heal_knowledge_is_leaf():
    """상위 계층(engine/cli/llm 등)을 import 하지 않는다 — leaf 경계를 소스 스캔으로 강제."""
    banned = {"engine", "cli", "chain", "replay", "crawlers", "core",
              "services", "llm_locators"}
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "heal_knowledge.py")
    offenders = []
    with open(src, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            m = re.match(r"(?:import|from)\s+([\w.]+)", line.strip())
            if m and m.group(1).split(".")[0] in banned:
                offenders.append(f"{i}: {line.strip()}")
    assert not offenders, "heal_knowledge 가 상위 계층을 import 함:\n" + "\n".join(offenders)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

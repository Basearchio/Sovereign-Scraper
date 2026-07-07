# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_segment.py
PURPOSE: (v5.0) 한 노드에 뭉친 여러 필드를 '사용자 예시 경계'로 분리(사이트 하드코딩 없음).
         Naver 증시 사례: 변동폭 "-655.32" + 변동률 "(7.89%)" 가 한 노드 "-655.32 (7.89%)".
         분리 규칙이 예시에서 파생되고, 추출에서 필드별로 다른 값이 나오며, 레시피 왕복에 보존됨을 검증.
DEPENDENCY: 표준 라이브러리 + lxml. 네트워크/LLM 불필요.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html
import engine
from engine import SelfHealingEngine
from core.schema import Schema


def test_split_and_segment_helpers():
    assert engine._split_segments("-655.32 (7.89%)", [" "]) == ["-655.32", "(7.89%)"]
    assert engine._segment_value("-655.32 (7.89%)", [" "], 0) == "-655.32"
    assert engine._segment_value("-655.32 (7.89%)", [" "], 1) == "(7.89%)"
    assert engine._segment_value("그대로", None, None) == "그대로"     # 규칙 없으면 원문


def test_derive_from_example_boundary():
    d = engine._derive_colocated_split(
        "-655.32 (7.89%)", [("변동폭", "-655.32"), ("변동률", "(7.89%)")])
    assert d["변동폭"] == (0, [" "], "-655.32")
    assert d["변동률"] == (1, [" "], "(7.89%)")
    # 겹치거나 예시가 없으면 분리 안 함(None)
    assert engine._derive_colocated_split("abc", [("x", "abc"), ("y", "abc")]) is None
    assert engine._derive_colocated_split("ab", [("x", "a"), ("y", "b")]) is None  # 딱 붙음


_HTML = """<ul>
  <li class="row"><span class="name">코스피</span><div class="ratio">-655.32 (7.89%)</div></li>
  <li class="row"><span class="name">코스닥</span><div class="ratio">-62.63 (6.74%)</div></li>
  <li class="row"><span class="name">S&amp;P 500</span><div class="ratio">-16.13 (0.22%)</div></li>
</ul>"""


def _build_engine():
    dom = lxml.html.fromstring(_HTML)
    rec = dom.findall(".//li")[0]
    name_node = rec.find(".//span")
    ratio_node = rec.find(".//div")
    sels = [("지수명", name_node, None, "코스피"),
            ("변동폭", ratio_node, None, "-655.32"),
            ("변동률", ratio_node, None, "(7.89%)")]
    eng = SelfHealingEngine(verbose=False)
    eng.build_schema_from_selection([rec], "li[span,div]", sels, dom=dom)
    return eng, dom


def test_build_learns_segment_from_shared_node():
    eng, _ = _build_engine()
    assert eng.schema.fields["변동폭"]["seg_index"] == 0
    assert eng.schema.fields["변동률"]["seg_index"] == 1
    assert eng.schema.fields["변동폭"]["seg_seps"] == [" "]
    # 지수명은 단독 노드 → 분리 규칙 없음
    assert eng.schema.fields["지수명"].get("seg_seps") is None


def test_extract_splits_each_row():
    eng, dom = _build_engine()
    rows = eng.extract(dom)
    assert len(rows) == 3
    assert rows[0]["변동폭"] == "-655.32" and rows[0]["변동률"] == "(7.89%)"
    assert rows[1]["변동폭"] == "-62.63" and rows[1]["변동률"] == "(6.74%)"
    assert rows[2]["변동폭"] == "-16.13" and rows[2]["변동률"] == "(0.22%)"
    assert rows[0]["지수명"] == "코스피"


def test_recipe_roundtrip_preserves_segment():
    eng, _ = _build_engine()
    p = os.path.join(tempfile.gettempdir(), "zz_seg_recipe.csv")
    try:
        eng.schema.save_csv_recipe(p, url="http://x", load_method="chrome")
        s2, url, lm, wait, pages = Schema.from_csv_recipe(p)
        assert s2.fields["변동폭"]["seg_index"] == 0
        assert s2.fields["변동률"]["seg_seps"] == [" "]
        assert s2.fields["지수명"].get("seg_index") is None   # 미분리 필드는 None 유지
    finally:
        if os.path.exists(p):
            os.remove(p)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_polish.py
PURPOSE: (v5.0) 결정적 폴리시 3종 — ①모든 필드 None 행 드롭, ②명시 링크와 중복되는 auto _url 제거,
         ③상대경로 링크 절대화(urljoin). 전부 추측 없는 규칙(하드코딩/휴리스틱 아님).
DEPENDENCY: 표준 라이브러리 + lxml. 네트워크/LLM 불필요.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html
import engine
from engine import SelfHealingEngine


def test_abs_url_deterministic():
    b = "http://ex.com/world"
    assert engine._abs_url(b, "/2026/x") == "http://ex.com/2026/x"
    assert engine._abs_url(b, "http://other.com/y") == "http://other.com/y"  # 이미 절대
    assert engine._abs_url(None, "/x") == "/x"                                # base 없으면 그대로
    assert engine._abs_url(b, "#") == "#"                                     # 프래그먼트 유지
    assert engine._abs_url(b, "mailto:a@b") == "mailto:a@b"


_HTML = """<ul>
  <li class="row"><a class="t" href="/pin/1">TITLE1</a></li>
  <li class="row"></li>
  <li class="row"><a class="t" href="/pin/2">TITLE2</a></li>
</ul>"""


def _build():
    dom = lxml.html.fromstring(_HTML)
    rec = dom.findall(".//li")[0]
    a = rec.find(".//a")
    sels = [("제목", a, None, "TITLE1"),      # 텍스트(노드에 href 있음 → auto 제목_url 생김)
            ("링크", a, "href", "/pin/1")]      # 사용자가 같은 링크를 명시
    eng = SelfHealingEngine(verbose=False)
    eng.build_schema_from_selection([rec], "li[a]", sels, dom=dom)
    return eng, dom


def test_duplicate_url_column_removed():
    eng, _ = _build()
    # 제목_url 은 명시 '링크'와 동일 href → 제거됨
    assert "제목_url" not in eng.schema.fields
    assert "링크" in eng.schema.fields and "제목" in eng.schema.fields


def test_all_none_row_dropped_and_links_absolutized():
    eng, dom = _build()
    rows = eng.extract(dom, base_url="http://ex.com/world")
    assert len(rows) == 2                                  # 가운데 빈 li 드롭
    assert rows[0]["링크"] == "http://ex.com/pin/1"        # 상대→절대
    assert rows[1]["링크"] == "http://ex.com/pin/2"
    assert rows[0]["제목"] == "TITLE1"


def test_no_base_keeps_relative():
    eng, dom = _build()
    rows = eng.extract(dom)                                # base 없음 → 그대로
    assert rows[0]["링크"] == "/pin/1"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

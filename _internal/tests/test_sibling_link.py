# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_sibling_link.py
PURPOSE: (v5.0, slice 3a) 링크가 레코드의 '형제 가지'(썸네일 <a>)에 있어도, 카드 경계까지 넓혀
         값싸게(LLM 없이) 회복한다. Bilibili 실패 재현: 레코드=video-card__info, 링크=video-card__content.
         좁은 스코프(_match_href)는 못 잡고, _match_href_broadened / locate_by_example 는 잡아야 한다.
DEPENDENCY: 표준 라이브러리 + lxml. 네트워크/LLM 불필요.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html
import engine
from engine import SelfHealingEngine
from locators import locate_by_example, _match_href, _match_href_broadened

# Bilibili 구조 모사: 카드(video-card) 아래 형제 두 가지 — content(링크) / info(텍스트).
_HTML = """<ul class="card-list">
  <li class="video-card">
    <div class="video-card__content"><a href="https://x.com/video/BV1">보기</a></div>
    <div class="video-card__info"><p class="name">제목하나</p><span class="up">작가하나</span></div>
  </li>
  <li class="video-card">
    <div class="video-card__content"><a href="https://x.com/video/BV2">보기</a></div>
    <div class="video-card__info"><p class="name">제목둘</p><span class="up">작가둘</span></div>
  </li>
</ul>"""


def _dom():
    return lxml.html.fromstring(_HTML)


def test_narrow_scope_misses_sibling_link():
    dom = _dom()
    info = [e for e in dom.iter() if "video-card__info" in (e.get("class") or "")][0]
    # 레코드(info) 자손+조상만 보는 좁은 매칭은 형제 가지의 링크를 못 잡는다
    assert _match_href(info, "https://x.com/video/BV1?") is None


def test_broadened_recovers_sibling_link():
    dom = _dom()
    info = [e for e in dom.iter() if "video-card__info" in (e.get("class") or "")][0]
    node = _match_href_broadened(dom, info, "https://x.com/video/BV1?")   # 끝 ? 포함(사용자 복사)
    assert node is not None and "BV1" in (node.get("href") or "")


def test_locate_by_example_includes_link_field():
    dom = _dom()
    values = ["제목하나", "작가하나", "https://x.com/video/BV1?"]
    rec, sig, matched, err = locate_by_example(dom, values)
    assert err is None
    by_val = {v: node for v, node, nm, attr in matched}
    # 링크가 형제 가지에 있어도 이제 잡힌다(값싼 회복) → node not None
    assert by_val["https://x.com/video/BV1?"] is not None
    assert "BV1" in (by_val["https://x.com/video/BV1?"].get("href") or "")
    # 레코드가 '카드'로 승격됐는지(텍스트+링크 공통 조상)
    assert "video-card" in (rec.get("class") or "")


def test_extraction_populates_link_per_row():
    # ★ 핵심: 학습만이 아니라 '행별 추출'에서도 각 카드의 링크가 채워져야 한다(재현).
    dom = _dom()
    rec, sig, matched, err = locate_by_example(
        dom, ["제목하나", "작가하나", "https://x.com/video/BV1?"])
    sels = [("제목", matched[0][1], None, "제목하나"),
            ("작가", matched[1][1], None, "작가하나"),
            ("링크", matched[2][1], "href", "https://x.com/video/BV1?")]
    eng = SelfHealingEngine(verbose=False)
    eng.build_schema_from_selection([rec], sig, sels, dom=dom)
    rows = eng.extract(dom)
    assert len(rows) == 2
    assert rows[0]["링크"] and "BV1" in rows[0]["링크"]      # 1행 링크 채워짐
    assert rows[1]["링크"] and "BV2" in rows[1]["링크"]      # 2행은 자기 링크(BV2)
    assert rows[0]["제목"] == "제목하나" and rows[1]["제목"] == "제목둘"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

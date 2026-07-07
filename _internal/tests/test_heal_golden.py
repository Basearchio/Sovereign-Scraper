# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_heal_golden.py
PURPOSE: 자가치유(Self-Heal) '행동' 골든 테스트 — 이 엔진의 심장. 클래스명이 난독화로 바뀌어
         CSS 셀렉터가 깨져도, '구조 시그니처/구조 경로'로 같은 값을 재획득하고 셀렉터를 자가
         갱신하는지를 결정적으로 못박는다. (구조/스모크 테스트로는 못 잡는 핵심 알고리즘 회귀 방지.)
DEPENDENCY: lxml. 네트워크/LLM/브라우저 불필요(오프라인 결정적 — 구조 경로만으로 치유되는 케이스).

[검증된 주요 사이트 및 케이스]
- 대표 실패유형(난독화 리빌드로 class 변경, DOM 구조 동일)의 축소 재현: 행/필드 셀렉터가 깨져도
  값 보존 + 셀렉터 자가 갱신. saramin/ruliweb 류 '클래스만 바뀜'의 핵심 계약.

[테스트/운영 교훈]
- 자가치유는 '결정론 우선(구조 경로) → 실패 시에만 LLM'이다. 여기서는 LLM 없이 구조만으로
  치유되는 경로를 고정한다(LLM 경로는 test_llm_service 가 별도 커버).
- 조용한 회귀가 치명적이라, '값 보존'뿐 아니라 '셀렉터가 실제로 새 클래스로 갱신됐는지'까지 확인.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html as H
from engine import SelfHealingEngine, find_repeating_rows, row_sig

# 원본: 정상 클래스(item/title/author). a 는 실제 이동 링크(href) → title_url 자동 생성.
_ORIG = """<html><body><ul>
<li class="item"><a class="title" href="/p/1">첫 제목</a><span class="author">홍길동</span></li>
<li class="item"><a class="title" href="/p/2">둘째 제목</a><span class="author">김철수</span></li>
<li class="item"><a class="title" href="/p/3">셋째 제목</a><span class="author">이영희</span></li>
</ul></body></html>"""

# 난독화 리빌드: 클래스명만 전부 바뀌고(DOM 구조/텍스트/링크는 동일) → CSS 셀렉터가 깨진다.
_MUTATED = """<html><body><ul>
<li class="card"><a class="t9x" href="/p/1">첫 제목</a><span class="a7z">홍길동</span></li>
<li class="card"><a class="t9x" href="/p/2">둘째 제목</a><span class="a7z">김철수</span></li>
<li class="card"><a class="t9x" href="/p/3">셋째 제목</a><span class="a7z">이영희</span></li>
</ul></body></html>"""


def _build_engine(html):
    """원본 HTML 로 '사용자가 title/author 를 고른' 스키마를 만든 엔진을 반환."""
    dom = H.fromstring(html)
    rows, _ = find_repeating_rows(dom)
    sample = rows[0]
    title_node = sample.xpath(".//a")[0]
    author_node = sample.xpath(".//span")[0]
    eng = SelfHealingEngine(verbose=False)
    eng.build_schema_from_selection(
        rows, row_sig(sample), [("title", title_node), ("author", author_node)], dom=dom)
    return eng


def test_fast_path_no_heal_on_original():
    """[역할] 클래스가 그대로면 빠른 경로로 정확히 추출(치유 불필요)."""
    eng = _build_engine(_ORIG)
    css_before = eng.schema.fields["title"]["css"]
    out = eng.extract(H.fromstring(_ORIG))
    assert [r["title"] for r in out] == ["첫 제목", "둘째 제목", "셋째 제목"]
    assert [r["author"] for r in out] == ["홍길동", "김철수", "이영희"]
    assert eng.schema.fields["title"]["css"] == css_before  # 셀렉터 변화 없음(치유 없음)
    assert css_before == "a.title"


def test_self_heal_preserves_values_when_classes_break():
    """[역할] 클래스가 전부 바뀌어 CSS 가 깨져도(구조 동일), 값을 그대로 재획득하는지(핵심 계약)."""
    eng = _build_engine(_ORIG)               # 원본으로 학습
    out = eng.extract(H.fromstring(_MUTATED))  # 난독화된 페이지에서 추출
    assert len(out) == 3, "행 셀렉터가 깨져도 구조 시그니처로 3행을 재탐색해야 함"
    assert [r["title"] for r in out] == ["첫 제목", "둘째 제목", "셋째 제목"]
    assert [r["author"] for r in out] == ["홍길동", "김철수", "이영희"]
    # 텍스트 필드가 품은 실제 링크(title_url)도 유지
    assert [r["title_url"] for r in out] == ["/p/1", "/p/2", "/p/3"]


def test_self_heal_rewrites_selectors():
    """[역할] 치유가 '값 보존'에 그치지 않고, 깨진 셀렉터를 새 클래스로 자가 갱신하는지."""
    eng = _build_engine(_ORIG)
    assert eng.schema.fields["title"]["css"] == "a.title"   # 학습 시점
    eng.extract(H.fromstring(_MUTATED))
    # 행/필드 셀렉터가 새 클래스로 갱신됐는지(옛 클래스는 사라져야 함)
    assert eng.schema.row_cls != "item", "행 셀렉터가 새 클래스로 갱신돼야 함"
    title_css = eng.schema.fields["title"]["css"]
    assert "title" not in title_css and title_css != "a.title", \
        f"필드 셀렉터가 갱신돼야 함(got {title_css})"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

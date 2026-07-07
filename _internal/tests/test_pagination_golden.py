# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_pagination_golden.py
PURPOSE: 목록 크롤의 '행동' 골든 — 중복제거 키(_rec_key), dedup 필드 선택(_choose_url_field),
         결과 유효성 가드(_run_is_valid), 페이지네이션 파라미터 학습/적용(learn/apply_page_param,
         _next_page_url 의 학습된 패턴 경로)을 결정적으로 못박는다.
DEPENDENCY: lxml(불필요할 수 있음), 표준. 네트워크/LLM 불필요(학습된 패턴 경로는 LLM 안 탐).

[검증된 주요 사이트 및 케이스]
- page 기반(1→2, step 1)·offset 기반(0→30, step 30) 페이지네이션 학습.
- 가짜 링크(javascript:;)는 dedup 키로 안 씀(모든 행 동일값으로 dedup 망치는 것 방지).

[테스트/운영 교훈]
- 자가치유가 차단/엉뚱 페이지에 끌려가면 전부 None → _run_is_valid 로 '레시피/CSV 오염' 차단.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import _rec_key, _choose_url_field, _run_is_valid, _next_page_url
from pagination import learn_page_param, apply_page_param


# ── 중복제거 키 ───────────────────────────────────────────────────────────────
def test_rec_key_prefers_explicit_url_field():
    assert _rec_key({"u": "http://a/1", "t": "x"}, ["u", "t"], url_field="u") == ("u", "http://a/1")


def test_rec_key_auto_uses_real_link_not_fake():
    # 실제 링크 필드가 있으면 그 값으로
    assert _rec_key({"제목": "x", "제목_url": "http://a/1"}, ["제목", "제목_url"]) == ("u", "http://a/1")
    # javascript:;/# 같은 가짜 링크는 키로 안 씀 → 값 전체(text) 튜플로 폴백
    k = _rec_key({"제목": "x", "제목_url": "javascript:;"}, ["제목", "제목_url"])
    assert k[0] == "t"
    # 링크 필드가 없으면 값 전체
    assert _rec_key({"a": "1", "b": "2"}, ["a", "b"]) == ("t", ("1", "2"))


# ── dedup 필드 선택 ──────────────────────────────────────────────────────────
def test_choose_url_field_picks_discriminating_link():
    rows = [{"t": "a", "link_url": "http://x/1"},
            {"t": "b", "link_url": "http://x/2"},
            {"t": "c", "link_url": "http://x/3"}]
    assert _choose_url_field(rows, ["t", "link_url"]) == "link_url"


def test_choose_url_field_none_when_links_all_same():
    rows = [{"link_url": "http://x/1"} for _ in range(3)]   # 변별력 없음
    assert _choose_url_field(rows, ["link_url"]) is None


# ── 결과 유효성 가드(오염 방지) ──────────────────────────────────────────────
def test_run_is_valid_half_threshold():
    assert _run_is_valid([{"a": "1", "b": "2"}], ["a", "b"])                       # 2/2
    assert not _run_is_valid([{"a": None, "b": None}], ["a", "b"])                 # 0/2
    assert not _run_is_valid([], ["a", "b"])                                       # 결과 없음
    assert _run_is_valid([{"a": "1", "b": "2", "c": None, "d": None}], list("abcd"))       # 2>=2(need)
    assert not _run_is_valid([{"a": "1", "b": None, "c": None, "d": None}], list("abcd"))  # 1<2


# ── 페이지네이션 파라미터 학습/적용 ──────────────────────────────────────────
def test_learn_and_apply_page_param_roundtrip():
    # page 기반(step 1)
    p = learn_page_param("http://x/list?page=1", "http://x/list?page=2")
    assert p == ("page", 1)
    assert apply_page_param("http://x/list?page=2", *p) == "http://x/list?page=3"
    # offset 기반(step 30)
    o = learn_page_param("http://x/l?offset=0", "http://x/l?offset=30")
    assert o == ("offset", 30)
    assert apply_page_param("http://x/l?offset=30", *o) == "http://x/l?offset=60"
    # 경로가 다르면 학습 불가(None) → LLM 이 매번 판단
    assert learn_page_param("http://x/a?page=1", "http://x/b?page=2") is None


def test_next_page_url_uses_learned_pattern_without_llm():
    """[역할] 패턴이 학습돼 있으면 LLM 호출 없이 기계적으로 다음 URL(dom 불필요)."""
    nxt, pat = _next_page_url(None, "http://x/list?page=3", ("page", 1))
    assert nxt == "http://x/list?page=4"
    assert pat == ("page", 1)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

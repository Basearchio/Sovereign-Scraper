# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_chain_golden.py
PURPOSE: 체인 크롤링(목록 CSV → 상세페이지) 핵심 블록의 '행동' 골든 테스트.
         (1) URL 정련 by-example(_derive_url_cleaner): 링크 1개를 고친 예시로 열 전체 규칙 추론.
         (2) 단일 레코드 추출(_extract_single): 스키마를 '고정'으로 다루고, 텍스트가 비면 그 페이지
             한정으로 이미지/링크 URL 폴백 — 한 페이지의 특이 케이스가 공유 스키마를 오염(#20)시키지
             않음을 못박는다.
DEPENDENCY: lxml. 네트워크/LLM/브라우저 불필요(오프라인 결정적).

[검증된 주요 사이트 및 케이스]
- incruit 류 체인: 추적 파라미터(&src=..) 꼬리 정련, 이미지 공고 폴백.
- 회귀 가드: '이미지 공고 1건이 이후 정상 페이지 전부를 오염'(개발이력 #20)의 재발 방지.

[테스트/운영 교훈]
- 체인은 '독립된 여러 페이지'를 도는 배치 → 단일 추출은 스키마 고정, 변형은 페이지별 폴백으로.
"""
import os
import sys
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html as H
from chain import _derive_url_cleaner   # Phase 4a: 체인 로직은 chain.py 로 분리
from engine import SelfHealingEngine, row_sig


# ─────────────────────────── (1) URL 정련 by-example ───────────────────────────

def test_url_cleaner_strips_tracking_query_param():
    """[역할] 꼬리가 쿼리(&src=..)면 '파라미터 이름' 기준 제거로 업그레이드(값 달라도 처리)."""
    cleaner, desc = _derive_url_cleaner("http://x/p?id=1&src=list", "http://x/p?id=1")
    assert cleaner("http://x/q?id=9&src=banner") == "http://x/q?id=9"   # 값 달라도 src 제거
    assert cleaner("http://x/q?id=9") == "http://x/q?id=9"              # 이미 깨끗하면 그대로
    assert desc and "src" in desc


def test_url_cleaner_unwraps_wrapping_literals():
    """[역할] 앞뒤 리터럴로 '감싼' 경우(괄호 등) 열 전체에서 그 리터럴 제거."""
    cleaner, desc = _derive_url_cleaner("(http://x/p/1)", "http://x/p/1")
    assert cleaner("(http://x/p/2)") == "http://x/p/2"
    assert cleaner("http://x/p/3") == "http://x/p/3"   # 감싸지 않은 값은 그대로


def test_url_cleaner_strips_prefix_literal():
    """[역할] 앞 리터럴(예: 'link: ') 제거."""
    cleaner, _ = _derive_url_cleaner("link: http://x/a", "http://x/a")
    assert cleaner("link: http://x/b") == "http://x/b"


def test_url_cleaner_identity_and_detection_fail():
    """[역할] 변화 없으면 원본 유지, 부분문자열이 아니면 감지 실패(desc=None)로 원본 보존."""
    same, desc_same = _derive_url_cleaner("http://x/p", "http://x/p")
    assert same("http://x/keep?a=1") == "http://x/keep?a=1"
    fail, desc_fail = _derive_url_cleaner("http://x/p", "전혀-다른-값")
    assert desc_fail is None                       # 감지 실패 신호
    assert fail("http://x/orig") == "http://x/orig"  # 원본 그대로


# ────────────────── (2) 단일 레코드 추출: 고정 스키마 + 미디어 폴백 ──────────────────

# 텍스트 상세(학습용): content 컨테이너 안에 제목/본문.
_DETAIL_TEXT = """<html><body><div class="content">
<h1 class="ttl">직무 제목</h1><div class="body">상세 본문 텍스트입니다</div>
</div></body></html>"""

# 이미지 공고 상세(같은 템플릿, 본문이 텍스트 대신 이미지): 본문 텍스트가 비어 있음.
_DETAIL_IMAGE = """<html><body><div class="content">
<h1 class="ttl">이미지 공고</h1><div class="body"><img src="http://x/ad.png"></div>
</div></body></html>"""


def _build_single_engine():
    """텍스트 상세로 '제목/본문'을 고른 단일 레코드(single) 스키마 엔진."""
    dom = H.fromstring(_DETAIL_TEXT)
    container = dom.xpath("//div[@class='content']")[0]
    title = container.xpath(".//h1")[0]
    body = container.xpath(".//div[@class='body']")[0]
    eng = SelfHealingEngine(verbose=False)
    eng.build_schema_from_selection(
        [container], row_sig(container), [("제목", title), ("본문", body)],
        dom=dom, single=True, link_split=False)
    return eng


def test_single_extract_text_detail():
    """[역할] 정상(텍스트) 상세에서 제목/본문 텍스트를 그대로 추출."""
    eng = _build_single_engine()
    out = eng.extract(H.fromstring(_DETAIL_TEXT))
    assert len(out) == 1
    assert out[0]["제목"] == "직무 제목"
    assert out[0]["본문"] == "상세 본문 텍스트입니다"


def test_single_extract_image_falls_back_to_media_url():
    """[역할] 본문이 이미지뿐이면 그 페이지 한정으로 이미지 URL 을 대신 뽑는다(텍스트 폴백)."""
    eng = _build_single_engine()
    out = eng.extract(H.fromstring(_DETAIL_IMAGE))
    assert out[0]["제목"] == "이미지 공고"
    assert out[0]["본문"] == "http://x/ad.png"   # 텍스트 없음 → 미디어 URL 폴백


def test_single_schema_is_fixed_not_mutated_by_image_page():
    """[역할] ★핵심(#20 회귀가드): 이미지 페이지를 추출해도 공유 스키마가 변형되지 않는지."""
    eng = _build_single_engine()
    before = copy.deepcopy(eng.schema.fields)
    eng.extract(H.fromstring(_DETAIL_IMAGE))          # 특이 케이스(이미지) 추출
    assert eng.schema.fields == before, "단일 추출은 스키마를 고정해야 함(자가치유로 변경 금지)"
    # 이어서 정상 텍스트 페이지가 오염 없이 여전히 텍스트로 추출되는지
    out2 = eng.extract(H.fromstring(_DETAIL_TEXT))
    assert out2[0]["본문"] == "상세 본문 텍스트입니다"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

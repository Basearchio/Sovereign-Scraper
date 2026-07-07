# -*- coding: utf-8 -*-
"""
MODULE_NAME: values.py
PURPOSE: '값 의미 분류' leaf — DOM/네트워크/LLM 없이 문자열만 보고 링크/가격/날짜/형태를 판별한다.
         engine(매칭·추출)과 cli(의미 검증 가드)가 공통으로 쓰던 판별기를 한곳으로 모은 것.
         (v5.0 co-split: engine._url_key/looks_url/is_real_href/_looks_price + cli._value_shape 통합)
DEPENDENCY: 표준 라이브러리 re 만. (engine/cli/core 등 상위 모듈 import 금지 = leaf, 순환 차단)

[테스트/운영 교훈]
- 순수 함수(입력 문자열 → 판정)라 오프라인 결정적으로 검증된다 → 값 의미의 '단일 출처'.
- paths.py 에도 _url_key 가 있으나 그것은 '파일 키(사이트 식별)'용 동명이인 — 여기 것은 'URL 비교 키'.
"""
from __future__ import annotations

import re

# 가격: '25,800원' 또는 '15,980' 형태
_PRICE_RE = re.compile(r"[0-9][0-9,]{1,}\s*원")

# 날짜: 2026-07-02 / 07월 04일 / 3일 전
_DATE_RE = re.compile(
    r"\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}"          # 2026-07-02 / 2026.7.2
    r"|\d{1,2}\s*[월/]\s*\d{1,2}\s*일"           # 07월 04일
    r"|\d+\s*(분|시간|일|주|개월|달|년)\s*전")   # 3일 전


def looks_url(v: str) -> bool:
    """예시 값이 '링크(URL)'로 보이는가 (절대 URL만 안전하게 인정)."""
    v = (v or "").strip()
    return v.startswith(("http://", "https://", "//"))


_IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif", ".ico")


def looks_image_url(v: str) -> bool:
    """URL 이 '이미지 파일'을 가리키는가(확장자 기준). 타이핑 입력에서도 이미지 필드를 알아채,
    링크가 아니라 <img> 를 구조로 잡고 아카이빙하게 한다(예: pixiv i.pximg.net/...master1200.jpg).
    ※ 야후 quriosity 처럼 확장자 없는 이미지 URL 은 피커 kind='image' 로 처리(여기선 False)."""
    if not looks_url(v):
        return False
    path = v.split("?")[0].split("#")[0].lower()
    return path.endswith(_IMG_EXT)


def is_real_href(h: str) -> bool:
    """실제로 '이동하는' 링크인가. javascript:;/#/mailto:/tel:/빈값은 가짜(버튼·토글)."""
    h = (h or "").strip()
    if not h or h in ("#", "/"):
        return False
    return not h.lower().startswith(("javascript:", "#", "mailto:", "tel:"))


def _url_key(u: str) -> str:
    """URL 비교용 키: scheme/host/query 영향을 줄이고 경로 위주로."""
    u = (u or "").strip()
    u = re.sub(r"^https?:", "", u)     # scheme 제거
    u = re.sub(r"[?#].*$", "", u)      # query/fragment 제거
    return u.strip("/")


def _looks_price(s: str) -> bool:
    """문자열이 '가격'처럼 보이는가 (예: '25,800원' 또는 '15,980')."""
    s = (s or "").strip()
    return bool(_PRICE_RE.search(s)) or bool(re.fullmatch(r"[0-9][0-9,]{2,}", s))


def _value_shape(s):
    """값의 '형태' 분류: url/date/num/text/empty. (텍스트·빈값은 제약이 약한 형태)"""
    s = (s or "").strip()
    if not s:
        return "empty"
    # URL 형태: 실제 URL 모양만(is_real_href 는 가짜링크 배제용이라 판별엔 과관대).
    if s.startswith(("http://", "https://", "//", "/", "www.")) or "://" in s:
        return "url"
    if _DATE_RE.search(s):
        return "date"
    compact = re.sub(r"\s", "", s)
    digits = sum(c.isdigit() for c in compact)
    if compact and digits >= 0.5 * len(compact):   # 숫자가 절반 이상 → 수치(가격/조회수/길이)
        return "num"
    return "text"

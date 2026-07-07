# -*- coding: utf-8 -*-
"""
MODULE_NAME: field_heuristics.py
PURPOSE: '필드 휴리스틱 매처' leaf — 프로토타입에서 LLM 이 하던 역할을 대신하는 규칙 매처(제목=가장 긴
         <a>, 날짜=날짜패턴 잎, 가격 보강, 이미지/링크 대체값)와 FIELD_DEFS 레지스트리. 자가치유 엔진이
         calibrate/extract 에서 이 매처를 부른다(engine→leaf). 구조·값 판별만 structure/values(leaf)에 의존.
DEPENDENCY: structure/values(leaf) + lxml. engine/cli/llm 을 import 하지 않는다(leaf).
"""
from __future__ import annotations

import re
from typing import Optional

from lxml.html import HtmlElement

from structure import (_text, _norm, _children)
from values import (is_real_href, _PRICE_RE)


def media_urls(node: HtmlElement) -> Optional[str]:
    """텍스트가 없는 컨테이너의 '대체 내용'을 뽑는다: 이미지 src, 없으면 링크 href.

    공고 본문을 텍스트 대신 이미지/링크로만 올리는 경우(회사소개 이미지 등),
    본문 텍스트가 비므로 그 안의 이미지 URL(들)을, 그마저 없으면 실제 링크(들)를
    공백으로 이어 반환한다. 아무것도 없으면 None.
    """
    seen, out = set(), []
    for img in node.iter("img"):
        u = (img.get("src") or img.get("data-src") or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    if out:
        return " ".join(out)
    for a in node.iter("a"):
        u = (a.get("href") or "").strip()
        if u and is_real_href(u) and u not in seen:
            seen.add(u)
            out.append(u)
    return " ".join(out) if out else None


def find_record_price(record: HtmlElement) -> Optional[str]:
    """한 레코드(카드) 안에서 '실제 판매가' 하나를 고른다 (사이트 무관 일반 규칙).

    쇼핑 카드엔 가격류 숫자가 여럿 섞인다:
      정상가(취소선) · 할인가 · 단가('10개당 475원') · 적립금('최대 910원 적립') · 쿠폰액.
    이 중 단가/적립/쿠폰액을 문맥으로 걸러내고, 남은 가격 중 '마지막'(정상가 다음에
    오는 할인가; 단일가면 그 하나)을 판매가로 본다.
    """
    text = _norm(_text(record))
    out = []
    for m in _PRICE_RE.finditer(text):
        before = text[max(0, m.start() - 8):m.start()]
        after = text[m.end():m.end() + 6]
        if "당" in before:                      # 10개당/100g당 = 단가
            continue
        if "배송" in before:                     # 배송비 N원 = 배송료(상품가 아님)
            continue
        if "최대" in before or after.strip()[:2] == "적립":   # 최대 N원 적립 = 적립금
            continue
        if after.strip()[:2] in ("할인", "쿠폰", "이상"):  # 할인·쿠폰액 / N원 이상 무배 임계
            continue
        out.append(m.group().replace(" ", ""))
    return out[-1] if out else None


DATE_RE = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d+\s*(분|시간|일)\s*전")


def match_link(row: HtmlElement) -> Optional[HtmlElement]:
    """제목/링크: 텍스트가 가장 긴 <a> 를 제목으로 본다."""
    anchors = [a for a in row.iter("a") if _text(a)]
    if not anchors:
        return None
    return max(anchors, key=lambda a: len(_text(a)))


def match_date(row: HtmlElement) -> Optional[HtmlElement]:
    """날짜: 날짜 패턴에 매칭되는 가장 안쪽(잎) 요소."""
    hits = [e for e in row.iter() if isinstance(e.tag, str)
            and DATE_RE.search(_text(e)) and not _children(e)]
    return hits[0] if hits else None


FIELD_DEFS = {
    "title": {"matcher": match_link, "attr": None},
    "url":   {"matcher": match_link, "attr": "href"},
    "date":  {"matcher": match_date, "attr": None},
}

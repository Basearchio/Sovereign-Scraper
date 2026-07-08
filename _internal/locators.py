# -*- coding: utf-8 -*-
"""
MODULE_NAME: locators.py
PURPOSE: '예시 기반 위치탐색' 계층 — 사용자가 준 예시 값으로 반복 레코드/필드 노드를 찾아낸다
         (locate_by_example / locate_single_record 및 _match_* 매처). 구조 원시함수는 structure(leaf),
         값 판별은 values(leaf), LLM 재배치는 hooks(주입 심)에만 의존 → engine 과 서로 모른다(형제 계층).
DEPENDENCY: structure/values/hooks(leaf) + lxml. engine/cli/llm 을 import 하지 않는다(진짜 탈결합).
"""
from __future__ import annotations

import re

from lxml.html import HtmlElement

from structure import (_norm, _children, row_sig, _repeats, marker_of, find_rows_by_marker,
                       find_record_image, SKIP_TAGS)
from values import (looks_url, looks_image_url, _url_key)
from hooks import (_relocate)


def _match_node(scope: HtmlElement, value: str):
    """scope 안에서 주어진 '예시 값'과 가장 잘 맞는 노드를 찾는다.

    공백을 제거해 비교하므로 "시급12,000원" 처럼 사용자가 붙여 쓴 값도,
    HTML에 "시급 12,000원"/"12,000원" 식으로 있어도 매칭된다.
    우선순위: 완전일치 > 노드가 값의 일부(긴 쪽) > 노드가 값을 포함(군더더기 적은 쪽).

    ★긴 자유 텍스트(이메일 본문 미리보기 등)를 손으로 옮겨 적으면 실제 DOM 텍스트와 완전히
    똑같기 어렵다 — 그러면 진짜 대상 노드는 매칭에서 탈락하고, 우연히 값 안에 등장하는 짧은
    조각(예: "AI-Hub" 속의 '-')만 매칭되는 구분자/기호 노드가 '유일한 후보'로 남아 이긴다.
    한 글자짜리 우연 매칭은 애초에 후보에서 제외해 이런 오탐(엉뚱한 "-" 같은 값)을 막는다.
    """
    vns = re.sub(r"\s+", "", _norm(value))
    if not vns:
        return None
    best, best_score = None, -1
    for e in scope.iter():
        if not isinstance(e.tag, str) or e.tag in SKIP_TAGS:
            continue
        t = _norm(e.text_content())
        if not t:
            continue
        tns = re.sub(r"\s+", "", t)
        if tns == vns:
            score = 1000
        elif tns in vns:
            if len(tns) < 2:                # 한 글자 우연 매칭(구분자·기호 등) 제외
                continue
            score = 200 + len(tns)          # 값의 일부 → 더 많이 덮을수록 좋음
        elif vns in tns:
            score = 100 - (len(tns) - len(vns))   # 값 포함 → 군더더기 적을수록 좋음
        else:
            continue
        # 동점이면 더 좁은(잎에 가까운) 노드 선호
        if score > best_score or (score == best_score and best is not None
                                  and len(_children(e)) < len(_children(best))):
            best, best_score = e, score
    return best


def _match_all_nodes(scope: HtmlElement, value: str):
    """value 와 '완전 일치'(공백무시)하는 노드를 모두 반환(등장 위치 후보들).
    완전일치가 없으면 value 를 포함하는 '작은' 노드들로 폴백. 앵커가 정렬탭/
    스크린리더/실제카드 등 여러 곳에 나올 때, 각 위치에서 grounding 을 시도하려는 용도."""
    vns = re.sub(r"\s+", "", _norm(value))
    if not vns:
        return []
    exact, contains = [], []
    for e in scope.iter():
        if not isinstance(e.tag, str) or e.tag in SKIP_TAGS:
            continue
        t = _norm(e.text_content())
        if not t:
            continue
        tns = re.sub(r"\s+", "", t)
        if tns == vns:
            exact.append(e)
        elif vns in tns:
            contains.append((len(tns), e))
    if exact:
        return exact
    contains.sort(key=lambda x: x[0])          # 군더더기 적은(작은) 노드 우선
    return [e for _, e in contains[:20]]


def _match_href(scope: HtmlElement, url: str, include_ancestors: bool = True):
    """scope 안(+조상)에서 href/src 가 주어진 URL 과 가장 잘 맞는 요소를 찾는다.

    트래킹 파라미터(?tr=...)나 scheme/host 차이를 견디도록 '경로'와
    '긴 숫자 id(상품/공고 번호)' 기준으로 매칭한다.
    include_ancestors=True 면 '카드 전체를 감싼 <a>'(레코드 조상)도 후보에 넣는다.
    """
    target = _url_key(url)
    if not target:
        return None
    tgt_ids = set(re.findall(r"\d{4,}", target))
    candidates = list(scope.iter())
    if include_ancestors:                 # 카드 전체가 링크로 감싸진 패턴 대응
        a = scope.getparent()
        while a is not None:
            if isinstance(a.tag, str):
                candidates.append(a)
            a = a.getparent()
    best, best_score = None, -1
    for e in candidates:
        if not isinstance(e.tag, str):
            continue
        for attr in ("href", "data-href", "data-url", "src"):
            h = e.get(attr)
            if not h:
                continue
            k = _url_key(h)
            if not k:
                continue
            if k == target:
                score = 1000
            elif target in k or k in target:
                score = 200 + min(len(k), len(target))
            elif tgt_ids and tgt_ids & set(re.findall(r"\d{4,}", k)):
                score = 120          # 상품/공고 id 일치
            else:
                continue
            if score > best_score:
                best, best_score = e, score
    return best


def _match_href_broadened(dom, rec, url):
    """레코드 안(자손+조상)에서 URL 을 못 찾으면, 링크가 '형제 가지'(예: 썸네일 <a>)에 있을 수
    있으니 레코드를 감싼 '반복 단위(카드)'까지 한 단계 넓혀 그 서브트리에서만 정확 URL 매칭한다.
    카드 경계에서 멈춰 다른 카드로 번지지 않게 한다(값싼·결정적 회복 — Bilibili 등)."""
    node = _match_href(rec, url)
    if node is not None:
        return node
    p = rec.getparent()
    while p is not None:
        if isinstance(p.tag, str) and _repeats(dom, p) >= 2:
            return _match_href(p, url, include_ancestors=False)
        p = p.getparent()
    return None


_MIXED_ROWS_TAG = "[예시값 불일치] "


def _marked_record_ancestor(dom, anode, targets):
    """anode 에서 위로 올라가며, '반복되는 컴포넌트 경계 속성'을 가진 가장 가까운
    조상을 record 로 고른다. 클래스가 균일한 SPA(X 등)에서 구조 시그니처가
    과다매칭될 때, 이 속성이 더 신뢰할 수 있는 record 경계다.

    조건: (a) 조상이 모든 타깃 값을 포함하고, (b) 같은 마커를 가진 요소가 문서에
    2개 이상(=반복). 가장 안쪽(tightest) 것을 고른다.
    반환: (record_el, marker) 또는 (None, None).
    """
    nospace = lambda s: re.sub(r"\s+", "", s)
    p = anode
    while p is not None:
        if isinstance(p.tag, str):
            mk = marker_of(p)
            if mk:
                t = nospace(_norm(p.text_content()))
                if all(tg in t for tg in targets):
                    if len(find_rows_by_marker(dom, mk)) >= 2:
                        return p, mk
        p = p.getparent()
    return None, None


def locate_by_example(dom, values, kinds=None):
    """사용자가 '눈으로 본 값들'을 주면, HTML에서 역으로 찾아
    하나의 반복 레코드와 각 값의 위치를 파악한다 (programming-by-example).

    kinds: values 와 평행한 종류 리스트(선택). kinds[i]=='image' 인 값은 URL 매칭을 건너뛰고
      레코드 안 <img> 를 '구조로' 찾아 attr='src' 로 잡는다(로컬화·CDN 토큰 드리프트 견딤).

    Returns: (record_root, row_signature, [(value, node|None, name, attr), ...], error|None)
    """
    image_vals = set()
    if kinds:
        image_vals = {_norm(v) for v, k in zip(values, kinds)
                      if k == "image" and _norm(v)}
    # 피커 kind 가 없어도(타이핑) '이미지 URL(.jpg 등)'은 이미지 필드로 — 링크 대신 <img> 를 구조로.
    image_vals |= {_norm(v) for v in values if _norm(v) and looks_image_url(v)}
    vals = [_norm(v) for v in values if _norm(v)]
    if not vals:
        return None, None, None, "예시 값이 비어 있습니다."

    # 링크(URL) 값은 텍스트가 아니라 href 로 따로 매칭 → 레코드 식별/anchor 에선 제외
    text_vals = [v for v in vals if not looks_url(v)]
    if not text_vals:
        return None, None, None, "텍스트 값이 하나는 있어야 합니다(링크만으로는 레코드 특정 불가)."

    # 1) anchor = 사용자가 '가장 먼저 입력한' 텍스트 값. 규칙이 단순·예측가능해
    #    사용자가 이해하기 쉽다("첫 값이 있는 곳을 기준으로 잡는다").
    nospace = lambda s: re.sub(r"\s+", "", s)
    anchor = text_vals[0]
    targets = [nospace(v) for v in text_vals]   # 레코드 포함 검사는 텍스트 값만
    # 앵커는 정렬탭·스크린리더·실제카드 등 '여러 곳'에 나올 수 있다 → 모든 등장 위치를
    # 후보로 두고, 각 위치에서 grounding 을 시도한다(비-레코드 위치는 자연히 걸러짐).
    anodes = _match_all_nodes(dom, anchor)
    if not anodes:
        return None, None, None, f"앵커 값을 HTML에서 못 찾음: '{anchor}'"

    # 2) 레코드 결정 — 앵커의 각 등장 위치에서 위로 올라가 '모든 값 포함 + 문서에서
    #    반복' 하는 가장 안쪽 조상을 record 로. 정렬탭/스크린리더처럼 반복 레코드를
    #    못 만드는 위치는 배제되고, 실제 반복 카드(TicketBody 등)만 남는다.
    rec = None
    rec_marker = None

    # 2-0) data-testid/role 마커 우선(클래스 균일 SPA: X 등). 각 등장 위치에서 시도.
    for a in anodes:
        m, mk = _marked_record_ancestor(dom, a, targets)
        if m is not None:
            rec, rec_marker = m, mk
            break

    # 2-1) 구조 반복 레코드: 각 등장 위치에서 '모든 값을 담는 가장 안쪽 조상' 중
    #      반복(>=2)하는 것을 후보로. 가장 tight(작은) 것을 채택.
    if rec is None:
        best_len = None
        for a in anodes:
            p = a
            while p is not None:
                if isinstance(p.tag, str):
                    t = nospace(_norm(p.text_content()))
                    if all(tg in t for tg in targets):
                        if _repeats(dom, p) >= 2 and (best_len is None or len(t) < best_len):
                            rec, best_len = p, len(t)
                        break   # 이 등장 위치의 최소 포함조상 확정(더 위는 더 큼)
                p = p.getparent()

    if rec is None:
        # 반복 레코드를 못 찾음. (a) 값들이 서로 다른 항목에 흩어졌거나 (b) 비-반복
        # 컨테이너뿐. (a)면 어떤 값이 어긋났는지 짚어 사용자가 스스로 고치게 한다.
        for a in anodes:
            p = a
            while p is not None:
                if isinstance(p.tag, str) and _repeats(dom, p) >= 2:
                    t = nospace(_norm(p.text_content()))
                    miss = [tv for tv, tg in zip(text_vals, targets) if tg not in t]
                    if miss and len(miss) < len(text_vals):   # 일부만 빠짐 = 다른 항목서 옴
                        lst = ", ".join(f'"{m}"' for m in miss)
                        return None, None, None, (
                            f"{_MIXED_ROWS_TAG}예시 값이 '한 항목'에 모여 있지 않습니다. "
                            f"{lst} 은(는) '{anchor[:24]}…' 와 다른 항목에 있습니다.\n"
                            "     → 반드시 '같은 하나의 항목'에서 본 값들만 입력하세요 "
                            "(예: 한 영상의 제목·채널·조회수·날짜·링크).")
                    break
                p = p.getparent()
        return None, None, None, "레코드가 반복 단위가 아님(리스트 컨테이너로 잡힘) — 비정상"

    # 3.5) 링크가 레코드의 '형제 가지'(썸네일 <a> 등)에 있으면, 레코드를 그것까지 포함하는
    #      '반복 카드'로 승격한다 → 모든 필드가 레코드 자손이 되어 '행별 추출'이 정상 재현된다.
    #      (Bilibili: 텍스트=video-card__info, 링크=video-card__content 형제. 공통 카드=video-card)
    for v in vals:
        if looks_url(v) and _match_href(rec, v) is None:
            p = rec.getparent()
            while p is not None:
                if isinstance(p.tag, str) and _repeats(dom, p) >= 2:
                    if _match_href(p, v, include_ancestors=False) is not None:
                        rec = p     # 레코드를 반복 카드로 승격(텍스트도 여전히 자손)
                    break           # 카드 경계에서 멈춤(다른 카드 침범 방지)
                p = p.getparent()

    # 3.6) 이미지 필드: 썸네일 <img> 가 텍스트와 다른 형제 가지(카드의 딴 곳)에 있으면,
    #      링크 때와 같은 원리로 레코드를 '반복 카드'로 승격해 <img> 도 자손이 되게 한다.
    #      (img 없는 중간 반복 컨테이너는 건너뛰고, img 를 품은 가장 가까운 반복 카드에서 멈춤.)
    if image_vals and rec.find(".//img") is None:
        p = rec.getparent()
        while p is not None:
            if isinstance(p.tag, str) and _repeats(dom, p) >= 2 and p.find(".//img") is not None:
                rec = p
                break
            p = p.getparent()

    # 4) 레코드 안에서 각 값의 노드를 특정 (이미지=구조로 <img>, URL=href, 나머지=텍스트)
    matched = []
    for v in vals:
        if v in image_vals:
            node = find_record_image(rec, hint=v)       # 값 매칭 대신 구조로(로컬화/드리프트 견딤)
            matched.append((v, node, None, "src"))      # 이미지 필드(src)
        elif looks_url(v):
            node = _match_href_broadened(dom, rec, v)   # 못 찾으면 카드 경계까지 넓혀 회복
            matched.append((v, node, None, "href"))   # 링크 필드
        else:
            node = _match_node(rec, v)
            if node is None:                            # 잎노드는 falsy → is None 으로 검사
                node = _relocate(rec, v, v)
            matched.append((v, node, None, None))      # 텍스트 필드
    return rec, row_sig(rec), matched, None


def locate_single_record(dom, values, kinds=None):
    """단일 레코드(상세 페이지) 역설계. locate_by_example 과 달리 '반복(>=2)'을
    요구하지 않는다 — 상세 페이지엔 레코드가 1개뿐이기 때문.

    앵커(첫 텍스트 값)의 등장 위치에서 위로 올라가, '모든 값을 담는 가장 안쪽 조상'을
    레코드로 잡는다(반복 검사 없음). 이 컨테이너의 클래스/구조 시그니처를 저장해두면,
    같은 템플릿의 다른 상세 페이지에서도 같은 컨테이너를 찾아 필드를 뽑는다.

    kinds: 시그니처 통일용으로 받되(select_by_example 이 동일 호출) 상세 모드의 이미지 구조매칭은
      아직 미지원 — 지금은 무시한다(URL 있으면 href/src 로 매칭). 목록 모드가 우선.

    Returns: (record_root, row_signature, [(value, node|None, name, attr), ...], error|None)
    """
    _ = kinds  # 예약(상세 페이지 이미지 구조매칭은 후속 슬라이스)
    vals = [_norm(v) for v in values if _norm(v)]
    if not vals:
        return None, None, None, "예시 값이 비어 있습니다."
    text_vals = [v for v in vals if not looks_url(v)]
    if not text_vals:
        return None, None, None, "텍스트 값이 하나는 있어야 합니다(링크만으로는 레코드 특정 불가)."

    nospace = lambda s: re.sub(r"\s+", "", s)
    anchor = text_vals[0]
    targets = [nospace(v) for v in text_vals]
    anodes = _match_all_nodes(dom, anchor)
    if not anodes:
        return None, None, None, f"앵커 값을 HTML에서 못 찾음: '{anchor}'"

    # 각 앵커 등장 위치에서 '모든 값 포함' 가장 안쪽 조상을 찾고, 가장 tight 한 것 채택.
    rec, best_len = None, None
    for a in anodes:
        p = a
        while p is not None:
            if isinstance(p.tag, str):
                t = nospace(_norm(p.text_content()))
                if all(tg in t for tg in targets):
                    if best_len is None or len(t) < best_len:
                        rec, best_len = p, len(t)
                    break   # 이 등장 위치의 최소 포함조상 확정
            p = p.getparent()

    if rec is None:
        # 모든 값을 한 페이지에 담는 컨테이너가 없음 → 값이 서로 다른 페이지에서 왔거나 오타.
        miss = None
        for a in anodes:
            t = nospace(_norm((a.getroottree().getroot()).text_content()))
            miss = [tv for tv, tg in zip(text_vals, targets) if tg not in t]
            break
        if miss:
            lst = ", ".join(f'"{m}"' for m in miss)
            return None, None, None, (
                f"{_MIXED_ROWS_TAG}이 페이지에 없는 값이 있습니다: {lst}\n"
                "     → 반드시 '이 상세 페이지 한 곳'에서 보이는 값들만 입력하세요.")
        return None, None, None, "예시 값들을 한 컨테이너로 묶지 못했습니다."

    matched = []
    for v in vals:
        if looks_url(v):
            matched.append((v, _match_href(rec, v), None, "href"))
        else:
            node = _match_node(rec, v)
            if node is None:
                node = _relocate(rec, v, v)
            matched.append((v, node, None, None))
    return rec, row_sig(rec), matched, None

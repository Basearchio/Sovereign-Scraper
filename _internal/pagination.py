# -*- coding: utf-8 -*-
"""
MODULE_NAME: pagination.py
PURPOSE: 'A 유형(URL 기반) 페이지네이션' leaf — 다음 페이지 URL 탐지(숫자 쿼리 파라미터/rel=next/'다음'
         텍스트)와 그 증가 규칙 학습·적용(page=1→2, offset=0→30). 자가치유 엔진 클래스는 이걸 쓰지 않고
         cli 크롤 루프만 쓴다 → engine 과 형제(서로 모름). 구조 텍스트 정규화만 structure(leaf)에 의존.
DEPENDENCY: structure(leaf) + urllib. engine/cli/locators/llm 을 import 하지 않는다(leaf).
"""
from __future__ import annotations

from structure import _norm


_NEXT_WORDS = ("다음페이지", "다음 페이지", "다음", "next page", "next", "뒤로")


_NEXT_SYMBOLS = ("›", "»", "≫", "→", "▶", ">", "≻")


def find_next_url(dom, base_url: str):
    """구조적으로 '다음 페이지' URL을 찾는다.

    핵심(페이지/offset 모두 처리): 같은 경로를 가리키면서 '숫자 쿼리 파라미터 하나만'
    다른 링크들을 모아, 그 파라미터의 '현재값보다 큰 가장 작은 값'을 다음 페이지로
    고른다. (ruliweb ?page=2, incruit ?startno=30 모두 OK. '다음' 블록점프도 회피)
    실패 시 rel=next / '다음' 텍스트로 폴백.
    """
    from urllib.parse import urljoin, urlparse, parse_qs

    def ok(h):
        return h and not h.startswith(("#", "javascript:", "mailto:"))

    base = urlparse(base_url)
    base_q = parse_qs(base.query)

    # 1) 숫자 쿼리 파라미터 기반 페이저 탐지
    cand = {}   # param -> {value: url}
    for a in dom.iter("a"):
        h = a.get("href")
        if not ok(h):
            continue
        p = urlparse(urljoin(base_url, h))
        if p.netloc != base.netloc or p.path != base.path:
            continue
        q = parse_qs(p.query)
        diffs = [k for k in set(q) | set(base_q) if q.get(k) != base_q.get(k)]
        if len(diffs) != 1:
            continue
        k = diffs[0]
        try:
            val = int(q.get(k, ["0"])[0])
        except (ValueError, IndexError):
            continue
        cand.setdefault(k, {})[val] = urljoin(base_url, h)
    if cand:
        k = max(cand, key=lambda x: len(cand[x]))   # 후보가 가장 많은 파라미터 = 페이저
        vals = cand[k]
        try:
            cur = int(base_q.get(k, [""])[0])
        except (ValueError, IndexError):
            cur = 1 if 1 in vals else 0             # base 에 없으면 첫 페이지로 추정
        nxts = sorted(v for v in vals if v > cur)
        if nxts:
            return vals[nxts[0]]

    # 2) rel="next"
    for a in dom.iter("a"):
        rel = a.get("rel")
        rel = " ".join(rel) if isinstance(rel, list) else (rel or "")
        if "next" in rel.lower() and ok(a.get("href")):
            return urljoin(base_url, a.get("href"))

    # 3) 텍스트/기호 '다음'
    words = [w.lower() for w in _NEXT_WORDS]
    for a in dom.iter("a"):
        h = a.get("href")
        if not ok(h):
            continue
        t = _norm(a.text_content()) or (a.get("aria-label") or a.get("title") or "").strip()
        if t and (t in _NEXT_SYMBOLS or any(w == t.lower() or w in t.lower() for w in words)):
            return urljoin(base_url, h)
    return None


def learn_page_param(cur_url: str, next_url: str):
    """cur→next 가 '같은 경로 + 숫자 쿼리 파라미터 하나'만 다르면 (param, step) 반환.

    양쪽 모두 그 파라미터를 가질 때만 학습(증가폭이 1인지 30인지 정확히 안다).
    page 기반(1→2: step 1), offset 기반(0→30→60: step 30) 모두 일반적으로 처리.
    경로 기반(/page/2)이나 불확실하면 None → 그때는 LLM 이 매번 판단.
    """
    from urllib.parse import urlparse, parse_qs
    pc, pn = urlparse(cur_url), urlparse(next_url)
    if pc.netloc != pn.netloc or pc.path != pn.path:
        return None
    qc, qn = parse_qs(pc.query), parse_qs(pn.query)
    for k in qn:
        if k not in qc:
            continue
        try:
            vc, vn = int(qc[k][0]), int(qn[k][0])
        except (ValueError, IndexError):
            continue
        if vn > vc:
            return (k, vn - vc)
    return None


def apply_page_param(url: str, param: str, step: int):
    """url 의 param 값을 step 만큼 증가시킨 새 URL."""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    p = urlparse(url)
    q = parse_qs(p.query)
    try:
        cur = int(q.get(param, ["0"])[0])
    except (ValueError, IndexError):
        cur = 0
    q[param] = [str(cur + step)]
    newq = urlencode({k: v[0] for k, v in q.items()})
    return urlunparse(p._replace(query=newq))

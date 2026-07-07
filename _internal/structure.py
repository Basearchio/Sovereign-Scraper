# -*- coding: utf-8 -*-
"""
MODULE_NAME: structure.py
PURPOSE: DOM '구조 원시함수' leaf — 클래스/텍스트를 버리고 태그 중첩 모양(시그니처)·상대 경로·반복 탐지·
         마커 등 '난독화와 무관한 구조'를 다룬다. engine(자가치유 엔진)과 locators(예시 기반 위치탐색)가
         '둘 다' 이 원시함수에 의존하므로, 어느 상위에도 두지 않고 공통 leaf 로 둔다(두 계층을 서로 모르게).
DEPENDENCY: lxml + 값 판별은 values(leaf). engine/cli/locators/llm 을 import 하지 않는다(leaf).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Optional

from lxml.html import HtmlElement

from values import is_real_href, _url_key


SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "link", "meta",
             "head", "br", "hr", "option", "iframe", "path", "use"}


def _children(el: HtmlElement):
    """주석/PI 등을 제외한 '요소' 자식만 반환."""
    return [c for c in el if isinstance(c.tag, str)]


def subtree_shape(el: HtmlElement, max_depth: int = 3) -> str:
    """요소의 하위 트리 '모양'을 문자열로 직렬화한다.

    클래스명/텍스트/속성을 전부 버리고 태그 중첩 구조만 남기므로,
    난독화로 클래스가 바뀌어도 동일 시그니처를 유지한다.
        예) li[a,span,span]
    """
    if max_depth <= 0:
        return el.tag
    kids = [subtree_shape(c, max_depth - 1) for c in _children(el)]
    return f"{el.tag}[{','.join(kids)}]" if kids else el.tag


GROUP_DEPTH = 2


MIN_RICHNESS = 2  # 빈 spacer/아이콘 행 제거용 최소 내용량


def row_sig(el: HtmlElement) -> str:
    """그룹핑/매칭용 '느슨한' 행 시그니처."""
    return subtree_shape(el, GROUP_DEPTH)


def _richness(el: HtmlElement) -> int:
    """행 하나의 '내용 풍부도' — 앵커/텍스트를 가진 요소 수.

    빈 spacer 행처럼 개수만 많고 내용이 없는 블록을 거르기 위함.
    """
    score = 0
    for e in el.iter():
        if not isinstance(e.tag, str):
            continue
        if e.tag == "a" and (e.get("href") or (e.text or "").strip()):
            score += 2
        if (e.text or "").strip():
            score += 1
    return score


def _richness_map(all_els):
    """모든 요소의 '내용량 = 텍스트 길이'를 O(N) 1패스(상향식)로 계산.

    node 개수보다 '실제 텍스트 길이'가 본문/chrome을 더 잘 가른다
    (긴 제목 = 본문, 짧은 버튼/메뉴 = chrome). 자식 tail 텍스트도 포함한다.
    문서순(pre-order)의 역순 = '자식이 부모보다 먼저' 이므로 누적 가능.
    all_els 가 프록시 참조를 살려두므로 id()가 안정적이다(lxml 프록시 캐시).
    """
    rich = {}
    for el in reversed(all_els):
        if not isinstance(el.tag, str) or el.tag in SKIP_TAGS:
            rich[id(el)] = 0
            continue
        base = len((el.text or "").strip())
        if el.tag == "a" and el.get("href"):
            base += 2
        for c in el:
            base += rich.get(id(c), 0)
            base += len((c.tail or "").strip())   # 자식 사이/뒤 텍스트
        rich[id(el)] = base
    return rich


WRAP_FRAC = 0.6   # 한 행의 텍스트 중 이 비율 이상이 '더 흔한 하위 단위'면 그 행은 래퍼


def find_repeating_rows(root: HtmlElement):
    """페이지 전역에서 반복되는 '데이터 레코드' 단위를 찾는다 (MDR 계열).

    포털형 페이지(예: ruliweb 메인 = 69개 보드)에서도 한 보드만이 아니라
    여러 보드에 흩어진 같은 모양의 글을 하나로 묶어 잡는다.

    3단계:
      1) 형제 그룹 수집 : 한 부모 아래 같은 row_sig 로 2번 이상 반복되는 자식들
         (=레코드 후보). 같은 sig 를 컨테이너를 가로질러 전역 합산.
      2) 래퍼 제외 : 어떤 후보 행의 텍스트가 대부분(WRAP_FRAC) '더 흔한 하위
         단위'로 채워지면(예: ul/섹션 ⊃ 글) 그 행은 래퍼다. 반대로 레코드 내부의
         작은 인라인 리스트(직무 링크 등)는 텍스트 점유율이 낮아 레코드를 래퍼로
         오판하지 않는다. (가장 가까운 후보 조상에만 텍스트를 귀속)
      3) 점수 : 전역 반복수 × 평균 텍스트량 → 짧은 버튼/메뉴(chrome) 탈락

    Returns: (rows[list], row_signature[str]) 또는 (None, None)
    """
    all_els = list(root.iter())          # 프록시 참조 유지 → id() 안정 + 1패스 richness
    rich = _richness_map(all_els)

    # 1) 형제 그룹(같은 row_sig 2개 이상) 후보 수집, sig 별 전역 합산
    by_sig: dict[str, list] = defaultdict(list)
    for parent in all_els:
        if not isinstance(parent.tag, str):
            continue
        groups: dict[str, list] = defaultdict(list)
        for c in parent:
            if isinstance(c.tag, str) and c.tag not in SKIP_TAGS:
                groups[row_sig(c)].append(c)
        for sig, members in groups.items():
            if len(members) >= 2 and rich[id(members[0])] >= MIN_RICHNESS:
                by_sig[sig].extend(members)
    if not by_sig:
        return None, None
    count = {sig: len(els) for sig, els in by_sig.items()}

    # 2) 래퍼 제외 — 각 후보 요소의 텍스트를 '가장 가까운 후보 조상'에 귀속시켜,
    #    어떤 행이 더 흔한 하위 단위로 대부분 채워지는지(=래퍼인지) 판정
    id_to_sig = {id(e): sig for sig, els in by_sig.items() for e in els}
    cov: dict[int, Counter] = defaultdict(Counter)   # id(조상행) -> {자손sig: 텍스트합}
    for sig, els in by_sig.items():
        for e in els:
            re = rich[id(e)]
            p = e.getparent()
            while p is not None:    # 모든 후보 조상에 귀속(전이적) → 깊은 래퍼도 감지
                if id(p) in id_to_sig:
                    cov[id(p)][sig] += re
                p = p.getparent()

    wrap_inst, total_inst = Counter(), Counter()
    for sig, els in by_sig.items():
        for e in els:
            total_inst[sig] += 1
            re = rich[id(e)]
            if re <= 0:
                continue
            # 이 행을 '더 흔한 하위 단위'가 대부분 채우면 래퍼
            #  (동점 커버리지가 있을 수 있으니 단일 최대가 아니라 전부 확인)
            if any(cs != sig and cv >= WRAP_FRAC * re and count[cs] >= count[sig]
                   for cs, cv in cov.get(id(e), {}).items()):
                wrap_inst[sig] += 1
    excluded = {s for s in by_sig
                if wrap_inst[s] >= 1 and wrap_inst[s] >= 0.5 * total_inst[s]}
    pool = [s for s in by_sig if s not in excluded] or list(by_sig)

    def score(s):
        sample = by_sig[s][:5]
        avg_rich = sum(rich[id(e)] for e in sample) / len(sample)
        return count[s] * avg_rich

    best = max(pool, key=score)
    return by_sig[best], best


def _norm(text: str) -> str:
    """내부 공백/개행을 한 칸으로 정규화."""
    return " ".join((text or "").split())


def _find_by_text(row: HtmlElement, value: str):
    """row 안에서 텍스트가 value 와 일치/포함하는 '가장 좁은' 요소를 찾는다."""
    v = _norm(value)
    if not v:
        return None
    best = None
    for e in row.iter():
        if not isinstance(e.tag, str) or e.tag in SKIP_TAGS:
            continue
        t = _norm(e.text_content())
        if t and (t == v or v in t or t in v):
            if best is None or len(t) < len(_norm(best.text_content())):
                best = e   # 값만 정확히 담은 가장 짧은 노드 선호
    return best


def _repeats(dom: HtmlElement, el: HtmlElement, need: int = 2) -> int:
    """el 의 구조 시그니처가 문서에서 몇 번 반복되는지(need 도달 시 조기 종료)."""
    rs = row_sig(el)
    cnt = 0
    for e in dom.iter():
        if isinstance(e.tag, str) and row_sig(e) == rs:
            cnt += 1
            if cnt >= need:
                break
    return cnt


_ANCESTOR_A = "::ancestor-a"


def _nearest_anchor(node: HtmlElement):
    """node 자신부터 위로 올라가며 '실제 이동하는' href 를 가진 가장 가까운 <a>."""
    p = node
    while p is not None:
        if isinstance(p.tag, str) and p.tag == "a" and is_real_href(p.get("href") or ""):
            return p
        p = p.getparent()
    return None


_RECORD_ROLE_OK = {"row", "listitem", "article"}


def marker_of(el: HtmlElement):
    """el 의 '레코드 경계 속성' 마커를 "<attr>=<value>" 로 (없으면 None).
    data-testid 를 우선하고, 없으면 반복 항목 성격의 role 을 본다."""
    if not isinstance(el.tag, str):
        return None
    tid = el.get("data-testid")
    if tid:
        return f"data-testid={tid}"
    role = el.get("role")
    if role in _RECORD_ROLE_OK:
        return f"role={role}"
    return None


def find_rows_by_marker(dom, marker: str):
    """"<attr>=<value>" 마커로 문서 전체에서 해당 요소들을 찾는다(추출 가속 경로)."""
    if not marker or "=" not in marker:
        return []
    attr, val = marker.split("=", 1)
    return [e for e in dom.iter() if isinstance(e.tag, str) and e.get(attr) == val]


def _classes(el: HtmlElement):
    return (el.get("class") or "").split()


def _sibling_unique_class(node: HtmlElement, siblings):
    """node 의 class 중 '같은태그 형제들 사이에서 유일한' 것 하나(있으면). 형제 지역 앵커라
    다른 컨테이너의 숨김 중복본과 무관하고, 중간에 형제(예: Gmail 대화 개수 뱃지)가 삽입돼도
    index 밀림 없이 이 노드를 다시 집게 한다. 유일 class 가 없으면 None."""
    for c in _classes(node):
        if sum(1 for e in siblings if c in _classes(e)) == 1:
            return c
    return None


def rel_path(row: HtmlElement, node: HtmlElement):
    """row → node 까지의 경로를 단계 리스트로 기록. 각 단계 = (tag, index) 또는, 형제에 class 가 있으면
    (tag, index, 형제유일class|None, [학습당시 형제 class들]). 뒤 두 값은 '형제 밀림'에 강한 재배치용:
      · 형제유일class : 그 class 를 가진 형제를 바로 앵커(삽입/재정렬 무관, 정확히 1개일 때).
      · 형제 class집합: 재현 때 '학습엔 없던 class 를 가진 형제(=삽입된 뱃지 등)'를 팬텀으로 걸러 index 를 맞춘다."""
    steps = []
    cur = node
    while cur is not None and cur is not row:
        parent = cur.getparent()
        if parent is None:
            return None
        same = [c for c in _children(parent) if c.tag == cur.tag]
        idx = same.index(cur)
        sib = sorted({c for e in same for c in _classes(e)})
        if sib:
            steps.append((cur.tag, idx, _sibling_unique_class(cur, same), sib))
        else:
            steps.append((cur.tag, idx))
        cur = parent
    steps.reverse()
    return steps


def follow_path(row: HtmlElement, steps):
    """rel_path 경로를 따라 노드를 다시 찾는다(형제 밀림에 강함).
      ① 형제유일 class 가 있으면 그 class 형제를 우선(정확히 1개일 때).
      ② 아니면, 학습에 없던 class 를 가진 형제(삽입된 팬텀)를 제외한 뒤 index 로.
      ③ 정보가 없으면(구버전 2-튜플) 그냥 index (하위호환)."""
    if steps and steps[0] and steps[0][0] == _ANCESTOR_A:
        return _nearest_anchor(row)     # 카드 전체를 감싼 조상 <a>
    cur = row
    for step in steps:
        tag, idx = step[0], step[1]
        uniq = step[2] if len(step) > 2 else None
        sib = step[3] if len(step) > 3 else None
        same = [c for c in _children(cur) if c.tag == tag]
        nxt = None
        if uniq:                                   # ① 형제-지역 class 앵커
            hits = [c for c in same if uniq in _classes(c)]
            if len(hits) == 1:
                nxt = hits[0]
        if nxt is None:                            # ②/③ 팬텀 제거 후 index
            cand = same
            if sib:
                learned = set(sib)
                # 학습 때 없던 class 를 가진 형제 = 삽입된 것 → 제외. class 없는 형제는 판단불가라 유지.
                filt = [c for c in same if (not _classes(c)) or (learned & set(_classes(c)))]
                if filt:
                    cand = filt
            if idx >= len(cand):
                return None
            nxt = cand[idx]
        cur = nxt
    return cur


def _text(el: HtmlElement) -> str:
    return (el.text_content() or "").strip()


# --- CSS 셀렉터 원시함수 (class 무관 구조에서 '유일할 때만' 클래스 활용) ---
def first_class(el: HtmlElement) -> Optional[str]:
    cls = el.get("class")
    return cls.split()[0] if cls else None


def css_of(el: HtmlElement) -> str:
    c = first_class(el)
    return f"{el.tag}.{c}" if c else el.tag


def unique_class(record: HtmlElement, node: HtmlElement):
    """node 의 클래스가 record 안에서 (tag, class) 로 '유일'할 때만 반환.
    유일하지 않으면(예: 할인율/가격 span 이 같은 클래스) None → 구조 경로로 해석.
    """
    c = first_class(node)
    if not c:
        return None
    same = [e for e in record.iter(node.tag)
            if e.get("class") and c in e.get("class").split()]
    return c if len(same) == 1 else None


# --- 이미지(대표 썸네일) 위치찾기: engine(행별 추출)·locators(예시 매칭) 공용 ---
def _img_src(e):
    """<img> 의 '실제' 이미지 URL. lazy 플레이스홀더(data: 1x1 base64)는 값으로 치지 않고
    data-src/data-original/data-lazy-src 등 지연로딩 원본을 함께 본다."""
    s = e.get("src") or ""
    if s.startswith("data:"):        # base64 인라인 = 대개 1x1 플레이스홀더 → 무시
        s = ""
    return s or e.get("data-src") or e.get("data-original") or e.get("data-lazy-src") or ""


def _img_dim(e, k):
    """width/height 를 정수로(야후는 '57.02' 같은 소수도 있음 → float 경유)."""
    try:
        return int(float(e.get(k) or 0))
    except (TypeError, ValueError):
        return 0


def find_record_image(rec, hint: str = ""):
    """레코드(카드) 안에서 '대표(요약) 이미지' <img> 를 값이 아니라 '구조/크기'로 찾는다.
    이유: 저장 스냅샷은 src 를 로컬 파일로 바꾸고(파일명이 공통 접두어로 잘려 고유토큰 소실), 라이브
    재렌더는 CDN 토큰이 매번 달라져서 '피커가 캡처한 이미지 URL'로는 못 찾는다. 또 카드엔 1x1 추적픽셀·
    아이콘 같은 잡음 img 가 섞인다 → 그걸 피하고 '가장 큰' 콘텐츠 이미지를 고른다. ★행별 추출에도 써서,
    news/article 처럼 구조가 다른 카드가 섞여도(고정 rel_path 로는 어긋남) 각 행의 대표 이미지를 잡는다.
    우선순위: (0) 1x1·data: 잡음 제외 → (1) hint 의 '충분히 고유한(12+)' 토큰과 정확히 겹치면 그것
      → (2) 가장 큰 img(면적) → (3) 첫 img."""
    def _junk(e):
        w, h = _img_dim(e, "width"), _img_dim(e, "height")
        return (0 < w <= 2) or (0 < h <= 2)     # 1x1/2x2 스페이서·추적픽셀

    imgs = [e for e in rec.iter("img") if _img_src(e) and not _junk(e)]
    if not imgs:                                 # 잡음 제외 후 없으면 완화(그래도 data: 는 제외)
        imgs = [e for e in rec.iter("img") if _img_src(e)]
        if not imgs:
            return None
    if hint:
        # 12+ 자 토큰만(야후 CDN 의 흔한 짧은 공통접두로 오매칭 방지). 전체 토큰이 같을 때만 채택.
        hint_ids = set(re.findall(r"[A-Za-z0-9]{12,}", _url_key(hint)))
        if hint_ids:
            for e in imgs:
                if hint_ids & set(re.findall(r"[A-Za-z0-9]{12,}", _url_key(_img_src(e)))):
                    return e

    def _area(e):
        return _img_dim(e, "width") * _img_dim(e, "height")

    big = max(imgs, key=_area)
    return big if _area(big) > 0 else imgs[0]

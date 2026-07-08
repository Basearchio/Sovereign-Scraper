# -*- coding: utf-8 -*-
"""
자가 치유형 웹 데이터 추출 엔진 (프로토타입)
=================================================

핵심 아이디어
-------------
난독화된 사이트는 "클래스명"은 매 빌드마다 바뀌어도,
"DOM 트리의 반복 구조(repeating block)"와 "필드의 상대적 위치"는 잘 변하지 않는다.
이 **구조적 불변성(Structural Invariants)** 을 anchor로 삼는다.

3단계 파이프라인
----------------
1) Calibration : 반복 구조 자동 탐지 → 필드별 (구조 경로 + CSS 셀렉터) 생성 → 캐시(JSON)
2) Parsing     : 캐시된 CSS 셀렉터로 즉시 추출 (LLM/재탐색 없음, Zero-latency)
3) Self-Heal   : CSS 셀렉터가 깨지면
                 ① 구조 경로(class 무관)로 노드 재탐색
                 ② 그래도 실패하면 휴리스틱 매처(=LLM 역할)로 재배치
                 → 새 CSS 셀렉터를 재생성하여 캐시를 패치

본 프로토타입은 lxml만 의존한다. 실제 운영에서는 load_dom()을
Playwright(headless) + playwright-stealth / curl-impersonate 로 교체하면 된다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 불변식(INVARIANT): 이 파일은 LLM 을 직접 import/호출하지 않는다. (LLM-FREE)
   · LLM 전송은 services/llm_service.py, DOM+LLM 오케스트레이션은 llm_locators.py 에 있다.
   · 자가치유의 '의미 기반 재배치'가 필요하면, 아래 set_relocator() 로 '주입된 훅'
     (_relocate)만 호출한다. 훅 미설정 시 None → 구조/휴리스틱 경로로만 동작(정상).
   · 이 불변식은 tests/test_engine_llm_free.py 가 강제한다(여기서 llm 을 import 하면 FAIL).
   ⇒ 즉 이 선언은 '주석'이 아니라 '테스트로 지켜지는 계약'이다. 되돌리지 말 것.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Callable, Optional

from lxml import html as lxml_html
from lxml.html import HtmlElement

# 수집(fetch) 전략은 crawlers/ 계층으로 분리(engine → crawlers 단방향). Phase 2:
#   · static_fetch: 정적/SSR 1차 경로   · playwright_fetch: SPA/무한스크롤 렌더 폴백
from crawlers.static import static_fetch
from crawlers.dynamic import playwright_fetch
# 데이터 계약(추출 스키마·레시피)은 core/ 계층(engine → core 단방향). Phase 3:
from core.schema import Schema, FieldSchema
# 구조 원시함수(시그니처/경로/반복/마커)는 structure.py leaf 로 분리 — engine·locators 공유. v5.0:
from structure import (_children, subtree_shape, row_sig, _richness, _richness_map,  # noqa: F401
                       find_repeating_rows, _norm, _text, _find_by_text, _repeats,  # noqa: F401
                       _nearest_anchor, marker_of, find_rows_by_marker, rel_path, follow_path,  # noqa: F401
                       SKIP_TAGS, GROUP_DEPTH, MIN_RICHNESS, WRAP_FRAC, _ANCESTOR_A, _RECORD_ROLE_OK,  # noqa: F401
                       first_class, css_of, unique_class, find_record_image, _img_src)  # noqa: F401
# 값 의미 분류(링크/가격/날짜/형태)는 values.py leaf 로 분리(engine·cli 공유). v5.0 co-split:
from values import looks_url, is_real_href, _url_key, _looks_price, _PRICE_RE  # noqa: F401


# 의미 기반 재배치/구조 파악 훅(LLM 주입 지점)은 hooks.py leaf 로 분리 — engine·locators 가 '둘 다'
# 최후 폴백으로 쓰므로 어느 상위에도 두지 않는다(두 계층을 서로 모르게 = 탈결합). engine 은 이 심만
# 부른다 → llm 을 import 하지 않는다(LLM-FREE 유지). set_* 는 cli 배선용으로 재-export.
from hooks import (set_relocator, _relocate,          # noqa: F401  (재배치 훅)
                   set_structure_discoverer, _discover_structure)  # noqa: F401  (재학습 훅)
# 필드 휴리스틱 매처(프로토타입의 LLM 역할)는 field_heuristics.py leaf 로 분리 — engine 이 calibrate/
# extract 에서 사용(engine→leaf). structure/values 만 의존. v5.0:
from field_heuristics import FIELD_DEFS, match_link, match_date, find_record_price, media_urls  # noqa: F401
# 예시경계 필드분리(한 노드에 뭉친 여러 필드)는 segment.py leaf 로 — engine build/extract 에서 사용. v5.0:
from segment import _split_segments, _segment_value, _derive_colocated_split  # noqa: F401
from i18n import t     # 다국어: self.log 문구 번역(미번역은 한국어 폴백)


# ---------------------------------------------------------------------------
# 0. DOM 로드 (Playwright는 선택적 — 데모는 로컬 파일/HTML 문자열로 동작)
# ---------------------------------------------------------------------------
def load_dom(source: str) -> HtmlElement:
    """source 가 로컬 파일이면 읽고, URL이면 fetch 한다.

    전략: 정적 fetch 를 '먼저'(빠르고 대부분 사이트 OK). 결과가 SPA 처럼
    비어 있으면(앵커가 거의 없음) 그때만 Playwright 로 렌더링한다.
    → 정적으로 되는 사이트(saramin/ruliweb/HN)는 빠르게, JS 사이트(musinsa)는
      자동으로 브라우저 렌더링. (TLS 지문 방어는 playwright-stealth 로 확장 가능)
    """
    if source.startswith(("http://", "https://")):
        dom = static_fetch(source)
        if dom is not None and sum(1 for _ in dom.iter("a")) >= 5:
            return dom   # 정상적인 정적/SSR 페이지
        # SPA 로 의심 → 브라우저 렌더링 시도
        rendered = playwright_fetch(source)
        if rendered is not None:
            return rendered
        if dom is not None:
            return dom   # Playwright 없거나 실패 → 정적 결과라도 반환
        raise RuntimeError(f"페이지 로드 실패: {source}")

    with open(source, "rb") as f:
        return lxml_html.fromstring(f.read())   # 로컬 HTML 파일(bytes → lxml 인코딩 자동감지)


# ---------------------------------------------------------------------------
# 필드 열거/미리보기 + 행 HTML (구조 시그니처·경로·반복 탐지는 structure.py leaf 로 이동)
# ---------------------------------------------------------------------------


def enumerate_fields(row: HtmlElement):
    """행(row) 안에서 '하나의 논리적 필드'로 보이는 노드들을 문서 순서로 나열.

    규칙: 어떤 노드의 모든 자식이 잎(leaf)이면 그 노드를 '필드 한 칸'으로 보고
          더 깊이 내려가지 않는다.
            예) <span><a>서울</a> <a>영등포구</a></span> → "서울 영등포구" 한 칸
                <span class="date">~ 08/01</span>        → 날짜 한 칸
          반대로 자식 중 더 쪼갤 게 있으면 내려가서 각 필드를 따로 잡는다.
            예) div.job_condition > span,span,span → 지역/경력/학력 각각

    Returns: 후보 노드 리스트(HtmlElement)
    """
    out = []

    def visit(el):
        if not isinstance(el.tag, str):
            return
        kids = _children(el)
        text = _norm(el.text_content())
        # 텍스트가 있고, 자식이 전부 잎이면 → 이 노드가 곧 한 필드
        if text and all(len(_children(c)) == 0 for c in kids):
            out.append(el)
            return  # 자식으로 내려가지 않음
        for c in kids:
            visit(c)

    for c in _children(row):
        visit(c)
    return out


def field_preview(node: HtmlElement, maxlen: int = 40):
    """후보 필드를 사람이 보기 좋은 (미리보기텍스트, 셀렉터힌트)로."""
    text = _norm(node.text_content())
    if len(text) > maxlen:
        text = text[:maxlen] + "…"
    cls = first_class(node)
    hint = node.tag + (f".{cls}" if cls else "")
    # 앵커(또는 내부에 링크 보유) 표시
    href = node.get("href")
    if href is None:
        a = node.find(".//a")
        href = a.get("href") if a is not None else None
    if href:
        hint += " 🔗"
    return text, hint, href


# --- LLM 기반 필드 재배치 (자가 치유의 마지막 폴백) -------------------------
def _row_html(row: HtmlElement, maxlen: int = 2500) -> str:
    from lxml import etree
    try:
        h = etree.tostring(row, encoding="unicode")
    except Exception:
        h = row.text_content() or ""
    return _norm(h)[:maxlen]


# ---------------------------------------------------------------------------
# 섹션 링크 (포털/인덱스 페이지에서 '들어갈 보드/섹션' 후보 찾기)
# ---------------------------------------------------------------------------
# 상세글/유틸 페이지로 보이는 URL (보드 목록이 아니라 '들어가는' 대상이 아님)
_DETAIL_RE = re.compile(
    r"/(read|view|article|articles|comment|reply|login|logout|join|signup|"
    r"register|search|profile|member|mypage|setting|help|terms|privacy)\b"
    r"|[?&](?:read|view)=", re.I)


def find_section_links(dom, base_url: str, limit: int = 60):
    """포털/인덱스 페이지에서 '들어갈 보드/섹션' 후보 링크를 추출한다.

    일반 휴리스틱(특정 사이트 URL 패턴에 의존하지 않음):
      - 같은 사이트 내부 링크
      - 텍스트가 짧음(1~30자) = 보드 이름 (긴 텍스트 = 글 제목 → 제외)
      - 상세글/유틸 URL 패턴 제외 (read/view/login ...)
      - 같은 URL이 여러 위젯/메뉴에서 반복될수록 '진짜 보드'일 가능성 ↑ → 빈도순

    Returns: [(name, absolute_url, freq), ...]  (빈도 높은 순)
    """
    from urllib.parse import urljoin, urlparse
    host = urlparse(base_url).netloc
    seen, order, freq = {}, [], Counter()
    for a in dom.iter("a"):
        href = a.get("href") or ""
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        txt = _norm(a.text_content())
        if not (1 <= len(txt) <= 30):
            continue
        url = urljoin(base_url, href)
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            continue
        if host and p.netloc and p.netloc != host:   # 같은 사이트만
            continue
        if not p.path or p.path == "/":               # 홈/빈 경로 제외
            continue
        if _DETAIL_RE.search(p.path) or _DETAIL_RE.search(url):
            continue
        freq[url] += 1
        if url not in seen:
            seen[url] = txt
            order.append(url)
    ranked = sorted(order, key=lambda u: (-freq[u], order.index(u)))
    return [(seen[u], u, freq[u]) for u in ranked[:limit]]


# ---------------------------------------------------------------------------
# URL 절대화 (페이지네이션→pagination.py, 필드 휴리스틱→field_heuristics.py,
#            예시경계 분리→segment.py, 셀렉터→structure.py 로 이동)
# ---------------------------------------------------------------------------


def _abs_url(base, href):
    """상대경로 링크(/2026/… 등)를 base 로 절대화(브라우저와 동일한 표준 urljoin).
    이미 절대거나 네비게이션 아님(mailto/js/#)이면 그대로 — 결정적, 추측 없음."""
    h = (href or "").strip()
    if not base or not h or h.startswith(
            ("http://", "https://", "mailto:", "javascript:", "tel:", "#", "data:")):
        return href
    from urllib.parse import urljoin
    try:
        return urljoin(base, h)
    except Exception:
        return href


def _img_value(src, base_url=None, local_base=None):
    """이미지 src 를 '데이터 값'으로 정규화한다.
      · 원격(http/https) → 그대로(진짜 이미지 웹 주소).
      · Save-As 스냅샷이 로컬화한 상대경로(./…_files/… 또는 file:) → 사이트 URL 에 붙이지 않고
        (그러면 https://site/…_files/… 처럼 무의미해짐) '스냅샷 폴더(local_base)' 기준의 실제
        로컬 파일 경로로 돌려준다 → 사용자가 그 파일을 바로 열 수 있음(오프라인 주소).
      · 그 외 사이트-상대경로 → 기존처럼 base_url 로 절대화."""
    s = (src or "").strip()
    if not s or s.startswith("data:"):
        return None if not s else s
    if s.startswith(("http://", "https://")):
        return s
    if s.startswith("file:"):
        from urllib.parse import urlparse, unquote
        return unquote(urlparse(s).path)
    # Save-As 로컬화 마커(상대 './'·'../' 또는 '_files/')는 스냅샷 폴더 기준 로컬 파일로
    if local_base and (s.startswith(("./", "../")) or "_files/" in s):
        return os.path.normpath(os.path.join(local_base, s))
    return _abs_url(base_url, s)


# ---------------------------------------------------------------------------
# 5. 엔진
# ---------------------------------------------------------------------------
class SelfHealingEngine:
    MIN_ROWS = 2  # 이보다 적게 매칭되면 'row 셀렉터 깨짐'으로 판단

    def __init__(self, cache_path=None, verbose: bool = True):
        # cache_path=None 이면 '기억하지 않음'(메모리만): 로드/저장 안 함.
        self.cache_path = cache_path
        self.verbose = verbose
        self.schema: Optional[Schema] = None
        if cache_path and os.path.exists(cache_path):
            self.schema = Schema.load(cache_path)

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    def _persist(self):
        """캐시 경로가 있을 때만 스키마를 저장(없으면 기억 안 함)."""
        if self.cache_path and self.schema is not None:
            self.schema.save(self.cache_path)
            self.log("  -> " + t("스키마 캐시 저장: {p}", p=self.cache_path))

    # --- 행/필드 해석 ----------------------------------------------------
    # 원칙: 클래스는 '있을 때만' 쓰는 가속기. 클래스가 없거나(난독화/무클래스)
    #       모호하면 '구조 시그니처/경로'라는 불변 anchor로 해석한다.
    def _match_rows(self, dom):
        s = self.schema
        # 클래스가 있으면 클래스로 빠르게
        if s.row_cls:
            out = [el for el in dom.iter(s.row_tag)
                   if el.get("class") and s.row_cls in el.get("class").split()]
            if len(out) >= self.MIN_ROWS:
                return out
        # 클래스가 없거나 부족 → 구조 시그니처로 (클래스 무관)
        return [e for e in dom.iter() if isinstance(e.tag, str)
                and row_sig(e) == s.row_signature]

    @staticmethod
    def _resolve_field(row, fs):
        """행 안에서 필드 노드를 찾는다. 클래스 → 구조 경로 순."""
        # ① 클래스 가속 경로 (고유 클래스가 살아있을 때)
        if fs.get("cls"):
            for el in row.iter(fs["tag"]):
                if el.get("class") and fs["cls"] in el.get("class").split():
                    return el
        # ② 구조 경로 (클래스 없음/변경 시에도 동작하는 불변 anchor)
        if fs.get("path"):
            return follow_path(row, [tuple(p) for p in fs["path"]])
        return None

    # === Calibration ====================================================
    def calibrate(self, dom) -> Schema:
        self.log("\n[CALIBRATION] " + t("반복 구조 자동 탐지 중..."))
        rows, sig = find_repeating_rows(dom)
        if not rows:
            raise RuntimeError("반복 구조(리스트)를 찾지 못했습니다.")
        self.log("  - " + t("반복 블록 발견: {n}개 행, 시그니처={sig}", n=len(rows), sig=sig))

        row0 = rows[0]
        schema = Schema(
            row_css=css_of(row0), row_tag=row0.tag,
            row_cls=first_class(row0), row_signature=sig,
        )
        self.log("  - " + t("row 셀렉터 생성: {css}", css=schema.row_css))

        for name, fdef in FIELD_DEFS.items():
            node = None
            for r in rows:                       # 필드가 잡히는 첫 행 사용
                node = fdef["matcher"](r)
                if node is not None:
                    base = r
                    break
            if node is None:
                self.log("  - [" + t("경고") + "] " + t("필드 '{name}' 위치를 못 찾음", name=name))
                continue
            cls = unique_class(base, node)
            fs = FieldSchema(
                css=f"{node.tag}.{cls}" if cls else node.tag,
                tag=node.tag, cls=cls,
                path=rel_path(base, node), attr=fdef["attr"],
                example=(node.get(fdef["attr"]) if fdef["attr"] else _norm(_text(node))) or "",
            )
            schema.fields[name] = asdict(fs)
            self.log("  - " + t("필드 '{name}' 셀렉터 생성: {css}", name=name, css=fs.css)
                     + (f" (@{fs.attr})" if fs.attr else ""))

        self.schema = schema
        self._persist()
        return schema

    # === 사용자 선택 기반 스키마 생성 ====================================
    def build_schema_from_selection(self, rows, sig, selections, dom=None,
                                    single=False, link_split=True):
        """사용자가 고른 노드들로 스키마를 구성한다.

        selections: [(name, node), ...] 또는 [(name, node, attr), ...]
          - attr=None  : 텍스트 필드 (링크 보유 시 <name>_url 자동 추가)
          - attr='href': 링크 필드 (그 자체가 URL, 추가 분리 없음)
        dom 을 주면, 레코드가 반복되는 data-testid/role 마커를 가졌는지 확인해
        row_testid 로 저장한다(클래스 균일 SPA 에서 추출 정확도↑).
        single=True 면 단일 레코드(상세 페이지) 스키마 — 반복 마커는 저장하지 않는다.
        link_split=False 면 텍스트 필드에 <name>_url 을 자동 추가하지 않는다
        (예: CSS 셀렉터로 큰 본문 컨테이너를 통째로 지정할 때 — 안쪽 첫 링크가
        엉뚱한 _url 로 붙는 것을 막는다).
        """
        row0 = rows[0]
        schema = Schema(
            row_css=css_of(row0), row_tag=row0.tag,
            row_cls=first_class(row0), row_signature=sig,
        )
        schema.single_record = bool(single)
        # 레코드 경계 마커(data-testid/role)가 문서에서 반복되면 저장 → 추출 가속·정확.
        # (단일 레코드 모드는 반복이 없으므로 마커 저장을 건너뛴다.)
        mk = None if single else marker_of(row0)
        if mk and dom is not None and len(find_rows_by_marker(dom, mk)) >= self.MIN_ROWS:
            schema.row_testid = mk
            self.log("  - " + t("레코드 경계 마커 사용: {mk} ({n}개 반복)",
                               mk=mk, n=len(find_rows_by_marker(dom, mk))))
        coloc = {}   # id(node) -> {"node": node, "members": [(name, 사용자예시값), ...]}
        auto_url = set()   # 텍스트 필드에서 자동 파생된 <name>_url 컬럼명(중복 제거 판정용)
        for item in selections:
            name, node = item[0], item[1]
            attr = item[2] if len(item) > 2 else None
            value = item[3] if len(item) > 3 else None   # 사용자가 준 예시 값(경계 계산용)
            path = rel_path(row0, node)
            # 링크 필드인데 노드가 레코드 '자손'이 아님(rel_path=None) → 카드 전체를
            # 감싼 '조상 <a>'. 하향 경로로는 못 잡으니 '가장 가까운 조상 <a>' 규칙으로 저장.
            if attr and path is None:
                schema.fields[name] = asdict(FieldSchema(
                    css=node.tag, tag=node.tag, cls=None,
                    path=[[_ANCESTOR_A, 0]], attr=attr,
                    example=(node.get(attr) or ""),
                ))
                continue
            cls = unique_class(row0, node)   # 레코드 내에서 유일할 때만 클래스 사용
            schema.fields[name] = asdict(FieldSchema(
                css=f"{node.tag}.{cls}" if cls else node.tag,
                tag=node.tag, cls=cls, path=path,
                attr=attr,
                example=(node.get(attr) if attr else _norm(_text(node))) or "",
            ))
            if attr is None:   # 텍스트 필드 → 같은 노드에 뭉친 필드 후보로 묶어둔다
                coloc.setdefault(id(node), {"node": node, "members": []})
                coloc[id(node)]["members"].append((name, value))
            if attr or not link_split:   # 링크 필드거나 자동분리 끔 → _url 추가 안 함
                continue
            # 텍스트 필드가 '실제 이동하는' 링크를 품으면 URL 필드도 함께.
            # (javascript:;/# 같은 버튼·토글 링크는 제외 → 모든 행 동일값으로 dedup 망치는 것 방지)
            href = node.get("href")
            href_node = node
            if not is_real_href(href or ""):
                href = None
            if href is None:
                a = node.find(".//a")
                if a is not None and is_real_href(a.get("href") or ""):
                    href, href_node = a.get("href"), a
            if href:
                hcls = unique_class(row0, href_node)
                schema.fields[f"{name}_url"] = asdict(FieldSchema(
                    css=f"{href_node.tag}.{hcls}" if hcls else href_node.tag,
                    tag=href_node.tag, cls=hcls,
                    path=rel_path(row0, href_node), attr="href",
                    example=href or "",
                ))
                auto_url.add(f"{name}_url")
        # 같은 노드에 텍스트 필드가 2개 이상 뭉쳤으면, 사용자 예시 경계로 분리 규칙을 학습한다
        # (사이트 무관 — 구분자는 예시에서 파생). 못 쪼개면(겹침/붙음/예시없음) 그냥 둔다.
        for grp in coloc.values():
            if len(grp["members"]) < 2 or any(v is None for _n, v in grp["members"]):
                continue
            node_text = _norm(_text(grp["node"]))
            derived = _derive_colocated_split(node_text, grp["members"])
            if not derived:
                continue
            for name, (idx, seps, seg_text) in derived.items():
                fs = schema.fields.get(name)
                if fs is None:
                    continue
                fs["seg_index"], fs["seg_seps"], fs["example"] = idx, seps, seg_text
            self.log("  - " + t("한 노드에 뭉친 {n}개 필드를 예시 경계로 분리: {names}",
                               n=len(derived), names=list(derived.keys())))
        # 자동 파생 <name>_url 이 '사용자가 명시한 링크 필드'와 완전히 같은 href 면 중복 → 제거
        # (같은 링크가 두 컬럼으로 새는 것 방지. href 문자열 정확 비교 — 결정적).
        for uname in list(auto_url):
            ufs = schema.fields.get(uname)
            if not ufs or not ufs.get("example"):
                continue
            if any(other != uname and other not in auto_url
                   and ofs.get("attr") == "href"
                   and ofs.get("example") == ufs.get("example")
                   for other, ofs in schema.fields.items()):
                del schema.fields[uname]
                self.log("  - " + t("중복 링크 컬럼 제거: {u} (사용자 지정 링크와 동일)", u=uname))
        self.schema = schema
        self._persist()
        return schema

    # === 자동 재학습(최후 폴백) =========================================
    def recalibrate(self, dom, field_names=None, examples=None):
        """값싼 방법이 다 실패(② 불통과)했을 때의 최후 폴백. 주입된 구조 파악자(_discover_structure,
        보통 LLM·save_as 로컬 HTML 기반)로 '기존 필드명을 보존'하며 스키마를 새로 만든다.
        훅 미설정/실패/노드 0 이면 None(호출부가 판단). 성공 시 build_schema_from_selection 을 거쳐
        self.schema 를 교체(+_persist) → 이 스키마로의 추출·의미검증·채택취소(롤백)는 cli 가 담당."""
        names = field_names or (list(self.schema.fields.keys()) if self.schema else [])
        if not names:
            return None
        result = _discover_structure(dom, names, examples or {})   # LLM 은 훅 뒤에(engine LLM-free)
        if not result:
            return None
        record, sig, selections, err = result
        if err or record is None:
            return None
        sels = [(n, node) for n, node in selections if node is not None]
        if not sels:
            return None
        self.log("  [" + t("재학습") + "] " +
                t("로컬 HTML 구조 파악 성공 → {n}개 필드 재구성: {names}",
                  n=len(sels), names=[n for n, _ in sels]))
        return self.build_schema_from_selection([record], sig, sels, dom=dom)

    # === Self-Healing helpers ===========================================
    def _heal_rows(self, dom):
        """row 셀렉터가 깨졌을 때: ① 시그니처로 재탐색 → ② 전체 재탐지."""
        s = self.schema
        # ① 캐시된 구조 시그니처로 문서 전체 스캔 (구조 동일, class만 변경된 경우)
        rows = [e for e in dom.iter() if isinstance(e.tag, str)
                and row_sig(e) == s.row_signature]
        if len(rows) >= self.MIN_ROWS:
            self.log("    · " + t("구조 시그니처 일치 → row 재탐색 성공 (구조 불변)"))
        else:
            # ② 구조 자체가 바뀜 → 반복 블록 전면 재탐지
            rows, sig = find_repeating_rows(dom)
            if not rows:
                raise RuntimeError("치유 실패: 반복 구조를 찾을 수 없음")
            s.row_signature = sig
            self.log("    · " + t("구조 드리프트 감지 → 반복 블록 재탐지 (새 시그니처={sig})", sig=sig))

        # 새 row 셀렉터 재생성 + 캐시 패치
        old = s.row_css
        s.row_tag, s.row_cls = rows[0].tag, first_class(rows[0])
        s.row_css = css_of(rows[0])
        self.log("    · " + t("row 셀렉터 자가 갱신: {old}  ->  {new}", old=old, new=s.row_css))
        return rows

    def _heal_field(self, name, rows):
        """필드 셀렉터가 깨졌을 때: 구조 경로 → 휴리스틱 순으로 재배치 후 갱신."""
        s = self.schema
        fdef = FIELD_DEFS.get(name)   # 사용자 선택 필드는 매처가 없을 수 있음
        fs = s.fields[name]
        sample = rows[0]

        # ① 구조 경로(class 무관)로 재탐색 — 클래스만 바뀐 경우 여기서 성공
        node = follow_path(sample, [tuple(p) for p in fs["path"]]) if fs["path"] else None
        how = t("구조 경로")

        # ② 경로도 안 맞으면(구조 드리프트) 휴리스틱 매처로 의미 기반 재배치
        if (node is None or (fs["attr"] is None and not _text(node))) and fdef:
            node = fdef["matcher"](sample)
            how = t("휴리스틱 매처")
            if node is not None:
                fs["path"] = rel_path(sample, node)  # 경로도 새로 학습

        # ③ 휴리스틱이 없거나 실패하면 '주입된 재배치 훅'(보통 LLM)에 의미 기반 위치를 맡긴다
        #    (텍스트 필드 한정; 훅 미설정/미연결 시 None → 자동 폴백. engine 은 LLM 을 모른다.)
        if (node is None or (fs["attr"] is None and not _text(node))) and fs["attr"] is None:
            llm_node = _relocate(sample, name, fs.get("example", ""))
            if llm_node is not None:
                node = llm_node
                how = t("의미 기반 재배치(주입 훅)")
                fs["path"] = rel_path(sample, node)

        if node is None:
            self.log("    · [" + t("실패") + "] " + t("필드 '{name}' 재배치 불가", name=name))
            return False

        old = fs["css"]
        fs["tag"], fs["cls"] = node.tag, first_class(node)
        fs["css"] = css_of(node)
        self.log("    · " + t("필드 '{name}' 재배치({how}) → 셀렉터 자가 갱신: {old}  ->  {new}",
                             name=name, how=how, old=old, new=fs['css']))
        return True

    # === Parsing (+ 자동 치유) ==========================================
    def extract(self, dom, base_url=None, local_base=None):
        if self.schema is None:
            raise RuntimeError("스키마 없음 — 먼저 calibrate() 필요")
        s = self.schema
        healed = False

        half = lambda n: max(1, n // 2)

        # --- 단일 레코드(상세 페이지) 모드: 반복 목록이 아니라 페이지당 레코드 1개 ---
        if s.single_record:
            return self._extract_single(dom, base_url=base_url, local_base=local_base)

        # --- row 추출 ---
        # 0) 레코드 경계 마커(data-testid/role) 최우선 — 클래스가 균일한 SPA(X 등)에서
        #    구조 시그니처는 과다매칭되지만 이 속성은 레코드만 정확히 집는다.
        rows = []
        if s.row_testid:
            rows = find_rows_by_marker(dom, s.row_testid)
        if s.row_testid and len(rows) >= self.MIN_ROWS:
            pass  # 마커 정상 — 가장 신뢰. (구조/클래스 확인 불필요)
        # 1) 클래스 가속 경로 시도
        elif s.row_cls and len(
                [el for el in dom.iter(s.row_tag)
                 if el.get("class") and s.row_cls in el.get("class").split()]
        ) >= self.MIN_ROWS:
            rows = [el for el in dom.iter(s.row_tag)
                    if el.get("class") and s.row_cls in el.get("class").split()]
        else:
            # 2) 클래스 깨짐 → 구조 시그니처로 재탐색
            sig_rows = [e for e in dom.iter() if isinstance(e.tag, str)
                        and row_sig(e) == s.row_signature]
            if len(sig_rows) >= self.MIN_ROWS:
                rows = sig_rows
                new_css = css_of(rows[0])
                if new_css != s.row_css:
                    self.log("  [DIFF] " + t("row 클래스 셀렉터 '{css}' 깨짐 → 구조 시그니처로 재탐색 성공",
                                             css=s.row_css))
                    self.log("    · " + t("row 셀렉터 자가 갱신: {old} -> {new}",
                                         old=s.row_css, new=new_css))
                    s.row_tag, s.row_cls, s.row_css = rows[0].tag, first_class(rows[0]), new_css
                    healed = True
            else:
                # 3) 구조까지 드리프트 → 반복 블록 전면 재탐지
                self.log("  [DIFF] " + t("row 구조 변경 감지 → 반복 블록 전면 재탐지"))
                rows = self._heal_rows(dom)
                healed = True

        # --- 필드 점검 ---
        for name in list(s.fields.keys()):
            fs = s.fields[name]
            resolved_ok, class_ok = 0, 0
            sample_node = None
            for r in rows:
                node = self._resolve_field(r, fs)
                if node is not None and (fs["attr"] or _text(node)):
                    resolved_ok += 1
                    if sample_node is None:
                        sample_node = node
                if fs.get("cls"):  # 클래스 가속 경로만 따로 카운트
                    cm = next((el for el in r.iter(fs["tag"])
                               if el.get("class") and fs["cls"] in el.get("class").split()),
                              None)
                    if cm is not None:
                        class_ok += 1

            if resolved_ok < half(len(rows)):
                # 구조 경로까지 실패 → 진짜 치유 (휴리스틱 재배치)
                self.log("  [DIFF] " + t("필드 '{name}' 위치 추적 실패 ({ok}/{tot}) → 자가 치유",
                                         name=name, ok=resolved_ok, tot=len(rows)))
                self._heal_field(name, rows)
                healed = True
            elif fs.get("cls") and class_ok < half(len(rows)) and sample_node is not None:
                # 구조 경로로는 살았지만 클래스가 바뀜 → 클래스 셀렉터 리프레시
                new_css = css_of(sample_node)
                self.log("  [DIFF] " + t("필드 '{name}' 클래스 셀렉터 '{css}' 깨짐 → 구조 경로로 위치 유지",
                                         name=name, css=fs['css']))
                self.log("    · " + t("필드 '{name}' 셀렉터 자가 갱신: {old} -> {new}",
                                     name=name, old=fs['css'], new=new_css))
                fs["tag"], fs["cls"], fs["css"] = sample_node.tag, first_class(sample_node), new_css
                healed = True

        if healed:
            self._persist()
        else:
            self.log("  " + t("(빠른 경로 적중 — 치유 불필요, Zero-latency)"))

        # --- 최종 데이터 추출 ---
        # 가격 필드(예시가 가격처럼 생긴 필드)는, 고정 경로로 값을 못 잡거나(=할인 카드
        # 등 구조 변종) 가격이 아닌 값이 나오면 레코드 안에서 '실제 판매가'를 보강한다.
        price_fields = {name for name, fs in s.fields.items()
                        if not fs.get("attr") and _looks_price(fs.get("example", ""))}
        results = []
        for r in rows:
            rec = {}
            for name, fs in s.fields.items():
                # 이미지 필드(src)는 '고정 경로' 대신 행마다 '대표 이미지'를 구조로 찾는다 —
                # news/article 처럼 카드 구조가 섞이거나 스냅샷↔렌더가 달라도 각 행의 썸네일을 잡음.
                if fs["attr"] == "src":
                    node = find_record_image(r, hint=fs.get("example", ""))
                    rec[name] = _img_value(_img_src(node), base_url, local_base) if node is not None else None
                    continue
                node = self._resolve_field(r, fs)
                if fs["attr"]:
                    v = node.get(fs["attr"]) if node is not None else None
                    if v and fs["attr"] in ("href", "src"):
                        v = _abs_url(base_url, v)   # 상대경로 링크/이미지 절대화(base 있을 때)
                    rec[name] = v
                    continue
                val = _norm(_text(node)) if node is not None else None
                # 한 노드에 뭉친 필드면 예시 경계로 이 필드 조각만 뽑는다(v5.0).
                if val is not None and fs.get("seg_seps"):
                    val = _segment_value(val, fs["seg_seps"], fs.get("seg_index"))
                if name in price_fields and not _looks_price(val or ""):
                    p = find_record_price(r)
                    if p:
                        val = p
                rec[name] = val
            results.append(rec)
        # 모든 필드가 빈 행(진짜 레코드 아님 — 헤더/광고 listitem 등)은 제외(결정적).
        results = [r for r in results if any(v not in (None, "") for v in r.values())]
        return results

    # === 단일 레코드(상세 페이지) 추출 =====================================
    def _find_single_root(self, dom):
        """상세 페이지에서 스키마의 '레코드 컨테이너' 1개를 찾는다.

        후보: 구조 시그니처 일치 ∪ (row_tag+row_cls) 클래스 일치. 필드가 가장 많이
        해석되는 후보를 채택한다(같은 템플릿의 다른 상세 페이지에서도 동작).
        후보가 없으면 문서 루트로 폴백 — 고유 클래스 기반 필드는 그래도 살아난다.
        """
        s = self.schema
        cands, seen = [], set()

        def add(e):
            if id(e) not in seen:
                seen.add(id(e))
                cands.append(e)

        if s.row_signature:
            for e in dom.iter():
                if isinstance(e.tag, str) and row_sig(e) == s.row_signature:
                    add(e)
        if s.row_cls:
            for e in dom.iter(s.row_tag):
                if e.get("class") and s.row_cls in e.get("class").split():
                    add(e)
        if not cands:
            return dom

        def score(root):
            n = 0
            for _name, fs in s.fields.items():
                node = self._resolve_field(root, fs)
                if node is None and not fs.get("path") and not fs.get("cls"):
                    node = root      # 필드 노드 == 레코드 루트인 퇴화 케이스
                if node is not None:   # '찾았는가'만 본다(텍스트 없어도 = 이미지 본문)
                    n += 1
            return n

        best = max(cands, key=score)
        return best if score(best) > 0 else dom

    def _extract_single(self, dom, base_url=None, local_base=None):
        """단일 레코드(상세 페이지) 추출 — 레코드 컨테이너 1개를 찾아 필드를 뽑는다.

        ★ 스키마를 '고정'으로 다룬다(자가 치유로 변경하지 않는다). 체인 크롤링은
        같은 템플릿의 '독립된 여러 페이지'를 도는데, 어떤 페이지의 특이 케이스
        (예: 회사소개가 텍스트가 아니라 이미지)로 필드 셀렉터를 재배치하면 그 변경이
        뒤따르는 정상 페이지 전부를 오염시키기 때문이다.
        → 텍스트가 비면 그 페이지 한정으로 이미지/링크 URL 을 대신 뽑는다(media_urls).
        """
        s = self.schema
        root = self._find_single_root(dom)

        def resolve(fs):
            node = self._resolve_field(root, fs)
            if node is None and not fs.get("path") and not fs.get("cls"):
                node = root      # 필드 노드가 레코드 루트 자체인 경우
            return node

        price_fields = {name for name, fs in s.fields.items()
                        if not fs.get("attr") and _looks_price(fs.get("example", ""))}
        rec = {}
        for name, fs in s.fields.items():
            node = resolve(fs)
            if fs["attr"] == "src":
                node = find_record_image(root, hint=fs.get("example", "")) or node
                rec[name] = _img_value(_img_src(node), base_url, local_base) if node is not None else None
                continue
            if fs["attr"]:
                v = node.get(fs["attr"]) if node is not None else None
                if v and fs["attr"] == "href":
                    v = _abs_url(base_url, v)
                rec[name] = v
                continue
            val = _norm(_text(node)) if node is not None else None
            if val is not None and fs.get("seg_seps"):   # 한 노드에 뭉친 필드 분리(v5.0)
                val = _segment_value(val, fs["seg_seps"], fs.get("seg_index"))
            if not val and node is not None:      # 텍스트 없음 → 이미지/링크로 폴백
                val = media_urls(node)
            if name in price_fields and not _looks_price(val or ""):
                p = find_record_price(root)
                if p:
                    val = p
            rec[name] = val
        return [rec]

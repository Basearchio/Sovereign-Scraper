# -*- coding: utf-8 -*-
"""
MODULE_NAME: llm_locators.py
PURPOSE: DOM + LLM 오케스트레이션 계층. engine(구조 헬퍼)과 services.llm_service(전송)를
         잇는 '접착제'다. LLM 에게 레코드 HTML/값을 주고 '의미'를 얻은 뒤, engine 의
         매칭 헬퍼로 실제 노드를 도출한다. (LLM 은 의미만, 노드/셀렉터는 engine 이.)
DEPENDENCY: engine(_row_html/_match_node/… 구조 헬퍼), services.llm_service(전송).

[계층/의존성 규율]
- 이 모듈은 engine 위에 있다: `import engine`(O). engine 은 이 모듈을 import 하지 않는다(X).
  engine 은 재배치가 필요하면 주입된 훅(engine._relocate)만 부른다 → 순환 없음.
- cli.py 가 시작 시 `engine.set_relocator(llm_locators.relocate)` 로 배선한다.

[검증된 주요 사이트 및 케이스]
- work24(라벨+값 분리): locate_by_example_llm 이 '역할(컬럼)' 기준으로 값을 매핑.
- 자가치유 재배치(relocate): 구조 드리프트 시 '그 필드의 현재 값'을 LLM 의미로 찾음.

[테스트/운영 교훈]
- LLM 미연결/실패 시 모든 함수가 None/err 로 우아하게 실패 → 호출부가 휴리스틱 폴백.
- [이력] Phase 1b 에서 engine 을 LLM-free 로 만들며 engine 에서 이 4개 함수를 이관.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from engine import _row_html, find_repeating_rows        # 필드 열거/미리보기 재료(engine)
from structure import _find_by_text, _norm, row_sig       # 구조 원시함수(leaf)
from locators import _match_href, _match_node             # 예시 기반 매처(locators)
from values import looks_url


def relocate(row, name: str, example: str):
    """
    [사용처/협력자] engine._relocate 훅으로 주입되어 locate_by_example / locate_single_record /
      _heal_field 의 최후 폴백에서 호출. 하부는 llm_service.ask + engine._find_by_text.
    [역할] 구조/휴리스틱이 다 실패했을 때, LLM 에게 행 HTML 을 주고 '그 필드의 현재 값'을
      의미로 알아낸 뒤 그 값으로 노드를 찾는다. 실패/미연결 시 None.
    (구 engine.llm_relocate — Phase 1b 이관, 이름만 relocate 로.)
    """
    if not example:
        return None
    try:
        from services import llm_service as llm
    except Exception:
        return None
    prompt = (
        "다음은 게시판/목록의 한 행(레코드) HTML이다.\n"
        f"```html\n{_row_html(row)}\n```\n"
        f"이 행에서 뽑던 '{name}' 필드의 이전 예시 값: \"{example}\"\n"
        "같은 의미의 값을 이 HTML에서 찾아 그 '텍스트 값'만 한 줄로 출력하라. "
        "설명·따옴표 없이 값만. 찾을 수 없으면 NONE 만 출력.")
    ans = llm.ask(prompt, max_tokens=120)
    if not ans:
        return None
    ans = ans.strip().strip('"').splitlines()[0].strip()
    if not ans or ans.upper() == "NONE":
        return None
    return _find_by_text(row, ans)


def locate_by_example_llm(dom, values):
    """
    [사용처/협력자] cli.select_by_example 의 ③단계(결정적 매칭 실패 시). 하부는
      engine.find_repeating_rows/_match_node + llm_service.ask_json.
    [역할] 사용자 값이 여러 노드 조합/표현 변형이라 HTML에 그대로 없을 때, LLM에게
      '레코드 HTML + 사용자 값'을 주고 '역할(컬럼)' 기준으로 매핑시킨다.
    Returns: (record, row_signature, [(value, node|None, name, attr), ...], error|None)
    """
    vals = [_norm(v) for v in values if _norm(v)]
    if not vals:
        return None, None, None, "예시 값이 비어 있습니다."
    try:
        from services import llm_service as llm
    except Exception:
        return None, None, None, "LLM 모듈 없음"

    rows, _ = find_repeating_rows(dom)
    if not rows:
        return None, None, None, "반복 레코드를 찾지 못함(LLM 분석도 불가)."

    # URL 값은 LLM 대상에서 빼고 href 로 직접 매칭
    text_vals = [v for v in vals if not looks_url(v)]

    # 사용자 텍스트 값 토큰과 가장 많이 겹치는 레코드를 표본으로 선택
    frags = [f for v in text_vals for f in v.split() if len(f) >= 2]
    def overlap(r):
        t = re.sub(r"\s+", "", _norm(r.text_content()))
        return sum(1 for f in frags if re.sub(r"\s+", "", f) in t)
    sample = max(rows, key=overlap) if frags else rows[0]

    role_of = {}
    if text_vals:
        listing = "\n".join(f"{i + 1}. {v}" for i, v in enumerate(text_vals))
        prompt = (
            "사용자가 어떤 '목록의 한 항목'에서 본 값들을 아래처럼 적었다"
            "(보이는 대로라 표현/순서/띄어쓰기가 실제 HTML과 다를 수 있다):\n"
            f"{listing}\n\n"
            "먼저 각 값이 '무슨 항목(역할/컬럼)'인지 판단하라"
            "(예: 공고제목/직무명, 회사명, 급여, 경력, 학력, 지역, 등록일 등).\n"
            "다음은 그 목록에서 '레코드 하나'의 실제 HTML이다 "
            "(사용자가 본 항목과 다른 데이터일 수 있음):\n"
            f"```html\n{_row_html(sample, 4000)}\n```\n"
            "각 번호에 대해, 텍스트 유사성이 아니라 '같은 역할(컬럼)' 기준으로 "
            "이 레코드 안에서 대응하는 실제 텍스트를 찾아라.\n"
            "출력은 JSON 배열로만. 각 원소는 "
            '{"name":"역할 짧은 한국어 이름", "value":"이 레코드 안의 실제 텍스트"} '
            f"형식이고, 해당 역할이 없으면 value 를 null 로. 정확히 {len(text_vals)}개, "
            "설명 없이 배열만.")
        arr = llm.ask_json(prompt, max_tokens=600)
        if not isinstance(arr, list) or len(arr) != len(text_vals):
            return None, None, None, "LLM이 필드를 매핑하지 못함."
        role_of = {v: item for v, item in zip(text_vals, arr)}

    matched, seen = [], {}
    for v in vals:
        if looks_url(v):                       # 링크 → href 매칭
            matched.append((v, _match_href(sample, v), "링크", "href"))
            continue
        item = role_of.get(v)
        if isinstance(item, dict):
            real, name = item.get("value"), item.get("name")
        else:
            real, name = item, None
        node = _match_node(sample, str(real)) if real else None
        nm = re.sub(r"\s+", "_", str(name).strip())[:20] if name else None
        if nm:                                 # 역할명 중복 방지
            seen[nm] = seen.get(nm, 0) + 1
            if seen[nm] > 1:
                nm = f"{nm}{seen[nm]}"
        matched.append((v, node, nm, None))
    if not any(n is not None for _, n, _, _ in matched):
        return None, None, None, "LLM 매핑 결과를 HTML에서 못 찾음."
    return sample, row_sig(sample), matched, None


def discover_structure(dom, field_names, examples=None):
    """
    [사용처/협력자] 자동 재학습의 최후 폴백. engine.recalibrate 가 engine._discover_structure
      훅으로 호출(cli 가 save_as 로 받은 '로컬 HTML'의 dom 을 넘김 → 라이브 무접촉·탐지 회피).
      하부는 engine.find_repeating_rows/_match_node + llm_service.ask_json.
    [역할] 값싼 방법이 다 실패했을 때, LLM 에게 '레코드 HTML + 기존 필드명/예시'를 주고 각 필드의
      현재 값을 의미로 찾게 한 뒤, 그 값으로 실제 노드를 도출한다. 예시가 아니라 '기존 필드명'을
      키로 쓰므로 사용자가 지정한 필드명이 그대로 보존된다.
    Returns: (record, row_signature, [(name, node|None), ...], error|None)
      — locate_by_example_llm 과 같은 계약 → cli 가 build_schema_from_selection 으로 레시피화.
    """
    names = [n for n in (field_names or []) if n]
    if not names:
        return None, None, None, "필드명이 없습니다."
    try:
        from services import llm_service as llm
    except Exception:
        return None, None, None, "LLM 모듈 없음"

    rows, sig = find_repeating_rows(dom)
    if not rows:
        return None, None, None, "반복 레코드를 찾지 못함(구조 파악 불가)."

    ex = examples or {}
    # 표본: 기존 예시 값과 가장 많이 겹치는 레코드(사이트가 바뀌어도 '비슷한' 카드를 고름)
    frags = [f for n in names for f in _norm(str(ex.get(n, ""))).split() if len(f) >= 2]
    def overlap(r):
        t = re.sub(r"\s+", "", _norm(r.text_content()))
        return sum(1 for f in frags if re.sub(r"\s+", "", f) in t)
    sample = max(rows, key=overlap) if frags else rows[0]

    listing = "\n".join(
        f'{i + 1}. {n}' + (f' (이전 예시: "{ex[n]}")' if ex.get(n) else "")
        for i, n in enumerate(names))
    prompt = (
        "다음은 어떤 목록에서 '레코드 하나'의 실제 HTML이다:\n"
        f"```html\n{_row_html(sample, 4000)}\n```\n"
        "아래 각 '필드'에 대해, 이 레코드 안에서 대응하는 실제 텍스트 값을 찾아라. "
        "이전 예시는 사이트/표현이 달라 그대로 없을 수 있으니 '같은 의미/역할'로 판단하라:\n"
        f"{listing}\n\n"
        "출력은 JSON 배열로만. 각 원소는 "
        '{"name":"<위 필드명을 그대로>", "value":"이 레코드 안의 실제 텍스트"} '
        f"형식이고, 정확히 {len(names)}개. 해당 값이 없으면 value 를 null 로. 설명 없이 배열만.")
    arr = llm.ask_json(prompt, max_tokens=700)
    if not isinstance(arr, list):
        return None, None, None, "LLM이 구조를 파악하지 못함."

    by_name = {}
    for item in arr:
        if isinstance(item, dict) and item.get("name"):
            by_name[re.sub(r"\s+", "_", str(item["name"]).strip())] = item.get("value")

    selections = []
    for n in names:
        real = by_name.get(n)
        node = _match_node(sample, str(real)) if real else None
        selections.append((n, node))
    if not any(node is not None for _, node in selections):
        return None, None, None, "LLM 값들을 HTML에서 못 찾음."
    return sample, row_sig(sample), selections, None


def looks_like_real_records(records, fields):
    """
    [사용처/협력자] cli 가드 — 결과가 너무 적을 때(예: ≤3행) 호출. 하부는 llm_service.ask.
    [역할] 추출된 레코드가 '실제 목록 콘텐츠'인지, '봇 차단/인증(验证·captcha·robot)/오류/빈 페이지'
      부스러기인지 LLM 에게 한 단어로 판정시킨다. 실제=True, 차단/오류=False,
      LLM 미연결/불명확=None(호출부는 None 을 '통과'로 처리 → 못 믿을 때 정상 데이터를 막지 않음).
    """
    if not records:
        return None
    try:
        from services import llm_service as llm
    except Exception:
        return None
    lines = []
    for i, r in enumerate(records[:5], 1):
        vals = " | ".join(f"{f}={r.get(f)}" for f in fields if r.get(f) not in (None, ""))
        lines.append(f"{i}. {vals or '(빈 값)'}")
    prompt = (
        "아래는 어떤 목록 페이지에서 추출한 레코드다:\n" + "\n".join(lines) + "\n\n"
        "이것이 '실제 목록 콘텐츠'(게시글/상품/검색결과 등 사람이 원하는 데이터)인지, 아니면 "
        "'봇 차단/인증(로봇 확인·验证·captcha·slider)/오류/빈 페이지'의 부스러기인지 판정하라. "
        "실제 콘텐츠면 REAL, 차단/인증/오류/무의미면 BLOCK — 딱 한 단어만 출력.")
    ans = llm.ask(prompt, max_tokens=10)
    if not ans:
        return None
    a = ans.strip().upper()
    if "BLOCK" in a:
        return False
    if "REAL" in a:
        return True
    return None


def improvement_brief(record_html, findings, engine_hint=""):
    """
    [사용처/협력자] cli 자동재학습(5b)이 성공 시 heal_knowledge 저널에 fix_prompt 로 저장.
      하부는 llm_service.ask.
    [역할] full-HTML 재학습으로만 뚫린 케이스에 대해 '왜 값싼(정적/동적) 휴리스틱이 못 찾았고,
      어떻게 코드를 고치면 다음엔 LLM 없이 잡을지'를 개발자(Claude)가 바로 쓸 수 있는 한국어 브리핑
      으로 작성시킨다. → 사용자가 저널의 이 글을 Claude 에게 붙여넣어 휴리스틱을 개선하는 재료.
      실패/미연결/입력 없음 시 None.
    findings: [(field, resolved_text, locator_desc), ...]  (locator_desc 예: 'span.cost, path=[...]')
    """
    if not findings:
        return None
    try:
        from services import llm_service as llm
    except Exception:
        return None
    items = "\n".join(f'- {f}: 값="{v}", 위치={loc}' for f, v, loc in findings)
    prompt = (
        "우리 크롤러는 '값싼' 결정적 방법으로 목록 필드를 찾는다: "
        "(1)저장된 CSS/클래스 셀렉터, (2)클래스 무관 구조 경로, (3)태그 구조 시그니처, "
        "(4)engine.FIELD_DEFS 의 키워드/패턴 휴리스틱 매처. "
        "이번엔 이 값싼 방법이 모두 실패하고 LLM 전체 분석으로만 아래 필드를 찾았다:\n"
        f"{items}\n\n"
        + (f"[참고] {engine_hint}\n\n" if engine_hint else "")
        + "이 레코드의 HTML:\n```html\n" + (record_html or "") + "\n```\n\n"
        "개발자(코딩 AI)가 코드를 고쳐 '다음엔 LLM 없이' 이 필드를 잡게 하려 한다. 다음을 간결한 "
        "한국어 불릿 3~6줄로만 답하라(코드블록 금지): "
        "1) 값싼 휴리스틱이 왜 놓쳤는지 추정, "
        "2) 이 필드를 구별하는 '안정적' 단서(텍스트 형태/속성/구조 위치), "
        "3) 어느 휴리스틱을 어떻게 바꾸면 되는지 구체적 제안(예: FIELD_DEFS['가격'] 매처가 '원' 접미"
        "뿐 아니라 '₩' 접두·class~=cost 도 인정).")
    ans = llm.ask(prompt, max_tokens=500)
    if not (ans and ans.strip()):
        return None
    # 라이프사이클 마무리(고정): 개선을 반영했으면 사건을 기록 후 활성 저널에서 삭제하라는 지시.
    footer = ("\n\n---\n[적용 후] 위 개선을 코드에 반영했다면, 함께 저장된 html_sample 로 제안의 "
              "타당성을 먼저 검증하라. 반영·검증이 끝나면 이 사건을 해결 기록으로 남긴 뒤 활성 저널에서 "
              "삭제하라: 같은 field/site/path 로 `heal_knowledge.resolve(cue, note=...)`. "
              "활성 저널(_heal_hints.json)엔 '아직 안 고친' 이슈만 남긴다.")
    return ans.strip() + footer


def llm_name_fields(previews):
    """
    [사용처/협력자] cli 의 필드명 자동 명명(select_by_example / discover_and_select).
      하부는 llm_service.ask_json.
    [역할] 후보 필드 미리보기 텍스트들에 의미 있는 한국어 필드명을 붙인다.
      실패/미연결 시 None → 호출부는 f1,f2.. 로 폴백.
    """
    if not previews:
        return None
    try:
        from services import llm_service as llm
    except Exception:
        return None
    lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(previews))
    prompt = (
        "다음은 목록의 한 항목에서 뽑은 후보 필드 값들이다. 각 번호에 어울리는 "
        "짧은 한국어 필드명(예: 제목, 작성자, 날짜, 가격)을 JSON 문자열 배열로만 "
        f"출력하라. 설명 없이 배열만, 개수는 정확히 {len(previews)}개.\n{lines}")
    arr = llm.ask_json(prompt, max_tokens=300)
    if isinstance(arr, list) and len(arr) == len(previews):
        names, seen = [], {}
        for i, x in enumerate(arr):
            n = re.sub(r"\s+", "_", str(x).strip())[:20] or f"f{i + 1}"
            if n in seen:               # 중복 방지
                seen[n] += 1
                n = f"{n}{seen[n]}"
            else:
                seen[n] = 1
            names.append(n)
        return names
    return None


def llm_next_url(dom, base_url: str):
    """
    [사용처/협력자] engine 이 아니라 cli._next_page_url 이 호출(구조 폴백 전에 LLM 우선).
      하부는 llm_service.ask.
    [역할] 구조로 못 찾을 때 LLM에게 페이지 링크 목록을 주고 다음 페이지 URL을 추론.
    """
    try:
        from services import llm_service as llm
    except Exception:
        return None
    links, seen = [], set()
    for a in dom.iter("a"):
        h = a.get("href") or ""
        if not h or h.startswith(("#", "javascript:", "mailto:")):
            continue
        t = _norm(a.text_content()) or (a.get("aria-label") or "").strip()
        if not t or len(t) > 15:
            continue
        u = urljoin(base_url, h)
        if u in seen:
            continue
        seen.add(u)
        links.append((t, u))
        if len(links) >= 80:
            break
    if not links:
        return None
    listing = "\n".join(f"{t} -> {u}" for t, u in links)
    prompt = (
        f"현재 목록 페이지 URL: {base_url}\n"
        f"이 페이지의 링크들(텍스트 -> URL):\n{listing}\n\n"
        "이 목록의 '다음 페이지'로 가는 링크의 URL 하나만 정확히 출력하라. "
        "페이지네이션이 없으면 NONE 만 출력. 설명·따옴표 없이 URL만.")
    ans = llm.ask(prompt, max_tokens=200)
    if not ans:
        return None
    ans = ans.strip().strip('"').splitlines()[0].strip()
    if not ans or ans.upper() == "NONE":
        return None
    return ans if ans.startswith("http") else urljoin(base_url, ans)

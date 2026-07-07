# -*- coding: utf-8 -*-
"""
자가 치유형 크롤러 CLI (대화형 필드 선택)
==========================================
흐름:
  1) 대상 사이트의 반복 블록을 찾는다 (크롤링은 아직 안 함)
  2) 첫 번째 반복 요소 안의 후보 필드를 '번호 + 미리보기'로 보여준다
  3) 사용자가 원하는 번호(예: 1,3,5)를 고르면 → 그 필드만 전체 행에서 추출

사용법:
    python cli.py <URL 또는 HTML경로>            # 미리보기 → 번호 입력 → 추출
    python cli.py <대상> --select 1,3,5          # 번호를 바로 지정(비대화형)
    python cli.py <대상> --rediscover            # 필드 선택을 처음부터 다시
    python cli.py <대상> --json                  # 결과 JSON 출력

CSV 체인 크롤링 (목록 CSV 의 링크 열 → 각 상세페이지):
    python cli.py <목록.csv>                      # ① CSV → ② URL 컬럼명(예: 직무_url)
                                                 # → ③ URL 정련(선택) → ④ 상세 by-example
    · target 이 .csv 파일이면 자동으로 체인 모드로 진입한다.
    · ③ 정련: 1행 URL 을 '원하는 형태로' 고쳐 붙여넣으면(예: 꼬리 &src=.. 또는 감싼
      괄호 제거) 그 규칙을 열 전체 링크에 동일 적용한다. Enter 면 원본 그대로.
    · ④ 필드 지정 세 가지:
        (A) by-example  : 보이는 값 한 줄  회사명@#3,000만원@#2026-07-15 마감
        (B) 본문 통째    : '본문:'/'body:'  본문: LLM/Agentic AI에 대한 이해 및 …
            → 그 한 줄이 든 '본문 컨테이너 전체'를 끌어온다(여러 줄 입력 불필요).
        (C) CSS 셀렉터   : 'css:' 로 시작   css: 상세=div#content_job @# 급여=strong.pay
    · 상세페이지의 <iframe> 본문(incruit 공고처럼)은 자동으로 DOM 에 인라인해 잡는다.
    · 스키마는 첫 페이지 기준 '고정'(페이지별 자가치유로 안 바꿈 → 특이 1건이 나머지를
      오염시키지 않음). 본문이 텍스트가 아니라 이미지/링크뿐이면 그 URL 을 대신 뽑는다.
    · 결과는 output/<csv이름>_detail.csv 로 따로 저장(원본 CSV 는 건드리지 않음).
    · 상세페이지 요청 사이엔 랜덤 대기로 사이트 부담을 줄인다. --delay 는 '숫자 하나'
      (평균 초, 기본 15=대형 사이트 기준)이고 그 값 주위로 ±50% 자동 랜덤된다.
    · 비대화형: --url-col 직무_url --clean-url "<정련한 URL>" --limit N --delay 5

차단/느린 사이트 옵션 (쿠팡·스카이스캐너 등):
    --chrome        내 진짜 크롬으로 페이지를 열어 'Save As'(Ctrl+S)로 HTML 을 받아
                    그걸 파싱한다. 안티봇(Akamai/DataDome)이 막는 사이트용.
                    마우스 안 움직이고 실제 세션/쿠키를 쓰므로 탐지 회피.
                    (차단이 자동 감지되면 이 옵션 없이도 자동으로 크롬 경로로 전환됨)
    --wait <초>     로딩 대기를 늘린다. 결과가 수십 초에 걸쳐 그려지는 무거운 SPA용.
                    크롬 Save As 의 '저장 전 대기'와 헤드리스 렌더링의 '안정화 대기'에
                    동시에 적용된다. 예) 스카이스캐너 --wait 35

    예) python cli.py "<URL>" --chrome --wait 35
    · PowerShell 에서 URL 에 & 가 많아 따옴표로 감싸기 번거로우면, 그냥
      'python cli.py' 로 띄운 뒤 프롬프트에 'URL --chrome --wait 35' 처럼
      끝에 붙여넣어도 인식한다. --chrome/--wait 뿐 아니라 --rediscover,
      --scroll 등 '아무 플래그나' 끝에 붙여도 떼어내 적용한다.

로드방식(레시피 load_method)은 사이트별로 자동 기록·재현된다:
    auto   정적/SSR 페이지(대부분)
    render JS-SPA(YouTube 등): 학습 때 렌더링이 필요했으면 자동 기록 → 재현도 렌더링
    chrome 안티봇 차단(쿠팡 등): 내 크롬 Save As

한 번 고르면 스키마가 cache/ 에 저장되어, 다음 실행부터는 같은 필드를
자동으로(필요 시 자가 치유까지) 다시 추출한다.
또한 --chrome / --wait 값은 사이트별 레시피(recipes/<site>.csv)에 함께 저장되어,
replay.py 나 스케줄러가 target 만 줘도 같은 로드방식·대기시간으로 재현한다.
"""
import os as _os, sys as _sys
# 내부 모듈은 _internal/ 폴더에 있다 → import 전에 검색 경로에 추가.
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_internal"))
import bootstrap  # 첫 실행: 가상환경(.venv) 안내·자동설치 후 venv 로 재실행
if __name__ == "__main__":
    bootstrap.ensure_env()

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")   # 한글 값 입력 보호
except Exception:
    pass

import re

from engine import (SelfHealingEngine, Schema, load_dom, find_repeating_rows,
                    enumerate_fields, field_preview, find_section_links,
                    row_sig, set_relocator, set_structure_discoverer)
# A 유형(URL 기반) 페이지네이션은 pagination.py leaf 에서(engine 클래스와 형제). v5.0 탈결합:
from pagination import find_next_url, learn_page_param, apply_page_param
# 예시 기반 위치탐색은 locators.py 에서(engine 과 형제 계층 — 서로 모름). v5.0 탈결합:
from locators import (locate_by_example, locate_single_record,
                      _MIXED_ROWS_TAG as MIXED_ROWS_TAG)
# 값 의미 분류(링크/형태)는 values.py leaf 에서(engine 속으로 값 의미를 가지러 가지 않는다). v5.0:
from values import looks_url
# 성공 기준 가드(잘못된 성공으로 좋은 레시피를 덮지 않는다)는 guards.py 에서. v5.0:
from guards import (_run_is_valid, _semantic_ok, _coverage_ok,
                    _looks_like_block, _llm_confirms_real)
# 수집 전략(fetch): 학습 중 렌더링(_playwright_fetch)·다음 페이지 차단 감지(block_reason)만 cli 가 직접
# 쓴다. 크롬 Save As 등 'DOM 획득'은 loader.py 로 이관(안티봇/차단 전환은 거기서).
from crawlers.dynamic import playwright_fetch as _playwright_fetch
from crawlers.base import block_reason
# LLM 오케스트레이션은 engine 이 아니라 llm_locators 에서(engine 은 LLM-free). 그리고
# 자가치유의 의미 기반 재배치를 LLM 구현으로 engine 에 '주입'한다(순환 없이 결합 차단).
from llm_locators import (llm_name_fields, locate_by_example_llm, llm_next_url,
                          relocate as _relocate_impl,
                          discover_structure as _discover_impl)
import crawl_config     # 레시피가 따르는 '기본 저장/로드 방식'(start.py 설정에서 변경)
from i18n import t       # 다국어: 대화형 프롬프트 번역(미번역은 한국어 폴백)

set_relocator(_relocate_impl)
# 자동 재학습(최후 폴백): save_as 로 받은 로컬 HTML 을 LLM 으로 구조 파악하는 구현을 주입.
set_structure_discoverer(_discover_impl)

import safe_io   # 엑셀 등 파일 잠금 시 풀릴 때까지 대기 후 저장(구멍 방지)
# 중복 제거 키(leaf, crawl_all/save_csv·autoheal 공유) + 자동 재학습·저널(autoheal). v5.0 분할:
from dedup import _rec_key, _choose_url_field
from output import save_csv   # CSV 저장 leaf(cli·chain 공유). v5.0 분할
import loader   # DOM 획득(안티봇/렌더/차단) — 가변 상태(LAST_LOAD_METHOD 등) 보유. v5.0 분할
from loader import load_or_die, _warn_if_spa, smart_load   # cli 자기 사용(체인은 loader 직접)
from autoheal import (try_auto_heal, _auto_heal, _auto_heal_enabled, _ask_load_method,
                      _record_heal_case, _heal_missing_at_learning)

# 파일 경로 규칙은 paths.py(leaf)로 분리 — cli/chain 이 재사용(engine 무관). Phase 4b:
from paths import (HERE, CACHE_DIR, OUTPUT_DIR, RUNLOG_PATH,
                   _site_key, cache_path_for, csv_path_for,
                   saved_html_path_for, saved_html_old_path_for,
                   recipe_path_for, chain_recipe_path_for, image_dir_for,
                   rel_to_root)
import image_archive


# 감사로그(_runs.csv)·계층 실행번호는 runlog.py(leaf)로 분리 — cli/chain/replay 가 재사용. Phase 4c:
from runlog import (_is_chain_target, RUNLOG_HEADER, assign_run_numbers, append_runlog,
                    next_batch, MODE_LABELS)




def parse_indices(text, n):
    """'1,3,5' / '1 3 5' → [0,2,4] (1-based 입력 → 0-based)."""
    out = []
    for tok in text.replace(",", " ").split():
        if tok.isdigit():
            i = int(tok)
            if 1 <= i <= n:
                out.append(i - 1)
    return out


def select_by_example(eng, dom, example, llm_name=False, target=None, wait=0,
                      single=False, kinds=None):
    """사용자가 본 값들(예: '제목@#12,000원@#서울 전체')로 파서를 역설계.

    3단계 전략(사이트별 하드코딩 없음):
      ① 결정적 매칭(빠름/무료)
      ② 실패 시, URL이면 Playwright 렌더링 후 재시도 (값이 JS로 그려지는 경우)
      ③ 그래도 실패 시, LLM에 레코드 HTML+사용자 값을 넣어 매핑
    single=True 면 상세페이지(레코드 1개) 모드 — 반복 블록(>=2)을 요구하지 않고
    locate_single_record 로 '모든 값을 담는 가장 안쪽 컨테이너'를 레코드로 잡는다.
    kinds: 값들과 평행한 종류('text'|'link'|'image') 리스트(피커 전용, 선택). 'image' 값은
      URL 로 못 찾으니(로컬화·CDN 토큰 드리프트) 엔진이 레코드 안 <img> 를 '구조로' 잡게 한다.
    반환: 실제로 사용한 dom (렌더링됐을 수 있으므로 호출부가 이걸로 추출).
    """
    locate = locate_single_record if single else locate_by_example
    # 필드 구분자: 우선 '@#'(숫자 쉼표 등과 충돌 없는 희귀 조합), 없으면 폴백.
    if "@#" in example:
        parts = example.split("@#")
    else:
        parts = re.split(r"\s*[|\n]\s*|,\s+", example)
    values = [s.strip() for s in parts if s.strip()]
    # kinds(피커) 는 @# 로 쪼갠 값들과 1:1 로 정렬될 때만 사용 — 어긋나면 안전하게 무시(URL 기반 폴백).
    locate_kinds = kinds if (kinds and len(kinds) == len(values)) else None
    print("\n■ " + t("예시 값 {n}개로 파서 역설계 중...", n=len(values)))
    for v in values:
        print(f"   · \"{v}\"")

    # ① 결정적 매칭
    rec, sig, matched, err = locate(dom, values, kinds=locate_kinds)

    # ② 실패 → '값이 정적 HTML에 아예 없으면'(=JS 렌더 필요) 브라우저 렌더링.
    #    값은 있는데 매칭만 실패면(예: incruit) 렌더링 생략하고 바로 LLM.
    if err and target and str(target).startswith(("http://", "https://")):
        ns = lambda s: re.sub(r"\s+", "", s)
        # '보이는 텍스트'만으로 판정한다. dom.text_content() 는 <script> 안의
        # ytInitialData(JSON) 같은 것도 포함해서, 값이 화면엔 안 보이는데 JS 데이터에만
        # 있어도 '있다'고 오판한다(YouTube: '3:38' 이 JSON 에 있음).
        # → script/style/template/noscript 를 뺀 실제 텍스트로 판단.
        vis = dom.xpath("//text()[not(ancestor::script) and not(ancestor::style)"
                        " and not(ancestor::template) and not(ancestor::noscript)]")
        page = ns("".join(vis)) if vis else ns(dom.text_content())
        # 값을 '하나하나' 개별 판단한다(요청). URL 값은 href(속성)라 텍스트엔 없을 수
        # 있으니 판단에서 제외. 텍스트 값 중 '하나라도' 보이는 정적 HTML에 없으면 →
        # 그 값은 JS 로 그려진다 → (좀 느려도) 렌더링해서 재시도. 렌더링은 안전하고,
        # 한 번 성공하면 레시피에 load_method=render 로 캐싱돼 재현 땐 비용이 없다.
        text_values = [v for v in values if not looks_url(v)]
        missing = [v for v in text_values if ns(v) and ns(v) not in page]
        if missing:
            extra = t(" (+{w}s 대기)", w=wait) if wait else ""
            ex = missing[0][:20] + ("…" if len(missing[0]) > 20 else "")
            print("  · " + t('정적 HTML에 안 보이는 값 {n}/{tot}개 (예: "{ex}") → JS 렌더링 사이트로 보고 브라우저 렌더링{extra}...',
                            n=len(missing), tot=len(text_values), ex=ex, extra=extra))
            rendered = _playwright_fetch(target, settle_ms=wait * 1000)
            if rendered is not None:
                loader.RENDER_REQUIRED = True   # 이 사이트는 재현 때도 렌더링 필요 → 레시피에 기록(loader 상태 실시간 갱신)
                dom = rendered
                rec, sig, matched, err = locate(dom, values, kinds=locate_kinds)

    # 예시 값이 '서로 다른 항목'에서 온 경우 → LLM 도 못 고침. 곧장 안내하고 종료
    # (사용자가 값을 한 항목에서 다시 입력하도록).
    if err and err.startswith(MIXED_ROWS_TAG):
        print("\n[" + t("입력 확인 필요") + "] " + err[len(MIXED_ROWS_TAG):])
        sys.exit(3)

    # ③ 그래도 실패 → LLM이 레코드 HTML을 역할 기반으로 분석해 매핑
    #    (안티봇 차단 사이트는 이미 DOM 로드 단계(smart_load)에서 진짜 크롬으로
    #     전환됐으므로, 여기 들어온 dom 은 정상 페이지다.)
    #    단일 레코드 모드는 반복 표본을 요구하는 이 폴백을 건너뛴다
    #    (locate_single_record 가 필드별로 이미 LLM 재배치를 시도함).
    if err and not single:
        print("  · " + t("결정적 매칭 실패({err})", err=err) + "\n  · " + t("→ LLM에 레코드 HTML 분석 요청..."))
        rec, sig, matched, err = locate_by_example_llm(dom, values)

    if err:
        print("[" + t("에러") + "] " + str(err))
        print("  · " + t("값을 HTML 에서 못 찾았습니다 — 로그인/안티봇/JS 렌더가 필요한 사이트일 수 있습니다."))
        print("    " + t("→ 로드 방식을 'save_as'(처음부터 실크롬)로 다시 시도해 보세요(Gmail 등에서 효과적)."))
        print("      " + t("auto 는 봇으로 보여 알맹이 없는 페이지를 받을 수 있습니다."))
        sys.exit(3)

    cls = (rec.get("class") or "").split()
    print("\n■ " + t("공통 레코드 식별: <{tag}>  (시그니처 {sig})",
                    tag=rec.tag + ('.' + cls[0] if cls else ''), sig=sig))
    print("  " + "-" * 60)
    selections, names, have_names, text_nodes, dropped = [], [], True, [], []
    for k, (v, node, nm, attr) in enumerate(matched, 1):
        if node is None:
            print("  ✗ " + t('"{v}" → 위치 못 찾음 (건너뜀)', v=v))
            dropped.append((v, attr == "href"))
            continue
        ncls = (node.get("class") or "").split()
        role = f"  [{nm}]" if nm else ""
        shown = (node.get(attr) if attr else field_preview(node)[0])
        kind = (" 🔗" + t("링크")) if attr == "href" else ((" 🖼" + t("이미지")) if attr == "src" else "")
        print(f"  ✓ \"{v}\"{role}{kind}")
        print(f"      → <{node.tag}{'.' + ncls[0] if ncls else ''}>  = \"{shown}\"")
        if nm is None:
            have_names = False
        names.append(nm or ("링크" if attr == "href" else "이미지" if attr == "src" else f"f{k}"))
        selections.append((node, attr, v))   # v=사용자 예시 값(한 노드 분리 경계 계산용)
        text_nodes.append(None if attr else node)
    print("  " + "-" * 60)
    # 성공 기준: '원한 필드를 실제로 가져왔는가'. 준 예시 값의 절반도 못 잡으면 = 구멍투성이 파싱
    # (대개 차단/인증/엉뚱한 페이지) → LLM 부를 것도 없이 결정적으로 실패 처리.
    n_want, n_got = len(matched), len(selections)
    if not _coverage_ok(n_want, n_got):
        print("[" + t("에러") + "] " + t("원한 필드 {want}개 중 {got}개만 찾았습니다 — 대부분 위치를 못 잡았습니다.", want=n_want, got=n_got))
        print("  · " + t("원한 내용을 못 가져오면 성공이 아닙니다. 차단/인증/엉뚱한 페이지일 가능성이 큽니다."))
        print("    " + t("→ 로드 방식을 'save_as'(처음부터 실크롬)로 다시 시도해 보세요(auto 는 봇으로 보여 빈/확인 페이지를 받을 수 있습니다)."))
        sys.exit(3)

    # 커버리지는 넘겼지만 '요청한 필드 일부'를 못 잡았으면 조용한 성공으로 넘기지 않는다(정직).
    if dropped:
        miss = ", ".join(f'"{v[:36]}"' for v, _u in dropped)
        print("\n  ⚠ " + t("요청한 {want}개 중 {got}개만 확보 — 누락: {miss}", want=n_want, got=n_got, miss=miss))
        print("     · " + t("저장은 되지만 '완전한 성공'은 아닙니다(링크 등은 dedup/이동에 중요)."))

    # LLM 분석 단계가 이미 역할 기반 필드명을 줬으면 그대로 사용.
    # 결정적 단계(이름 없음)에서만 별도로 LLM 명명을 시도(텍스트 필드만).
    if llm_name and not have_names:
        labels = llm_name_fields([field_preview(n)[0] if n is not None else "링크"
                                  for n in text_nodes])
        if labels:
            names = labels
    # (3c) 값싼 방법으로도 못 잡은 요청 필드를 학습 단계에서 LLM+로컬HTML 로 마지막 시도 + 저널 기록.
    # (llm_name 이 names 를 교체한 '뒤'에 붙여야 zip 정합이 깨지지 않는다.)
    if dropped:
        for n, node, attr, v in _heal_missing_at_learning(target, dom, rec, dropped, names):
            names.append(n)
            selections.append((node, attr, v))
        if len(names) < n_want:
            print("     · " + t("재학습[r] 하거나, 정말 그 위치라면 예시를 '한 항목'에서 다시 확인하세요."))
    print("  · " + t("필드명: {names}", names=names))
    eng.build_schema_from_selection(
        [rec], sig,
        [(nm, node, attr, val) for nm, (node, attr, val) in zip(names, selections)],
        dom=dom, single=single)   # dom 으로 data-testid/role 레코드 마커 감지
    return dom   # 렌더링됐을 수 있으므로 호출부가 이 dom 으로 추출


def discover_and_select(eng, dom, preset_select=None, as_json=False, llm_name=False):
    """반복 블록 탐지 → 후보 필드 미리보기 → 선택 → 스키마 생성."""
    rows, sig = find_repeating_rows(dom)
    if not rows:
        print("[" + t("에러") + "] " + t("반복 구조(리스트)를 찾지 못했습니다."))
        sys.exit(3)

    print("\n■ " + t("반복 블록 발견: {n}개 행", n=len(rows)))
    print("  " + t("시그니처: {sig}", sig=sig))
    print("  " + t("(행 셀렉터 추정: {sel})",
                  sel=rows[0].tag + ('.' + rows[0].get('class').split()[0] if rows[0].get('class') else '')))

    cands = enumerate_fields(rows[0])
    if not cands:
        print("[" + t("에러") + "] " + t("반복 요소 안에서 후보 필드를 찾지 못했습니다."))
        sys.exit(3)

    print("\n■ " + t("첫 번째 반복 요소 안의 후보 필드 (아직 크롤링 안 함):"))
    print("  " + "-" * 64)
    for i, node in enumerate(cands, 1):
        text, hint, href = field_preview(node)
        print(f"  {i:>2}. {text}")
        print(f"      └ <{hint}>" + (f"  href={href}" if href else ""))
    print("  " + "-" * 64)
    print("  · " + t("🔗 표시는 링크 보유(선택 시 텍스트 + URL 함께 추출)"))

    # 선택 받기
    if preset_select is not None:
        sel_text = preset_select
        print("\n" + t("선택(지정): {s}", s=sel_text))
    else:
        sel_text = input("\n" + t("추출할 항목 번호를 입력하세요 (예: 1,3,5 / Enter=미리보기만 종료): ")).strip()

    if not sel_text:
        print(t("선택 없음 — 미리보기만 하고 종료합니다. (크롤링 안 함)"))
        sys.exit(0)

    idxs = parse_indices(sel_text, len(cands))
    if not idxs:
        print(t("유효한 번호가 없습니다. 종료."))
        sys.exit(0)

    names = [f"f{i+1}" for i in idxs]
    if llm_name:   # LLM에게 의미 있는 필드명 부여(미연결 시 f1,f2.. 폴백)
        labels = llm_name_fields([field_preview(cands[i])[0] for i in idxs])
        if labels:
            names = labels
            print("  · " + t("LLM 필드명: {names}", names=names))
        else:
            print("  · " + t("(LLM 미연결/실패 → 기본 필드명 사용)"))
    selections = [(names[k], cands[i]) for k, i in enumerate(idxs)]
    print("\n" + t("선택된 필드: {names}", names=[name for name, _ in selections]))
    eng.build_schema_from_selection(rows, sig, selections, dom=dom)




def pick_board(dom, target, preset=None):
    """포털/인덱스 페이지 → 보드 목록을 보여주고 하나를 골라 그 URL을 반환."""
    links = find_section_links(dom, target)
    if not links:
        print("[" + t("에러") + "] " + t("들어갈 보드/섹션 링크를 찾지 못했습니다."))
        sys.exit(3)
    print("\n■ " + t("보드/섹션 후보 {n}개 (자주 링크된 순):", n=len(links)))
    print("  " + "-" * 60)
    for i, (name, url, freq) in enumerate(links, 1):
        print(f"  {i:>2}. {name}")
        print(f"      └ {url}" + (f"  (x{freq})" if freq > 1 else ""))
    print("  " + "-" * 60)
    if preset is not None:
        sel = preset
        print(t("보드 선택(지정): {s}", s=sel))
    else:
        sel = input("\n" + t("들어갈 보드 번호를 고르세요 (예: 3): ")).strip()
    idxs = parse_indices(sel, len(links))
    if not idxs:
        print(t("선택 없음 — 종료."))
        sys.exit(0)
    return links[idxs[0]][1]


# _rec_key/_choose_url_field 는 dedup.py leaf 로 이관(상단에서 import). crawl_all/save_csv 와
# autoheal.try_auto_heal 이 공유하므로 순환을 피해 leaf 로 둔다.


def _next_page_url(dom, cur_url, pattern):
    """다음 페이지 URL 결정.
    원칙: LLM 이 판단(하드코딩한 '다음/next' 단어에 의존하지 않음).
    효율: 한 번 LLM 판단에서 URL 증가 패턴이 학습되면 이후엔 기계적으로 적용.
    LLM 미연결 시에만 구조 휴리스틱으로 폴백.
    Returns: (next_url|None, new_pattern|None)
    """
    if pattern:                                   # 학습된 패턴 → LLM 호출 없이
        return apply_page_param(cur_url, *pattern), pattern
    nxt = llm_next_url(dom, cur_url)              # LLM 이 직접 판단
    src = "LLM"
    if not nxt:                                    # LLM 없거나 실패 → 구조 폴백
        nxt = find_next_url(dom, cur_url)
        src = t("구조(폴백)")
    if nxt:
        print("  · " + t("다음 페이지 판단: {src}", src=src))
        return nxt, learn_page_param(cur_url, nxt)   # 패턴 학습되면 다음부턴 기계적
    return None, None


# 성공 기준 가드(_run_is_valid/_semantic_ok/_coverage_ok/_looks_like_block/_llm_confirms_real)는
# guards.py 로 이관(상단에서 import). '잘못된 성공으로 좋은 레시피를 덮지 않는다'는 계약의 단일 출처.


# 자동 재학습(try_auto_heal/_auto_heal/_record_heal_case/_heal_missing_at_learning/
# _auto_heal_enabled/_ask_load_method)은 autoheal.py 로 이관(상단에서 import).


def crawl_all(eng, dom, target, max_pages, scroll):
    """A 유형 페이지네이션 순회 + dedup. scroll=True 면 한 페이지(이미 다 로드됨)만."""
    fields = list(eng.schema.fields.keys())
    is_web = str(target).startswith(("http://", "https://"))
    all_rows, seen, visited = [], set(), {target}
    cur_url, cur_dom, pattern, url_field = target, dom, None, None
    # 이미지 필드의 로컬화 경로 해석 기준: save_as 스냅샷 폴더(웹) 또는 로컬 HTML 이 있는 폴더.
    local_base = (os.path.dirname(saved_html_path_for(target)) if is_web
                  else os.path.dirname(os.path.abspath(str(target))))
    for page in range(1, max_pages + 1):
        rows = eng.extract(cur_dom, base_url=cur_url if is_web else None, local_base=local_base)
        if page == 1:    # 1페이지 데이터로 '변별력 있는' dedup 키 결정
            url_field = _choose_url_field(rows, fields)
            if url_field:
                print("  · " + t("dedup 기준: '{f}' (링크)", f=url_field))
        new = 0
        for r in rows:
            k = _rec_key(r, fields, url_field)
            if k in seen:
                continue
            seen.add(k)
            all_rows.append(r)
            new += 1
        print("  · " + t("{page}p: {n}건 중 신규 {new}건 (누적 {tot})",
                        page=page, n=len(rows), new=new, tot=len(all_rows)))
        if scroll or not is_web:
            break                       # 스크롤 모드/로컬파일은 페이지네이션 없음
        if loader.BLOCK_DETECTED or loader.LAST_LOAD_METHOD == "chrome":
            # 차단 사이트(쿠팡 등)는 페이지를 또 열면 불안정 + 봇 탐지 위험 →
            # 어떤 경로로 페이지를 얻었든 무조건 1페이지만 수집하고 종료.
            print("  · " + t("차단 사이트 → 봇 탐지 위험으로 1페이지만 수집하고 종료"))
            break
        if page > 1 and new == 0:
            print("  · " + t("신규 레코드 없음 → 종료"))
            break
        if page >= max_pages:
            print("  · " + t("최대 페이지 도달 → 종료"))
            break
        nxt, pattern = _next_page_url(cur_dom, cur_url, pattern)
        # http(s) 절대 URL 만 인정(LLM 환각/상대경로 거르기), 이미 방문이면 종료
        if not nxt or not str(nxt).startswith(("http://", "https://")) or nxt in visited:
            print("  · " + t("다음 페이지 없음 → 종료"))
            break
        visited.add(nxt)
        try:
            cur_dom = smart_load(nxt, scroll=scroll)   # 정적→렌더, 차단되면 진짜 크롬
        except Exception as e:
            print("  · " + t("다음 페이지 로드 실패 → 종료 ({e})", e=e))
            break
        # 다음 페이지가 차단 페이지면 추출/자가치유 대상으로 삼지 않는다(스키마 오염 방지).
        if block_reason(cur_dom):
            print("  · " + t("다음 페이지가 차단 페이지 → 추출 중단(스키마 보호)"))
            break
        cur_url = nxt
    return all_rows, url_field


# ============================ CSV 체인 크롤링 =================================
# 목록 CSV(예: incruit 검색결과)의 '링크 열'을 따라 각 상세페이지를 크롤링한다.
#   ① CSV 경로 입력 → ② URL 컬럼명 입력(예: 직무_url) → ③ URL 정련(선택)
#   → ④ 첫 상세페이지 by-example → 정련된 모든 URL 순회 → 별도 상세 CSV 저장.

def _looks_like_csv(target: str) -> bool:
    return target.lower().endswith(".csv") and os.path.isfile(target)


def _maybe_rediscover(recipe_path):
    """대화형: 이미 학습된 레시피가 있으면 '기존 재현 vs 초기화 후 재학습'을 묻는다. 초기화 선택 시 True.
    (start 가 아니라 cli 가 단일 소스로 안내 — 분기 중복 제거.)"""
    if not (recipe_path and os.path.exists(recipe_path)):
        return False
    print("\n· " + t("이 대상에는 '이미 학습된 레시피'가 있습니다."))
    print("    " + t("[Enter] 기존 레시피로 바로 크롤링(빠름)   [r] 레시피 초기화 후 새로 학습"))
    # 정의된 선택지(Enter/r)만 인정한다. 오타·IME 잔상(예: 'r' 키가 한글모드면 'ㄱ')을 조용히
    # '기존 사용'으로 흘리지 않고 '다시 입력'을 요청 → 언어 무관·일관(모든 나라 문자를 매핑할 필요 없음).
    while True:
        try:
            sel = input("  " + t("선택: ")).strip().lower()
        except EOFError:
            return False                      # 비대화형(EOF) → 안전 기본값(기존 레시피)
        if sel == "":
            return False                      # Enter = 기존 레시피로 재현
        if sel == "r":
            return True                       # r = 초기화 후 새로 학습
        print("    · " + t("'r'(초기화) 또는 Enter(기존)만 입력하세요. (입력이 인식되지 않았습니다)"))


def _interactive_setup(args):
    """대화형 시작 안내: 로드 방식 → 저장 방식 → 주소 순으로 고르게 하고 args(chrome/mode)를 채운다.
    Enter=설정된 기본값을 '적용'한다(일관성). 이 기본값은 crawl_config(=start.py 설정)에서 바꾼다.
    → 대화형 선택이 이번 실행·레시피에 반영. (비대화 replay 는 이 안내를 건너뛰어 레시피 저장값을 재현.
    auto 로 갔다가 막히면 자동 save_as 전환·재학습 프롬프트 등 '나중 폴백'은 그대로 둔다.)"""
    d_load = crawl_config.default_load_method()      # 설정된 기본 로드
    d_mode = crawl_config.default_save_mode()        # 설정된 기본 저장
    dflt = "  " + t("[기본]")
    print("\n=== " + t("크롤 설정") + " ===")
    print(t("[로드 방식] 이 크롤러의 강점은 '내 크롬 그대로 Save As'(안티봇·무거운 SPA 도 사람처럼)."))
    print("  1) auto    " + t("(정적/렌더 자동 — 빠름, 막히면 자동으로 save_as 전환)") + (dflt if d_load == "auto" else ""))
    print("  2) save_as " + t("(처음부터 실제 크롬으로)") + (dflt if d_load == "save_as" else ""))
    sel = input("  " + t("번호(Enter=기본:{d}): ", d=d_load)).strip()
    load = {"1": "auto", "2": "save_as"}.get(sel, d_load)
    args.chrome = (load == "save_as")                # Enter 여도 설정 기본값을 적용(일관성)
    print(f"  → {load}")

    print("\n" + t("[저장 방식] 결과 CSV 에 어떻게 쌓을까요?"))
    print("  1) " + t("추가하기            (중복 허용 — 회차로 구분, 랭킹 시계열용)"))
    print("  2) " + t("중복 제외하고 추가하기 (새 항목만 누적)"))
    print("  3) " + t("덮어쓰기            (매번 최신 상태로 교체 — 인기가요 등)"))
    sel = input("  " + t("번호(Enter=기본:{d}): ", d=t(MODE_LABELS.get(d_mode, d_mode)))).strip()
    args.mode = {"1": "history", "2": "append", "3": "overwrite"}.get(sel, d_mode)
    print("  → [" + t(MODE_LABELS.get(args.mode, args.mode)) + "]")

    target = input("\n" + t("[주소] 크롤링할 URL / HTML 경로 / 목록 CSV: ")).strip()
    if target and _maybe_rediscover(recipe_path_for(target)):
        args.rediscover = True
    return target


def _pickable_html(target):
    """[역할] 시각적 피커로 '클릭'할 로컬 HTML 경로를 돌려준다(없으면 None).
      · target 이 로컬 .htm(l) 파일이면 그 자체.
      · URL 이면 save_as 스냅샷(saved_html_path_for)이 이미 있을 때만(=save_as 로 받은 경우).
    즉 'save_as 로 이미 내 크롬으로 받아둔 그 파일'을 그대로 클릭 대상으로 쓴다(피커 DOM=엔진 DOM)."""
    t = str(target)
    if not t.startswith(("http://", "https://")):
        return t if t.lower().endswith((".htm", ".html")) and os.path.exists(t) else None
    p = saved_html_path_for(t)   # save_as 스냅샷(.html + _files: 이미지·CSS 로컬화)
    return p if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser(description="자가 치유형 크롤러 (대화형 필드 선택)")
    ap.add_argument("target", nargs="?", help="대상 URL 또는 로컬 HTML 경로")
    ap.add_argument("--boards", action="store_true",
                    help="포털 메인에서 보드 목록을 먼저 고른 뒤 그 안에서 추출(드릴다운)")
    ap.add_argument("--board", help="고를 보드 번호 (--boards 와 함께, 비대화형)")
    ap.add_argument("--example",
                    help="눈으로 본 값들을 @# 로 구분해 주면 파서를 역설계 "
                         "(예: \"제목@#12,000원@#강남구 삼성동\")")
    ap.add_argument("--numbered", action="store_true",
                    help="(구) 번호 선택 방식으로 동작")
    ap.add_argument("--select", help="번호 선택 방식의 필드 번호 (예: 1,3,5)")
    ap.add_argument("--llm-name", action="store_true",
                    help="번호 방식에서 필드명을 LLM으로 자동 명명 (예시 방식은 기본 적용)")
    ap.add_argument("--recipe",
                    help="레시피 엑셀(.xlsx). 있으면 그 레시피로 '바로 재현', 없으면 "
                         "이번에 만든 파서를 저장. 재실행 시 자가 치유로 자동 갱신")
    ap.add_argument("--remember", action="store_true",
                    help="스키마를 JSON 캐시에 저장/재사용. 기본은 기억 안 함")
    ap.add_argument("--rediscover", action="store_true", help="(--remember 시) 스키마 다시 만들기")
    ap.add_argument("--pages", "--max-pages", type=int, default=None, dest="pages",
                    help="크롤링할 최대 페이지 수 (기본 1=현재 페이지만; 예: --pages 5). "
                         "레시피에 기록되어 재현 시 유지됨. 차단/무거운SPA는 이 값과 무관하게 1p")
    ap.add_argument("--scroll", action="store_true",
                    help="무한스크롤 사이트: 브라우저로 끝까지 스크롤해 모두 로드")
    ap.add_argument("--wait", type=int, default=0,
                    help="느린 SPA(항공/지도 등): 렌더/Save As 시 추가 대기 초 (예: --wait 30)")
    ap.add_argument("--chrome", action="store_true",
                    help="차단 감지 없이도 '내 진짜 크롬 Save As'로 강제 로드(무거운 SPA·안티봇용)")
    ap.add_argument("--csv", nargs="?", const="AUTO",
                    help="CSV로 저장(사이트별 파일, 재실행 시 append). 경로 생략 시 output/ 에 자동")
    ap.add_argument("--no-dedup", action="store_true",
                    help="(구) CSV 중복 제거 안 함 = --mode history 별칭")
    ap.add_argument("--mode", choices=["append", "history", "overwrite", "upsert"], default=None,
                    help="저장 방식: append(중복제외 추가·기본)/history(전량 누적·회차)/"
                         "overwrite(덮어쓰기·인기가요 등)/upsert(키로 제자리 갱신). "
                         "미지정 시 레시피에 기록된 방식 재현, 그것도 없으면 append")
    ap.add_argument("--batch", type=int, default=None,
                    help="수집 '회차' 번호(한 replay 세션이 공유). 미지정 시 _runs.csv 최대+1")
    ap.add_argument("--json", action="store_true", help="결과 JSON 출력")
    ap.add_argument("--no-images", action="store_true",
                    help="이미지 필드가 있어도 실제 이미지 파일을 내려받지 않음(URL/경로 열만 유지)")
    # CSV 체인 크롤링(목록 CSV 의 링크 열 → 각 상세페이지). target 이 .csv 면 자동 진입.
    ap.add_argument("--url-col", dest="url_col",
                    help="(CSV 체인) URL 이 담긴 컬럼명 (예: 직무_url). 생략 시 대화형/자동추정")
    ap.add_argument("--clean-url", dest="clean_url",
                    help="(CSV 체인) 1행 URL 을 정련한 예시. 지운 부분을 열 전체에 동일 적용")
    ap.add_argument("--limit", type=int, default=None,
                    help="(CSV 체인) 크롤링할 상세페이지 최대 개수 (테스트용)")
    ap.add_argument("--delay", type=float, default=15.0,
                    help="(CSV 체인) 상세페이지 요청 간 평균 대기(초) 숫자 하나. "
                         "기본 15(대형 사이트 기준). 값 주위로 자동 ±50%% 랜덤. "
                         "빨리 하려면 낮게(예: --delay 5)")
    args = ap.parse_args()

    # 레시피 로드: 파일이 있으면 텍스트 입력 없이 그대로 '재현'
    recipe_loaded, loaded_schema, loaded_url = False, None, ""
    if args.recipe and os.path.exists(args.recipe):
        try:
            loaded_schema, loaded_url = Schema.from_excel(args.recipe)
            recipe_loaded = True
            print("■ " + t("레시피 로드: {p}  (필드={f})", p=args.recipe, f=list(loaded_schema.fields)))
        except Exception as e:
            print("[" + t("경고") + "] " + t("레시피 읽기 실패({e}) → 새로 만듭니다.", e=e))

    if args.target or loaded_url:
        target = args.target or loaded_url          # 인자/레시피로 지정됨 → 안내 생략(비대화·start·replay)
    elif sys.stdin.isatty():
        target = _interactive_setup(args)           # 대화형: 로드→저장→주소 안내(save_as 를 처음부터)
    else:
        target = input(t("크롤링할 사이트 URL / HTML 경로 / 목록 CSV: ")).strip()
    if not target:
        print(t("대상이 지정되지 않았습니다."))
        sys.exit(1)

    # 편의: 프롬프트에 붙여넣은 대상 끝에 플래그(' --chrome', ' --wait 35',
    # ' --rediscover', ' --scroll' 등)가 섞여 있으면 argparse 를 안 거쳤어도
    # 여기서 떼어내 재적용한다. (PowerShell 에서 & 많은 URL 을 따옴표로 못 감싸
    # 프롬프트에 통째로 붙여넣는 경우 대응 — 특정 플래그만이 아니라 '전부' 처리.)
    #
    # ★ 불변식: 여기서 target 을 '깨끗한 URL' 로 만든 뒤에만 저장/기록에 쓴다.
    #   특히 --rediscover 같은 '일회성' 플래그는 절대 target 에 남으면 안 된다.
    #   (recipe url / _runs.csv 에 --rediscover 가 박히면, replay·스케줄러가 매번
    #    레시피를 지우고 재학습→비대화형 실패하는 '캐시 초기화 루프'가 됨.)
    #   → 이 strip 은 recipe_path_for / 레시피 저장 / runlog 보다 반드시 앞에 온다.
    if " --" in target:
        url_part, flag_part = target.split(" --", 1)
        flag_tokens = ("--" + flag_part).split()
        try:
            # 기존 args 네임스페이스에 덮어쓰기(인식 못한 토큰은 무시).
            ap.parse_known_args(flag_tokens, namespace=args)
            picked = [tok for tok in flag_tokens if tok.startswith("--")]
            print("  · " + t("(입력에서 플래그 인식) {flags}", flags=' '.join(picked)))
        except SystemExit:
            print("  · [" + t("경고") + "] " + t("입력 끝 플래그 해석 실패 → 무시: {flag}", flag=repr(flag_part)))
        target = url_part.strip()
    target = target.strip()

    # URL 칸에 예시 값을 붙여넣은 경우(@# 포함) 친절히 안내
    if "@#" in target:
        print("\n[" + t("안내") + "] " + t("URL 칸에 '예시 값'을 입력하신 것 같습니다."))
        print("  " + t("순서: ① 먼저 크롤링할 '목록 페이지'의 URL 만 입력"))
        print("        " + t("② 그 다음 값 입력 칸에서  제목@#가격@#회사  처럼 입력"))
        print("  · " + t("링크는 보통 제목에서 자동 추출됩니다(<필드>_url)."))
        print("    " + t("링크를 따로 원하면 값에 전체 URL(https://...)을 한 칸으로 넣으면 됩니다."))
        sys.exit(1)

    # CSV 체인 크롤링: target 이 실제 .csv 파일이면 '목록 → 상세페이지' 모드로 진입.
    #   (일반 URL/HTML 단일 페이지 흐름과 완전히 분리 — 여기서 끝난다.)
    if _looks_like_csv(target):
        from chain import run_chain_crawl   # 지연 import: chain 이 cli 를 import → 순환 회피
        run_chain_crawl(target, args)
        return

    # 사이트별 CSV 레시피 자동 로드 — 있으면 재연산(by-example/LLM) 없이 바로 재현.
    #   · 명시적 방식 요청(--example/--numbered/--select) 이나 --rediscover 면 건너뜀.
    #   · load_method=chrome 면(쿠팡 등) 처음부터 진짜 크롬으로 로드.
    user_chrome = bool(args.chrome)    # 사용자가 명시한 --chrome (레시피보다 우선)
    force_chrome = user_chrome          # --chrome: 차단 감지 없이도 내 크롬 Save As 강제
    force_render = False                # 레시피 load_method=render (JS-SPA) 재현용
    explicit = (args.example is not None) or args.numbered or (args.select is not None)
    auto_recipe_path = recipe_path_for(target)
    if not recipe_loaded and not explicit and os.path.exists(auto_recipe_path):
        if args.rediscover:
            os.remove(auto_recipe_path)
            print("■ " + t("레시피 재생성(--rediscover): 기존 {p} 삭제", p=auto_recipe_path))
        else:
            try:
                loaded_schema, _u, _lm, _wait, _pages = Schema.from_csv_recipe(auto_recipe_path)
                recipe_loaded = True
                # 사용자 --chrome 이 레시피 load_method 보다 우선. chrome 이 render 보다 우선.
                force_chrome = user_chrome or (_lm == "chrome")
                force_render = (_lm == "render") and not force_chrome
                if _wait and not args.wait:   # 레시피에 기록된 대기시간 복원(느린 SPA 재현)
                    args.wait = _wait
                if args.pages is None and _pages:   # 레시피에 기록된 페이지 수 복원
                    args.pages = _pages
                eff_lm = "chrome" if force_chrome else ("render" if force_render else _lm)
                override = t(" → {lm}(--chrome 우선)", lm=eff_lm) if eff_lm != _lm else ""
                print("■ " + t("CSV 레시피 로드: {p}", p=auto_recipe_path))
                print("  · " + t("필드={f}  로드방식={lm}{override}  대기={w}s  페이지={p}",
                                f=list(loaded_schema.fields), lm=_lm, override=override,
                                w=args.wait, p=(args.pages or 1)))
            except Exception as e:
                print("[" + t("경고") + "] " + t("CSV 레시피 읽기 실패({e}) → 새로 진행.", e=e))

    print("\n■ " + t("대상 : {target}", target=target))
    print("\n[1] " + t("DOM 로드 중..."))
    if args.scroll:
        print("  · " + t("스크롤 모드: 브라우저로 끝까지 스크롤하여 로드..."))
        dom = _playwright_fetch(target, scroll=True, settle_ms=args.wait * 1000)
        if dom is None:
            print("[" + t("에러") + "] " + t("스크롤 로드 실패(Playwright 필요). pip install playwright && python -m playwright install chromium"))
            sys.exit(2)
    else:
        dom = load_or_die(target, force_chrome=force_chrome, wait=args.wait,
                          force_render=force_render)
        _warn_if_spa(dom)

    # 드릴다운: 보드를 먼저 고르고, 그 보드 페이지로 들어가서 진행
    if args.boards and not recipe_loaded:
        print("[1.5] " + t("포털 → 보드 선택"))
        target = pick_board(dom, target, preset=args.board)
        print("\n■ " + t("들어간 보드 : {target}", target=target))
        print("[1.6] " + t("보드 페이지 로드 중..."))
        dom = load_or_die(target, force_chrome=force_chrome, wait=args.wait,
                          force_render=force_render)

    # 기본은 '기억 안 함'(매번 새로 입력). --remember 일 때만 JSON 캐시 사용.
    cache = None
    if args.remember and not recipe_loaded:
        cache = cache_path_for(target)
        if args.rediscover and os.path.exists(cache):
            os.remove(cache)
        print("■ " + t("캐시 : {cache}", cache=cache))

    eng = SelfHealingEngine(cache, verbose=True)
    parse_method, example_input = "recipe", ""   # 실행기록(_runs.csv)용

    if recipe_loaded:
        # 레시피로 바로 재현 (텍스트 입력 불필요). 깨진 부분은 추출 단계에서 자가 치유.
        eng.schema = loaded_schema
        parse_method = "recipe"
        # replay/recipe 로 돌려도 '무엇으로 크롤링했는지'가 _runs.csv 에 남도록,
        # 레시피에 저장된 필드별 예시값(참조 대상)을 복원해 기록한다(동일 레시피면 동일).
        example_input = "@#".join(
            v for v in (fs.get("example", "") for fs in loaded_schema.fields.values()
                        if not fs.get("attr")) if v)
        print("[2] " + t("레시피로 재현 → 바로 추출 (구조 바뀌면 자가 치유)"))
    elif args.example is not None:
        # by-example (비대화형): 눈으로 본 값 → 파서 역설계
        parse_method, example_input = "by-example", args.example
        print("[2] " + t("예시 값으로 파서 역설계 (by-example)"))
        dom = select_by_example(eng, dom, args.example, llm_name=True, target=target, wait=args.wait)
    elif args.numbered or args.select is not None:
        # (구) 번호 선택 방식
        parse_method = "numbered"
        print("[2] " + t("반복 구조 탐지 + 후보 필드 번호 선택"))
        discover_and_select(eng, dom, preset_select=args.select,
                            as_json=args.json, llm_name=args.llm_name)
    elif eng.schema is not None:
        # --remember 로 저장해둔 스키마가 있을 때만 (자가 치유 재실행)
        parse_method = "cache"
        print("[2] " + t("저장된 스키마 사용 → 바로 추출 (필요 시 자가 치유)"))
    else:
        # 기본: 보이는 값을 텍스트로 받아 by-example
        print("[2] " + t("원하는 한 항목의 값을 '보이는 대로' 입력하세요 (HTML 구조분석+LLM으로 파싱)."))
        print("    " + t("필드 구분은 @# 로 하세요 (숫자 쉼표 12,000 등과 안 겹침)."))
        print("    " + t("예) [삼성] 코엑스 7월4일 행사 알바 모집@#12,000@#강남구 삼성동"))
        pick_path = _pickable_html(target)   # save_as 스냅샷/로컬 HTML 이 있으면 마우스 피킹 가능
        prompt = "\n" + t("값 입력: ")
        if pick_path:
            print("    " + t("또는 'p' → 화면에서 마우스로 클릭해 값 고르기") + f" [{os.path.basename(pick_path)}]")
            print("       " + t("(클릭=텍스트 · Alt+클릭=링크 · Shift+클릭=이미지, '완료' 누르면 끝)"))
            prompt = "\n" + t("값 입력 (또는 'p'=클릭 피킹): ")
        ex = input(prompt).strip()
        pick_kinds = None   # 피킹일 때만 값별 종류(text/link/image) — 이미지 구조매칭용
        if pick_path and ex.lower() in ("p", "pick", "클릭"):
            from crawlers.picker import pick_from_html, picks_to_example, picks_kinds
            try:
                _picks = pick_from_html(pick_path, log=print)
                ex = picks_to_example(_picks)
                pick_kinds = picks_kinds(_picks)
            except RuntimeError as e:
                print("  · " + t("피커 실행 불가({e}) → 직접 입력하세요.", e=e))
                ex = input(prompt).strip()
            if ex:
                print("  → " + t("피킹된 예시값: {ex}", ex=ex))
        if not ex:
            print(t("입력 없음 — 종료."))
            sys.exit(0)
        parse_method, example_input = "by-example", ex
        dom = select_by_example(eng, dom, ex, llm_name=True, target=target,
                                wait=args.wait, kinds=pick_kinds)

    # 추출 (페이지네이션 순회 + dedup, 또는 스크롤 모드면 한 번)
    #   pages: 명시(--pages/레시피)면 그 값, 아니면 기본 1(현재 페이지만 = 안전).
    pages = args.pages if args.pages is not None else 1
    mode = t("스크롤") if args.scroll else (t("최대 {p}p", p=pages) if pages > 1 else "1p")
    print("\n[3] " + t("추출 ({mode}, dedup)", mode=mode))
    rows, url_field = crawl_all(eng, dom, target, pages, args.scroll)

    fields = list(eng.schema.fields.keys())
    print("\n=== " + t("추출 완료: {n}건, 필드={fields}", n=len(rows), fields=fields) + " ===")
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(rows, 1):
            line = " | ".join(f"{k}={r.get(k)}" for k in fields)
            print(f"{i:>3}. {line}")

    # 추출 품질 검사 — 자가치유가 차단/엉뚱한 페이지에 끌려가 망가지면 전부 None 이 된다.
    # 이런 비정상 결과로 '좋은 레시피'를 덮어쓰거나 결과 CSV를 더럽히지 않도록 가드.
    valid = _run_is_valid(rows, fields)
    # 채워졌더라도 형태가 레시피와 어긋나면(잘못된 치유) 저장 스킵 — 다음 단계(자동 재학습)의 트리거.
    if valid:
        sem_ok, sem_bad = _semantic_ok(rows, eng.schema)
        if not sem_ok:
            valid = False
            print("\n[" + t("가드") + "] " + t("값은 채워졌지만 '형태'가 레시피와 다릅니다(잘못된 치유 의심):"))
            for _n, _w, _r in sem_bad:
                print("    · " + t("필드 '{n}': {want} 형태 기대인데 {real} 만 일치", n=_n, want=_w, real=_r))
    # 차단/인증 페이지 결정적 감지(값싼) — 값이 验证/verify/robot 등으로 도배면 실제 데이터 아님.
    if valid and _looks_like_block(rows, fields):
        valid = False
        print("\n[" + t("가드") + "] " + t("추출 값이 차단/인증 페이지 특유의 텍스트(验证/verify/robot 등)입니다 → 저장 스킵."))
    # 최후 백스톱: 결과가 극소수(≤2)면 그때만 LLM 에 '실제 목록 vs 차단/오류'를 물어 확인.
    if valid and len(rows) <= 2 and not _llm_confirms_real(rows, fields):
        valid = False
        print("\n[" + t("가드") + "] " + t("결과가 너무 적고 LLM 확인 결과 '실제 목록이 아님(차단/오류)'으로 판정 → 저장 스킵."))
    recipe_csv = recipe_path_for(target)
    # 저장 방식(회차 포함) 결정: --mode > 레시피에 기록된 방식 > (--no-dedup=history) > append.
    recipe_mode = ""
    if os.path.exists(recipe_csv):
        try:
            recipe_mode = Schema.read_recipe_meta(recipe_csv).get("save_mode", "")
        except Exception:
            recipe_mode = ""
    save_mode = args.mode or recipe_mode or ("history" if args.no_dedup
                                             else crawl_config.default_save_mode())
    batch = args.batch if args.batch is not None else next_batch()
    # old(마지막 성공)/new(이번 시도) HTML 관리 — Save As 로 받은 파일이 있을 때만.
    new_html = saved_html_path_for(target)
    old_html = saved_html_old_path_for(target)
    # 자동 재학습(설정 AUTO_HEAL ON, 값싼 방법 실패 시): save_as 1회로 로컬 HTML 확보 → 전체 HTML LLM
    # 구조 파악 → ①+②검증 통과 시 채택(라이브 재fetch 없음·탐지 회피). 기본 OFF 라 평소 동작 불변.
    healed_via_saveas = False
    if not valid and _auto_heal_enabled():
        recovered, h_rows, h_fields, h_url = _auto_heal(eng, target, args)
        if recovered:
            rows, fields, url_field = h_rows, h_fields, h_url
            valid, healed_via_saveas = True, True
    if not valid:
        print("\n[" + t("가드") + "] " + t("추출 결과가 비정상(대부분 빈 값)입니다 → 결과/레시피 저장을 건너뜁니다."))
        print("  · " + t("기존 레시피를 보호합니다. 구조가 진짜 바뀐 거면: --rediscover 로 재학습하세요."))
        print("    " + t("(재학습: python cli.py \"{target}\" --rediscover)", target=target))
        if not _auto_heal_enabled():
            print("  · [" + t("안내") + "] " + t("심층 재학습(전체 HTML LLM 분석)이 꺼져 있어 '값싼 방법'까지만 분석했습니다."))
            print("    " + t("더 뚫어보려면 start.py → 설정 → LLM 공급자 설정 → 'd. 심층 재학습' 을 켜세요."))
        # 실패 HTML(new)은 그대로 두고, 지난 성공본(old)이 있으면 '비교' 안내.
        if os.path.exists(new_html) and os.path.exists(old_html):
            print("  · [" + t("비교") + "] " + t("잘 되던 사이트가 실패했다면 old(성공) vs new(실패) HTML 을 비교하세요:"))
            print("      " + t("old(성공): {p}", p=old_html))
            print("      " + t("new(실패): {p}", p=new_html))
        result_csv = None
    else:
        # ①' 이미지 아카이빙 — 이미지 필드(attr='src')가 있으면 그 원격 URL(또는 save_as 로컬 경로)을
        #     회차 폴더로 내려받아 오프라인 사본을 만들고 '<name>_file' 열을 붙인다. 크롬 save_as 는
        #     URL 을 버리지만 우리가 직접 받으면 URL↔파일이 정확히 짝지어지고 확장자도 보정된다.
        #     폴더 규칙: history=회차 폴더, append/upsert=dedup 누적, overwrite=비우고 새로.
        img_fields = [(n, f"{n}_file") for n, fs in eng.schema.fields.items()
                      if fs.get("attr") == "src"]
        if img_fields and not args.no_images and rows:
            out_dir = image_dir_for(target, save_mode, batch)
            image_archive.prepare_dir(out_dir, overwrite=(save_mode == "overwrite"))
            print("\n■ " + t("이미지 아카이빙 → {p}", p=out_dir))
            ref = target if str(target).startswith(("http://", "https://")) else ""
            sv, ru, fl = image_archive.archive_images(rows, img_fields, out_dir,
                                                      log=print, referer=ref)
            fields = [c for n in fields for c in ((n, f"{n}_file")
                      if (n, f"{n}_file") in img_fields else (n,))]  # url 뒤에 _file 삽입
            print("  · " + t("저장 {sv} · 재사용 {ru} · 실패 {fl}  (오프라인 경로를 '<필드>_file' 열에 기록)",
                            sv=sv, ru=ru, fl=fl))
        # 이식성: 이미지 관련 '로컬 절대경로'를 프로젝트 루트 기준 상대경로로(폴더 이동해도 CSV 가 안 깨짐).
        #         원격 URL(http)은 그대로 둔다.
        if img_fields:
            for row in rows:
                for uf, ff in img_fields:
                    for col in (uf, ff):
                        if row.get(col):
                            row[col] = rel_to_root(row[col])

        # ① 결과 CSV — 사이트명 기반 파일에 저장(재실행 시 append). 기본 자동 저장.
        result_csv = args.csv if (args.csv and args.csv != "AUTO") else csv_path_for(target)
        added, updated = save_csv(result_csv, rows, fields, mode=save_mode,
                                  url_field=url_field, batch=batch)
        upd = t(", 갱신 {u}건", u=updated) if updated else ""
        print("■ " + t("결과 CSV: {csv}  [{label}] 회차={batch} (추가 {added}건{upd})",
                       csv=result_csv, label=t(MODE_LABELS.get(save_mode, save_mode)),
                       batch=batch, added=added, upd=upd))

        # ② 레시피 CSV — '타격 위치(랜덤클래스 무관 구조경로)' + 로드방식 자동 저장/갱신.
        #    학습 때 브라우저 렌더링이 필요했으면(RENDER_REQUIRED) load_method=render 로
        #    저장해, 재현 때도 정적이 아니라 렌더링으로 로드하게 한다(YouTube 등).
        if healed_via_saveas:
            # 재학습은 save_as 로 뚫었다 → 로드 방식을 고정(대화형이면 save_as vs auto 질문).
            save_lm = _ask_load_method(args, default="chrome")
        else:
            save_lm = ("render" if (loader.RENDER_REQUIRED and loader.LAST_LOAD_METHOD == "auto")
                       else loader.LAST_LOAD_METHOD)
        try:
            eng.schema.save_csv_recipe(recipe_csv, url=target,
                                       load_method=save_lm, wait=args.wait, pages=pages,
                                       extra_meta={"save_mode": save_mode})
            verb = t("갱신") if recipe_loaded else t("저장")
            print("■ " + t("레시피 CSV {verb}: {csv}  (다음 실행 시 자동 재현, 로드방식={lm}, 대기={w}s, 페이지={p})",
                           verb=verb, csv=recipe_csv, lm=save_lm, w=args.wait, p=pages))
        except Exception as e:
            print("[" + t("경고") + "] " + t("레시피 CSV 저장 실패: {e}", e=e))

        # ③ 성공한 HTML(new)을 old(마지막 성공본)로 승격 → 다음에 실패하면 비교 기준.
        if os.path.exists(new_html):
            try:
                import shutil
                shutil.copy2(new_html, old_html)
                print("■ " + t("성공 HTML 보관(old): {p}", p=old_html))
            except Exception as e:
                print("[" + t("경고") + "] " + t("old HTML 보관 실패: {e}", e=e))

    # (옵션) 엑셀 레시피도 --recipe 로 명시하면 함께 저장
    if args.recipe:
        try:
            eng.schema.save_excel(args.recipe, url=target)
            print("■ " + t("엑셀 레시피 저장: {p}", p=args.recipe))
        except Exception as e:
            print("[" + t("경고") + "] " + t("엑셀 레시피 저장 실패: {e}", e=e))

    # ③ 실행 기록 — 이번 실행을 '녹화하듯' _runs.csv 에 append (성공/실패 포함).
    try:
        append_runlog(target, "success" if valid else "fail",
                      loader.LAST_LOAD_METHOD, parse_method, example_input,
                      fields, len(rows), rel_to_root(result_csv), rel_to_root(recipe_csv),
                      batch=batch, save_mode=save_mode)
        print("■ " + t("실행 기록: {p}  (status={s})", p=RUNLOG_PATH, s=('success' if valid else 'fail')))
    except PermissionError:
        print("[" + t("경고") + "] " + t("실행 기록 실패: '{p}' 가 잠겨 있습니다.", p=RUNLOG_PATH))
        print("  · " + t("엑셀/편집기에서 _runs.csv 를 '닫고' 다시 실행하세요(열려 있으면 기록 못 함)."))
    except Exception as e:
        print("[" + t("경고") + "] " + t("실행 기록 실패: {e}", e=e))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
MODULE_NAME: loader.py
PURPOSE: 'DOM 획득' 계층 — URL/파일을 로드하되 안티봇 차단 감지 시 '내 크롬 Save As'로 자동 전환하고,
         JS-SPA 는 렌더링으로, 레시피 load_method=chrome/render 는 처음부터 그 경로로 받는다. cli(단발)와
         chain(체인) 두 진입점이 '둘 다' 쓰므로 공통 모듈로 둔다(chain 이 cli 갓-모듈을 통째로 끌어오던 결합 해소).
  ★가변 상태 계약: smart_load 가 LAST_LOAD_METHOD/BLOCK_DETECTED 를, 학습 흐름이 RENDER_REQUIRED 를
   '실행 중' 갱신한다. 읽는 쪽(cli.crawl_all/레시피저장, chain)은 반드시 loader.<이름> 으로 '실시간' 참조
   할 것(값 복사 금지) — 복사하면 갱신 전 값을 쓰게 된다.
DEPENDENCY: engine.load_dom · crawlers(static/dynamic/chrome/base) · paths. cli/chain 을 import 하지 않는다.
"""
from __future__ import annotations

import sys

from engine import load_dom
from crawlers.dynamic import playwright_fetch as _playwright_fetch
from crawlers.chrome import chrome_save_as_fetch
from crawlers.base import block_reason
from paths import saved_html_path_for
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)


def _playwright_installed():
    import importlib.util
    return importlib.util.find_spec("playwright") is not None


def _warn_if_spa(dom):
    """정적 HTML에 내용이 거의 없으면(=JS 렌더링 SPA) Playwright 설치를 안내."""
    if _playwright_installed():
        return  # 이미 렌더링됨
    n_a = sum(1 for _ in dom.iter("a"))
    if n_a < 5:
        print("\n⚠  " + t("이 페이지는 JavaScript로 데이터를 그리는 SPA로 보입니다"))
        print("   " + t("(정적 HTML에 링크/내용이 거의 없음 → 값을 못 찾습니다)."))
        print("   " + t("Playwright를 설치하면 브라우저 렌더링 후 크롤링됩니다:"))
        print("     pip install playwright")
        print("     python -m playwright install chromium\n")


# 직전 로드가 어떤 경로였는지 기록(레시피에 load_method 로 저장하기 위함).
LAST_LOAD_METHOD = "auto"
# 이 실행에서 '봇 차단'이 한 번이라도 감지됐는가. True 면 (어떤 경로로 페이지를
# 얻었든) 페이지네이션을 하지 않는다 — 차단 사이트는 무조건 1페이지.
BLOCK_DETECTED = False
# 학습 중 '정적 HTML엔 값이 없어 브라우저 렌더링이 필요했는가'(YouTube 등 JS-SPA).
# True 면 레시피 load_method 를 'render' 로 저장 → 재현 때도 정적이 아니라 렌더링.
RENDER_REQUIRED = False


def smart_load(target, scroll=False, force_chrome=False, wait=0, force_render=False):
    """URL 로드. 안티봇 '차단 페이지'가 감지되면 '내 크롬 Save As'로 자동 전환.

    쿠팡처럼 봇을 막는 사이트는 정적/헤드리스로는 차단 안내 페이지만 돌아온다.
    block_reason 으로 감지하면, 내 진짜 크롬으로 페이지를 열고 Ctrl+S(다른 이름으로
    저장)를 자동 집행해 받은 HTML 을 쓴다. (Chrome 136+ 가 실제 프로필 디버그를 막아
    CDP 는 불가 → Save As 가 내 세션을 쓰는 유일한 길. output/saved/ 에 저장)

    force_chrome=True(레시피 load_method=chrome) 면 차단 페이지를 받느라 헛걸음하지
    않고 처음부터 Save As 로 받는다.
    """
    global LAST_LOAD_METHOD, BLOCK_DETECTED
    is_url = str(target).startswith(("http://", "https://"))
    load_wait = 10.0 + max(0, wait)   # 느린 SPA 는 --wait 로 로드 대기 연장
    tried_saveas = False     # Save As 는 한 실행에서 '한 번만' (중복 크롬 오픈 방지)

    # 레시피 load_method=render (JS-SPA: YouTube 등) → 정적 fetch 를 건너뛰고
    # 처음부터 브라우저 렌더링. (정적 HTML 에 a 태그가 우연히 많아 load_dom 이
    # 렌더링을 생략하고 껍데기만 파싱하는 것을 방지.)
    if force_render and is_url and not force_chrome:
        print("  · " + t("JS-SPA(render) → 브라우저 렌더링으로 로드")
              + (t(" (+{w}s 대기)", w=wait) if wait else "") + "...")
        rdom = _playwright_fetch(target, scroll=scroll, settle_ms=wait * 1000)
        if rdom is not None:
            LAST_LOAD_METHOD = "render"
            return rdom
        print("  · " + t("렌더링 실패 → 일반 경로로 폴백."))
    if force_chrome and is_url:
        BLOCK_DETECTED = True   # 레시피 chrome/--chrome = 차단·무거운SPA → 무조건 1페이지
        print("  · " + t("내 크롬 'Save As'로 곧장 수신 (로드 대기 {s}s)...", s=f"{load_wait:.0f}"))
        tried_saveas = True
        cdom = chrome_save_as_fetch(target, saved_html_path_for(target),
                                    log=print, load_wait=load_wait)
        if cdom is not None and not block_reason(cdom):
            LAST_LOAD_METHOD = "chrome"
            return cdom
        print("  · " + t("Save As 실패 → 일반 경로 확인(추가 Save As 는 안 함)."))

    dom = load_dom(target)
    LAST_LOAD_METHOD = "auto"
    if not is_url:
        return dom
    reason = block_reason(dom)
    if not reason:
        return dom
    BLOCK_DETECTED = True   # 차단 감지됨 → 이후 페이지네이션 금지(1페이지만)
    if tried_saveas:
        # 이미 이번 실행에서 Save As 를 시도(실패)했다 → 또 열지 않는다(중복 방지).
        print("  · " + t("이미 Save As 시도 실패 → 차단 페이지 그대로 반환(크롬 재오픈 안 함)."))
        return dom
    print("  · " + t("봇 차단 감지({reason})", reason=reason))
    print("  · " + t("→ 내 크롬으로 'Save As' 자동 수신 (로드 대기 {s}s, 마우스 0번)...", s=f"{load_wait:.0f}"))
    cdom = chrome_save_as_fetch(target, saved_html_path_for(target),
                                log=print, load_wait=load_wait)
    if cdom is None:
        print("  · " + t("Save As 자동 수신 실패 → 원래(차단) 결과 사용. 크롬 창을 맨 앞에 두고 다시 시도하세요."))
        return dom
    if block_reason(cdom):
        print("  · " + t("Save As 했지만 여전히 차단 페이지 → 원래 결과 사용."))
        return cdom
    print("  · " + t("Save As 수신 성공"))
    LAST_LOAD_METHOD = "chrome"
    return cdom


def load_or_die(target, scroll=False, force_chrome=False, wait=0, force_render=False):
    try:
        return smart_load(target, scroll=scroll, force_chrome=force_chrome,
                          wait=wait, force_render=force_render)
    except Exception as e:
        print("[" + t("에러") + "] " + t("사이트 로드 실패: {e}", e=e))
        print("  · " + t("JS 렌더링 사이트면: pip install playwright && python -m playwright install chromium"))
        sys.exit(2)

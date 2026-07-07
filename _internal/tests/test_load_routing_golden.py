# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_load_routing_golden.py
PURPOSE: 로드 전략의 핵심 '라우팅 결정' 골든 — smart_load 가 안티봇 차단 페이지를 감지하면 '내 크롬
         Save As' 로 자동 전환하고(LAST_LOAD_METHOD='chrome', BLOCK_DETECTED=True), 차단이 아니면
         정적('auto') 결과를 그대로 쓰며 크롬을 열지 않는지를 결정적으로 못박는다.
DEPENDENCY: lxml. 네트워크/브라우저 없이 fetch 심(load_dom/chrome_save_as_fetch)을 모킹해 라우팅만 검증.

[검증된 주요 사이트 및 케이스]
- 쿠팡류 차단('just a moment' 등) → chrome_save_as_fetch 경로로 라우팅.
- block_reason 판정 자체는 test_crawlers_chrome 가, 여기서는 '판정→라우팅' 결정을 고정.

[테스트/운영 교훈]
- 차단 감지 시 BLOCK_DETECTED=True 로 이후 페이지네이션을 금지(1페이지) — 차단 페이지 오염 방지.
"""
import os
import sys
import io
import contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html as H
import cli
import loader

# 안티봇 차단 페이지(제목 시그니처) vs 정상 페이지(길고 시그니처 없음).
_BLOCKED = H.fromstring("<html><head><title>Just a moment...</title></head>"
                        "<body>Checking your browser (cloudflare)</body></html>")
_CLEAN = H.fromstring("<html><head><title>상품 목록</title></head><body>"
                      + "정상 콘텐츠 " * 200 + "</body></html>")


def _run_smart_load(load_dom_ret, chrome_ret):
    """load_dom/chrome_save_as_fetch 를 모킹해 smart_load 를 돌리고, 결과와 크롬 호출여부·전역을 반환."""
    orig_load = loader.load_dom
    orig_chrome = loader.chrome_save_as_fetch
    orig_lm, orig_blk = loader.LAST_LOAD_METHOD, loader.BLOCK_DETECTED
    calls = []
    try:
        loader.load_dom = lambda t: load_dom_ret
        loader.chrome_save_as_fetch = lambda *a, **k: (calls.append(1), chrome_ret)[1]
        loader.LAST_LOAD_METHOD, loader.BLOCK_DETECTED = "auto", False
        with contextlib.redirect_stdout(io.StringIO()):   # smart_load 로그 억제
            out = loader.smart_load("https://example.com/list")
        return out, calls, loader.LAST_LOAD_METHOD, loader.BLOCK_DETECTED
    finally:
        loader.load_dom, loader.chrome_save_as_fetch = orig_load, orig_chrome
        loader.LAST_LOAD_METHOD, loader.BLOCK_DETECTED = orig_lm, orig_blk


def test_block_detected_routes_to_chrome():
    """[역할] 정적 결과가 차단 페이지면 → 크롬 Save As 로 전환, load_method=chrome, BLOCK_DETECTED=True."""
    out, calls, lm, blk = _run_smart_load(load_dom_ret=_BLOCKED, chrome_ret=_CLEAN)
    assert out is _CLEAN, "차단 감지 시 크롬 수신 결과를 써야 함"
    assert calls == [1], "chrome_save_as_fetch 가 정확히 한 번 호출돼야 함"
    assert lm == "chrome"
    assert blk is True


def test_clean_page_stays_auto_no_chrome():
    """[역할] 차단이 아니면 정적('auto') 결과 그대로, 크롬을 열지 않음."""
    out, calls, lm, blk = _run_smart_load(load_dom_ret=_CLEAN, chrome_ret=_CLEAN)
    assert out is _CLEAN
    assert calls == [], "정상 페이지는 크롬을 열면 안 됨"
    assert lm == "auto"
    assert blk is False


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_crawlers_dynamic.py
PURPOSE: Phase 2 슬라이스2 고정 — 렌더링 전략(playwright_fetch)이 crawlers.dynamic 으로 분리되고
         engine.load_dom(폴백)과 cli(강제 렌더/스크롤)가 그것을 '위임'하는지(배선) 확인.
DEPENDENCY: 없음(표면/배선만 확인 — 실제 브라우저 미기동, 네트워크 불필요).

[검증된 주요 사이트 및 케이스]
- 해당 없음(구조 슬라이스). 실제 렌더는 SPA 실사이트 스모크로 별도 확인.

[테스트/운영 교훈]
- playwright 미설치 환경에서도 playwright_fetch 는 None 을 반환해야(폴백) — 코드상 ImportError 처리.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_dynamic_surface():
    """[역할] crawlers.dynamic 이 임포트되고 playwright_fetch 심이 실재하는지."""
    import crawlers.dynamic as dynamic
    assert callable(dynamic.playwright_fetch)


def test_engine_delegates_playwright():
    """[역할] engine 이 자체 _playwright_fetch 를 버리고 crawlers.dynamic.playwright_fetch 를 쓰는지."""
    import engine
    import crawlers.dynamic as dynamic
    assert engine.playwright_fetch is dynamic.playwright_fetch, "engine 이 crawlers.dynamic 을 위임해야 함"
    assert not hasattr(engine, "_playwright_fetch"), "engine 에 옛 _playwright_fetch 가 남아있음"


def test_cli_uses_dynamic_playwright():
    """[역할] cli 의 렌더 호출이 crawlers.dynamic.playwright_fetch 로 배선됐는지."""
    import cli
    import crawlers.dynamic as dynamic
    assert cli._playwright_fetch is dynamic.playwright_fetch, "cli 가 crawlers.dynamic 을 써야 함"


def test_engine_no_longer_imports_ua():
    """[역할] 렌더 이관 후 engine 이 더는 _UA 를 직접 들이지 않는지(수집 관심사 완전 이전) 고정."""
    import engine
    assert not hasattr(engine, "_UA"), "engine 에 _UA 가 남아있음(수집 관심사 잔존)"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

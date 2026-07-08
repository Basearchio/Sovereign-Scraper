# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/dynamic.py
PURPOSE: 동적/JS 렌더링 수집 전략 — 헤드리스 Playwright(Chromium)로 페이지를 렌더한 뒤 DOM 을 반환.
         정적 fetch 가 비어 나오는 SPA(무신사 등)나 무한스크롤/느린 스트리밍 SPA(항공/지도)를 담당.
DEPENDENCY: lxml(필수), playwright(선택; 미설치/실패 시 None → 호출부가 정적 결과로 폴백).

[검증된 주요 사이트 및 케이스]
- musinsa 류 SPA: load_dom 이 정적 결과의 a 태그가 적으면 이 경로로 자동 렌더.
- 무한스크롤: scroll=True 로 반복 스크롤. 종료 조건은 '바닥 도달'(높이 정체, 조기 종료) OR
  '시간 예산 소진'(scroll_seconds) 중 먼저 오는 쪽. 횟수 상한(구 max_scrolls) 대신 시간 상한을
  쓰는 이유는 순수하게 기술적 문제 때문 — SNS류 피드는 스크롤할수록 계속 새 콘텐츠가 생겨
  높이가 영원히 정체되지 않을 수 있어, 횟수 기반으로는 자연스러운 종료 시점을 잡을 수 없다.
  차단 페이지가 뜨면(block_reason) 그 즉시 멈추고 물러난다 — 스크롤은 막힌 걸 뚫는 수단이
  아니라, 막히지 않은 동안 로딩을 기다리는 수단일 뿐이다.
- 느린 SPA(항공/지도): settle_ms 로 networkidle 후 추가 대기.

[테스트/운영 교훈]
- networkidle 은 '짧게+비치명적'으로: 광고/트래커 때문에 영영 idle 에 도달 못하는 사이트가 많다.
- UA 는 crawlers.base._UA 공용(정적/렌더가 같은 지문) → 사이트가 다르게 응답하는 것 방지.
- 모든 예외는 삼켜 None → '렌더 실패 = 정적 결과라도 반환' 폴백을 단순 유지.
"""
from __future__ import annotations

from lxml import html as lxml_html
from lxml.html import HtmlElement

from crawlers.base import _UA


def playwright_fetch(url: str, scroll: bool = False, scroll_seconds: float = 15.0,
                     settle_ms: int = 0):
    """
    [사용처/협력자] engine.load_dom 의 SPA 폴백, cli 의 강제 렌더(--render)·스크롤 경로.
      하부는 playwright.sync_api. 실패/미설치 시 None → 호출부가 정적 결과로 폴백.
    [역할] 헤드리스 브라우저 렌더링 후 DOM. scroll/settle_ms 로 무한스크롤·느린 SPA 대응.
      scroll_seconds: 스크롤을 계속할 최대 시간(초). 바닥에 닿아 높이가 정체되면 그 전에도
      조기 종료 — '끝까지'가 아니라 '시간 예산 안에서 최대한'이 목표.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import time
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_UA)
            # domcontentloaded 로 빠르게 진입 후 networkidle 은 '짧게+비치명적'
            # (광고/트래커로 networkidle 에 영영 도달 못하는 사이트가 많음).
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            if settle_ms > 0:        # 느린 SPA: 콘텐츠가 다 그려질 때까지 추가 대기
                page.wait_for_timeout(settle_ms)
            if scroll:
                prev_h = -1
                deadline = time.monotonic() + scroll_seconds
                while time.monotonic() < deadline:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(900)
                    h = page.evaluate("document.body.scrollHeight")
                    if h == prev_h:        # 더 안 늘어나면 끝까지 로드된 것
                        break
                    prev_h = h
            content = page.content()
            browser.close()
        return lxml_html.fromstring(content)
    except Exception:
        return None

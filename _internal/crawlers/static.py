# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/static.py
PURPOSE: 정적/SSR 페이지 수집 전략 — requests(있으면) 또는 urllib 로 HTML 을 받아 lxml DOM 으로.
         대부분의 사이트(saramin/albamon/incruit/ruliweb/HN 등)를 ~1초에 로드하는 1차 경로.
DEPENDENCY: lxml(필수), requests(선택; 없으면 urllib 폴백).

[검증된 주요 사이트 및 케이스]
- saramin/albamon/incruit(정적/SSR): auto 로드의 1차 경로로 안정 수집.
- 실패(네트워크/타임아웃/차단 응답 등) 시 None → 호출부(engine.load_dom)가 렌더 경로로 폴백.

[테스트/운영 교훈]
- bytes 로 파싱(lxml_html.fromstring(r.content))해야 인코딩 자동감지가 된다(한글 깨짐 방지).
- 예외는 전부 삼켜 None 반환 → '정적 실패 = 렌더 시도' 폴백 흐름을 단순하게 유지.
"""
from __future__ import annotations

from lxml import html as lxml_html

from crawlers.base import default_headers


def static_fetch(url: str):
    """
    [사용처/협력자] engine.load_dom 의 1차 경로(정적 우선). 실패 시 load_dom 이 dynamic 으로 폴백.
    [역할] 정적 HTML fetch (requests > urllib). 성공 시 lxml DOM, 실패 시 None.
    """
    headers = default_headers()
    try:
        try:
            import requests
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            return lxml_html.fromstring(r.content)   # bytes → 인코딩 자동감지
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return lxml_html.fromstring(resp.read())
    except Exception:
        return None

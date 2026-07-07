# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/__init__.py
PURPOSE: 수집(fetch/load) 전략 계층(leaf) 패키지. 사이트 성격별 로드방식을 전략 패턴으로 분리한다.
         static(정적/SSR) · dynamic(Playwright 렌더/스크롤) · chrome(pywin32 Save As) 순으로 이관.
DEPENDENCY: 하위 모듈이 각자의 외부 라이브러리(requests/lxml/playwright/pywin32)를 지연 import.

[계층 규율] 이 계층은 내부 모듈(cli/engine)을 import 하지 않는다(engine → crawlers 단방향).
"""

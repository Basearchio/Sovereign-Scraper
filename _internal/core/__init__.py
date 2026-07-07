# -*- coding: utf-8 -*-
"""
MODULE_NAME: core/__init__.py
PURPOSE: 도메인 핵심 데이터 계층(leaf) 패키지. 엔진/컨트롤러가 공유하는 '데이터 계약'을 담는다.
         현재: schema(추출 스키마·레시피 직렬화). DOM 조작/네트워크 없음 — 순수 데이터/직렬화.
DEPENDENCY: 표준 라이브러리(json/csv/dataclasses) + 선택적 openpyxl(엑셀 레시피).

[계층 규율] 이 계층은 내부 상위 모듈(engine/cli/crawlers/llm_locators)을 import 하지 않는다
            (engine → core 단방향). 순수 값·직렬화만 다룬다.
"""

# -*- coding: utf-8 -*-
"""
MODULE_NAME: services/__init__.py
PURPOSE: 외부 시스템 연동 서비스 계층(leaf) 패키지. 현재 llm_service(LM Studio) 를 담는다.
DEPENDENCY: 없음(하위 모듈이 각자의 외부 라이브러리를 지연 import).

[규율] 이 계층은 내부 모듈(cli/engine/crawlers)을 import 하지 않는다(순환 의존 차단).
       평범한 타입(문자열/리스트/딕트)으로만 대화한다 — lxml 노드를 경계 밖으로 넘기지 않음.
"""

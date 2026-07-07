# -*- coding: utf-8 -*-
"""
MODULE_NAME: hooks.py
PURPOSE: 의미 기반 재배치/구조 파악의 '주입 레지스트리' leaf — LLM 구현을 런타임에 주입받는 심(shim).
         engine(자가치유)과 locators(예시 기반 위치탐색)가 '둘 다' 최후 폴백으로 이 훅을 부르므로,
         엔진·로케이터 어느 쪽에도 두지 않고 공통 leaf 로 둔다(두 상위 계층을 서로 모르게 = 진짜 탈결합).
DEPENDENCY: 없음(순수 함수·전역만). llm/engine/cli/lxml 를 import 하지 않는다(leaf, LLM-FREE 보증).

  · 기본값 None → 훅 비활성(구조/휴리스틱만으로 정상 동작).
  · cli 시작 시 set_relocator(llm_locators.relocate) / set_structure_discoverer(discover_structure) 배선.
"""
from __future__ import annotations

_RELOCATOR = None


def set_relocator(fn):
    """[사용처] cli 시작 배선. [역할] 자가치유의 '의미 기반 재배치자'(보통 LLM)를 주입. None 이면 비활성."""
    global _RELOCATOR
    _RELOCATOR = fn


def _relocate(row, name, example):
    """[사용처] locators.locate_by_example/locate_single_record, engine._heal_field 의 최후 폴백.
    [역할] 주입된 재배치자를 호출(미설정 시 None) — 상위 계층이 LLM 을 직접 모르게 하는 심."""
    return _RELOCATOR(row, name, example) if _RELOCATOR is not None else None


_STRUCTURE_DISCOVERER = None


def set_structure_discoverer(fn):
    """[사용처] cli 시작 배선. [역할] '로컬 HTML + 기존 필드명/예시 → 구조(레시피 재료)'를 파악하는
    최후 재학습자(보통 LLM)를 주입. None 이면 비활성."""
    global _STRUCTURE_DISCOVERER
    _STRUCTURE_DISCOVERER = fn


def _discover_structure(dom, field_names, examples):
    """[사용처] engine.recalibrate — 모든 값싼 경로가 실패한 뒤의 자동 재학습.
    [역할] 주입된 구조 파악자를 호출(미설정 시 None). dom 은 save_as 로 받은 '로컬 HTML'(라이브 무접촉)."""
    return (_STRUCTURE_DISCOVERER(dom, field_names, examples)
            if _STRUCTURE_DISCOVERER is not None else None)

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_engine_llm_free.py
PURPOSE: 불변식 강제 — engine.py 는 LLM 을 직접 import/호출하지 않는다(LLM-FREE). engine 상단
         선언이 '주석'이 아니라 '테스트로 지켜지는 계약'이 되게 한다. 누가 engine 에 llm 을
         다시 끌어들이면 이 테스트가 빨개진다.
DEPENDENCY: 없음(engine 소스 텍스트 스캔 + 훅 동작만 확인). 네트워크/LLM 불필요.

[검증된 주요 사이트 및 케이스]
- 해당 없음(구조 불변식). Phase 1b 의 핵심 계약을 지킨다.

[테스트/운영 교훈]
- 경계(boundary)는 문서가 아니라 테스트로 지켜야 한다. import 한 줄이 슬쩍 들어오면
  '주석 선언'은 거짓말이 되지만, 이 테스트는 그 순간 실패한다.
- 자가치유의 '의미 기반 재배치'는 engine 이 직접 아는 게 아니라 '주입된 훅'으로만 동작한다:
  훅 미설정(None) → 구조/휴리스틱만(정상), 훅 설정 → 그 구현 호출.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ENGINE_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine.py")


def test_engine_source_has_no_llm_import():
    """[역할] engine.py 의 import 문 중 'llm'(llm/llm_service/llm_locators)을 들이는 게 있으면 FAIL."""
    offenders = []
    with open(_ENGINE_PY, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if re.match(r"^(import|from)\s", s) and "llm" in s.lower():
                offenders.append(f"{i}: {s}")
    assert not offenders, "engine 이 LLM 계층을 import 함(불변식 위반):\n" + "\n".join(offenders)


def test_engine_no_longer_defines_llm_functions():
    """[역할] 이관된 LLM 함수가 engine 에 남아있지 않은지(중복/혼선 방지) 고정."""
    import engine
    for name in ("llm_relocate", "locate_by_example_llm", "llm_name_fields", "llm_next_url"):
        assert not hasattr(engine, name), f"engine 에 {name} 가 아직 남아있음(이관 누락)"


def test_engine_exposes_relocator_hook():
    """[역할] engine 이 재배치 훅 심(set_relocator/_relocate)을 제공하는지 고정."""
    import engine
    assert callable(engine.set_relocator)
    assert callable(engine._relocate)


def test_relocate_hook_behavior():
    """[역할] 훅 미설정 시 None(휴리스틱만), 설정 시 그 구현을 호출하는지 고정.
    (훅 상태는 hooks.py leaf 에 있고 engine 은 set_relocator/_relocate 를 재-export 한다.)"""
    import engine
    import hooks
    old = hooks._RELOCATOR
    try:
        engine.set_relocator(None)
        assert engine._relocate("ROW", "field", "example") is None
        engine.set_relocator(lambda row, name, ex: ("HIT", row, name, ex))
        assert engine._relocate("ROW", "field", "ex") == ("HIT", "ROW", "field", "ex")
    finally:
        engine.set_relocator(old)   # 다른 테스트에 영향 주지 않도록 원복


def test_engine_exposes_structure_discoverer_hook():
    """[역할] 자동 재학습의 최후 폴백 훅(set_structure_discoverer/_discover_structure) 제공 고정."""
    import engine
    assert callable(engine.set_structure_discoverer)
    assert callable(engine._discover_structure)


def test_structure_discoverer_hook_behavior():
    """[역할] 훅 미설정 시 None(재학습 비활성), 설정 시 로컬 HTML+필드명+예시로 호출되는지 고정."""
    import engine
    import hooks
    old = hooks._STRUCTURE_DISCOVERER
    try:
        engine.set_structure_discoverer(None)
        assert engine._discover_structure("<html>", ["가격"], {"가격": "12,000"}) is None
        engine.set_structure_discoverer(lambda html, names, ex: ("HIT", html, names, ex))
        assert engine._discover_structure("<html>", ["가격"], {"가격": "12,000"}) == (
            "HIT", "<html>", ["가격"], {"가격": "12,000"})
    finally:
        engine.set_structure_discoverer(old)   # 원복


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_smoke_imports.py
PURPOSE: 리팩터(Phase 1: LLM 서비스 모듈 분리) 안전망 — 핵심 모듈이 임포트되고
         LLM 공개 표면(callable)이 실재하는지 최소 보장. 모듈 배선이 안 끊겼나만 본다.
DEPENDENCY: lxml (engine 임포트에 필요). 네트워크/LLM 서버/브라우저 불필요.

[검증된 주요 사이트 및 케이스]
- 해당 없음(구조 스모크). 사이트 픽스처를 쓰지 않는다.

[테스트/운영 교훈]
- `_extract_single` 미정의 사건: 새 경로가 '임포트는 되는데 실제 함수가 없음'으로 잠복 가능.
  → 임포트 + callable 존재 확인으로 그 부류(미정의 참조)를 즉시 잡는다.
- Phase 1a 에서 llm.py → services/llm_service.py 로 이동하면, 아래 LLM_TRANSPORT 임포트만
  갱신하면 된다(그때 이 파일이 '무엇이 어디로 갔는지'의 단일 기준점이 된다).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hooks


def test_core_modules_import():
    """[역할] engine/cli/replay 와 서비스·오케스트레이션 계층이 에러 없이 임포트되는지 확인."""
    import engine                       # noqa: F401
    import services.llm_service         # noqa: F401  (Phase 1a: 전송 정식 위치)
    import llm_locators                 # noqa: F401  (Phase 1b: DOM+LLM 오케스트레이션)
    import paths                        # noqa: F401  (Phase 4b: 경로 규칙 leaf)
    import runlog                       # noqa: F401  (Phase 4c: 감사로그·계층번호 leaf)
    import cli                          # noqa: F401
    import chain                        # noqa: F401  (Phase 4a: 체인 크롤링 컨트롤러)
    import replay                       # noqa: F401


def test_llm_transport_surface():
    """[역할] LLM 전송 계층(services.llm_service)의 공개 함수가 callable 로 실재하는지 고정."""
    import services.llm_service as svc
    for name in ("chat", "ask", "ask_json", "available"):
        assert callable(getattr(svc, name, None)), f"llm_service.{name} 가 없음/비호출"


def test_llm_backward_compat_shim():
    """[역할] Phase 1a 이후에도 기존 `import llm` 이 같은 함수를 재-export 하는지 보장."""
    import llm
    import services.llm_service as svc
    for name in ("chat", "ask", "ask_json", "available"):
        assert getattr(llm, name, None) is getattr(svc, name), f"llm.{name} 재-export 불일치"


def test_llm_orchestration_surface():
    """[역할] LLM 오케스트레이션(llm_locators)의 함수가 실재하는지 고정(Phase 1b: engine→llm_locators)."""
    import llm_locators
    for name in ("relocate", "locate_by_example_llm", "llm_name_fields", "llm_next_url"):
        assert callable(getattr(llm_locators, name, None)), f"llm_locators.{name} 가 없음/비호출"


def test_relocator_hook_wired():
    """[역할] cli 가 engine 에 재배치 훅을 주입했는지(hooks._RELOCATOR 설정) 고정."""
    import cli          # noqa: F401  (import 시 set_relocator 실행)
    import engine
    import llm_locators
    assert hooks._RELOCATOR is llm_locators.relocate, "cli 가 relocate 훅을 주입해야 함"


def test_chain_and_numbering_surface():
    """[역할] 체인·계층번호 진입점이 실재하는지 고정. Phase 4a: 체인 실행은 chain.py,
    dispatch/번호매기기는 cli 유지."""
    import cli
    import chain
    for name in ("assign_run_numbers", "chain_recipe_path_for",
                 "_looks_like_csv", "_is_chain_target"):
        assert callable(getattr(cli, name, None)), f"cli.{name} 가 없음/비호출"
    for name in ("run_chain_crawl", "_derive_url_cleaner", "_inline_iframes",
                 "_build_detail_schema_by_css"):
        assert callable(getattr(chain, name, None)), f"chain.{name} 가 없음/비호출"


def test_chain_no_circular_import():
    """[역할] cli↔chain 순환이 실제로 안 나는지(양쪽 import 성공)와 가변 전역 실시간 참조 배선 확인."""
    import cli
    import chain
    assert chain.load_or_die is cli.load_or_die      # 안정 헬퍼는 바인딩 공유
    assert chain.cli is cli                           # 가변 전역은 cli.<name> 실시간 참조


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_split_boundaries.py
PURPOSE: (v5.0 분할) 새로 분리한 모듈의 계층 경계를 소스 스캔으로 강제한다.
         dedup=leaf(values 만), autoheal=cli 를 import 하지 않음(cli→autoheal 단방향, 순환 차단).
         누가 어기는 import 를 넣으면 즉시 실패(주석 아니라 테스트가 지킨다).
DEPENDENCY: 표준 라이브러리만.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dedup
import autoheal
import structure
import locators
import engine


def _imports(mod, name):
    src = open(mod.__file__, encoding="utf-8").read()
    return bool(re.search(rf"^\s*(import|from)\s+{name}\b", src, re.M))


def test_dedup_is_leaf():
    for mod in ("engine", "cli", "guards", "autoheal", "chain", "crawlers"):
        assert not _imports(dedup, mod), f"dedup.py 가 '{mod}' import — leaf 위반"


def test_structure_is_leaf():
    # 구조 원시함수 leaf — engine·locators·cli·llm 어느 상위도 import 안 함(values leaf 만 허용).
    for mod in ("engine", "locators", "cli", "guards", "autoheal", "llm", "llm_locators", "chain"):
        assert not _imports(structure, mod), f"structure.py 가 '{mod}' import — leaf 위반"


def test_engine_and_locators_are_decoupled():
    # ★진짜 탈결합: engine 과 locators 는 '형제'다 — 서로를 절대 import 하지 않는다.
    #   (둘 다 structure/values/hooks 위에만 선다. 누가 한쪽을 다른 쪽에 끌어들이면 여기서 빨개진다.)
    assert not _imports(engine, "locators"), "engine 이 locators 를 import — 탈결합 위반"
    assert not _imports(locators, "engine"), "locators 가 engine 을 import — 탈결합 위반"


def test_locators_only_depends_on_leaves():
    # locators 는 structure/values/hooks(leaf) + lxml 만 의존, LLM/cli 는 모른다.
    for mod in ("engine", "cli", "llm", "llm_locators", "autoheal", "guards", "chain"):
        assert not _imports(locators, mod), f"locators.py 가 '{mod}' import — 계층 위반"


def test_pagination_is_sibling_leaf():
    # pagination(URL 기반)은 engine 클래스가 안 쓰는 형제 leaf — structure 만 의존, engine 도 미import.
    import pagination
    for mod in ("engine", "cli", "locators", "llm", "llm_locators", "guards"):
        assert not _imports(pagination, mod), f"pagination.py 가 '{mod}' import — leaf 위반"
    assert not _imports(engine, "pagination"), "engine 이 pagination 을 import — 형제여야 함"


def test_field_heuristics_is_leaf():
    # 필드 휴리스틱 매처(프로토타입 LLM 역할)는 structure/values(leaf)만 의존.
    import field_heuristics
    for mod in ("engine", "cli", "locators", "llm", "llm_locators", "autoheal", "chain"):
        assert not _imports(field_heuristics, mod), f"field_heuristics.py 가 '{mod}' import — leaf 위반"


def test_segment_is_leaf():
    # 예시경계 분리는 structure(leaf)만 의존.
    import segment
    for mod in ("engine", "cli", "locators", "values", "llm", "llm_locators", "chain"):
        assert not _imports(segment, mod), f"segment.py 가 '{mod}' import — leaf 위반"


def test_output_is_leaf():
    # CSV 저장(cli·chain 공유)은 dedup(leaf)/safe_io 만 의존 — 진입점(cli/chain)·engine 을 모른다.
    import output
    for mod in ("cli", "chain", "engine", "loader", "locators", "llm_locators"):
        assert not _imports(output, mod), f"output.py 가 '{mod}' import — leaf 위반"


def test_loader_does_not_import_entrypoints():
    # ★loader 는 cli·chain(진입점) 아래에 있는 공유 모듈 — 그들을 절대 import 하지 않는다
    #   (chain 이 cli 갓-모듈을 통째로 끌어오던 결합을 loader/output 이 대신 받음).
    import loader
    for mod in ("cli", "chain"):
        assert not _imports(loader, mod), f"loader.py 가 '{mod}' import — 결합/순환 위험"


def test_hooks_is_pure_leaf():
    # 훅 레지스트리는 engine·locators 가 '둘 다' 쓰는 공통 심 → 어느 상위도, LLM 도, lxml 도 import 안 함.
    import hooks
    for mod in ("engine", "cli", "locators", "llm", "llm_locators", "lxml", "values"):
        assert not _imports(hooks, mod), f"hooks.py 가 '{mod}' import — 순수 leaf 위반"


def test_autoheal_does_not_import_cli():
    # autoheal 은 engine/guards/dedup/llm_locators 등 '아래'만 쓰고 cli/chain 을 import 하지 않는다.
    for mod in ("cli", "chain"):
        assert not _imports(autoheal, mod), f"autoheal.py 가 '{mod}' import — 순환 위험"


def test_cli_re_exports_moved_symbols():
    # cli 가 재-export 로 여전히 노출(호출부·테스트 호환)하는지.
    import cli
    for name in ("_rec_key", "_choose_url_field", "try_auto_heal", "_auto_heal",
                 "_auto_heal_enabled", "_ask_load_method", "_heal_missing_at_learning",
                 "_run_is_valid", "_semantic_ok", "_coverage_ok", "_looks_like_block"):
        assert hasattr(cli, name), f"cli 가 '{name}' 를 재-export 하지 않음(호출부 깨짐)"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

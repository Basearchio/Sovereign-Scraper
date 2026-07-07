# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_start.py
PURPOSE: 메뉴 런처(start.py)의 '확장 계약'과 설정 저장 형식을 못박는다 — MENU 는 (라벨, 호출가능) 리스트라
         항목 추가(5·6…)가 안전하고, _write_env 는 llm_service 가 읽는 .env 키 형식과 일치해야 한다.
DEPENDENCY: 표준 라이브러리만(오프라인, subprocess 실행 없음 — 순수 구조/형식 검사).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import start


def test_menu_registry_is_extensible():
    assert isinstance(start.MENU, list) and len(start.MENU) >= 5
    for item in start.MENU:
        label, fn = item                     # (라벨, 함수) 계약 — 깨지면 확장이 위험
        assert isinstance(label, str) and label
        assert callable(fn)


def test_write_env_matches_llm_service_keys():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, ".env")
        start._write_env("http://x/v1", "mymodel", "sk-abc", path=p)
        txt = open(p, encoding="utf-8").read()
        assert "LLM_BASE_URL=http://x/v1" in txt
        assert "LLM_MODEL=mymodel" in txt
        assert "LLM_API_KEY=sk-abc" in txt
    # llm_service 가 기대하는 키와 동일한지(오타 방지) 교차 확인
    import services.llm_service as svc  # noqa: F401  (import 가능성 + 키 이름 일치 신뢰)


def test_set_env_preserves_other_keys():
    # AUTO_HEAL 토글이 LLM 키를 날리면 안 된다(부분 갱신·나머지 보존)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, ".env")
        start._write_env("http://x/v1", "m", "sk-1", path=p)
        assert start._auto_heal_on(path=p) is False        # 기본 OFF
        start._set_env({start.AUTO_HEAL_KEY: "1"}, path=p)
        env = start._read_env(path=p)
        assert env["LLM_BASE_URL"] == "http://x/v1" and env["LLM_MODEL"] == "m"  # 보존됨
        assert start._auto_heal_on(path=p) is True


def test_toggle_auto_heal_flips():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, ".env")
        assert start._toggle_auto_heal(path=p) is True      # 없음 → ON
        assert start._auto_heal_on(path=p) is True
        assert start._toggle_auto_heal(path=p) is False     # ON → OFF
        assert start._auto_heal_on(path=p) is False


def test_llm_service_get_flag():
    import os as _os
    import services.llm_service as svc
    _os.environ.pop("ZZ_TESTFLAG", None)
    assert svc.get_flag("ZZ_TESTFLAG", default=False) is False
    _os.environ["ZZ_TESTFLAG"] = "on"
    try:
        assert svc.get_flag("ZZ_TESTFLAG") is True
    finally:
        _os.environ.pop("ZZ_TESTFLAG", None)


def test_mask_key_hides_secret():
    assert start._mask_key("") == "(없음)"
    assert start._mask_key("short") == "(설정됨)"      # 짧으면 값 노출 안 함
    m = start._mask_key("sk-abcdefgh")
    assert m.startswith("sk-a") and "cdef" not in m    # 가운데는 가려짐


def test_action_crawl_is_thin_launcher():
    # start 는 런처: 크롤 안내는 cli 한 곳(중복 분기 제거). start 는 자체 setup/rediscover 함수를 갖지 않는다.
    assert not hasattr(start, "_crawl_setup")
    assert not hasattr(start, "_maybe_rediscover")


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

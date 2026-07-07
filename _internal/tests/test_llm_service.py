# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_llm_service.py
PURPOSE: 리팩터(Phase 1) 핵심 안전망 — LLM '심(seam)'을 모킹해, 결정적 매칭 실패 시
         LLM 경로가 올바로 동작하고 '엔드포인트 다운 시 폴백(None)'이 유지되는지 고정.
         이 테스트가 그린이면, llm 전송 계층을 services/llm_service 로 옮겨도 회귀를 잡는다.
DEPENDENCY: lxml (engine). 네트워크/LLM 서버 불필요 — llm.ask/ask_json 을 직접 모킹한다.

[검증된 주요 사이트 및 케이스]
- work24(값 분리→LLM 역할 매핑) 계열의 '핵심 계약'을 사이트 HTML 없이 재현:
  · LLM 이 배열을 주면 필드명이 붙는다 (llm_name_fields).
  · LLM 이 없으면(None) 호출부가 폴백한다 (crash 아님).

[테스트/운영 교훈]
- LLM 은 외부·비결정적이라 '라이브 서버 의존 테스트'는 flaky 하다 → 반드시 심을 모킹.
- llm.ask_json 은 응답 텍스트에서 첫 JSON 만 추출 → 잡음이 섞인 응답도 견뎌야 한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html as H
import services.llm_service as llm   # llm_locators 가 실제로 쓰는 정식 모듈을 패치해야 반영됨
import llm_locators


class _patch:
    """[사용처] 이 테스트 파일 전용. [역할] llm 모듈 속성을 임시 교체 후 원복(누수 방지)."""
    def __init__(self, **attrs):
        self.attrs = attrs
        self.old = {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.old[k] = getattr(llm, k, None)
            setattr(llm, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(llm, k, v)


def test_strip_removes_think_tokens():
    """[역할] Qwen3 <think>…</think> 추론 토큰 제거를 고정(chat 응답 정제 계약)."""
    assert llm._strip("<think>reasoning</think>  안녕 ") == "안녕"
    assert llm._strip("") == ""


def test_ask_json_extracts_embedded_json():
    """[역할] 잡음 섞인 응답에서도 첫 JSON 배열/객체만 파싱하는 계약 고정."""
    with _patch(ask=lambda *a, **k: 'noise ["제목","가격"] tail'):
        assert llm.ask_json("p") == ["제목", "가격"]
    with _patch(ask=lambda *a, **k: '앞 {"a": 1} 뒤'):
        assert llm.ask_json("p") == {"a": 1}


def test_ask_json_none_when_down():
    """[역할] 엔드포인트 다운(ask=None) 시 ask_json 도 None → 폴백 신호 유지."""
    with _patch(ask=lambda *a, **k: None):
        assert llm.ask_json("p") is None
    with _patch(ask=lambda *a, **k: "설명만 있고 JSON 없음"):
        assert llm.ask_json("p") is None


def test_name_fields_uses_llm():
    """[역할] LLM 이 정상 배열을 주면 필드명이 부여됨(work24 역할 매핑 계약)."""
    with _patch(ask_json=lambda *a, **k: ["제목", "가격"]):
        assert llm_locators.llm_name_fields(["사과", "1,000원"]) == ["제목", "가격"]


def test_name_fields_fallback_when_down():
    """[역할] LLM 다운 시 llm_name_fields 는 None → 호출부가 f1,f2.. 폴백."""
    with _patch(ask_json=lambda *a, **k: None):
        assert llm_locators.llm_name_fields(["사과", "1,000원"]) is None


def test_locate_by_example_llm_graceful_when_down():
    """[역할] LLM 다운이어도 crash 없이 (…, err) 4-튜플로 우아하게 실패."""
    html = ("<html><body><ul>"
            "<li class=c><a href=/1>사과</a><span>1,000원</span></li>"
            "<li class=c><a href=/2>배</a><span>2,000원</span></li>"
            "</ul></body></html>")
    dom = H.fromstring(html)
    with _patch(ask=lambda *a, **k: None, ask_json=lambda *a, **k: None):
        rec, sig, matched, err = llm_locators.locate_by_example_llm(dom, ["사과", "1,000원"])
    assert err, "LLM 다운 시 err 가 있어야 함(폴백 신호)"
    assert rec is None


def test_env_picks_first_nonempty():
    """[역할] _env 가 여러 후보 환경변수 중 첫 비어있지 않은 값을 고른다(하위호환 별칭 지원)."""
    os.environ.pop("_T_A", None); os.environ.pop("_T_B", None)
    assert llm._env("_T_A", "_T_B", default="dft") == "dft"
    os.environ["_T_B"] = "b"
    assert llm._env("_T_A", "_T_B", default="dft") == "b"
    os.environ["_T_A"] = "a"
    assert llm._env("_T_A", "_T_B", default="dft") == "a"   # 앞 후보 우선
    os.environ.pop("_T_A", None); os.environ.pop("_T_B", None)


def test_auth_headers_bearer_only_with_key():
    """[역할] API 키가 있을 때만 Authorization: Bearer 헤더가 붙는다(로컬은 키 없이)."""
    old = llm.LLM_API_KEY
    try:
        llm.LLM_API_KEY = ""
        assert "Authorization" not in llm._auth_headers()
        llm.LLM_API_KEY = "sk-test"
        assert llm._auth_headers().get("Authorization") == "Bearer sk-test"
    finally:
        llm.LLM_API_KEY = old


def test_backward_compat_aliases():
    """[역할] LM_STUDIO_* 별칭이 새 LLM_* 설정과 동일 값(기존 llm.py 심·참조 보호)."""
    assert llm.LM_STUDIO_BASE_URL == llm.LLM_BASE_URL
    assert llm.LM_STUDIO_MODEL == llm.LLM_MODEL


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

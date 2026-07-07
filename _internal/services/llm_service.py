# -*- coding: utf-8 -*-
"""
MODULE_NAME: services/llm_service.py
PURPOSE: LLM 전송 계층(OpenAI 호환 /chat/completions). '결정적 매칭 실패 시에만' 타는 폴백에서,
         행 HTML/값을 프롬프트로 넘겨 '의미'를 얻고(셀렉터 생성은 코드가) 응답을 파싱한다.
         공급자 무관: 로컬 LM Studio(기본) / OpenAI / OpenRouter / together 등 OpenAI 호환이면 .env
         로 전환(LLM_BASE_URL/LLM_MODEL/LLM_API_KEY). 엔드포인트가 안 닿으면 모든 함수가 None →
         호출부는 휴리스틱으로 폴백(로컬 GPU 없이도 프로그램은 동작, 단 LLM 폴백 기능만 비활성).
DEPENDENCY: requests(있으면) 또는 urllib(폴백). 내부 모듈 import 없음(leaf).

[검증된 주요 사이트 및 케이스]
- work24(라벨+값 분리): 역할 기반 매핑을 LLM 으로 해결(engine.locate_by_example_llm 경유).
- 자가치유 재배치(engine.llm_relocate): 구조 드리프트 시 '그 필드의 현재 값'을 의미로 찾음.

[테스트/운영 교훈]
- 엔드포인트 미연결 시 반드시 None 반환(예외 삼킴) → 호출부 폴백이 성립(tests/test_llm_service).
- Qwen3 <think>…</think> 추론 토큰을 제거해야 파싱이 안정적(_strip).
- 응답에 잡음이 섞여도 첫 JSON 객체/배열만 추출(ask_json).
- [이력] Phase 1a 에서 프로젝트 루트 `llm.py` → 여기로 이동. `llm.py` 는 하위호환 재-export 심.
"""
from __future__ import annotations

import json
import os
import re


def _load_dotenv():
    """프로젝트 루트의 .env 를 os.environ 에 채운다(이미 설정된 값은 유지). python-dotenv
    의존 없는 최소 파서: 'KEY=VALUE', # 주석, 양끝 따옴표 처리. 파일 없으면 조용히 통과."""
    # _internal/services/llm_service.py → 프로젝트 루트(_internal 의 부모)의 .env
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        with open(os.path.join(root, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def _env(*names, default=""):
    """여러 후보 환경변수 이름 중 처음으로 값이 있는 것을 반환(하위호환 별칭 지원용)."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def get_flag(*names, default=False):
    """.env/환경변수의 불리언 설정 읽기(1/true/on/yes/y → True). 예: get_flag('AUTO_HEAL').
    .env 는 import 시 _load_dotenv 로 os.environ 에 실려 있음(설정 툴은 별 프로세스라 매 실행 최신)."""
    _load_dotenv()
    for n in names:
        v = (os.environ.get(n) or "").strip().lower()
        if v:
            return v in ("1", "true", "on", "yes", "y")
    return default


_load_dotenv()

# ── LLM 공급자 설정(OpenAI 호환) — .env 로 로컬↔클라우드 전환 ──────────────────
#   · 로컬 LM Studio(기본): LLM_BASE_URL=http://localhost:1234/v1, 키 불필요
#   · OpenAI:     LLM_BASE_URL=https://api.openai.com/v1,     LLM_MODEL=gpt-4o-mini, LLM_API_KEY=sk-...
#   · OpenRouter: LLM_BASE_URL=https://openrouter.ai/api/v1,  LLM_MODEL=qwen/qwen-2.5-72b-instruct, LLM_API_KEY=...
LLM_BASE_URL = _env("LLM_BASE_URL", "LM_STUDIO_BASE_URL", default="http://localhost:1234/v1")
LLM_MODEL = _env("LLM_MODEL", "LM_STUDIO_MODEL", default="local-model")
LLM_API_KEY = _env("LLM_API_KEY", "OPENAI_API_KEY", default="")

# 하위호환 별칭(llm.py 심 및 기존 참조가 계속 동작하도록 유지).
LM_STUDIO_BASE_URL = LLM_BASE_URL
LM_STUDIO_MODEL = LLM_MODEL

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)   # Qwen3 등 추론 토큰 제거


def _auth_headers():
    """API 키가 있으면 Bearer 인증 헤더 추가(클라우드 공급자용). 로컬은 키 없이 동작."""
    h = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        h["Authorization"] = f"Bearer {LLM_API_KEY}"
    return h


def _strip(text: str) -> str:
    """[역할] 응답에서 <think>…</think> 추론 토큰 제거 후 트림. chat() 이 반환 직전 호출."""
    if not text:
        return ""
    return _THINK_RE.sub("", text).strip()


def chat(messages, temperature=0.0, max_tokens=512, timeout=60):
    """
    [사용처/협력자] ask()/ask_json() 의 하부. requests(없으면 urllib) 로 HTTP POST.
    [역할] OpenAI 호환 /chat/completions 호출 → 정제된 텍스트. 실패 시 None(폴백 신호).
    """
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = _auth_headers()
    try:
        try:
            import requests
            r = requests.post(url, data=body, headers=headers, timeout=timeout)
            r.raise_for_status()
            data = r.json()
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        return _strip(data["choices"][0]["message"]["content"])
    except Exception:
        return None


def ask(prompt, system=None, **kw):
    """
    [사용처/협력자] engine.llm_relocate / llm_next_url 등이 호출. 하부는 chat().
    [역할] 단일 프롬프트 → 텍스트(또는 None).
    """
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return chat(msgs, **kw)


def ask_json(prompt, system=None, **kw):
    """
    [사용처/협력자] engine.locate_by_example_llm / llm_name_fields 가 호출. 하부는 ask().
    [역할] LLM 응답에서 첫 JSON 객체/배열만 파싱해 반환(실패/잡음/미연결 시 None).
    """
    out = ask(prompt, system=system, **kw)
    if not out:
        return None
    m = re.search(r"\{.*\}|\[.*\]", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def available(timeout=5) -> bool:
    """[역할] 엔드포인트 연결 가능 여부(모델 목록 조회). 진단/수동 확인용."""
    url = LLM_BASE_URL.rstrip("/") + "/models"
    headers = _auth_headers()
    try:
        try:
            import requests
            return requests.get(url, headers=headers, timeout=timeout).ok
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status == 200
    except Exception:
        return False


if __name__ == "__main__":
    import sys, os
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # _internal
    from i18n import t
    print("base :", LLM_BASE_URL)
    print("model:", LLM_MODEL)
    print("auth :", t("Bearer(설정됨)") if LLM_API_KEY else t("없음(로컬)"))
    print(t("연결 :"), "OK" if available() else t("실패(엔드포인트/키 확인)"))
    r = ask(t("한국어로 '준비됨'이라고만 답해."))
    print(t("응답 :"), r)

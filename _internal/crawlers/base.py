# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/base.py
PURPOSE: 수집 전략 공통 요소 — 모든 로드방식(static/dynamic/chrome)이 공유하는 상수/헬퍼.
         현재는 공용 User-Agent 와 표준 헤더 빌더를 제공한다.
DEPENDENCY: 없음(표준 라이브러리도 불필요).

[검증된 주요 사이트 및 케이스]
- 해당 없음(공용 상수 계층). static/dynamic 이 동일 UA 로 일관된 지문을 쓰게 한다.

[테스트/운영 교훈]
- static/dynamic 이 서로 다른 UA 를 쓰면 사이트가 다르게 응답해 '학습 때/재현 때' 결과가
  갈릴 수 있다 → UA 를 한 곳(여기)에 두어 일관성 보장.
- (헤더 보강, 탐지 우회 아님) static_fetch 가 UA+Accept-Language 딱 2개뿐이라 실제 브라우저
  요청보다 눈에 띄게 빈약했다 → 평범한 데스크톱 크롬이 보내는 표준 헤더 세트로 정상화.
  Accept-Encoding 은 일부러 넣지 않는다: br/zstd 를 광고했다가 그 코덱을 풀 라이브러리가
  설치돼 있지 않으면 응답이 깨진다(requests 가 실제 설치된 코덱 기준으로 알아서 광고하게 둠).
  이건 안티봇의 행동/기기 지문 판별을 뚫으려는 게 아니라 '너무 부자연스러운 요청'만 없애는
  선 — 자세한 배경은 README 상단 고지 참고.
"""
from __future__ import annotations

# 공용 User-Agent (일반 데스크톱 크롬). static fetch·headless 렌더가 동일 지문을 쓴다.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_SEC_CH_UA = '"Chromium";v="126", "Not.A/Brand";v="24", "Google Chrome";v="126"'


def default_headers(extra: dict = None) -> dict:
    """[사용처] crawlers.static(및 향후 dynamic 헤더 구성).
    [역할] 공용 UA + 데스크톱 크롬이 실제로 보내는 표준 헤더 세트(한국어 우선)."""
    h = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "sec-ch-ua": _SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    if extra:
        h.update(extra)
    return h


# 안티봇 차단 페이지 시그니처. 사이트가 자동 접근을 막으면 상품/공고 대신
# 짧은 '차단 안내' 페이지를 돌려준다. 이걸 감지해 '진짜 크롬' 경로로 자동 전환한다.
_BLOCK_TITLE = (
    "access denied", "attention required", "just a moment",
    "pardon our interruption", "are you a robot", "forbidden",
    "service unavailable", "잠시 후 다시", "비정상적인 접근",
)
_BLOCK_TEXT = (
    "errors.edgesuite.net",          # Akamai
    "cloudflare",                    # Cloudflare
    "perimeterx", "px-captcha",      # PerimeterX/HUMAN
    "captcha-delivery",              # DataDome
    "incapsula",                     # Imperva
    "you don't have permission to access",
    "enable javascript and cookies to continue",
)


def block_reason(dom) -> "str | None":
    """
    [사용처/협력자] cli 가 로드 결과마다 호출해 '차단됐나?'를 판정 → 참이면 crawlers.chrome 폴백.
      lxml DOM 만 검사(순수 함수, 외부 의존 없음).
    [역할] DOM 이 안티봇 '차단 페이지'면 사람이 읽을 사유를, 아니면 None.
      Akamai/Cloudflare/PerimeterX/DataDome 등의 짧은 안내 페이지를 제목/본문 시그니처로 가려내되,
      본문이 길면(>800자) 정상 페이지에 단어만 우연히 들어간 경우라 오탐을 피한다.
    """
    if dom is None:
        return None
    title = (dom.findtext(".//title") or "").strip().lower()
    if any(s in title for s in _BLOCK_TITLE):
        return f"차단 페이지 제목 감지: '{title[:60]}'"
    body = " ".join(dom.text_content().split())
    low = body.lower()
    for sig in _BLOCK_TEXT:
        if sig in low and len(body) < 800:
            return f"안티봇 차단 시그니처 감지: '{sig}' (본문 {len(body)}자)"
    return None

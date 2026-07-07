# -*- coding: utf-8 -*-
"""
MODULE_NAME: i18n.py
PURPOSE: 다국어(i18n) — 한국어를 '소스(기본값)'로 두고, 언어별 오버레이(한국어→번역)를 얹는다.
         t("크롤링") 은 현재 언어 번역이 있으면 그걸, 없으면 **한국어 원문 그대로** 돌려준다(폴백).
         → 문자열을 하나씩 번역해도 앱이 안 깨지고, 미번역은 자연히 한국어로 나온다("한국어 구성 후 언어 확장").
DEPENDENCY: 표준 라이브러리(os/json)만. 최하위 leaf(누구나 import). engine/cli/start 무관.

- 언어: 루트 `.env` 의 LANG(기본 ko). 번역표: `_internal/i18n/<lang>.json` = {"한국어원문": "번역", …}.
- 쓰기는 start 설정 메뉴(_set_env), 읽기는 여기. set_lang() 으로 런타임 전환(캐시 갱신).
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENV = os.path.join(os.path.dirname(_HERE), ".env")      # 루트/.env
_LOCALES = os.path.join(_HERE, "i18n")                   # _internal/i18n/<lang>.json

LANG_KEY = "LANG"
DEFAULT_LANG = "ko"          # 소스 언어(=키 언어): 번역 없을 때의 폴백. _load_table 은 이 언어의 표를 안 만든다.
DISPLAY_DEFAULT = "en"      # .env 에 LANG 이 없을 때 '보여줄' 기본 언어(=배포 기본). 소스(ko)와 분리.
SUPPORTED = ("ko", "en")                                 # 언어 추가 시: 여기 + <lang>.json

_lang = None        # 현재 언어(지연 초기화 캐시)
_table = {}         # 현재 언어 번역표(캐시)


def _read_env_lang():
    """루트 .env 에서 LANG 값(소문자). 없으면 ''."""
    try:
        with open(_ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == LANG_KEY:
                    return v.strip().lower()
    except FileNotFoundError:
        pass
    return ""


def _load_table(lang):
    """<lang>.json 번역표 로드. 기본 언어(ko)는 소스라 표 불필요. 없거나 깨지면 빈 표(→ 원문 폴백)."""
    if lang == DEFAULT_LANG:
        return {}
    try:
        with open(os.path.join(_LOCALES, f"{lang}.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def set_lang(lang):
    """현재 언어 설정 + 번역표 로드. 미지원 언어면 기본(ko). 반환: 실제 적용된 언어."""
    global _lang, _table
    lang = (lang or "").strip().lower()
    if lang not in SUPPORTED:
        lang = DEFAULT_LANG
    _lang, _table = lang, _load_table(lang)
    return _lang


def current_lang():
    """현재 언어(최초 호출 시 .env 에서 지연 초기화). .env 에 LANG 없으면 배포 기본(DISPLAY_DEFAULT=en)."""
    if _lang is None:
        set_lang(_read_env_lang() or DISPLAY_DEFAULT)
    return _lang


def t(text, **kw):
    """한국어 원문 text 를 현재 언어로. 번역 없으면 원문 그대로. kw 가 있으면 .format(**kw) 적용."""
    current_lang()                      # 초기화 보장
    s = _table.get(text, text)          # 번역 없으면 한국어 폴백
    if kw:
        try:
            s = s.format(**kw)
        except (KeyError, IndexError, ValueError):
            pass
    return s

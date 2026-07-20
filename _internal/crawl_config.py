# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawl_config.py
PURPOSE: 크롤 '기본 설정'(레시피가 따르는 기준값)을 한곳에서 읽는 leaf. 대화형 시작 안내의 [기본]
         선택과, 명시 지정이 없을 때의 저장/로드 방식 폴백이 이 값을 쓴다. 값은 .env 에 저장되고
         start.py 설정 메뉴에서 바꾼다(읽기는 여기, 쓰기는 start).
DEPENDENCY: envfile(최하위 leaf, .env 단일 파서)만. engine/cli/llm 무관(leaf).

[정책]
- 대화형(cli 직접 실행): 사용자가 고른 값(Enter=여기 기본값)이 이번 실행에 적용되고 레시피에 저장된다.
- 비대화(replay/스케줄러/인자지정): 레시피에 저장된 방식이 그대로 재현된다(여기 기본값은 폴백).
  → "레시피는 설정한 기본값을 기준으로 작동하되, 이미 만들어진 레시피의 재현은 저장값을 지킨다."
"""
from envfile import read_env as _read_env   # .env 파싱은 envfile leaf 단일 파서(복제 제거)

SAVE_MODE_KEY = "DEFAULT_SAVE_MODE"
LOAD_METHOD_KEY = "DEFAULT_LOAD_METHOD"

SAVE_MODES = ("append", "history", "overwrite", "upsert")   # 유효한 저장 방식
LOAD_METHODS = ("auto", "save_as")                          # 유효한 로드 방식

FALLBACK_SAVE_MODE = "append"       # 설정 없거나 잘못됐을 때
FALLBACK_LOAD_METHOD = "auto"


def default_save_mode(path=None):
    """설정된 기본 저장 방식(append/history/overwrite/upsert). 없거나 잘못되면 append."""
    v = (_read_env(path).get(SAVE_MODE_KEY, "") or "").strip().lower()
    return v if v in SAVE_MODES else FALLBACK_SAVE_MODE


def default_load_method(path=None):
    """설정된 기본 로드 방식(auto/save_as). 없거나 잘못되면 auto."""
    v = (_read_env(path).get(LOAD_METHOD_KEY, "") or "").strip().lower()
    return v if v in LOAD_METHODS else FALLBACK_LOAD_METHOD

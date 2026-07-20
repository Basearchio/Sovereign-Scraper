# -*- coding: utf-8 -*-
"""
MODULE_NAME: envfile.py
PURPOSE: 루트 `.env` 읽기/부분 갱신의 '단일 파서' leaf. 같은 KEY=VALUE 파싱이 네 곳
         (start._read_env / llm_service._load_dotenv / crawl_config._read_env / i18n._read_env_lang)에
         복제돼 있던 것을 한곳으로 모았다 — 파싱 규칙이 서로 어긋나 설정이 유실/불일치하는 사고 방지.
DEPENDENCY: 표준 라이브러리(os)만. 내부 모듈 import 없음(최하위 leaf — i18n 보다도 아래, 누구나 import).

[형식 계약]
- 'KEY=VALUE' 한 줄 하나. '#' 시작 줄/빈 줄/'=' 없는 줄 무시. 키·값 양끝 공백 제거,
  값 양끝의 '짝 맞는' 따옴표 한 겹 제거(사용자가 API 키를 따옴표로 감싼 경우 대응).
- set_env 는 '일부 키'만 갱신하고 나머지 키는 보존한다(전체 덮어쓰기 금지 — AUTO_HEAL 토글이
  LLM 키를 날리는 사고 방지). 파일 없으면 생성.
"""
import os

# 프로젝트 루트(_internal 의 부모)의 .env — 모든 소비자가 같은 파일을 본다.
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def read_env(path=None):
    """.env 를 {키: 값} dict 로 읽는다. 파일 없으면 빈 dict(소비자가 폴백)."""
    d = {}
    try:
        with open(path or ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]                      # 짝 따옴표만 한 겹 제거(값 안의 따옴표는 보존)
                d[k.strip()] = v
    except FileNotFoundError:
        pass
    return d


def set_env(updates, path=None):
    """.env 의 '일부 키'만 갱신하고 나머지 키는 보존한다. 파일 없으면 생성."""
    path = path or ENV_PATH
    cur = read_env(path)
    for k, v in updates.items():
        cur[k] = "" if v is None else str(v)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 설정 (start.py 가 생성/갱신). .env 는 .gitignore 됩니다 — 커밋되지 않음.\n")
        for k, v in cur.items():
            f.write(f"{k}={v}\n")

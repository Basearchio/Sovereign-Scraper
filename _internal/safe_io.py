# -*- coding: utf-8 -*-
"""
MODULE_NAME: safe_io.py
PURPOSE: 파일이 다른 프로그램(엑셀 등)에 잠겨 쓸 수 없을 때 '조용히 스킵'하면 데이터에 구멍이 난다.
         이 모듈은 잠금이 풀릴 때까지(=엑셀을 닫을 때까지) 대기·재시도해 저장을 보장한다(시스템 완결성).
DEPENDENCY: 표준 라이브러리(os/sys/time)만. 어떤 내부 모듈도 import 하지 않는다(최하위 leaf → 순환 0).

[설계]
- 쓰기 모드(w/a/x/+)에서만 재시도. 읽기는 그대로(엑셀은 CSV 를 읽기 공유로 열어 read 는 보통 됨).
- 기본은 '무한 대기'(timeout=None) — 파일을 닫으면 자동으로 이어서 저장. Ctrl+C 로 취소 가능.
  스케줄러 등 무인 실행에서 무한 대기가 곤란하면 timeout(초) 을 줘 초과 시 PermissionError 를 올린다.
"""
import os
import sys
import time

from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)

_REPROMPT_EVERY = 5.0   # 초마다 재안내


def _is_write_mode(mode: str) -> bool:
    return any(c in mode for c in "wax+")


def open_when_writable(path, mode="r", *, timeout=None, poll=1.0, announce=True, **kwargs):
    """open() 과 동일하되, 쓰기 모드에서 파일이 잠겨(PermissionError) 있으면 풀릴 때까지 대기·재시도.
    반환값은 파일 핸들(그대로 with 문에 사용). 읽기 모드는 재시도하지 않는다."""
    if not _is_write_mode(mode):
        return open(path, mode, **kwargs)
    start = time.time()
    announced = False
    last_msg = 0.0
    name = os.path.basename(path)
    while True:
        try:
            return open(path, mode, **kwargs)
        except PermissionError:
            now = time.time()
            if timeout is not None and now - start >= timeout:
                raise
            if announce and not announced:
                print("\n[" + t("대기") + "] " + t("'{name}' 이(가) 다른 프로그램(엑셀 등)에서 열려 있어 저장할 수 없습니다.", name=name))
                print("       " + t("그 파일을 닫아 주세요 — 닫으면 자동으로 이어서 저장합니다. (Ctrl+C = 취소)"))
                sys.stdout.flush()
                announced, last_msg = True, now
            elif announce and now - last_msg >= _REPROMPT_EVERY:
                print("       " + t("...아직 '{name}' 이(가) 잠겨 있습니다. 파일을 닫아 주세요.", name=name))
                sys.stdout.flush()
                last_msg = now
            time.sleep(poll)

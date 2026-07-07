# -*- coding: utf-8 -*-
"""
MODULE_NAME: output.py
PURPOSE: 결과 CSV 저장 leaf — 4가지 저장 방식(append/history/overwrite/upsert) + 회차/crawled_at 부가 +
         헤더 진화(옛 컬럼 보존) + 파일 잠금 대기(safe_io). cli(단발 크롤)와 chain(체인 크롤)이 '둘 다'
         쓰므로 어느 진입점에도 두지 않고 공통 모듈로 둔다(chain 이 cli 갓-모듈을 통째로 끌어오던 결합 해소).
DEPENDENCY: dedup(leaf, 중복키)·safe_io + 표준 csv. engine/cli/chain/llm 을 import 하지 않는다.
"""
from __future__ import annotations

import os

import safe_io
from dedup import _rec_key


def save_csv(path, rows, fields, mode="append", url_field=None, batch=None, key_field=None):
    """결과 CSV 저장. 데이터 성격에 맞는 4가지 방식(mode) + '회차'(수집 세션 번호)·crawled_at 부가.
      · append   : 키 중복 제외 후 뒤에 추가 (기본, P6)  — 채용/신규상품 누적
      · history  : 전량 추가(중복 무시), 회차로 스냅샷 구분 (P1+회차=P10) — 랭킹 시계열
      · overwrite: 기존 전량 교체 (P5) — 인기가요 등 '지금 상태'만 의미 있는 것
      · upsert   : 키로 제자리 갱신 + 신규 삽입 (P7) — 가격/상태 변하는 목록
    모든 모드가 전체를 다시 쓴다(회차 컬럼 추가·헤더 진화 대응, 잠금은 safe_io). 반환: (added, updated).
    """
    import csv
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    b = "" if batch is None else str(batch)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    existing, existing_cols = [], []
    if mode != "overwrite" and os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            dr = csv.DictReader(f)
            existing_cols = list(dr.fieldnames or [])
            existing = list(dr)
    # 기존 컬럼을 '보존'하며 새 컬럼(회차)만 덧붙인다 → 옛 파일 컬럼명이 달라도 데이터 손실 없음.
    new_cols = list(fields) + ["회차", "crawled_at"]
    header = (existing_cols + [c for c in new_cols if c not in existing_cols]
              if existing_cols else new_cols)

    def key_of(r):                       # upsert/dedup 식별키: url_field > key_field > 전체필드
        if url_field and (r.get(url_field) or "").strip():
            return ("u", (r.get(url_field) or "").strip())
        if key_field and (r.get(key_field) or "").strip():
            return ("k", (r.get(key_field) or "").strip())
        return ("r", _rec_key(r, fields, url_field))

    def stamp(r):                        # 이번 실행 행 = 회차/시각 찍기
        out = {k: ("" if r.get(k) is None else r.get(k)) for k in fields}
        out["회차"], out["crawled_at"] = b, ts
        return out

    added = updated = 0
    if mode == "overwrite":
        final = [stamp(r) for r in rows]
        added = len(final)
    elif mode == "upsert":
        final = list(existing)
        idx = {key_of(r): i for i, r in enumerate(final)}
        for r in rows:
            k = key_of(r)
            if k in idx:
                final[idx[k]] = stamp(r); updated += 1
            else:
                idx[k] = len(final); final.append(stamp(r)); added += 1
    elif mode == "history":
        final = list(existing) + [stamp(r) for r in rows]
        added = len(rows)
    else:                                 # append (중복 제외)
        seen = {key_of(r) for r in existing}
        final = list(existing)
        for r in rows:
            k = key_of(r)
            if k in seen:
                continue
            seen.add(k); final.append(stamp(r)); added += 1

    # 잠기면(엑셀) 풀릴 때까지 대기 후 저장(구멍 방지).
    with safe_io.open_when_writable(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in final:
            w.writerow(r)
    return added, updated

# -*- coding: utf-8 -*-
"""
MODULE_NAME: runlog.py
PURPOSE: 실행 감사 로그(_runs.csv) 기록 + 계층 실행번호(site_no) 부여. 매 실행을 '녹화하듯'
         append 하고, 파일 전체를 다시 써 site_no 를 일관 부여한다(일반=정수, 체인=부모-자식 P-k).
         replay 목록 번호와 _runs.csv 의 site_no 가 항상 일치하도록 하는 단일 규칙.
DEPENDENCY: 표준 라이브러리(csv/datetime/time) + paths(OUTPUT_DIR/RUNLOG_PATH). engine/DOM 무관.

[검증된 주요 사이트 및 케이스]
- 부모-자식 번호: incruit 목록(정수 6) → 그 목록 CSV 를 따라간 체인 = '6-1'. 부모 매칭은
  result_csv **basename** 으로(폴더 이동에도 강함).
- 파일 잠금(엑셀 열림) 시 safe_io 로 '풀릴 때까지 대기' 후 저장 → 로그에 구멍이 나지 않음.

[테스트/운영 교훈]
- leaf 규율: 상위 모듈(cli/engine/chain/replay) 을 import 하지 않는다(순환 차단). paths(leaf)만 의존.
- 번호 규칙(assign_run_numbers)은 cli/replay 가 '동일 함수'로 공유 → 목록번호와 로그가 어긋나지 않음.
- 행동 계약은 tests/test_runlog.py 가 고정(P-k 계층 번호).
"""
from __future__ import annotations

import os

import safe_io
from paths import OUTPUT_DIR, RUNLOG_PATH


def _is_chain_target(t: str) -> bool:
    return (t or "").strip().lower().endswith(".csv")


# site_no 를 맨 앞에 둬, _runs.csv 만 봐도 사이트별 '고정 번호'(=replay 목록 번호)를 안다.
# url_col: 체인 크롤링 재현에 필요(부모 CSV 의 어느 링크 열을 따라갔는지) + 자식 번호 구분용.
RUNLOG_HEADER = ["site_no", "crawled_at", "status", "target", "load_method",
                 "parse_method", "input_example", "fields", "n_records",
                 "result_csv", "recipe_csv", "url_col", "batch", "save_mode"]

# 저장 방식(패턴) → 사람이 읽는 라벨. cli/replay 가 공유(replay 목록에 표시).
MODE_LABELS = {
    "append":    "중복제외 추가",     # P6 (기본)
    "history":   "전량 누적(회차)",   # P1+회차 = P10 (랭킹 시계열)
    "overwrite": "덮어쓰기",          # P5 (스냅샷 교체)
    "upsert":    "키 갱신",           # P7 (제자리 update+insert)
}


def next_batch() -> int:
    """다음 '회차' 번호 = _runs.csv 의 최대 batch + 1 (상태파일 없이). 한 replay 세션은 이 값을 공유."""
    import csv
    mx = 0
    if os.path.exists(RUNLOG_PATH):
        with open(RUNLOG_PATH, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    mx = max(mx, int(r.get("batch") or 0))
                except (ValueError, TypeError):
                    pass
    return mx + 1


def assign_run_numbers(rows):
    """실행기록 rows(파일 순서)에 site_no(문자열)를 부여한다(각 행 dict 를 직접 수정).

    · 일반(비체인) target: '최초 등장 순' 정수  1, 2, 3 …
    · 체인(target 이 .csv): 부모(그 CSV 를 만든 일반 크롤) 번호 P 밑에서 'P-k'.
      부모 매칭은 result_csv 의 **basename** 으로(폴더 이동에도 강함). 자식 k 는 부모 밑
      distinct (target, url_col) 등장 순. 부모를 못 찾으면 일반처럼 정수 부여.
    → replay 목록 번호와 _runs.csv 의 site_no 가 항상 일치. 부모-자식 관계가 눈에 보임.
    """
    intmap, nxt = {}, [1]
    def next_int():
        v = nxt[0]; nxt[0] += 1; return v
    # 1) 일반 target 정수 부여 + result_csv basename → 부모 번호 맵
    csv_parent = {}
    for r in rows:
        t = (r.get("target") or "").strip()
        if not t or _is_chain_target(t):
            continue
        if t not in intmap:
            intmap[t] = next_int()
    for r in rows:
        t = (r.get("target") or "").strip()
        if not t or _is_chain_target(t):
            continue
        rc = (r.get("result_csv") or "").strip()
        if rc:
            csv_parent.setdefault(os.path.basename(rc).lower(), intmap[t])
    # 2) 각 행에 번호 부여(체인은 P-k, 부모없는 체인/일반은 정수)
    child_idx, chain_top = {}, {}
    for r in rows:
        t = (r.get("target") or "").strip()
        if not t:
            r["site_no"] = ""
            continue
        if not _is_chain_target(t):
            r["site_no"] = str(intmap[t])
            continue
        col = (r.get("url_col") or "").strip()
        pno = csv_parent.get(os.path.basename(t).lower())
        key = (t, col)
        if pno is not None:
            d = child_idx.setdefault(pno, {})
            if key not in d:
                d[key] = len(d) + 1
            r["site_no"] = f"{pno}-{d[key]}"
        else:
            if key not in chain_top:
                chain_top[key] = next_int()
            r["site_no"] = str(chain_top[key])
    return rows


def append_runlog(target, status, load_method, parse_method, example, fields,
                  n_records, result_csv, recipe_csv, url_col="", batch=None, save_mode=""):
    """실행 한 건을 '녹화하듯' _runs.csv 에 기록(파일을 다시 써 site_no 를 일관 부여).
    status: 'success'|'fail' — replay 가 성공 건만 재현 대상으로 고를 때 사용.
    url_col: 체인 크롤링일 때 부모 CSV 의 URL 컬럼명(재현·자식번호용). 일반이면 빈칸."""
    import csv, datetime
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    new_row = {
        "crawled_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "status": status, "target": target, "load_method": load_method,
        "parse_method": parse_method, "input_example": example or "",
        "fields": "|".join(fields), "n_records": n_records,
        "result_csv": result_csv or "", "recipe_csv": recipe_csv or "",
        "url_col": url_col or "",
        "batch": "" if batch is None else str(batch),
        "save_mode": save_mode or "",
    }
    rows = []
    if os.path.exists(RUNLOG_PATH):
        with open(RUNLOG_PATH, encoding="utf-8-sig", newline="") as fp:
            rows = list(csv.DictReader(fp))
    rows.append(new_row)
    assign_run_numbers(rows)              # site_no 재부여(옛 기록 마이그레이션 겸용)
    # 파일이 잠겨 있으면(엑셀 열림) 풀릴 때까지 대기 후 저장 → 로그에 '구멍'이 나지 않도록 보장.
    with safe_io.open_when_writable(RUNLOG_PATH, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=RUNLOG_HEADER, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

# -*- coding: utf-8 -*-
"""
MODULE_NAME: guards.py
PURPOSE: '성공 기준' 가드 모음 — 추출 결과가 저장할 만한가를 결정적으로 판정한다.
         잘못된 성공(차단/인증 페이지·엉뚱한 치유·구멍투성이)으로 좋은 레시피/CSV를 덮지 않게 막는다.
         (v5.0 분할: cli 에서 _run_is_valid/_semantic_ok/_coverage_ok/_looks_like_block/_llm_confirms_real 이관)

  성공 = '사용자가 원한 필드를 실제로 가져왔는가'. 다층(값싼 것부터):
    ① _coverage_ok      : 요청 필드의 절반도 못 잡으면 실패(결정적, LLM 불요)
    ② _looks_like_block : 값이 차단/인증 마커로 도배되면 무효(결정적)
    ③ _semantic_ok      : example 형태(num/url/date)와 다르면 '채웠지만 엉뚱' 거부
    ④ _llm_confirms_real: 행 ≤2 극소수일 때만 LLM 에 REAL/BLOCK 확인(명시 BLOCK 만 거부)
DEPENDENCY: 값 의미는 values(leaf), 극소수 LLM 판정은 llm_locators. engine/cli 를 import 하지 않는다.
"""
from __future__ import annotations

from values import _value_shape
from llm_locators import looks_like_real_records


def _run_is_valid(rows, fields):
    """추출 결과가 '쓸 만한지' 판정. 자가치유가 차단/엉뚱한 페이지에 끌려가면 전부
    None 이 되는데, 그런 결과로 레시피/CSV를 오염시키지 않기 위한 가드.
    기준: 적어도 한 행에서 필드의 절반 이상이 실제 값으로 채워졌는가."""
    if not rows:
        return False
    need = max(1, len(fields) // 2)
    for r in rows:
        if sum(1 for k in fields if r.get(k)) >= need:
            return True
    return False


def _semantic_ok(rows, schema, min_ratio=0.2, min_vals=3):
    """치유/추출 값이 레시피 example 의 형태와 맞는지. 강한 형태(num/url/date) 필드가
    표본(≥min_vals) 중 min_ratio 미만만 그 형태면 '엉뚱하게 채워짐'으로 판정.
    보수적: 형태 약한 필드(text/empty)·표본 부족·일부만 다른 경우(정상적 변동)는 통과.
    반환: (ok, 문제필드[(name, 기대형태, '일치/표본')])."""
    if schema is None:
        return True, []
    bad = []
    for name, fs in schema.fields.items():
        want = _value_shape(fs.get("example", ""))
        if want in ("empty", "text"):        # 형태 제약이 약함 → 판정 보류
            continue
        vals = [str(r.get(name)) for r in rows if r.get(name)]
        if len(vals) < min_vals:              # 표본 부족 → 판정 보류
            continue
        match = sum(1 for v in vals if _value_shape(v) == want)
        if match < min_ratio * len(vals):     # 거의 다 다른 형태 → 잘못된 치유
            bad.append((name, want, f"{match}/{len(vals)}"))
    return (len(bad) == 0, bad)


def _coverage_ok(n_want, n_got):
    """사용자가 원한 필드 수(n_want) 대비 실제로 잡힌 수(n_got)가 '절반 이상'인가.
    대부분 구멍이면 False. → 성공 = 내가 가져오자고 한 내용을 가져왔는가(LLM 불필요, 결정적)."""
    return n_got >= 1 and n_got * 2 >= n_want


# 차단/인증/로봇확인 페이지 특유 텍스트(값이 이걸로 도배되면 실제 데이터가 아님)
_BLOCK_MARKERS = ("验证", "verify", "verification", "captcha", "robot", "로봇",
                  "unusual traffic", "access denied", "blocked", "请稍候", "人机",
                  "checking your browser", "안전 확인", "보안문자", "잠시만", "滑块", "拖动")


def _looks_like_block(rows, fields):
    """추출 값의 절반 이상이 차단/인증 마커면 True — 값싼 결정적 감지(LLM 불필요)."""
    vals = [str(r.get(f)) for r in rows for f in fields if r.get(f)]
    if not vals:
        return False
    ml = [m.lower() for m in _BLOCK_MARKERS]
    hits = sum(1 for v in vals if any(m in v.lower() for m in ml))
    return hits * 2 >= len(vals)


def _llm_confirms_real(rows, fields):
    """결과가 극소수일 때만 쓰는 최후 백스톱. LLM 이 '차단/오류'로 '명시(False)'할 때만 거짓.
    미연결/불명확(None)·실제(True)면 통과 → 못 믿을 땐 정상 데이터를 막지 않는다."""
    return looks_like_real_records(rows, fields) is not False

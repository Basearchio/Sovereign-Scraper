# -*- coding: utf-8 -*-
"""
MODULE_NAME: heal_knowledge.py
PURPOSE: '값싼 방법(정적/동적 휴리스틱·구조 캐스케이드·_relocate)으로는 못 찾고, 비싼 full-HTML LLM
         으로만 뚫린' 치유 케이스를 [왜 못 찾았나 + 무엇이 답이었나] 로 기록하는 실패 진단 저널.
         1차 목적은 '런타임 재사용'이 아니라 '엔진 개선의 근거' — 사람(개발자)이 읽고 휴리스틱을 고쳐
         다음엔 값싼 경로가 잡게 만드는 피드백 루프(LLM 의존을 구조적으로 줄인다). 순수 저장/조회만.
DEPENDENCY: 표준 라이브러리(json/os) + paths(RECIPE_DIR) + safe_io. engine/llm/crawlers/DOM 무관(leaf).

[왜 남기나 — 레시피와 역할이 다르다]
- 레시피(_persist): 그 '사이트'의 정답 위치를 캐시 → 재방문 시 가벼움(사이트별). 이미 존재.
- heal_knowledge: '왜 값싼 방법이 실패했나'의 증거를 모아 → 휴리스틱/시그니처 로직 자체를 개선(전 사이트).
  부차 목적: 익명화 공유 자산, 그리고 훗날(규칙 성숙 시) 런타임 큐 재사용(_relocate 단일 패스 돌파).

[큐 항목(권장)]
- 정체: field, site, example, source(=어느 계단이 풀었나: heuristic/relocate/full_llm)
- 답:   tag, attr, class_token, shape(②의 _value_shape), path
- 진단: tried(실패한 값싼 방법들 [class/signature/structural_path/heuristic/relocate]),
        why(짧은 사유 예: 'structural path=None'/'no heuristic matcher'/'text cue mismatch'),
        context(진단용 HTML 스니펫 일부), when(시각)
  → 저장소는 임의 dict 를 그대로 받으므로 스키마는 소비자가 확장 가능(코드 변경 불필요).

[지금 넣지 않는 것(YAGNI)]
- hits/misses 랭킹·도태: 런타임 재사용은 아직 부차 목적이고, 소비자가 큐를 '전부 시도'+②검증하면
  빗나감이 무해. 규칙이 늘어 '전부 시도'가 비싸질 때 재고한다.
"""
from __future__ import annotations

import json
import os

import safe_io
from paths import RECIPE_DIR

# 여러 사이트에 걸친 '누적 지식' — 특정 레시피가 아니라 치유 노하우라 별도 파일.
HINTS_PATH = os.path.join(RECIPE_DIR, "_heal_hints.json")
# 해결(코드 개선 완료)된 사건의 이력. 활성 저널에서 빠진 것들이 여기 남아 '무엇을 왜 고쳤나'가 보존된다.
RESOLVED_PATH = os.path.join(RECIPE_DIR, "_heal_resolved.json")


def _load(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def _key(c):
    """중복 판정 키 — 같은 (사이트, 필드, 경로)면 같은 큐로 본다."""
    return (c.get("site", ""), c.get("field", ""),
            json.dumps(c.get("path") or [], ensure_ascii=False, sort_keys=True))


def record(cue, path=None):
    """성공 해결 큐 1건 축적(append). 같은 (site, field, path)면 최신으로 교체(중복 방지)."""
    path = path or HINTS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    hints = [c for c in _load(path) if _key(c) != _key(cue)]
    hints.append(dict(cue))
    # 엑셀이 열 파일은 아니지만 다른 쓰기 지점과 일관되게 잠금 대기(구멍 방지).
    with safe_io.open_when_writable(path, "w", encoding="utf-8") as f:
        json.dump(hints, f, ensure_ascii=False, indent=2)


def hints_for(field, site="", path=None):
    """그 필드의 큐 목록. 사이트 일치 우선 → 크로스사이트 폴백(각 그룹 최신 먼저).
    소비자(llm_locators)는 이 순서로 '전부 시도'하고 ②로 검증해 첫 통과를 채택한다."""
    hints = [c for c in _load(path or HINTS_PATH) if c.get("field") == field]
    same = [c for c in hints if site and c.get("site") == site]
    other = [c for c in hints if not (site and c.get("site") == site)]
    return list(reversed(same)) + list(reversed(other))


def resolve(cue, note="", path=None, resolved_path=None):
    """개선(코드 수정) 완료 시: 사건을 resolved 로그에 '기록한 뒤' 활성 저널에서 '삭제'한다.
    → 활성 저널(_heal_hints.json)엔 '아직 안 고친' 이슈만 남는다(자기 정리). 반환: 삭제된 건수.
    (fix_prompt 마무리가 지시하는 라이프사이클 — 개발자/코딩 AI 가 개선 반영 후 호출)."""
    import datetime
    path = path or HINTS_PATH
    rp = resolved_path or RESOLVED_PATH
    active = _load(path)
    removed = [c for c in active if _key(c) == _key(cue)]
    if not removed:
        return 0
    kept = [c for c in active if _key(c) != _key(cue)]
    log = _load(rp)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for c in removed:
        rec = dict(c)
        rec["resolved_note"], rec["resolved_at"] = note, now
        log.append(rec)
    os.makedirs(os.path.dirname(rp) or ".", exist_ok=True)
    with safe_io.open_when_writable(rp, "w", encoding="utf-8") as f:      # 먼저 이력 기록
        json.dump(log, f, ensure_ascii=False, indent=2)
    with safe_io.open_when_writable(path, "w", encoding="utf-8") as f:    # 그다음 활성에서 삭제
        json.dump(kept, f, ensure_ascii=False, indent=2)
    return len(removed)


def all_hints(path=None):
    """진단/공유용 전체 큐(원본 순서)."""
    return _load(path or HINTS_PATH)

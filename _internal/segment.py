# -*- coding: utf-8 -*-
"""
MODULE_NAME: segment.py
PURPOSE: (v5.0 slice 1a) '한 텍스트 노드에 뭉친 여러 필드'를 사용자가 준 예시 값의 경계로 분리하는 leaf.
         하드코딩된 사이트 규칙이 아니라, 예시 값들에서 구분자(seps)를 역으로 도출해 추출 때 그 자리에서
         쪼갠다. 자가치유 엔진이 build(경계 도출)/extract(적용)에서 사용. 구조 텍스트 정규화만 의존.
DEPENDENCY: structure(leaf)만. engine/cli/values/llm 을 import 하지 않는다(leaf).
"""
from __future__ import annotations

from structure import _norm


def _split_segments(text, seps):
    """텍스트를 구분자 리스트로 순차 분할 → k개 세그먼트(seps 길이 = k-1)."""
    parts, rest = [], text
    for sep in seps or []:
        if sep and sep in rest:
            head, rest = rest.split(sep, 1)
        else:
            head, rest = rest, ""
        parts.append(head)
    parts.append(rest)
    return parts


def _segment_value(text, seps, index):
    """seg 규칙이 있으면 text 에서 이 필드의 조각만 반환(없거나 범위 밖이면 원문)."""
    if not text or not seps or index is None:
        return text
    parts = _split_segments(text, seps)
    if 0 <= index < len(parts):
        return _norm(parts[index])
    return text


def _derive_colocated_split(node_text, members):
    """한 노드 텍스트에 여러 필드 예시가 '겹치지 않고 순서대로' 들어 있으면, 사이 구분자(seps)와
    각 필드의 조각 번호를 예시에서 파생한다(사이트 무관). members: [(name, example), ...].
    반환 {name: (index, seps, segment_text)} 또는 None(못 쪼갬 → 분리 안 함)."""
    located = []
    for name, ex in members:
        ex = _norm(ex or "")
        if not ex:
            return None
        i = node_text.find(ex)
        if i < 0:
            return None
        located.append((i, i + len(ex), name, ex))
    located.sort()
    seps = []
    for a, b in zip(located, located[1:]):
        if b[0] < a[1]:            # 겹침 → 경계 애매 → 분리 안 함
            return None
        gap = node_text[a[1]:b[0]]
        if gap == "":              # 딱 붙음 → 경계 불명 → 분리 안 함
            return None
        seps.append(gap)
    return {name: (idx, list(seps), ex)
            for idx, (_s, _e, name, ex) in enumerate(located)}

# -*- coding: utf-8 -*-
"""
MODULE_NAME: dedup.py
PURPOSE: 레코드 중복 제거 키 helper leaf — '변별력 있는 링크'로 dedup 하되, 가짜 링크(javascript:;/#)는
         모든 행이 같아 dedup 을 망치므로 키에서 제외한다. cli(crawl_all/save_csv)와 autoheal(try_auto_heal)
         이 공유하던 것을 leaf 로 분리(순환 차단 — cli↔autoheal 사이에 두지 않는다).
DEPENDENCY: 값 판별은 values(leaf)만. engine/cli 를 import 하지 않는다.
"""
from __future__ import annotations

from values import is_real_href


def _rec_key(r, fields, url_field=None):
    """레코드 중복 제거 키.
    url_field 가 지정되면 그 값으로, 아니면 '실제 링크'인 _url 필드, 그것도 없으면 값 전체.
    (javascript:;/# 같은 가짜 링크는 모든 행이 같아 dedup 을 망치므로 키로 안 씀)
    """
    if url_field is not None:
        v = r.get(url_field)
        if v:
            return ("u", v)
    else:
        for k in fields:
            if k.endswith("_url") or k == "링크":
                v = r.get(k)
                if v and is_real_href(str(v)):
                    return ("u", v)
    return ("t", tuple(str(r.get(k)) for k in fields))


def _choose_url_field(rows, fields):
    """page-1 행들로 dedup 에 쓸 '변별력 있는' 링크 필드를 고른다.
    링크 값이 행마다 충분히 다르면 그 필드를, 아니면 None(값 전체로 dedup)."""
    for k in fields:
        if not (k.endswith("_url") or k == "링크"):
            continue
        vals = [str(r.get(k)) for r in rows if r.get(k) and is_real_href(str(r.get(k)))]
        if vals and len(set(vals)) >= max(2, 0.6 * len(rows)):
            return k
    return None

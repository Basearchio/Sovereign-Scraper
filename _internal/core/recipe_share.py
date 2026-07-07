# -*- coding: utf-8 -*-
"""
MODULE_NAME: core/recipe_share.py
PURPOSE: 레시피를 '공유용으로 정제(마스킹)'한다. 자동 저장된 레시피에는 내 실제 크롤 URL(검색어)과
         스크랩 스니펫(example)이 박혀 있어 그대로 공개하면 개인정보가 샌다. 이 모듈은 구조 규칙
         (셀렉터/경로/시그니처)은 보존하고, url 의 검색어·example 스니펫만 지워 recipes/shared/ 로 뽑는다.
DEPENDENCY: 표준 라이브러리(urllib.parse/os) + core.schema. 내부 상위 모듈 import 없음(leaf).

[검증된 주요 사이트 및 케이스]
- 검색형(saramin/incruit/coupang): 쿼리 값(searchword/q 등) → EXAMPLE, 숫자(page)는 보존.
- 경로매립형(skyscanner 날짜, youtube list): 긴 숫자 경로 세그먼트(≥5자리) → N, list= 등 쿼리값 마스킹.

[테스트/운영 교훈]
- 자동 마스킹은 '검색어 누출'을 없애지만 경로에 남은 특이값(항공 노선코드 등)까지 완벽히 지우진
  못한다 → 호출부는 반드시 '검토하라'고 안내한다(사람이 최종 확인).
- 레시피는 구조 경로/셀렉터로 동작하므로 example 을 비워도 추출은 된다(LLM 치유 힌트만 약해짐).
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from core.schema import Schema


def mask_url(url: str, placeholder: str = "EXAMPLE") -> str:
    """공유용 URL 마스킹. 도메인/경로 구조는 남기되 '검색어(쿼리 값)'와 '긴 숫자 경로'는 가린다.
    · http(s): 쿼리 값 → placeholder(짧은 숫자만 보존, ≥5자리 숫자 ID 는 마스킹), 경로의 ≥5자리 숫자 세그먼트 → 'N'.
    · 파일 경로(체인의 목록 CSV 등): 개인 경로 노출 방지로 basename 만."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        # 로컬 파일 경로(체인의 목록 CSV 등) — 'C:\\' 를 scheme 으로 오인하지 않도록 여기서 처리.
        return os.path.basename(url.replace("\\", "/")) or placeholder
    try:
        s = urlsplit(url)
    except Exception:
        return placeholder
    segs = ["N" if (seg.isdigit() and len(seg) >= 5) else seg
            for seg in s.path.split("/")]
    path = "/".join(segs)
    q = parse_qsl(s.query, keep_blank_values=True)
    # 짧은 숫자(page=2, adultsv2=1 등 구조적 값)만 보존; ≥5자리 숫자는 ID(공고/상품 번호 등)로 보고
    # 마스킹한다(경로 세그먼트 규칙과 동일). 이게 없으면 chain clean_url 의 job=2606230002617 같은 게 샌다.
    mq = urlencode([(k, v if (v.isdigit() and len(v) < 5) else placeholder) for k, v in q])
    return urlunsplit((s.scheme, s.netloc, path, mq, ""))


def sanitize_recipe(src_path: str, dst_path: str) -> dict:
    """[역할] src 레시피를 읽어 개인정보(url 검색어·example 스니펫·chain clean_url)를 마스킹/제거한 뒤
    dst 로 저장. 구조 규칙은 그대로. [반환] 요약 dict(원본/마스킹 url, 지운 example 수, chain 여부)."""
    schema, url, load_method, wait, pages = Schema.from_csv_recipe(src_path)
    meta = Schema.read_recipe_meta(src_path)

    cleared = 0
    for f in schema.fields.values():       # 스크랩 스니펫 힌트 제거
        if f.get("example"):
            cleared += 1
        f["example"] = ""

    masked_url = mask_url(url)
    extra = {}
    is_chain = meta.get("chain") == "1"
    if is_chain:                           # 체인 레시피: url_col 은 규칙(보존), clean_url 은 마스킹
        extra = {"chain": "1", "url_col": meta.get("url_col", ""),
                 "clean_url": mask_url(meta.get("clean_url", ""))}

    schema.save_csv_recipe(dst_path, url=masked_url, load_method=load_method,
                           wait=int(wait or 0), pages=int(pages or 1), extra_meta=extra)
    return {"orig_url": url, "masked_url": masked_url,
            "examples_cleared": cleared, "chain": is_chain, "dst": dst_path}


def retarget_recipe(src_path: str, new_url: str, dst_path: str) -> str:
    """[역할] 남이 공유한(마스킹된) 레시피를 '내 URL'에 붙여 쓰도록, 구조는 그대로 두고 meta.url 만
    new_url 로 바꿔 dst 로 저장한다(= sanitize 의 역방향). 이렇게 저장해야 cli 가 new_url 로 크롤할 때
    슬롯(recipe_path_for = netloc+path+query 매칭)이 맞아 '자동 로드'된다. [반환] dst 경로.
    체인 레시피의 clean_url 은 마스킹된 채로 둔다(체인 자동 적용은 아직 부분 지원)."""
    schema, _url, load_method, wait, pages = Schema.from_csv_recipe(src_path)
    meta = Schema.read_recipe_meta(src_path)
    extra = {}
    if meta.get("chain") == "1":
        extra = {"chain": "1", "url_col": meta.get("url_col", ""),
                 "clean_url": meta.get("clean_url", "")}
    schema.save_csv_recipe(dst_path, url=new_url, load_method=load_method,
                           wait=int(wait or 0), pages=int(pages or 1), extra_meta=extra)
    return dst_path

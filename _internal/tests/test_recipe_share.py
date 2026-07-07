# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_recipe_share.py
PURPOSE: '공유용 레시피 정제(--export-recipe)'의 행동 골든 — url 검색어·example 스니펫을 마스킹/제거하되
         구조 규칙(시그니처/필드/경로/로드방식)은 보존하는지를 결정적으로 못박는다(개인정보 누출 방지).
DEPENDENCY: 표준 라이브러리만(오프라인 결정적).

[검증된 주요 사이트 및 케이스]
- 검색형(saramin): searchword=... → EXAMPLE, page 숫자 보존.
- 경로매립형(skyscanner): 긴 숫자 경로(날짜) → N. 체인: clean_url 마스킹 + url_col(규칙) 보존.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import asdict
from core.schema import Schema, FieldSchema
from core.recipe_share import mask_url, sanitize_recipe, retarget_recipe


def test_mask_url_masks_search_keeps_numbers():
    assert mask_url("https://www.saramin.co.kr/search?searchword=ax+자동화&page=2") \
        == "https://www.saramin.co.kr/search?searchword=EXAMPLE&page=2"


def test_mask_url_masks_long_numeric_path_segments():
    got = mask_url("https://www.skyscanner.co.kr/transport/flights/sela/hgh/261001/261004/?adultsv2=1")
    assert got == "https://www.skyscanner.co.kr/transport/flights/sela/hgh/N/N/?adultsv2=1"


def test_mask_url_masks_long_numeric_query_id_keeps_short():
    # 긴 숫자 쿼리값(공고/상품 ID)은 마스킹, 짧은 숫자(page/flag)는 보존 (체인 clean_url job= 누출 회귀 가드).
    assert mask_url("https://job.incruit.com/jobdb_info/jobpost.asp?job=2606230002617") \
        == "https://job.incruit.com/jobdb_info/jobpost.asp?job=EXAMPLE"
    assert mask_url("https://x/list?page=2&rtn=1&adultsv2=1") == "https://x/list?page=2&rtn=1&adultsv2=1"


def test_mask_url_file_path_to_basename():
    assert mask_url(r"C:\Users\me\output\jobs_detail.csv") == "jobs_detail.csv"
    assert mask_url("") == ""


def _make_recipe(path, url, chain=False):
    s = Schema("a.t", "li", None, "li[a,span]")
    s.fields = {
        "제목": asdict(FieldSchema("a.t", "a", "t", [["a", 0]], None, "실제 스크랩 제목 스니펫")),
        "제목_url": asdict(FieldSchema("a.t", "a", "t", [["a", 0]], "href", "https://x/1")),
    }
    extra = {"chain": "1", "url_col": "직무_url",
             "clean_url": "https://job.example/view?idx=99&src=list"} if chain else None
    s.save_csv_recipe(path, url=url, load_method="render", wait=3, pages=2, extra_meta=extra)


def test_sanitize_masks_url_and_clears_examples_keeps_structure():
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "src.csv"), os.path.join(d, "shared.csv")
        _make_recipe(src, "https://www.saramin.co.kr/search?searchword=비밀검색어&page=2")
        summary = sanitize_recipe(src, dst)
        assert summary["examples_cleared"] == 2
        s2, url2, lm2, w2, p2 = Schema.from_csv_recipe(dst)
        # url: 검색어 제거, 숫자 보존
        assert "비밀검색어" not in url2 and "searchword=EXAMPLE" in url2 and "page=2" in url2
        # example 스니펫 전부 제거
        assert all(f["example"] == "" for f in s2.fields.values())
        # 구조 규칙은 보존(재현 가능해야 함)
        assert s2.row_signature == "li[a,span]"
        assert set(s2.fields) == {"제목", "제목_url"}
        assert s2.fields["제목"]["path"] == [["a", 0]]
        assert lm2 == "render" and w2 == 3 and p2 == 2


def test_sanitize_chain_masks_clean_url_keeps_url_col():
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "src.csv"), os.path.join(d, "shared.csv")
        _make_recipe(src, r"C:\Users\me\output\jobs.csv", chain=True)
        summary = sanitize_recipe(src, dst)
        assert summary["chain"] is True
        meta = Schema.read_recipe_meta(dst)
        assert meta.get("chain") == "1"
        assert meta.get("url_col") == "직무_url"            # 규칙(보존)
        assert "src=list" not in meta.get("clean_url", "")   # clean_url 마스킹됨
        assert meta.get("url") == "jobs.csv"                 # 파일경로 → basename


def test_retarget_sets_my_url_keeps_structure():
    """공유(마스킹) 레시피를 내 URL 로 재지정 → 구조 보존 + url 이 내 것 → 슬롯 매칭돼 자동로드 가능."""
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "shared.csv"), os.path.join(d, "mine.csv")
        _make_recipe(src, "https://www.saramin.co.kr/search?searchword=EXAMPLE&page=2")
        mine = "https://www.saramin.co.kr/search?searchword=내검색어&page=1"
        assert retarget_recipe(src, mine, dst) == dst
        s2, url2, lm2, w2, p2 = Schema.from_csv_recipe(dst)
        assert url2 == mine                                    # meta.url = 내 URL(슬롯 매칭 핵심)
        assert s2.row_signature == "li[a,span]"                # 구조 규칙 보존
        assert set(s2.fields) == {"제목", "제목_url"}
        assert lm2 == "render" and w2 == 3 and p2 == 2         # 로드/대기/페이지 보존


def test_retarget_chain_preserves_url_col():
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "shared.csv"), os.path.join(d, "mine.csv")
        _make_recipe(src, "listfile.csv", chain=True)
        retarget_recipe(src, r"C:\Users\me\my_list.csv", dst)
        meta = Schema.read_recipe_meta(dst)
        assert meta.get("chain") == "1" and meta.get("url_col") == "직무_url"
        assert meta.get("url") == r"C:\Users\me\my_list.csv"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

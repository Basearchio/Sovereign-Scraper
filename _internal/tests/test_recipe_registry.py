# -*- coding: utf-8 -*-
"""tests/test_recipe_registry.py — 공유 레시피 레지스트리 읽기 클라이언트(core.recipe_registry).
네트워크는 fetch 주입으로 대체 → 오프라인·결정적 검증. (받기: 검색·다운로드 / 공유: 업로드 URL)"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import recipe_registry as R

_INDEX = {
    "version": 1,
    "recipes": [
        {"id": "saramin_jobs", "site": "saramin.co.kr", "category": "채용",
         "fields": ["공고제목", "경력"], "file": "recipes/saramin_jobs.csv", "desc": "사람인 검색결과"},
        {"id": "coupang_items", "site": "coupang.com", "category": "쇼핑",
         "fields": ["상품명", "가격"], "file": "recipes/coupang_items.csv", "desc": "쿠팡 검색"},
        {"id": "bad_entry", "site": "x.com"},   # file 없음 → 걸러져야 함
    ],
}


def _fetch_for(mapping):
    """url→bytes 매핑을 쓰는 가짜 fetch. 없으면 KeyError(=네트워크 실패 흉내)."""
    def _f(url, timeout=15):
        return mapping[url]
    return _f


def test_resolve_defaults_and_override():
    raw, web = R.resolve_registry()
    assert raw.endswith("/") and "shc-recipes" in raw
    assert web.startswith("https://github.com/")
    raw2, web2 = R.resolve_registry({"RECIPE_REGISTRY_RAW": "https://x.dev/r",
                                     "RECIPE_REGISTRY_WEB": "https://github.com/me/reg/"})
    assert raw2 == "https://x.dev/r/"          # 끝에 / 보정
    assert web2 == "https://github.com/me/reg"  # 끝 / 제거


def test_is_configured():
    assert not R.is_configured(R.DEFAULT_RAW_BASE)              # placeholder(OWNER) → 미설정
    assert R.is_configured("https://raw.githubusercontent.com/me/shc-recipes/main/")


def test_fetch_index_parses_and_filters_invalid():
    raw = "https://raw.example/main/"
    fetch = _fetch_for({raw + "index.json": json.dumps(_INDEX).encode("utf-8")})
    entries = R.fetch_index(raw, fetch=fetch)
    assert len(entries) == 2                     # bad_entry(file 없음) 제외
    assert {e["id"] for e in entries} == {"saramin_jobs", "coupang_items"}


def test_fetch_index_tolerates_garbage():
    raw = "https://raw.example/main/"
    assert R.fetch_index(raw, fetch=_fetch_for({raw + "index.json": b"not json{"})) == []
    def _boom(url, timeout=15):
        raise OSError("network down")
    assert R.fetch_index(raw, fetch=_boom) == []   # 네트워크 실패도 조용히 []


def test_search_keyword_and_empty():
    entries = _INDEX["recipes"][:2]
    assert {e["id"] for e in R.search(entries, "채용")} == {"saramin_jobs"}      # category
    assert {e["id"] for e in R.search(entries, "COUPANG")} == {"coupang_items"}  # 대소문자 무시(site)
    assert {e["id"] for e in R.search(entries, "가격")} == {"coupang_items"}      # fields
    assert len(R.search(entries, "")) == 2                                        # 빈 쿼리=전체
    assert R.search(entries, "존재안함") == []


def test_download_recipe_writes(tmp_path=None):
    import tempfile
    raw = "https://raw.example/main/"
    entry = _INDEX["recipes"][0]
    body = b"kind,name,tag\nmeta,url,https://saramin.co.kr/...\n"
    fetch = _fetch_for({raw + "recipes/saramin_jobs.csv": body})
    with tempfile.TemporaryDirectory() as d:
        dst = R.download_recipe(entry, raw, d, fetch=fetch)
        assert os.path.basename(dst) == "saramin_jobs.csv"
        assert open(dst, "rb").read() == body


def test_share_page_url():
    assert R.share_page_url("https://github.com/me/shc-recipes") == \
        "https://github.com/me/shc-recipes/upload/main/recipes"


def test_registry_is_leaf():
    """core.recipe_registry 는 표준 라이브러리만 import(내부 상위 모듈 결합 없음)."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "recipe_registry.py"), encoding="utf-8").read()
    for banned in ("import engine", "import cli", "import locators", "from engine", "from cli",
                   "import schema", "from core"):   # 생성기도 주입식 → schema 결합 없이 stdlib 순수
        assert banned not in src


def test_build_index_format():
    recipes = [
        {"name": "saramin_공고제목_경력.csv", "site": "www.saramin.co.kr",
         "category": "채용 검색", "fields": ["공고제목", "경력"], "chain": False, "load": "auto"},
        {"name": "chain_직무_url.csv", "site": "job.incruit.com",
         "category": "채용 검색", "fields": ["상세"], "chain": True, "load": "auto"},
        {"name": "", "site": "무시"},   # 이름 없음 → 걸러짐
    ]
    idx = R.build_index(recipes)
    assert idx["version"] == 1 and len(idx["recipes"]) == 2
    e = idx["recipes"][0]
    assert e["id"] == "saramin_공고제목_경력"
    assert e["file"] == "recipes/saramin_공고제목_경력.csv"   # raw_base 기준 상대경로
    assert e["fields"] == ["공고제목", "경력"] and e["category"] == "채용 검색" and e["load"] == "auto"
    assert e["desc"] == "www.saramin.co.kr — 공고제목, 경력"
    assert idx["recipes"][1]["desc"].endswith("[체인]")      # 체인 표시


def test_build_index_default_category_and_roundtrip():
    # category 없으면 '기타'; 생성물이 fetch_index/search 로 그대로 소비되는지 왕복 검증(계약 일치).
    idx = R.build_index([{"name": "foo.csv", "site": "foo.com", "fields": ["a"]}])
    assert idx["recipes"][0]["category"] == "기타"
    raw = "https://raw.githubusercontent.com/me/shc-recipes/main/"
    entries = R.fetch_index(raw, fetch=_fetch_for({raw + "index.json": json.dumps(idx).encode("utf-8")}))
    assert len(entries) == 1 and R.search(entries, "foo")[0]["file"] == "recipes/foo.csv"

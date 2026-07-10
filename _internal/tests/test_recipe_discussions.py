# -*- coding: utf-8 -*-
"""tests/test_recipe_discussions.py — GitHub Discussions 공유 게시판 URL 빌더(core.recipe_discussions).
네트워크·API 호출 없음(순수 문자열 조립) → 오프라인·결정적 검증."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import recipe_discussions as D


def test_resolve_defaults_and_override():
    web, cat = D.resolve_discussions()
    assert web == "https://github.com/Basearchio/Sovereign-Scraper"
    assert cat == "recipes"
    web2, cat2 = D.resolve_discussions({"RECIPE_DISCUSSIONS_REPO": "https://github.com/me/fork/",
                                        "RECIPE_DISCUSSIONS_CATEGORY": "레시피"})
    assert web2 == "https://github.com/me/fork"     # 끝 / 제거
    assert cat2 == "레시피"


def test_search_url_empty_query_is_category_listing():
    url = D.search_url("https://github.com/me/fork", "recipes", "")
    assert url == "https://github.com/me/fork/discussions/categories/recipes"


def test_search_url_with_query_is_urlencoded():
    url = D.search_url("https://github.com/me/fork", "recipes", "사람인 채용")
    assert url.startswith("https://github.com/me/fork/discussions/categories/recipes?discussions_q=")
    assert "%EC%82%AC%EB%9E%8C%EC%9D%B8" in url    # '사람인' 이 인코딩됐는지


def test_build_post_body_contains_manifest_and_csv_block():
    body = D.build_post_body("saramin.co.kr", ["공고제목", "경력"], "auto", "kind,name\nmeta,url,https://x")
    assert "- site: saramin.co.kr" in body
    assert "- fields: 공고제목, 경력" in body
    assert "- load: auto" in body
    assert "```csv\nkind,name\nmeta,url,https://x\n```" in body


def test_build_post_body_no_fields():
    body = D.build_post_body("x.com", [], "", "kind,name")
    assert "- fields: (none)" in body


def test_new_post_url_prefills_title_and_body():
    url, included = D.new_post_url("https://github.com/me/fork", "recipes", "saramin_공고제목", "본문내용")
    assert included is True
    assert url.startswith("https://github.com/me/fork/discussions/new?category=recipes&title=")
    assert "title=saramin_%EA%B3%B5%EA%B3%A0%EC%A0%9C%EB%AA%A9" in url
    assert "body=" in url


def test_new_post_url_without_body():
    url, included = D.new_post_url("https://github.com/me/fork", "recipes", "제목")
    assert included is False
    assert "body=" not in url


def test_new_post_url_drops_oversized_body():
    huge = "x" * 10000
    url, included = D.new_post_url("https://github.com/me/fork", "recipes", "제목", huge)
    assert included is False
    assert "body=" not in url
    assert len(url) < 200    # body 없이 title/category 만


def test_recipe_discussions_is_leaf():
    """core.recipe_discussions 는 표준 라이브러리만 import(내부 상위 모듈 결합 없음)."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "recipe_discussions.py"), encoding="utf-8").read()
    for banned in ("import engine", "import cli", "import locators", "from engine", "from cli",
                   "import schema", "from core"):
        assert banned not in src

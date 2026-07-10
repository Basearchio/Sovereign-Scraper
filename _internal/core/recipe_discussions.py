# -*- coding: utf-8 -*-
"""
MODULE_NAME: core/recipe_discussions.py
PURPOSE: 공유 레시피를 GitHub Discussions 게시판으로 주고받기 위한 URL 빌더.
         받기(검색)를 앱이 API로 직접 하려면 public repo 라도 GitHub 토큰(로그인)이 필요해
         '무인증' 원칙과 충돌한다 — 그래서 검색은 브라우저로 게시판을 열어 사람이 훑어보고,
         마음에 드는 글의 CSV(코드블록)를 복사해 inbox 에 저장하는 방식으로 대체한다.
         올리기(공유)도 브라우저로 '새 글쓰기'를 제목/본문 프리필해서 열어, 사람이 마스킹 결과를
         확인한 뒤 제출한다.
DEPENDENCY: 표준 라이브러리(urllib.parse)만. 내부 상위 모듈 import 없음(leaf).
"""
from urllib.parse import quote

DEFAULT_REPO_WEB = "https://github.com/Basearchio/Sovereign-Scraper"
DEFAULT_CATEGORY = "recipes"

# GitHub 새 글쓰기 URL 은 title/body 를 querystring 으로 프리필할 수 있지만 길이 한계가 있다
# (브라우저·서버 양쪽). 넘으면 body 프리필을 포기하고 사람이 직접 붙여넣게 안내한다.
_MAX_URL_LEN = 6000


def resolve_discussions(env=None):
    """(repo_web, category) 를 돌려준다. env(dict, 예: .env 읽은 것)로 덮어쓰기 가능(자기 fork 운영 시)."""
    env = env or {}
    web = (env.get("RECIPE_DISCUSSIONS_REPO") or DEFAULT_REPO_WEB).strip().rstrip("/")
    category = (env.get("RECIPE_DISCUSSIONS_CATEGORY") or DEFAULT_CATEGORY).strip()
    return web, category


def search_url(repo_web, category, query=""):
    """게시판 검색 페이지 URL(브라우저로 열 용도). 빈 쿼리면 카테고리 전체 목록."""
    base = f"{repo_web}/discussions/categories/{category}"
    q = (query or "").strip()
    return f"{base}?discussions_q={quote(q)}" if q else base


def build_post_body(site, fields, load_method, csv_text):
    """공유 글 본문 — 매니페스트(사이트·필드·로드방식) + 마스킹된 CSV 원문(코드블록).
    받는 사람이 이 코드블록을 그대로 복사해 inbox 에 파일로 저장하면 끝."""
    head = [
        f"- site: {site}",
        f"- fields: {', '.join(fields) if fields else '(none)'}",
        f"- load: {load_method or ''}",
    ]
    return "\n".join(head) + "\n\n```csv\n" + (csv_text or "").rstrip() + "\n```\n"


def new_post_url(repo_web, category, title, body=""):
    """새 글쓰기 프리필 URL(브라우저로 열 용도). 반환: (url, body_included).
    body 포함 시 URL 이 너무 길어지면(_MAX_URL_LEN 초과) body 없이 돌려주고 False — 호출부가
    '본문을 못 채웠으니 직접 붙여넣으라'고 안내할 근거가 된다."""
    url = f"{repo_web}/discussions/new?category={quote(category)}&title={quote(title)}"
    if not body:
        return url, False
    full = f"{url}&body={quote(body)}"
    if len(full) <= _MAX_URL_LEN:
        return full, True
    return url, False

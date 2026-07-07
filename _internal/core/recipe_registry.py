# -*- coding: utf-8 -*-
"""
MODULE_NAME: core/recipe_registry.py
PURPOSE: 공유 레시피 '레지스트리'(공개 GitHub repo) 읽기 클라이언트 — 받기(검색·적용)를 인증/git 없이 HTTPS 로만.
         index.json 카탈로그를 받아 로컬에서 검색하고, 고른 레시피 CSV 를 다운로드한다.
         공유(올리기)는 앱이 직접 push 하지 않고 repo '업로드 페이지' URL 을 만들어 브라우저로 사람이 검수 제출한다
         (프라이버시: 레시피엔 크롤 URL=검색어가 박히므로 자동 push 금지. 마스킹은 core.recipe_share 가 담당).
DEPENDENCY: 표준 라이브러리(urllib/json/os)만. 네트워크는 fetch 주입으로 대체(테스트·오프라인). 내부 상위 모듈 import 없음(leaf).

레지스트리 구조(공개 repo):
    index.json                     # 카탈로그(아래 스키마)
    recipes/<id>.csv               # 마스킹된 공유 레시피(recipe_share.sanitize_recipe 산출물)
index.json:
    {"version":1,"recipes":[
       {"id":"saramin_jobs","site":"saramin.co.kr","category":"채용",
        "fields":["공고제목","경력"],"file":"recipes/saramin_jobs.csv","desc":"사람인 검색결과","load":"auto"}
    ]}
"""
import json
import os
from urllib.parse import urljoin

# 기본 레지스트리(공개 repo). .env 의 RECIPE_REGISTRY_RAW / RECIPE_REGISTRY_WEB 로 덮어쓸 수 있음.
DEFAULT_RAW_BASE = "https://raw.githubusercontent.com/OWNER/shc-recipes/main/"
DEFAULT_REPO_WEB = "https://github.com/OWNER/shc-recipes"


def resolve_registry(env=None):
    """(raw_base, repo_web) 를 돌려준다. env(dict, 예: os.environ/.env)로 덮어쓰기 가능(없으면 기본)."""
    env = env or {}
    raw = (env.get("RECIPE_REGISTRY_RAW") or DEFAULT_RAW_BASE).strip()
    if not raw.endswith("/"):
        raw += "/"
    web = (env.get("RECIPE_REGISTRY_WEB") or DEFAULT_REPO_WEB).strip().rstrip("/")
    return raw, web


def is_configured(raw_base):
    """레지스트리가 실제 주소로 설정됐는지(기본 placeholder 'OWNER' 그대로면 아직 미설정)."""
    return bool(raw_base) and "OWNER/" not in raw_base


def _default_fetch(url, timeout=15):
    """urllib 로 바이트를 받는다(요청 시에만 import — leaf 유지, requests 불요)."""
    from urllib.request import Request, urlopen
    req = Request(url, headers={"User-Agent": "shc-recipe-registry"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_index(raw_base, fetch=None):
    """레지스트리의 index.json 을 받아 recipe 항목 리스트를 돌려준다. 실패/형식오류면 [](조용히)."""
    fetch = fetch or _default_fetch
    try:
        data = fetch(urljoin(raw_base, "index.json"))
        doc = json.loads(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
    except Exception:
        return []
    recipes = doc.get("recipes") if isinstance(doc, dict) else doc
    return [e for e in (recipes or []) if isinstance(e, dict) and e.get("file")]


def search(entries, query):
    """키워드로 항목 필터(대소문자 무시). site/category/desc/id/fields 대상. 빈 쿼리면 전체."""
    q = (query or "").strip().lower()
    if not q:
        return list(entries)
    out = []
    for e in entries:
        hay = " ".join([
            str(e.get("id", "")), str(e.get("site", "")), str(e.get("category", "")),
            str(e.get("desc", "")), " ".join(e.get("fields", []) or []),
        ]).lower()
        if q in hay:
            out.append(e)
    return out


def download_recipe(entry, raw_base, dest_dir, fetch=None):
    """항목의 레시피 CSV 를 dest_dir 로 내려받고 저장 경로를 돌려준다. file 은 raw_base 기준 상대경로."""
    fetch = fetch or _default_fetch
    rel = entry["file"]
    data = fetch(urljoin(raw_base, rel))
    os.makedirs(dest_dir, exist_ok=True)
    dst = os.path.join(dest_dir, os.path.basename(rel))
    with open(dst, "wb") as f:
        f.write(data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8"))
    return dst


def share_page_url(repo_web):
    """공유(올리기) 시 브라우저로 열 'repo 업로드' 페이지 URL. 사람이 마스킹된 CSV 를 올려 PR 로 검수."""
    return f"{repo_web}/upload/main/recipes"


def _entry_desc(rec):
    """카탈로그 항목 설명: '<site> — <필드…>' (+ 체인 표시). 사람이 목록에서 알아보게."""
    site = str(rec.get("site") or "")
    fields = ", ".join(rec.get("fields") or [])
    tail = " [체인]" if rec.get("chain") else ""
    return (f"{site} — {fields}" if fields else site) + tail


def build_index(recipes):
    """[생성기·순수] 마스킹 레시피 메타 목록 → 레지스트리 카탈로그 dict(fetch_index 가 읽는 바로 그 형식).
    입력 recipes: [{"name":"x.csv", "site":str, "category":str, "fields":[...], "chain":bool, "load":str}, …]
    CSV 파싱·사이트 분류는 '주입'(호출 툴이 core.schema/paths/capabilities 로 준비) → 이 모듈은 stdlib 순수 유지.
    반환: {"version":1, "recipes":[{id,site,category,fields,file,desc,load}, …]} — file 은 raw_base 기준 'recipes/<name>'."""
    entries = []
    for r in recipes:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        stem = name[:-4] if name.lower().endswith(".csv") else name
        entries.append({
            "id": stem,
            "site": str(r.get("site") or ""),
            "category": str(r.get("category") or "기타"),
            "fields": list(r.get("fields") or []),
            "file": f"recipes/{name}",
            "desc": _entry_desc(r),
            "load": str(r.get("load") or ""),
        })
    return {"version": 1, "recipes": entries}

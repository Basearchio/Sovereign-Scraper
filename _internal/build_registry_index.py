# -*- coding: utf-8 -*-
"""
MODULE_NAME: build_registry_index.py  (유지보수 도구 · 별개 실행)
PURPOSE: outbox 의 '마스킹된 공유 레시피'들을 스캔해 **공개 레지스트리 페이로드**(index.json + recipes/)를
         만든다. 나중에 공개 `shc-recipes` repo 루트에 그대로 올리면 앱의 '온라인에서 찾기'가 작동한다.
         ★현재 공개는 보류(i18n 후) — 이 도구는 '준비'만. 스위치는 준비돼 있게.
DEPENDENCY: 표준 라이브러리 + core.schema/paths/capabilities/core.recipe_share·recipe_registry. leaf 아님(도구).

사용: python _internal/build_registry_index.py            # outbox → recipes/shared/registry_build/
      python _internal/build_registry_index.py --src <dir> --out <dir>

안전장치(공개 전 이중 방어): 레시피마다 '완전 마스킹' 재검 —
  · url·clean_url 이 mask_url 로 더 이상 안 바뀌면(멱등) 이미 마스킹된 것, 바뀌면 개인정보 잔존 → 제외+경고
  · field example(스크랩 스니펫)이 남아 있으면 → 제외+경고
새는 레시피는 index 에 넣지 않는다(공개 누출 차단).
"""
import argparse
import glob
import json
import os
import shutil
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # _internal 을 검색경로에(직접 실행 대응)

import paths
import capabilities
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)
from core.schema import Schema
from core.recipe_share import mask_url
from core import recipe_registry as reg


def _leaks_of(path):
    """레시피 1개의 마스킹 누출 사유 리스트(비면 깨끗). schema/meta 도 함께 반환."""
    schema, url, load_method, _w, _p = Schema.from_csv_recipe(path)
    meta = Schema.read_recipe_meta(path)
    reasons = []
    if url and mask_url(url) != url:
        reasons.append("url 미마스킹")
    clean_url = meta.get("clean_url", "")
    if clean_url and mask_url(clean_url) != clean_url:
        reasons.append("clean_url 미마스킹")
    if any((f.get("example") or "").strip() for f in schema.fields.values()):
        reasons.append("example 잔존")
    return reasons, schema, url, load_method, meta


def collect(src_dir):
    """src_dir 의 *.csv 를 검사해 (레시피 메타 목록, 제외목록) 반환. 제외=누출 있는 것."""
    recipes, skipped = [], []
    fallback = getattr(capabilities, "_FALLBACK", "기타")
    for path in sorted(glob.glob(os.path.join(src_dir, "*.csv"))):
        name = os.path.basename(path)
        try:
            reasons, schema, url, load_method, meta = _leaks_of(path)
        except Exception as e:
            skipped.append((name, [f"읽기 실패: {e}"]))
            continue
        if reasons:
            skipped.append((name, reasons))
            continue
        label = paths._site_label(url)
        recipes.append({
            "name": name,
            "site": urlparse(url).netloc or label,
            "category": capabilities._CATEGORY.get(label, fallback),
            "fields": [n for n in schema.fields if not n.endswith("_url")],
            "chain": meta.get("chain") == "1",
            "load": load_method or "",
        })
    return recipes, skipped


def main():
    ap = argparse.ArgumentParser(description="공유 레시피 → 레지스트리 페이로드(index.json + recipes/) 생성")
    ap.add_argument("--src", default=paths.OUTBOX_DIR, help="마스킹 레시피 폴더(기본: recipes/shared/outbox)")
    ap.add_argument("--out", default=os.path.join(paths.SHARED_DIR, "registry_build"),
                    help="페이로드 출력 폴더(기본: recipes/shared/registry_build)")
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print("⚠ " + t("소스 폴더가 없습니다: {src}\n  먼저 start → 레시피 → 공유하기 로 outbox 에 마스킹본을 뽑으세요.", src=args.src))
        return 1
    recipes, skipped = collect(args.src)

    for name, reasons in skipped:
        print("  ⚠ " + t("제외: {name} — {reasons} (마스킹 다시 확인)", name=name, reasons=', '.join(reasons)))
    if not recipes:
        print(t("생성할 깨끗한 레시피가 없습니다."))
        return 1

    idx = reg.build_index(recipes)
    out_recipes = os.path.join(args.out, "recipes")
    os.makedirs(out_recipes, exist_ok=True)
    for r in recipes:
        shutil.copy2(os.path.join(args.src, r["name"]), os.path.join(out_recipes, r["name"]))
    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    print("\n✔ " + t("레지스트리 페이로드 생성 → {p}/", p=os.path.relpath(args.out, os.path.dirname(HERE))))
    print("   " + t("index.json ({n}개) + recipes/*.csv {skip}",
                  n=len(idx['recipes']), skip=(t("· 제외 {k}", k=len(skipped)) if skipped else "")))
    print("   " + t("공개 준비되면: 이 폴더 내용을 공개 shc-recipes repo 루트에 올리고, .env 에 RECIPE_REGISTRY_RAW/WEB 설정."))
    return 0


if __name__ == "__main__":
    sys.exit(main())

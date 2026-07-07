# -*- coding: utf-8 -*-
"""
MODULE_NAME: capabilities.py
PURPOSE: '역량 매트릭스' 자동 생성 도구(완전 별개 프로그램). output/ + recipes/ 를 읽어 사이트별로
         '실제로 가져온 필드'만 나열한다(사이트마다 항목이 다름). 크롤링/네트워크 없음(파일만).
         로컬은 실제 사이트명, --mask 는 카테고리로 익명화(= git 공개용). URL·쿼리·스크랩값은 어느 모드에서도
         출력하지 않는다(마스킹되는 것은 '페이지 유형' 한 컬럼뿐).
DEPENDENCY: 표준 라이브러리 + core.schema · paths(재사용). 메인 크롤 흐름과 독립.

사용:
  python capabilities.py                      # 실제 사이트명으로 표 출력(로컬 확인용)
  python capabilities.py --mask               # 사이트명 → 카테고리(공개용)
  python capabilities.py --mask -o docs/capabilities.md

[포함 기준] '실제로 가져온 것'의 근거는 output CSV 의 컬럼(부기 컬럼 crawled_at 제외)이다 — 레시피 필드명은
  내부 명칭(f1 등)이라 output 표시명(상품명 등)과 다를 수 있어 신뢰하지 않는다. 값이 하나라도 있는 컬럼만 V.
"""
import bootstrap  # 첫 실행: 가상환경(.venv) 안내·자동설치 후 venv 로 재실행
if __name__ == "__main__":
    bootstrap.ensure_env()

import os
import sys
import csv
import glob
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.schema import Schema
import paths
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)

# 마스킹용 사이트 라벨 → 카테고리(공개 시 브랜드 대신 유형만 노출). 필요 시 여기만 수정.
_CATEGORY = {
    "youtube": "동영상 플랫폼",
    "saramin": "채용 검색", "incruit": "채용 검색", "albamon": "채용 검색",
    "coupang": "커머스 검색", "naver": "커머스 검색",
    "skyscanner": "항공 검색", "x": "소셜/트렌드",
}
_FALLBACK = "웹 페이지"


_BOOKKEEPING = {"crawled_at"}   # 데이터가 아닌 부기 컬럼 → 필드에서 제외


def _output_fields(output_csv: str):
    """output CSV 의 실제 컬럼(부기 제외) → [(컬럼명, 채움률)], 행수. '가져온 것'의 진짜 근거."""
    if not os.path.exists(output_csv):
        return [], 0
    with open(output_csv, encoding="utf-8-sig", newline="") as f:
        dr = csv.DictReader(f)
        names = [c for c in (dr.fieldnames or []) if c not in _BOOKKEEPING]
        rows = list(dr)
    n = len(rows)
    fields = [(c, (sum(1 for r in rows if (r.get(c) or "").strip()) / n if n else 0.0))
              for c in names]
    return fields, n


def _label_of(core: str) -> str:
    """recipes_<core>.csv 의 core('incruit_1' 또는 'incruit_1__직무_url')에서 사이트 라벨."""
    listcore = core.split("__", 1)[0]          # incruit_1
    return listcore.rsplit("_", 1)[0] if "_" in listcore else listcore


def collect(recipe_dir=None, output_dir=None):
    """recipes/ + output/ 스캔 → 사이트별 역량 항목 리스트(파일만 읽음)."""
    recipe_dir = recipe_dir or paths.RECIPE_DIR
    output_dir = output_dir or paths.OUTPUT_DIR
    items = []
    for rp in sorted(glob.glob(os.path.join(recipe_dir, "recipes_*.csv"))):
        base = os.path.basename(rp)
        try:
            meta = Schema.read_recipe_meta(rp)
        except Exception:
            meta = {}
        out_csv = os.path.join(output_dir, "output_" + base[len("recipes_"):])
        fields, n = _output_fields(out_csv)
        core = base[len("recipes_"):-4]
        items.append({
            "label": _label_of(core),
            "load": meta.get("load_method", ""),
            "chain": meta.get("chain") == "1",
            "col": (core.split("__", 1)[1] if "__" in core else ""),
            "fields": fields,
            "records": n,
        })
    return items


def render(items, mask: bool = False) -> str:
    """항목 → Markdown 표. mask=True 면 사이트명 대신 카테고리(브랜드 비노출)."""
    lines = ["# 역량 매트릭스 (자동 생성 — capabilities.py)",
             "",
             "> 각 사이트에서 **실제로 가져온 필드** 목록 (`V` = 추출 성공)."
             + (" (사이트명은 카테고리로 익명화됨)" if mask else ""),
             "",
             "| 페이지 유형 | 로드 | 레코드 | 가져온 필드 |",
             "|---|---|---:|---|"]
    for it in items:
        typ = (_CATEGORY.get(it["label"], _FALLBACK) if mask else it["label"])
        if it["chain"]:
            typ += f" → 상세({it['col']})"
        got = [name for name, r in it["fields"] if r > 0.0]      # 실제 값이 있는 필드만
        cov = ", ".join(f"{name}:V" for name in got) or "—"
        lines.append(f"| {typ} | {it['load']} | {it['records']} | {cov} |")
    lines += ["", f"_총 {len(items)}개 대상. 생성: capabilities.py"
                  + (" --mask" if mask else "") + "_"]
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="역량 매트릭스 자동 생성(output/+recipes/ 읽기)")
    ap.add_argument("--mask", action="store_true", help="사이트명 → 카테고리(공개용)")
    ap.add_argument("-o", "--output", help="Markdown 저장 경로(미지정 시 화면 출력)")
    args = ap.parse_args()

    md = render(collect(), mask=args.mask)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print(t("저장됨 → {p}  ({kind})", p=args.output,
                kind=(t("마스킹") if args.mask else t("실제 사이트명"))))
    else:
        print(md)


if __name__ == "__main__":
    main()

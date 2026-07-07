# -*- coding: utf-8 -*-
"""
MODULE_NAME: doctor.py
PURPOSE: 정합성 점검 도구(읽기 전용, 완전 별개 프로그램). recipe · output · _runs.csv 3자를 대사해
         '고아(orphan)'·깨진 행·데이터 섞임 위험을 리포트한다. 파일을 절대 수정하지 않는다(진단만).
DEPENDENCY: 표준 라이브러리 + paths(경로 재사용). 크롤링/네트워크 없음.

사용:
  python doctor.py            # 정합성 리포트 출력

[점검 항목]
1. 로그 없는 레시피   : recipe 는 있는데 _runs.csv 가 참조 안 함(= 로그 행을 손으로 지운 흔적).
2. 데이터 없는 레시피 : recipe 는 있는데 짝 output_*.csv 가 없음.
3. 레시피 없는 output : output 은 있는데 짝 recipe_*.csv 가 없음(재크롤 시 옛 데이터에 섞여 append 위험).
4. 깨진 로그 행       : recipe_csv/result_csv 가 실제 없는 파일을 가리키거나 crawled_at 이 빔.
5. 중복 target(정보성): 같은 대상이 여러 번 로그됨(replay 목록은 최신만 보여주므로 손정리 불필요).
"""
import bootstrap  # 첫 실행: 가상환경(.venv) 안내·자동설치 후 venv 로 재실행
if __name__ == "__main__":
    bootstrap.ensure_env()

import os
import sys
import csv
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)


def _basename(cell):
    return os.path.basename((cell or "").replace("\\", "/"))


def audit(recipe_dir=None, output_dir=None, runlog_path=None):
    recipe_dir = recipe_dir or paths.RECIPE_DIR
    output_dir = output_dir or paths.OUTPUT_DIR
    runlog_path = runlog_path or paths.RUNLOG_PATH

    recipes = {os.path.basename(p) for p in glob.glob(os.path.join(recipe_dir, "recipes_*.csv"))}
    outputs = {os.path.basename(p) for p in glob.glob(os.path.join(output_dir, "output_*.csv"))}

    rows = []
    if os.path.exists(runlog_path):
        with open(runlog_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

    logged_recipes = {_basename(r.get("recipe_csv")) for r in rows if r.get("recipe_csv")}

    def recipe_to_output(rname):     # recipes_X.csv → output_X.csv
        return "output_" + rname[len("recipes_"):]

    def output_to_recipe(oname):     # output_X.csv → recipes_X.csv
        return "recipes_" + oname[len("output_"):]

    report = {
        "recipe_no_log": sorted(r for r in recipes if r not in logged_recipes),
        "recipe_no_data": sorted(r for r in recipes if recipe_to_output(r) not in outputs),
        "output_no_recipe": sorted(o for o in outputs if output_to_recipe(o) not in recipes),
        "broken_rows": [],
        "dup_targets": {},
    }

    # 깨진 로그 행: 참조 파일 부재 or 빈 타임스탬프
    for i, r in enumerate(rows, 1):
        problems = []
        if not (r.get("crawled_at") or "").strip():
            problems.append("crawled_at 빔")
        for col in ("recipe_csv", "result_csv"):
            cell = (r.get(col) or "").strip()
            if cell and not os.path.exists(cell):
                problems.append(f"{col} 파일없음")
        if problems:
            report["broken_rows"].append((i, (r.get("target", "") or "")[:55], ", ".join(problems)))

    # 중복 target(2회 이상)
    counts = {}
    for r in rows:
        t = (r.get("target") or "").strip()
        if t:
            counts[t] = counts.get(t, 0) + 1
    report["dup_targets"] = {t: c for t, c in counts.items() if c >= 2}
    return report


def _print(report):
    def section(title, items, fmt):
        print("\n■ " + t("{title}: {n}건", title=title, n=len(items)))
        for it in (items if isinstance(items, list) else items.items()):
            print("   " + fmt(it))

    section(t("로그 없는 레시피(손삭제 흔적)"), report["recipe_no_log"], lambda x: x)
    section(t("데이터(output) 없는 레시피"), report["recipe_no_data"], lambda x: x)
    section(t("레시피 없는 output(재크롤 섞임 위험)"), report["output_no_recipe"], lambda x: x)
    section(t("깨진 로그 행"), report["broken_rows"],
            lambda row: t("행{n}: {msg}  ({ctx})", n=row[0], msg=row[1], ctx=row[2]))
    dups = sorted(report["dup_targets"].items(), key=lambda kv: -kv[1])
    print("\n■ " + t("중복 target(정보성, replay 목록은 최신만): {n}종", n=len(dups)))
    for tgt, c in dups[:10]:
        print("   " + t("{c}회  {tgt}", c=f"{c:>3}", tgt=tgt[:70]))

    total = (len(report["recipe_no_log"]) + len(report["recipe_no_data"])
             + len(report["output_no_recipe"]) + len(report["broken_rows"]))
    print("\n=== " + t("정합성 이슈 합계: {n}건 (중복 target 은 제외 — 정상)", n=total) + " ===")
    if total == 0:
        print(t("깨끗합니다 ✔"))
    print(t("(doctor.py 는 읽기 전용입니다 — 어떤 파일도 수정하지 않았습니다.)"))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=== " + t("정합성 점검 (doctor.py · 읽기 전용)") + " ===")
    _print(audit())


if __name__ == "__main__":
    main()

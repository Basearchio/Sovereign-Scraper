# -*- coding: utf-8 -*-
"""
자가 치유 증명 데모
===================
시나리오:
  1) v1(원본)로 Calibration → 셀렉터 캐시
  2) v1 추출 → 빠른 경로 적중
  3) v2(클래스명 전부 무작위 변경) 추출 → 셀렉터 깨짐 감지 → 구조 기반 재탐색 → 셀렉터 자가 갱신
  4) v2 재추출 → 갱신된 셀렉터로 빠른 경로 적중 (치유 학습 확인)
  5) v3(클래스 변경 + 구조 드리프트) 추출 → 휴리스틱 재배치로 자가 치유
"""
import os
import sys

# Windows 콘솔(cp949)에서도 한글/em-dash가 깨지지 않도록 UTF-8 강제
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from engine import SelfHealingEngine, load_dom
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "fixtures")
CACHE = os.path.join(HERE, "schema_cache.json")


def show(title, rows):
    print("  >>> " + t("추출 결과 ({title}): {n}건", title=title, n=len(rows)))
    for r in rows:
        print(f"      - [{r.get('date')}] {r.get('title')}  ({r.get('url')})")


def banner(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def main():
    if os.path.exists(CACHE):
        os.remove(CACHE)

    banner("STEP 1) v1 캘리브레이션")
    eng = SelfHealingEngine(CACHE)
    eng.calibrate(load_dom(os.path.join(FX, "board_v1.html")))

    banner("STEP 2) v1 추출 (빠른 경로 기대)")
    show("v1", eng.extract(load_dom(os.path.join(FX, "board_v1.html"))))

    banner("STEP 3) v2 추출 — 클래스명 전부 무작위 변경됨 (자가 치유 기대)")
    show("v2", eng.extract(load_dom(os.path.join(FX, "board_v2.html"))))

    banner("STEP 4) v2 재추출 — 갱신된 셀렉터로 빠른 경로 기대")
    show("v2(재)", eng.extract(load_dom(os.path.join(FX, "board_v2.html"))))

    banner("STEP 5) v3 추출 — 클래스+구조 동시 변경 (구조 드리프트 치유 기대)")
    show("v3", eng.extract(load_dom(os.path.join(FX, "board_v3.html"))))


if __name__ == "__main__":
    main()

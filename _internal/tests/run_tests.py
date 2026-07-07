# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/run_tests.py
PURPOSE: pytest 없이도 도는 초경량 테스트 러너. tests/test_*.py 의 test_ 함수를 모아
         실행하고 PASS/FAIL 을 집계한다(리팩터 각 단계 후 '그린' 확인용).
DEPENDENCY: 표준 라이브러리만. (pytest 가 설치돼 있으면 `pytest tests/` 도 그대로 됨)

[사용법]
    python tests/run_tests.py        # 전체 실행, 실패 시 종료코드 1

[테스트/운영 교훈]
- pytest 미설치 환경(이 프로젝트)에서도 안전망이 항상 돌아가야 한다 → 의존성 0 러너.
"""
import glob
import importlib
import os
import sys
import traceback

# 테스트/서브프로세스는 첫 실행 부트스트랩(venv 재실행)을 건너뛴다(러너가 멈추거나 venv 로 튀는 것 방지).
os.environ["SHC_NO_BOOTSTRAP"] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))   # _internal/tests
INTERNAL = os.path.dirname(HERE)                     # _internal (내부 모듈)
PROJECT = os.path.dirname(INTERNAL)                  # 프로젝트 루트(front: cli/replay)
sys.path.insert(0, PROJECT)    # cli/replay(front) 임포트용
sys.path.insert(0, INTERNAL)   # engine/locators/... 내부 모듈 임포트용(output.py 가 output/ 폴더보다 우선)
sys.path.insert(0, HERE)       # test_*.py 임포트용


def main():
    files = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    total = passed = 0
    failures = []
    for f in files:
        modname = os.path.splitext(os.path.basename(f))[0]
        mod = importlib.import_module(modname)
        for name in sorted(dir(mod)):
            fn = getattr(mod, name)
            if not (name.startswith("test_") and callable(fn)):
                continue
            total += 1
            try:
                fn()
                passed += 1
                print(f"  PASS  {modname}.{name}")
            except Exception as e:
                failures.append((modname, name, traceback.format_exc()))
                print(f"  FAIL  {modname}.{name}: {e}")
    print(f"\n=== {passed}/{total} passed, {len(failures)} failed ===")
    for m, n, tb in failures:
        print(f"\n----- {m}.{n} -----\n{tb}")
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()

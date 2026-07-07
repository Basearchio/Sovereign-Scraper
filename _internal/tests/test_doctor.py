# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_doctor.py
PURPOSE: 정합성 점검 도구(doctor.py)가 고아·깨진 행을 정확히 탐지하고, '절대 파일을 수정하지 않음'을
         못박는다(읽기 전용 계약). 오프라인·결정적.
DEPENDENCY: 표준 라이브러리만.
"""
import os
import sys
import csv
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import doctor


def _touch(p):
    with open(p, "w", encoding="utf-8") as f:
        f.write("x")


def _setup(d):
    _touch(os.path.join(d, "recipes_a_1.csv")); _touch(os.path.join(d, "output_a_1.csv"))  # 정상 쌍
    _touch(os.path.join(d, "recipes_b_1.csv"))                    # 로그 없음 + 데이터 없음
    _touch(os.path.join(d, "output_c_1.csv"))                     # 레시피 없는 output
    runlog = os.path.join(d, "_runs.csv")
    with open(runlog, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["crawled_at", "target", "recipe_csv", "result_csv"])
        w.writerow(["2026-01-01", "http://a", os.path.join(d, "recipes_a_1.csv"),
                    os.path.join(d, "output_a_1.csv")])
        w.writerow(["", "http://x", "", ""])                     # crawled_at 빔 → 깨진 행
    return runlog


def test_audit_detects_orphans_and_broken():
    with tempfile.TemporaryDirectory() as d:
        runlog = _setup(d)
        rep = doctor.audit(recipe_dir=d, output_dir=d, runlog_path=runlog)
        assert "recipes_b_1.csv" in rep["recipe_no_log"]        # 로그 없는 레시피
        assert "recipes_a_1.csv" not in rep["recipe_no_log"]    # 정상 쌍은 아님
        assert "output_c_1.csv" in rep["output_no_recipe"]      # 레시피 없는 output
        assert "recipes_b_1.csv" in rep["recipe_no_data"]       # 데이터 없는 레시피
        assert any("crawled_at" in b[2] for b in rep["broken_rows"])  # 빈 타임스탬프


def test_doctor_is_read_only():
    """audit 실행 후 대상 디렉터리의 파일 목록·내용이 그대로여야 한다(수정 0)."""
    with tempfile.TemporaryDirectory() as d:
        runlog = _setup(d)
        before = {f: os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)}
        doctor.audit(recipe_dir=d, output_dir=d, runlog_path=runlog)
        after = {f: os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)}
        assert before == after                                  # 파일 추가/변경 없음


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

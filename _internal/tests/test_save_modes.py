# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_save_modes.py
PURPOSE: 저장 방식 4종(append/history/overwrite/upsert)과 '회차' 컬럼의 행동 골든.
         데이터 성격별 저장(인기가요=overwrite, 랭킹시계열=history, 가격추적=upsert)을 못박는다.
DEPENDENCY: 표준 라이브러리만(cli.save_csv 직접 호출, 네트워크/LLM 무관).
"""
import os
import sys
import csv
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli


def _read(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_append_dedup_and_회차():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "o.csv")
        a, u = cli.save_csv(p, [{"곡": "A"}, {"곡": "B"}], ["곡"], mode="append", batch=1)
        assert (a, u) == (2, 0)
        a, u = cli.save_csv(p, [{"곡": "A"}, {"곡": "C"}], ["곡"], mode="append", batch=2)
        assert a == 1                       # 중복 A 제외, C만 추가
        rows = _read(p)
        assert [r["곡"] for r in rows] == ["A", "B", "C"]
        assert "회차" in rows[0]
        assert rows[2]["곡"] == "C" and rows[2]["회차"] == "2"   # 새 행은 이번 회차


def test_overwrite_replaces_all():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "o.csv")
        cli.save_csv(p, [{"순위": "1", "곡": "A"}, {"순위": "2", "곡": "B"}], ["순위", "곡"],
                     mode="overwrite", batch=1)
        a, u = cli.save_csv(p, [{"순위": "1", "곡": "X"}], ["순위", "곡"], mode="overwrite", batch=2)
        rows = _read(p)
        assert len(rows) == 1 and rows[0]["곡"] == "X" and rows[0]["회차"] == "2"  # 전량 교체


def test_history_keeps_all_snapshots():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "o.csv")
        cli.save_csv(p, [{"곡": "A"}, {"곡": "B"}], ["곡"], mode="history", batch=1)
        cli.save_csv(p, [{"곡": "A"}, {"곡": "D"}], ["곡"], mode="history", batch=2)
        rows = _read(p)
        assert [r["곡"] for r in rows] == ["A", "B", "A", "D"]     # 중복 허용(회차별 스냅샷)
        assert [r["회차"] for r in rows] == ["1", "1", "2", "2"]


def test_upsert_updates_by_key():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "o.csv")
        cli.save_csv(p, [{"순위": "1", "곡": "A"}, {"순위": "2", "곡": "B"}], ["순위", "곡"],
                     mode="overwrite", batch=1)
        a, u = cli.save_csv(p, [{"순위": "1", "곡": "Z"}, {"순위": "3", "곡": "C"}], ["순위", "곡"],
                            mode="upsert", key_field="순위", batch=2)
        assert (a, u) == (1, 1)              # 순위1 갱신, 순위3 신규
        rows = {r["순위"]: r["곡"] for r in _read(p)}
        assert rows == {"1": "Z", "2": "B", "3": "C"}


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

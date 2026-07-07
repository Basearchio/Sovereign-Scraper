# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_safe_io.py
PURPOSE: 파일 잠금(엑셀 열림) 시 '구멍'을 막는 safe_io.open_when_writable 의 계약 —
         쓰기 모드는 잠금(PermissionError)이 풀릴 때까지 재시도, 읽기는 그대로, timeout 초과 시 전파.
DEPENDENCY: 표준 라이브러리만(builtins.open 을 가짜로 바꿔 잠금을 흉내, 실제 OS 잠금 불필요).
"""
import os
import sys
import builtins
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import safe_io


def test_write_retries_until_unlocked():
    """쓰기 모드: 처음 2번은 잠김(PermissionError) → 재시도 → 3번째에 저장 성공."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "runs.csv")
        real = builtins.open
        state = {"fails": 2}
        def fake(path, mode="r", *a, **k):
            if any(c in mode for c in "wax+") and state["fails"] > 0:
                state["fails"] -= 1
                raise PermissionError("locked by Excel")
            return real(path, mode, *a, **k)
        builtins.open = fake
        try:
            with safe_io.open_when_writable(p, "w", poll=0, announce=False, encoding="utf-8") as f:
                f.write("ok")
        finally:
            builtins.open = real
        assert state["fails"] == 0                 # 두 번 재시도했음
        assert real(p, encoding="utf-8").read() == "ok"


def test_read_mode_not_retried():
    """읽기 모드는 재시도 대상이 아니다(엑셀은 읽기 공유를 허용)."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hi")
        with safe_io.open_when_writable(p, "r", encoding="utf-8") as f:
            assert f.read() == "hi"


def test_timeout_raises_when_stays_locked():
    """timeout 초과까지 계속 잠겨 있으면 PermissionError 를 전파(무인 실행 보호)."""
    real = builtins.open
    builtins.open = lambda *a, **k: (_ for _ in ()).throw(PermissionError("locked"))
    try:
        raised = False
        try:
            safe_io.open_when_writable("whatever.csv", "w", timeout=0, poll=0, announce=False)
        except PermissionError:
            raised = True
        assert raised
    finally:
        builtins.open = real


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

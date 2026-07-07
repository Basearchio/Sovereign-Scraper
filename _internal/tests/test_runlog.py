# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_runlog.py
PURPOSE: Phase 4c 고정 — 감사로그·계층번호(runlog.py)가 leaf 로 분리되고 cli/chain/replay 가
         재사용(배선)하는지, 그리고 계층 실행번호(assign_run_numbers)의 P-k 규칙을 결정적으로 못박는다.
DEPENDENCY: 표준 라이브러리만(오프라인 결정적). append_runlog 는 실제 _runs.csv 를 건드리므로 호출하지
            않고 표면만 확인(번호 규칙은 assign_run_numbers 로 직접 검증).

[검증된 주요 사이트 및 케이스]
- 부모-자식 번호: 목록 크롤(정수) → 그 목록 CSV 를 따라간 체인 = 'P-k'. 부모 매칭은 result_csv basename.

[테스트/운영 교훈]
- replay 목록번호와 _runs.csv site_no 가 어긋나면 재현이 엉킨다 → 번호 규칙을 결정적으로 고정.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_runlog_surface():
    """[역할] runlog 의 공개 심볼이 실재하는지."""
    import runlog
    assert callable(runlog.assign_run_numbers)
    assert callable(runlog.append_runlog)
    assert callable(runlog._is_chain_target)
    assert isinstance(runlog.RUNLOG_HEADER, list) and runlog.RUNLOG_HEADER[0] == "site_no"


def test_is_chain_target():
    """[역할] .csv 대상만 체인으로 판별."""
    import runlog
    assert runlog._is_chain_target("jobs.csv")
    assert runlog._is_chain_target(" LIST.CSV ")
    assert not runlog._is_chain_target("https://a.com/list")


def test_hierarchical_numbering_pk():
    """[역할] ★골든: 일반=정수(등장순), 체인=부모(result_csv basename 매칭) 밑 'P-k', 부모없으면 정수."""
    from runlog import assign_run_numbers
    rows = [
        {"target": "http://site1/list", "result_csv": "/out/jobs.csv"},          # 부모 → 1
        {"target": "jobs.csv", "url_col": "직무_url", "result_csv": "/out/jobs_detail.csv"},   # → 1-1
        {"target": "jobs.csv", "url_col": "회사_url", "result_csv": "/out/jobs_d2.csv"},        # → 1-2
        {"target": "http://site2/list", "result_csv": "/out/news.csv"},          # 부모 → 2
        {"target": "orphan.csv", "url_col": "u", "result_csv": "/out/x.csv"},     # 부모없음 → 3
        {"target": "", "result_csv": ""},                                        # 빈 target → ""
    ]
    assign_run_numbers(rows)
    assert [r["site_no"] for r in rows] == ["1", "1-1", "1-2", "2", "3", ""]


def test_cli_and_chain_and_replay_reuse_runlog():
    """[역할] cli 재-export + chain 직접 import 가 모두 같은 runlog 함수를 가리키는지(단일 규칙)."""
    import runlog
    import cli
    import chain
    assert cli.append_runlog is runlog.append_runlog
    assert cli.assign_run_numbers is runlog.assign_run_numbers
    assert cli._is_chain_target is runlog._is_chain_target
    assert chain.append_runlog is runlog.append_runlog


def test_runlog_is_leaf():
    """[역할] runlog 가 상위 내부 모듈을 import 하지 않는지(paths 만 허용) 소스 스캔."""
    banned = {"engine", "cli", "chain", "replay", "crawlers", "core", "services", "llm_locators"}
    offenders = []
    with open(os.path.join(_ROOT, "runlog.py"), encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            m = re.match(r"(?:import|from)\s+([\w.]+)", s)
            if m and m.group(1).split(".")[0] in banned:
                offenders.append(f"runlog.py:{i}: {s}")
    assert not offenders, "runlog 가 상위 모듈 import(순환 위험):\n" + "\n".join(offenders)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

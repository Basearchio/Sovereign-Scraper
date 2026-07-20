# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_paths.py
PURPOSE: Phase 4b 고정 — 파일 경로 규칙(paths.py)이 leaf 로 분리되고, cli 가 그것을 재-export 해
         쓰는지(배선)와 경로 계산의 결정성/규칙을 확인한다.
DEPENDENCY: 표준 라이브러리만(오프라인 결정적). 네트워크/LLM 불필요.

[검증된 주요 사이트 및 케이스]
- csv/recipe/chain 경로의 결정성(같은 대상=같은 경로, 다른 대상=다른 경로) — 재현/누적의 기준.
- 사이트라벨(coupang) 규칙 — Save As ASCII 경로 안정성.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_paths_surface():
    """[역할] paths 의 공개 함수/상수가 실재하는지."""
    import paths
    for n in ("cache_path_for", "csv_path_for", "recipe_path_for",
              "chain_recipe_path_for", "chain_csv_path_for", "chain_recipe_glob",
              "saved_html_path_for", "saved_html_old_path_for",
              "_site_label"):
        assert callable(getattr(paths, n, None)), f"paths.{n} 없음"
    for n in ("HERE", "CACHE_DIR", "OUTPUT_DIR", "RECIPE_DIR", "RUNLOG_PATH"):
        assert isinstance(getattr(paths, n, None), str), f"paths.{n} 없음"


def test_path_determinism_and_rules():
    """[역할] 같은 대상=같은 경로, 다른 대상=다른 경로. 사이트라벨/체인경로 규칙."""
    import paths
    a1 = paths.csv_path_for("https://a.com/list?x=1")
    a2 = paths.csv_path_for("https://a.com/list?x=1")
    b = paths.csv_path_for("https://b.com/list?x=1")
    assert a1 == a2 and a1 != b, "대상별로 결정적이어야 함"
    assert a1.endswith(".csv")
    assert paths._site_label("https://www.coupang.com/np/1") == "coupang"
    # 체인: 목록(output_<label>_<n>)의 코어를 물려받아 레시피/데이터가 같은 코어(한 쌍), 'chain' 은 안 들어감
    assert os.path.basename(paths.chain_recipe_path_for("output_incruit_1.csv", "직무_url")) == "recipes_incruit_1__직무_url.csv"
    assert os.path.basename(paths.chain_csv_path_for("output_incruit_1.csv", "직무_url")) == "output_incruit_1__직무_url.csv"
    assert paths.chain_recipe_glob("output_incruit_1.csv").endswith(os.path.join("recipes", "recipes_incruit_1__*.csv"))


def test_new_naming_scheme_prefix_and_pairing():
    """[역할] 새 파일명 규칙: output_<label>_<n> / recipes_<label>_<n> (종류 접두사 + 사이트라벨 + 순번).
    같은 <label>_<n> = 한 쌍(데이터+레시피). RECIPE_DIR 을 빈 임시로 격리(실제 recipes 상태 무관)."""
    import tempfile
    import paths
    with tempfile.TemporaryDirectory() as d:
        old = paths.RECIPE_DIR
        try:
            paths.RECIPE_DIR = d
            url = "https://www.incruit.com/list?kw=A"
            assert os.path.basename(paths.csv_path_for(url)) == "output_incruit_1.csv"
            assert os.path.basename(paths.recipe_path_for(url)) == "recipes_incruit_1.csv"
            assert os.path.basename(paths.saved_html_path_for(url)) == "output_incruit_1.html"
        finally:
            paths.RECIPE_DIR = old


def test_slot_reuse_by_url_and_increment():
    """[역할] 상태파일 없이: 같은 URL=순번 재사용, 다른 URL=다음 순번, 새 사이트=1. (핵심 자가치유 계약)"""
    import tempfile
    import paths
    with tempfile.TemporaryDirectory() as d:
        old = paths.RECIPE_DIR
        try:
            paths.RECIPE_DIR = d
            url_a = "https://search.incruit.com/list?kw=A"
            url_b = "https://search.incruit.com/list?kw=B"   # 같은 사이트, 다른 검색어
            # incruit_1 슬롯을 url_a 의 레시피로 이미 사용 중이라고 가정
            with open(os.path.join(d, "recipes_incruit_1.csv"), "w", encoding="utf-8", newline="") as f:
                f.write("kind,name,tag,cls,attr,path,example\n")
                f.write(f"meta,url,{url_a},,,,\n")
            assert os.path.basename(paths.recipe_path_for(url_a)) == "recipes_incruit_1.csv"  # 같은 URL → 재사용
            assert os.path.basename(paths.recipe_path_for(url_b)) == "recipes_incruit_2.csv"  # 다른 URL → 증가
            assert os.path.basename(paths.csv_path_for(url_a)) == "output_incruit_1.csv"      # 쌍(데이터)도 동일 번호
            assert os.path.basename(paths.csv_path_for(url_b)) == "output_incruit_2.csv"
            assert os.path.basename(paths.recipe_path_for("https://www.other.com/x")) == "recipes_other_1.csv"  # 새 사이트 → 1
        finally:
            paths.RECIPE_DIR = old


def test_slot_gap_robust_after_deletion():
    """[역할] 낮은 슬롯이 지워져 '구멍'이 나도, 높은 슬롯의 URL 은 자기 번호로 정확히 해석된다.
    (skyscanner_1 삭제 후 skyscanner_2(HGH)가 슬롯1로 오인돼 재학습되는 것을 방지)."""
    import tempfile
    import paths
    with tempfile.TemporaryDirectory() as d:
        old = paths.RECIPE_DIR
        try:
            paths.RECIPE_DIR = d
            url_b = "https://search.incruit.com/list?kw=B"
            # 슬롯1 은 비어 있고(삭제됨), 슬롯2 에만 url_b 레시피가 있는 상황
            with open(os.path.join(d, "recipes_incruit_2.csv"), "w", encoding="utf-8", newline="") as f:
                f.write("kind,name,tag,cls,attr,path,example\n")
                f.write(f"meta,url,{url_b},,,,\n")
            assert os.path.basename(paths.recipe_path_for(url_b)) == "recipes_incruit_2.csv"  # 구멍에도 자기번호
            new_url = "https://search.incruit.com/list?kw=NEW"
            assert os.path.basename(paths.recipe_path_for(new_url)) == "recipes_incruit_1.csv"  # 새 URL → 최저 빈칸
        finally:
            paths.RECIPE_DIR = old


def test_cli_reexports_paths():
    """[역할] cli 가 paths 를 재-export 해 기존 `from cli import ...` 가 그대로 동작하는지."""
    import cli
    import paths
    assert cli.csv_path_for is paths.csv_path_for
    assert cli.chain_recipe_path_for is paths.chain_recipe_path_for
    assert cli.OUTPUT_DIR is paths.OUTPUT_DIR and cli.RUNLOG_PATH is paths.RUNLOG_PATH


def test_chain_uses_paths_for_path_symbols():
    """[역할] chain 이 경로 심볼을 leaf(paths)에서 가져오는지(결합 축소 확인)."""
    import chain
    import paths
    assert chain.chain_recipe_path_for is paths.chain_recipe_path_for
    assert chain.chain_csv_path_for is paths.chain_csv_path_for


def test_rel_to_root_and_abs_roundtrip():
    """[역할] 데이터 파일 이식성 — 루트 안 절대경로는 상대로 저장, 읽을 때 현재 루트로 복원.
    원격 URL·루트 밖 경로는 건드리지 않는다(폴더 이동해도 CSV/_runs.csv 가 안 깨지게)."""
    import paths
    inside = os.path.join(paths.HERE, "output", "output_x_1.csv")
    rel = paths.rel_to_root(inside)
    assert not os.path.isabs(rel) and "output" in rel            # 루트 안 → 상대화
    assert os.path.normpath(paths.abs_from_root(rel)) == os.path.normpath(inside)  # 복원
    # 원격 URL·상대·루트 밖은 그대로
    assert paths.rel_to_root("https://cdn/x.jpg") == "https://cdn/x.jpg"
    assert paths.rel_to_root("already/rel.csv") == "already/rel.csv"
    assert paths.abs_from_root("https://cdn/x.jpg") == "https://cdn/x.jpg"


def test_abs_from_root_reanchors_moved_legacy_path():
    """[역할] ★폴더를 옮기거나 이름을 바꿔 저장된 '옛 절대경로'가 깨져도, 프로젝트 폴더명 이후 꼬리를
    현재 루트에 다시 붙여 복원한다(과거 _runs.csv 의 절대경로도 재현 가능)."""
    import paths
    marker = os.path.basename(paths.HERE)
    real = os.path.join(paths.HERE, "output", "_reanchor_probe.csv")
    os.makedirs(os.path.dirname(real), exist_ok=True)
    with open(real, "w", encoding="utf-8") as f:
        f.write("x")
    try:
        legacy = f"D:/old_place/{marker}/output/_reanchor_probe.csv"   # 존재 안 함(옛 위치)
        got = paths.abs_from_root(legacy)
        assert os.path.normpath(got) == os.path.normpath(real), got     # 현재 루트로 재-앵커
    finally:
        os.remove(real)


def test_paths_is_leaf():
    """[역할] paths 가 상위 내부 모듈을 import 하지 않는지(순환 차단) 소스 스캔."""
    banned = {"engine", "cli", "chain", "replay", "crawlers", "core", "services", "llm_locators"}
    offenders = []
    with open(os.path.join(_ROOT, "paths.py"), encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            m = re.match(r"(?:import|from)\s+([\w.]+)", s)
            if m and m.group(1).split(".")[0] in banned:
                offenders.append(f"paths.py:{i}: {s}")
    assert not offenders, "paths 가 상위 모듈 import(순환 위험):\n" + "\n".join(offenders)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_core_schema.py
PURPOSE: Phase 3 슬라이스 고정 — 데이터 계약(Schema/FieldSchema)이 core/schema.py 로 분리되고,
         engine/cli 가 그것을 위임해 쓰는지(배선) + CSV 레시피 왕복 동작 + 계층 규율을 확인한다.
DEPENDENCY: 표준 라이브러리만(json/csv/tempfile). 네트워크/LLM/브라우저 불필요(오프라인 결정적).

[검증된 주요 사이트 및 케이스]
- CSV 레시피 왕복(save_csv_recipe ↔ from_csv_recipe): replay 재현의 핵심 계약. extra_meta 보존.

[테스트/운영 교훈]
- core 는 leaf 여야 한다(engine/cli/crawlers import 금지 → 순환 차단) → 소스 스캔으로 강제.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_core_schema_surface():
    """[역할] core.schema 가 임포트되고 Schema/FieldSchema 가 실재하는지."""
    from core.schema import Schema, FieldSchema
    assert callable(Schema) and callable(FieldSchema)


def test_csv_recipe_roundtrip():
    """[역할] save_csv_recipe → from_csv_recipe/read_recipe_meta 왕복에서 값·메타가 보존되는지."""
    from core.schema import Schema, FieldSchema
    from dataclasses import asdict
    s = Schema("a.t", "li", None, "li[a,span]")
    s.single_record = True
    s.fields = {"제목": asdict(FieldSchema(css="a.t", tag="a", cls="t",
                                          path=[["a", 0]], attr=None, example="샘플제목"))}
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        path = f.name
    try:
        s.save_csv_recipe(path, url="http://x/list", load_method="chrome",
                          wait=5, pages=2, extra_meta={"url_col": "직무_url", "chain": "1"})
        s2, url, load_method, wait, pages = Schema.from_csv_recipe(path)
        assert (url, load_method, wait, pages) == ("http://x/list", "chrome", 5, 2)
        assert s2.single_record is True
        assert s2.row_tag == "li" and s2.row_signature == "li[a,span]"
        assert s2.fields["제목"]["example"] == "샘플제목"
        meta = Schema.read_recipe_meta(path)
        assert meta["url_col"] == "직무_url" and meta["chain"] == "1"
    finally:
        os.unlink(path)


def test_engine_and_cli_use_core_schema():
    """[역할] engine·cli 의 Schema 가 core.schema.Schema 와 동일 객체인지(위임/배선)."""
    import core.schema as cs
    import engine
    import cli
    assert engine.Schema is cs.Schema, "engine 이 core.schema.Schema 를 써야 함"
    assert cli.Schema is cs.Schema, "cli 가 (engine 재-export 통해) core.schema.Schema 를 써야 함"


def test_engine_no_longer_defines_schema():
    """[역할] 이동된 dataclass 가 engine 에 중복 정의로 남지 않았는지(소스 스캔)."""
    with open(os.path.join(_ROOT, "engine.py"), encoding="utf-8") as f:
        src = f.read()
    assert "class Schema:" not in src and "class FieldSchema:" not in src, \
        "engine 에 스키마 클래스 정의가 남아있음(이관 누락)"


def test_core_layer_has_no_internal_import():
    """[역할] core/* 가 상위 모듈(engine/cli/crawlers/llm_locators)을 import 하지 않는지(leaf 규율)."""
    cdir = os.path.join(_ROOT, "core")
    banned = {"engine", "cli", "replay", "crawlers", "llm_locators"}
    offenders = []
    for fn in os.listdir(cdir):
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(cdir, fn), encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                s = line.strip()
                m = re.match(r"(?:import|from)\s+([\w.]+)", s)
                if m and m.group(1).split(".")[0] in banned:
                    offenders.append(f"core/{fn}:{i}: {s}")
    assert not offenders, "core 계층이 상위 모듈을 import(순환 위험):\n" + "\n".join(offenders)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_crawlers_static.py
PURPOSE: Phase 2 슬라이스1 고정 — 수집 전략의 static/base 계층이 분리되고, engine 이 그것을
         '위임'해 쓰는지(배선)와 계층 규율(crawlers → engine import 금지)을 확인한다.
DEPENDENCY: lxml(load_dom 로컬 파싱). 네트워크 불필요(오프라인 결정적).

[검증된 주요 사이트 및 케이스]
- 해당 없음(구조 슬라이스). static_fetch 의 실네트워크는 실사이트 스모크로 별도 확인.

[테스트/운영 교훈]
- 수집 계층은 leaf 여야 한다(engine 을 import 하면 순환) → 소스 스캔으로 강제.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_crawlers_static_surface():
    """[역할] crawlers.base/static 이 임포트되고 공개 심(static_fetch/_UA/default_headers)이 실재."""
    import crawlers.base as base
    import crawlers.static as static
    assert callable(static.static_fetch)
    assert isinstance(base._UA, str) and "Mozilla" in base._UA
    assert base.default_headers()["User-Agent"] == base._UA


def test_engine_delegates_static_fetch():
    """[역할] engine 이 자체 _static_fetch 를 버리고 crawlers.static.static_fetch 를 쓰는지(배선)."""
    import engine
    import crawlers.static as static
    assert engine.static_fetch is static.static_fetch, "engine 이 crawlers.static 을 위임해야 함"
    assert not hasattr(engine, "_static_fetch"), "engine 에 옛 _static_fetch 가 남아있음"


def test_load_dom_parses_local_file_offline():
    """[역할] load_dom 의 로컬파일 경로가 여전히 동작(fetch 분리로 회귀 없음)."""
    import engine
    html = "<html><body><ul><li>apple</li><li>pear</li></ul></body></html>"
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        dom = engine.load_dom(path)
        assert [li.text for li in dom.iter("li")] == ["apple", "pear"]
    finally:
        os.unlink(path)


def test_crawlers_layer_has_no_internal_import():
    """[역할] crawlers/* 가 engine/cli/llm_locators 를 import 하지 않는지(leaf 규율) 소스 스캔."""
    cdir = os.path.join(_ROOT, "crawlers")
    banned = {"engine", "cli", "replay", "llm_locators"}
    offenders = []
    for fn in os.listdir(cdir):
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(cdir, fn), encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                s = line.strip()
                # import 대상 '최상위 모듈명'만 정확히 검사(부분문자열 오탐 방지:
                # 예) win32clipboard 의 'cli' 는 위반이 아님).
                m = re.match(r"(?:import|from)\s+([\w.]+)", s)
                if m and m.group(1).split(".")[0] in banned:
                    offenders.append(f"crawlers/{fn}:{i}: {s}")
    assert not offenders, "crawlers 계층이 상위 모듈을 import(순환 위험):\n" + "\n".join(offenders)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

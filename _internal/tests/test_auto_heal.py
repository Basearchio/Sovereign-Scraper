# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_auto_heal.py
PURPOSE: cli.try_auto_heal 계약 — save_as 로 받은 로컬 HTML(dom)으로 recalibrate→재추출→①빈값+
         ②형태검증을 통과하면 (recovered=True, rows, ...). 실패/훅 없음이면 후보 폐기(롤백)로 기존
         스키마를 보호(recovered=False, eng.schema 원복). LLM 은 페이크.
DEPENDENCY: lxml + cli + engine + llm_locators + services.llm_service(ask_json 페이크). cache_path=None.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lxml import html

import cli
import hooks
import engine
import llm_locators
import services.llm_service as svc

# test_discover_structure 에서 li 가 레코드로 잡히는 것이 검증된 구조(제목=a>span, 가격=span).
_HTML = """
<ul class="list">
  <li class="card"><a href="/1"><span class="t">제목A</span></a><span class="p">1,000원</span></li>
  <li class="card"><a href="/2"><span class="t">제목B</span></a><span class="p">2,000원</span></li>
  <li class="card"><a href="/3"><span class="t">제목C</span></a><span class="p">3,000원</span></li>
  <li class="card"><a href="/4"><span class="t">제목D</span></a><span class="p">4,000원</span></li>
</ul>
"""


def _engine_with_schema():
    eng = engine.SelfHealingEngine(cache_path=None, verbose=False)
    s = engine.Schema(row_css="li.card", row_tag="li", row_cls="card", row_signature="")
    s.fields = {"제목": {"example": "제목X"}, "가격": {"example": "9,999원"}}
    eng.schema = s
    return eng


def test_auto_heal_recovers_and_preserves_names():
    dom = html.fromstring(_HTML)
    eng = _engine_with_schema()
    old_d, old_a = hooks._STRUCTURE_DISCOVERER, svc.ask_json
    engine.set_structure_discoverer(llm_locators.discover_structure)
    svc.ask_json = lambda *a, **k: [{"name": "제목", "value": "제목A"},
                                    {"name": "가격", "value": "1,000원"}]
    try:
        recovered, rows, url_field, new_schema = cli.try_auto_heal(eng, dom)
    finally:
        engine.set_structure_discoverer(old_d)
        svc.ask_json = old_a
    assert recovered is True
    assert "제목" in new_schema.fields and "가격" in new_schema.fields   # 이름 보존
    assert len(rows) >= 2


def test_auto_heal_rollback_when_discoverer_unset():
    dom = html.fromstring(_HTML)
    eng = _engine_with_schema()
    keep = eng.schema
    old = hooks._STRUCTURE_DISCOVERER
    engine.set_structure_discoverer(None)          # 재학습 불가
    try:
        recovered, rows, url_field, new_schema = cli.try_auto_heal(eng, dom)
    finally:
        engine.set_structure_discoverer(old)
    assert recovered is False and rows == [] and new_schema is None
    assert eng.schema is keep                       # 기존 스키마 원복(보호)


def test_ask_load_method_noninteractive_replay_uses_default():
    import argparse
    # replay 는 --batch 를 넘긴다 → 비대화 → 질문 없이 감지된 방식(chrome) 자동 채택(멈추지 않음)
    args = argparse.Namespace(batch=7)
    assert cli._ask_load_method(args, default="chrome") == "chrome"


def test_auto_heal_disabled_by_default():
    # 설정(.env AUTO_HEAL) 없으면 기본 OFF → 기존 동작 보존
    assert cli._auto_heal_enabled() in (False, True)   # 환경에 따라 값은 다르나 호출 안전
    import os as _os
    if not (_os.environ.get("AUTO_HEAL") or "").strip():
        assert cli._auto_heal_enabled() is False


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_recalibrate.py
PURPOSE: 자동 재학습 engine.recalibrate 계약 — 주입된 구조 파악자(_discover_structure)로 '기존
         필드명을 보존'하며 새 스키마를 만든다. 훅 미설정이면 None(engine 은 LLM 을 모른다).
DEPENDENCY: lxml + engine + llm_locators(discoverer) + services.llm_service(ask_json 페이크).
         cache_path=None 으로 생성 → _persist 는 no-op(실파일 무접촉).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lxml import html

import hooks
import engine
import llm_locators
import services.llm_service as svc

_HTML = """
<ul class="list">
  <li class="card"><a href="/1"><span class="t">제목A</span></a><span class="p">1,000원</span></li>
  <li class="card"><a href="/2"><span class="t">제목B</span></a><span class="p">2,000원</span></li>
  <li class="card"><a href="/3"><span class="t">제목C</span></a><span class="p">3,000원</span></li>
  <li class="card"><a href="/4"><span class="t">제목D</span></a><span class="p">4,000원</span></li>
</ul>
"""


def test_recalibrate_builds_schema_with_preserved_names():
    dom = html.fromstring(_HTML)
    eng = engine.SelfHealingEngine(cache_path=None, verbose=False)
    old_d, old_a = hooks._STRUCTURE_DISCOVERER, svc.ask_json
    engine.set_structure_discoverer(llm_locators.discover_structure)
    svc.ask_json = lambda *a, **k: [{"name": "제목", "value": "제목A"},
                                    {"name": "가격", "value": "1,000원"}]
    try:
        sch = eng.recalibrate(dom, ["제목", "가격"], {"제목": "x", "가격": "y"})
    finally:
        engine.set_structure_discoverer(old_d)
        svc.ask_json = old_a
    assert sch is not None
    assert "제목" in sch.fields and "가격" in sch.fields   # 사용자 필드명 보존
    assert eng.schema is sch                               # self.schema 교체됨(cli 가 이후 추출/검증)


def test_recalibrate_none_when_discoverer_unset():
    dom = html.fromstring(_HTML)
    eng = engine.SelfHealingEngine(cache_path=None, verbose=False)
    old = hooks._STRUCTURE_DISCOVERER
    engine.set_structure_discoverer(None)          # 훅 없음 → engine 은 재학습 못 함(LLM 모름)
    try:
        assert eng.recalibrate(dom, ["제목"], {}) is None
    finally:
        engine.set_structure_discoverer(old)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

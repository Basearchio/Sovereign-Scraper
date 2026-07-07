# -*- coding: utf-8 -*-
"""tests/test_i18n.py — 다국어 t(): 한국어 소스 + 언어 오버레이 + 미번역 폴백 + 포맷.
한국어를 기본으로 두고 언어를 늘리는 구조라, 핵심 계약은 '미번역은 한국어로 폴백(안 깨짐)'."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import i18n

_MENU_LABEL = "크롤링 (URL/HTML 한 페이지·목록)"


def test_ko_returns_source_as_is():
    i18n.set_lang("ko")
    assert i18n.t(_MENU_LABEL) == _MENU_LABEL               # 한국어=소스, 그대로
    assert i18n.t("등록 안 된 문자열") == "등록 안 된 문자열"


def test_en_overlay_translates():
    i18n.set_lang("en")
    assert i18n.t(_MENU_LABEL) == "Crawl (a URL/HTML page or list)"
    assert i18n.t("종료") == "Exit"


def test_missing_translation_falls_back_to_korean():
    i18n.set_lang("en")
    assert i18n.t("번역 안 된 한국어") == "번역 안 된 한국어"   # en 표에 없으면 한국어 폴백


def test_format_interpolation():
    i18n.set_lang("ko")
    assert i18n.t("적용됨 → {p}", p="x.csv") == "적용됨 → x.csv"
    assert i18n.t("값 {missing}") == "값 {missing}"          # 인자 부족해도 안 터지고 원문 유지


def test_unsupported_lang_falls_back_to_default():
    assert i18n.set_lang("zz") == "ko"
    assert i18n.set_lang("") == "ko"


def test_en_json_covers_menu_labels():
    # 공개 메뉴가 en 에서 안 깨지게: start.MENU 라벨이 en.json 에 모두 있는지 고정.
    import start
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n", "en.json")
    table = json.load(open(p, encoding="utf-8"))
    assert isinstance(table, dict)
    for label, _fn in start.MENU:
        assert label in table, f"en.json 에 메뉴 번역 없음: {label}"
    i18n.set_lang("ko")   # 다른 테스트 오염 방지(기본 복귀)


def test_i18n_is_leaf():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "i18n.py"), encoding="utf-8").read()
    for banned in ("import engine", "import cli", "import start", "from engine", "from cli", "from start"):
        assert banned not in src

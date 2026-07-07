# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_picker.py
PURPOSE: 시각적 요소 피커의 '브라우저 없이 검증 가능한 부분'을 고정 — picks_to_example(순수 변환)과
         모듈 임포트/JS 무결성. 실제 클릭(headed 브라우저)은 수동 스모크로만 검증(도메인 특성).
DEPENDENCY: 표준 라이브러리만(playwright 불필요 — 순수 헬퍼·소스 스캔).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.picker import picks_to_example, picks_kinds, _PICKER_JS, script_free_copy


def test_picks_kinds_aligns_1to1_with_example_values():
    # picks_kinds 는 picks_to_example 와 '같은 필터(빈 값 제외)'로 정렬 → @# 값들과 1:1.
    picks = [{"kind": "text", "value": "제목A"},
             {"kind": "image", "value": "https://cdn/x.jpg"},
             {"kind": "text", "value": ""},          # 빈 값 → 둘 다 버림
             {"kind": "link", "value": "https://x/1"}]
    ex = picks_to_example(picks)
    kinds = picks_kinds(picks)
    assert ex.split("@#") == ["제목A", "https://cdn/x.jpg", "https://x/1"]
    assert kinds == ["text", "image", "link"]        # 길이·순서 일치
    assert len(kinds) == len(ex.split("@#"))


def test_picks_kinds_defaults_text_and_handles_empty():
    assert picks_kinds([]) == [] and picks_kinds(None) == []
    assert picks_kinds([{"value": "가"}]) == ["text"]   # kind 없으면 text


def test_picks_to_example_joins_with_delim():
    picks = [{"kind": "text", "value": "제목A"},
             {"kind": "text", "value": "9,900"},
             {"kind": "link", "value": "https://x/1"}]
    assert picks_to_example(picks) == "제목A@#9,900@#https://x/1"


def test_picks_to_example_drops_blank_and_trims():
    picks = [{"kind": "text", "value": "  가  "}, {"kind": "text", "value": ""},
             {"value": None}, {"kind": "text", "value": "나"}]
    assert picks_to_example(picks) == "가@#나"        # 빈/None 버림, 공백 정리


def test_picks_to_example_empty():
    assert picks_to_example([]) == "" and picks_to_example(None) == ""


def test_picker_js_has_core_hooks():
    # 주입 JS 가 파이썬 계약(실시간 통보/최종목록/완료 플래그/수식키)을 담고 있는지 최소 고정.
    for token in ("window._pick", "window.__picks", "window.__pickDone",
                  "altKey", "shiftKey", "closest('a')"):
        assert token in _PICKER_JS, f"피커 JS 에 '{token}' 없음(계약 깨짐)"


def test_pickable_html_resolves_local_and_rejects_missing():
    # cli 통합: save_as 스냅샷/로컬 HTML 이 있으면 그 경로, 아니면 None(그때는 기존 타이핑).
    import cli
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        assert cli._pickable_html(p) == p                    # 로컬 .html 존재 → 그 경로
        assert cli._pickable_html(p + ".bak") is None        # 없는 파일 → None
    finally:
        os.remove(p)
    # 스냅샷 없는 URL → None. (호스트 라벨이 실데이터와 겹치지 않게: 'x' 는 트위터/X 스냅샷과 충돌)
    assert cli._pickable_html("https://no-such-site-zzz.example/y") is None
    assert cli._pickable_html("nope_zzz.html") is None


def test_script_free_copy_strips_scripts_keeps_dom():
    # 픽커가 여는 사본: <script>·자동새로고침 meta 제거(하이재킹 방지), 냉동 DOM·같은 폴더는 유지.
    from lxml import html as lh
    import tempfile
    import pathlib
    d = tempfile.mkdtemp()
    src = pathlib.Path(d) / "snap.html"
    src.write_text('<html><head><meta http-equiv="refresh" content="0;url=x">'
                   '<script>location="/error"</script></head>'
                   '<body><div class="zA"><span>제목</span></div>'
                   '<script src="_files/boot.js"></script></body></html>', encoding="utf-8")
    out = script_free_copy(str(src))
    try:
        assert out.parent == src.parent                         # 같은 폴더 → _files/ 상대경로 유지
        doc = lh.parse(str(out)).getroot()
        assert doc.xpath("//script") == []                      # 인라인+외부 스크립트 전부 제거
        assert not doc.xpath("//meta[@http-equiv='refresh']")   # 자동 새로고침 제거
        assert doc.xpath("//div[contains(@class,'zA')]")        # 냉동 DOM 보존
        assert "제목" in doc.text_content()
    finally:
        out.unlink(missing_ok=True)
        src.unlink(missing_ok=True)


def test_picker_does_not_import_cli_or_engine():
    import crawlers.picker as pk
    src = open(pk.__file__, encoding="utf-8").read()
    for mod in ("import cli", "import engine", "from cli", "from engine"):
        assert mod not in src, f"picker 가 '{mod}' — 상위 계층 의존 금지"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

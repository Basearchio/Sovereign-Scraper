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

from crawlers.picker import (picks_to_example, picks_kinds, _PICKER_JS, script_free_copy,
                             _local_stylesheet_paths, _file_url_to_path,
                             detect_repeating_fields, _annotate_repeating_fields)


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


def test_picker_js_flags_oversized_captures():
    # 저장 스냅샷의 CSS 가 file:// 재오픈 시 일부 안 먹으면(구글류 확장자 없는 리소스 등) 여러
    # 항목이 박스 구분 없이 붙어 보여 한 번의 클릭이 뭉친 값을 담을 수 있다 → 'big' 플래그로 그
    # 자리에서 경고(파이썬 _pick 콜백도 이 플래그를 보고 터미널에 경고를 낸다).
    assert "big" in _PICKER_JS and "120" in _PICKER_JS


def test_picker_js_has_reader_mode_escape_hatch():
    # 원본 CSS 가 file:// 재오픈 시 깨져(사이드바가 한 덩어리로 붙는 등) 클릭 대상을 구분하기
    # 어려우면, 모양 복원을 포기하고 모든 요소를 강제로 한 줄씩 분리해 '내용만이라도' 클릭 가능하게
    # 하는 탈출구가 있어야 한다. DOM 은 안 건드리고(구조 경로 유지) CSS 만 덮어써야 한다.
    assert "__reader-mode" in _PICKER_JS
    assert "__readerCss" in _PICKER_JS
    assert "all: revert" in _PICKER_JS   # DOM 이 아니라 CSS 만 리셋(추출 경로 불변)


def test_picker_js_reader_mode_only_reveals_previously_visible():
    # ★실사용자 확인된 회귀: 모든 요소를 무조건 display:block 하면 원래 display:none 이던
    # 닫힌 메뉴·스크린리더 전용 텍스트까지 전부 펼쳐져 문서 높이가 폭발, 진짜 내용은 화면 밖
    # 아득히 아래로 밀려나 '로고 하나만 보이는' 것처럼 된다. 켜기 '전' 크기(0×0 여부)로 판정해
    # 원래 안 보이던 요소는 계속 숨겨야 한다.
    assert "__reader-show" in _PICKER_JS and "__reader-hide" in _PICKER_JS


def test_picker_js_reader_mode_unblocks_html_scroll():
    # ★실사용자 확인된 회귀: 'html.__reader-mode .__reader-show'(공백=자손 결합자)는 <html> 이
    # __reader-show 를 '자기 자신'에게 가질 때 안 먹는다(자기 자신은 자기 자손이 될 수 없음).
    # 그래서 <html> 자신의 원래 overflow:hidden(Gmail 앱쉘용)이 안 풀려 스크롤이 완전히 막혔다
    # (문서 높이는 정상인데 휠을 굴려도 scrollY 가 0 에서 안 움직임, 실측 확인) — html 자신이
    # 해당하는 경우(콤마로 병기, 결합자 없음)도 함께 지정해야 한다.
    assert "html.__reader-mode.__reader-show" in _PICKER_JS
    assert "overflow: visible" in _PICKER_JS


def test_picker_js_reader_mode_batches_reads_before_writes():
    # ★실사용자 확인된 회귀: 요소 수만 개짜리 DOM(Gmail)에서 rect 읽기와 class 쓰기를 한
    # 요소씩 번갈아 하면 매번 강제 리플로우(레이아웃 스래싱)가 걸려 몇 초~수십 초씩 멎는다
    # (그동안 클릭이 씹혀 '피커가 안 먹는다'로 보였음) → rect 를 전부 먼저 읽고 나서 class 를
    # 몰아 쓰도록 단계를 분리해야 한다.
    assert "els.map(el => el.getBoundingClientRect())" in _PICKER_JS


def test_picker_js_reader_mode_lets_clicks_pass_through_empty_overlays():
    # ★실사용자 확인된 회귀: Gmail 은 텍스트가 없는 빈 <a>(추적용 등)가 실제 텍스트를 가진
    # 요소와 같은 자리에 겹쳐, 읽기모드에서 클릭이 그 빈 요소에 가로채여 아무 값도 안 잡혔다.
    # 텍스트도 이미지도 없는 요소는 pointer-events:none 으로 클릭을 통과시켜야 한다.
    assert "__reader-empty" in _PICKER_JS
    assert "pointer-events: none" in _PICKER_JS
    assert "getBoundingClientRect" in _PICKER_JS


def test_picker_js_undo_echoes_to_python():
    # '되돌리기'가 브라우저 쪽 목록만 지우고 파이썬 _pick() 으로 이미 누적된 picks 는 그대로 두면
    # (예전 버그) '취소했는데 안 지워진 것 같다'는 증상이 남는다 → window._unpick 콜백으로
    # 되돌린 직후 남은 개수를 파이썬에 즉시 통보해 목록을 실제로 줄인다.
    assert "window._unpick" in _PICKER_JS


def test_picker_js_highlights_data_field_attribute():
    # _annotate_repeating_fields 가 파이썬에서 심어둔 data-__field=N 을, 읽기모드가 CSS 만으로
    # 번호 배지(#1, #2…)를 붙여 보여줘야 한다(레시피/사전 지식 없이 구조 반복만으로 찾은 후보).
    assert "[data-__field]" in _PICKER_JS
    assert "attr(data-__field)" in _PICKER_JS


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
    # 픽커가 여는 사본: <script>·<iframe>·자동새로고침 meta 제거(하이재킹 방지), 냉동 DOM·같은 폴더는 유지.
    # ★실사용자 확인된 회귀: <script>만 지우고 <iframe>(app.html, m=_b,_tp 등 저장된 모듈 로더)을
    # 남겨두면, Gmail 이 그 iframe 안에서 계속 '살아있는 세션'처럼 모듈 초기화를 시도하다 실패를
    # 반복(gapi 미정의·postMessage 오류)하며 화면·픽커 동작을 방해했다 — iframe 도 통째로 제거.
    from lxml import html as lh
    import tempfile
    import pathlib
    d = tempfile.mkdtemp()
    src = pathlib.Path(d) / "snap.html"
    src.write_text('<html><head><meta http-equiv="refresh" content="0;url=x">'
                   '<script>location="/error"</script></head>'
                   '<body><div class="zA"><span>제목</span></div>'
                   '<iframe src="_files/app.html"></iframe>'
                   '<script src="_files/boot.js"></script></body></html>', encoding="utf-8")
    out = script_free_copy(str(src))
    try:
        assert out.parent == src.parent                         # 같은 폴더 → _files/ 상대경로 유지
        doc = lh.parse(str(out)).getroot()
        assert doc.xpath("//script") == []                      # 인라인+외부 스크립트 전부 제거
        assert doc.xpath("//iframe") == []                       # iframe 도 전부 제거(모듈 로더 하이재킹 방지)
        assert not doc.xpath("//meta[@http-equiv='refresh']")   # 자동 새로고침 제거
        assert doc.xpath("//div[contains(@class,'zA')]")        # 냉동 DOM 보존
        assert "제목" in doc.text_content()
    finally:
        out.unlink(missing_ok=True)
        src.unlink(missing_ok=True)


def test_local_stylesheet_paths_finds_relative_link_only():
    # 확장자 없는 크롬 저장 리소스(rs=xxx 등)를 file:// 로 다시 열면 MIME 오판으로 스타일 적용이
    # 거부된다(실사이트 실측: cssRules 접근 시 SecurityError) → 그 경로만 미리 골라내 나중에
    # text/css 로 명시 응답하기 위한 헬퍼. http(s)/data: 링크는 대상에서 제외(로컬 파일이 아님).
    import tempfile
    import pathlib
    d = tempfile.mkdtemp()
    html = pathlib.Path(d) / "snap.html"
    html.write_text(
        '<html><head>'
        '<link rel="stylesheet" href="./snap_files/rs=AA2Yr">'
        '<link rel="stylesheet" href="https://cdn.example/x.css">'
        '<link rel="icon" href="./snap_files/favicon.ico">'
        '</head><body>hi</body></html>', encoding="utf-8")
    try:
        paths = _local_stylesheet_paths(html)
        assert len(paths) == 1
        expect = os.path.normcase(os.path.abspath(str(pathlib.Path(d) / "snap_files" / "rs=AA2Yr")))
        assert expect in paths
    finally:
        html.unlink(missing_ok=True)


# 최소 반복 리스트 5장: 카드마다 제목<a> + 가격<span> (레시피/사전 지식 없이 구조 반복만으로
# 탐지되는지 확인하는 용도 — test_extract_deterministic.py 의 3장짜리 검증된 모양을 그대로 확장).
def _repeating_html(n=5, empty_price_from=None):
    """empty_price_from 이 주어지면 그 인덱스부터는 <span class="price"> 를 '빈 텍스트'로 둬서
    '가끔 값이 비는 필드' 상황을 만든다(태그 자체는 유지 — 구조 시그니처가 흔들리면
    find_repeating_rows 가 애초에 한 그룹으로 안 묶으므로, 일관성 문턱 검증은 '태그는 있는데
    텍스트만 없는' 경우로 해야 한다)."""
    import lxml.html as H
    cards = []
    for i in range(n):
        empty = empty_price_from is not None and i >= empty_price_from
        price_text = "" if empty else f"{(i + 1) * 1000}원"
        cards.append(f'<li class="card"><a href="https://ex.com/p/{i}" class="t">상품{i}</a>'
                     f'<span class="price">{price_text}</span></li>')
    return H.fromstring("<html><body><ul>" + "".join(cards) + "</ul></body></html>")


def test_detect_repeating_fields_finds_consistent_leaf_positions():
    rows, good = detect_repeating_fields(_repeating_html())
    assert len(rows) == 5
    assert len(good) == 2                        # <a>(제목) 경로 + <span>(가격) 경로
    from crawlers.picker import _resolve_path
    texts = [_resolve_path(rows[0], p).text_content() for p in good]
    assert texts == ["상품0", "1000원"]           # 문서 순서(왼→오)대로 번호가 매겨짐


def test_detect_repeating_fields_drops_below_threshold_field():
    # 5장 중 3장(60%)에 가격 텍스트가 비어있음 → 일치율 40% < 문턱(0.6) → 가격 후보 탈락, 제목만 채택.
    rows, good = detect_repeating_fields(_repeating_html(n=5, empty_price_from=2))
    assert len(good) == 1


def test_detect_repeating_fields_tolerates_occasional_missing_field():
    # 5장 중 1장(20%)만 가격이 비어있음 → 일치율 80% ≥ 문턱(0.6) → 여전히 채택(가끔 빠진 값 허용).
    rows, good = detect_repeating_fields(_repeating_html(n=5, empty_price_from=4))
    assert len(good) == 2


def test_detect_repeating_fields_empty_when_no_repetition():
    import lxml.html as H
    dom = H.fromstring("<html><body><p>그냥 페이지 하나, 반복 없음</p></body></html>")
    rows, good = detect_repeating_fields(dom)
    assert rows == [] and good == []


def test_annotate_repeating_fields_marks_every_row():
    import tempfile, pathlib
    import lxml.html as H
    d = tempfile.mkdtemp()
    html = pathlib.Path(d) / "list.html"
    cards = "".join(f'<li class="card"><a href="https://ex.com/p/{i}" class="t">상품{i}</a>'
                    f'<span class="price">{(i + 1) * 1000}원</span></li>' for i in range(5))
    html.write_text(f"<html><body><ul>{cards}</ul></body></html>", encoding="utf-8")
    try:
        out = _annotate_repeating_fields(html)
        assert out == html                        # 같은 파일에 덮어씀
        doc = H.fromstring(html.read_text(encoding="utf-8"))
        titles = doc.xpath('//a[@data-__field="1"]')
        prices = doc.xpath('//span[@data-__field="2"]')
        assert len(titles) == 5 and len(prices) == 5   # 모든 행에 번호가 붙어야 함
    finally:
        html.unlink(missing_ok=True)


def test_file_url_to_path_roundtrips_local_path():
    import pathlib
    p = pathlib.Path(__file__).resolve()
    url = p.as_uri()
    assert _file_url_to_path(url) == os.path.normcase(str(p))


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

# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_image_field.py
PURPOSE: M3 — '이미지 필드'가 값(URL) 매칭이 아니라 '구조'로 <img> 를 잡는 계약 고정.
         저장 스냅샷은 src 를 로컬 파일로 바꾸고(로컬화) 라이브 재렌더는 CDN 토큰이 달라져서,
         피커가 캡처한 이미지 URL 로는 DOM 에서 못 찾는다 → kinds=='image' 면 레코드 안 <img> 를
         위치로 잡고 attr='src' 로 표시. 썸네일이 텍스트와 다른 형제 가지면 카드로 승격해 자손이 되게 한다.
DEPENDENCY: lxml 만(오프라인 결정적). 브라우저/LLM 불필요.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lxml import html as lxml_html

from locators import locate_by_example
from structure import find_record_image as _find_record_image

# 썸네일 <img> 가 텍스트(.info h3)와 '다른 형제 가지'(.thumb a)에 있는 반복 카드 목록.
# 게다가 텍스트를 감싼 .info 는 반복하지만 img 가 없다 → 승격은 img 를 품은 .card 까지 올라가야 한다.
_HTML = """
<html><body><div class="list">
  <div class="card">
    <a class="thumb" href="/a/1001"><img src="/loc/aaaa11110000.jpg" width="80" height="80"></a>
    <div class="info"><h3 class="t">First Post Title</h3><span class="src">SrcA</span></div>
  </div>
  <div class="card">
    <a class="thumb" href="/a/1002"><img src="/loc/bbbb22220000.jpg" width="80" height="80"></a>
    <div class="info"><h3 class="t">Second Post Title</h3><span class="src">SrcB</span></div>
  </div>
  <div class="card">
    <a class="thumb" href="/a/1003"><img src="/loc/cccc33330000.jpg" width="80" height="80"></a>
    <div class="info"><h3 class="t">Third Post Title</h3><span class="src">SrcC</span></div>
  </div>
</div></body></html>
"""


def _dom():
    return lxml_html.fromstring(_HTML)


def test_image_pick_matched_as_src_via_structure_not_url():
    """[역할] 피커가 잡은 이미지 URL 이 DOM 에 없어도(로컬화/드리프트 모사), 구조로 <img> 를 찾아
    attr='src' 로 매칭한다. 텍스트는 정상 매칭."""
    dom = _dom()
    # 두 번째 값(이미지)은 '원격 CDN URL' 을 흉내 — DOM 의 로컬화된 src 와 안 맞는다.
    values = ["First Post Title", "https://cdn.example.com/thumbs/aaaa11110000_hires.jpg"]
    kinds = ["text", "image"]
    rec, sig, matched, err = locate_by_example(dom, values, kinds=kinds)
    assert err is None, err
    assert len(matched) == 2
    # 이미지 필드: 노드를 찾았고 attr='src'
    img_row = matched[1]
    v, node, name, attr = img_row
    assert attr == "src"
    assert node is not None and node.tag == "img", "이미지를 구조로 찾아야 함"
    assert node.get("src", "").endswith("aaaa11110000.jpg"), "hint 토큰(aaaa11110000)으로 그 카드의 img 를 골라야 함"


def test_record_promoted_to_card_so_img_is_descendant():
    """[역할] 텍스트 레코드가 img 없는 좁은 컨테이너로 잡혀도, 이미지 필드가 있으면 img 를 품은
    반복 카드로 승격 → img 가 레코드 자손이라 rel_path 로 행별 추출이 가능."""
    dom = _dom()
    values = ["First Post Title", "https://cdn.example.com/x/aaaa11110000.jpg"]
    rec, sig, matched, err = locate_by_example(dom, values, kinds=["text", "image"])
    assert err is None, err
    # 승격된 레코드는 img 를 자손으로 가진다
    assert rec.find(".//img") is not None
    # 매칭된 img 노드가 레코드의 자손인지
    img_node = matched[1][1]
    assert img_node is not None
    anc = img_node
    inside = False
    while anc is not None:
        if anc is rec:
            inside = True
            break
        anc = anc.getparent()
    assert inside, "img 는 승격된 레코드의 자손이어야 함(rel_path 계산 가능)"


def test_full_extract_yields_per_row_image_src():
    """[역할] locate→build→extract 전 구간: 각 행에서 그 카드의 이미지 src 를 뽑는다(구조 경로 재현)."""
    from engine import SelfHealingEngine
    dom = _dom()
    values = ["First Post Title", "https://cdn.example.com/x/aaaa11110000.jpg"]
    rec, sig, matched, err = locate_by_example(dom, values, kinds=["text", "image"])
    assert err is None, err
    sels = [("제목", matched[0][1], None, values[0]),
            ("이미지", matched[1][1], "src", values[1])]
    eng = SelfHealingEngine(verbose=False)
    eng.build_schema_from_selection([rec], sig, sels, dom=dom)
    out = eng.extract(dom)
    assert len(out) == 3, f"3개 카드가 나와야 함: {len(out)}"
    imgs = [r.get("이미지") for r in out]
    assert imgs[0].endswith("aaaa11110000.jpg"), imgs
    assert imgs[1].endswith("bbbb22220000.jpg"), imgs
    assert imgs[2].endswith("cccc33330000.jpg"), imgs
    assert out[0]["제목"] == "First Post Title"


def test_per_row_image_handles_mixed_card_structures():
    """[역할] ★news/article 처럼 '구조가 다른 카드'가 섞여도, 이미지를 고정 rel_path 가 아니라
    행마다 find_record_image 로 뽑으므로 각 카드의 제 이미지가 나온다(사용자 지적 회귀 방지).
    카드2는 img 가 <figure> 안에 더 깊이 있어(=다른 경로) 고정 경로였다면 놓쳤을 것."""
    from engine import SelfHealingEngine
    dom = lxml_html.fromstring("""
    <html><body><div class="list">
      <div class="card"><div class="thumb"><img src="/n/news1.jpg" width="90" height="57"></div>
        <h3 class="t">News One</h3></div>
      <div class="card"><div class="thumb"><figure><img src="/a/art2.jpg" width="200" height="105"></figure></div>
        <h3 class="t">Article Two</h3></div>
      <div class="card"><div class="thumb"><img src="/n/news3.jpg" width="90" height="57"></div>
        <h3 class="t">News Three</h3></div>
    </div></body></html>""")
    rec, sig, matched, err = locate_by_example(
        dom, ["News One", "https://cdn/n/news1.jpg"], kinds=["text", "image"])
    assert err is None, err
    sels = [("제목", matched[0][1], None, "News One"),
            ("이미지", matched[1][1], "src", "https://cdn/n/news1.jpg")]
    eng = SelfHealingEngine(verbose=False)
    eng.build_schema_from_selection([rec], sig, sels, dom=dom)
    out = eng.extract(dom)
    imgs = [r.get("이미지") for r in out]
    assert imgs[0].endswith("news1.jpg"), imgs
    assert imgs[1].endswith("art2.jpg"), imgs      # 다른 구조(figure 안)여도 제 이미지
    assert imgs[2].endswith("news3.jpg"), imgs


def test_find_record_image_prefers_size_then_first_without_hint():
    """[역할] hint 없으면 가장 큰 img → 없으면 첫 img. (레코드 안 대표 이미지 선택 규칙)"""
    dom = lxml_html.fromstring(
        '<div class="c"><img src="/i/icon.png" width="16" height="16">'
        '<img src="/i/hero.jpg" width="300" height="200"></div>')
    node = _find_record_image(dom, hint="")
    assert node is not None and node.get("src").endswith("hero.jpg"), "가장 큰 img 를 골라야 함"


def test_find_record_image_skips_1px_spacer_and_data_uri():
    """[역할] 1x1 추적픽셀·base64 플레이스홀더(잡음)를 건너뛰고 실제 콘텐츠 썸네일을 고른다.
    (야후 라이브 DOM 에서 스페이서를 잡던 버그 재발 방지.)"""
    dom = lxml_html.fromstring(
        '<div class="card">'
        '<img src="https://cdn/spacer.gif" width="1" height="1">'          # 추적픽셀
        '<img src="data:image/gif;base64,R0lGODlh" width="80" height="80">'  # lazy 플레이스홀더
        '<img src="https://cdn/thumb.jpg" data-src="https://cdn/thumb.jpg" width="80" height="80">'  # 진짜
        '</div>')
    node = _find_record_image(dom, hint="")
    assert node is not None and node.get("src").endswith("thumb.jpg"), \
        f"1px/data: 를 건너뛰고 진짜 썸네일을 골라야 함: {None if node is None else node.get('src')}"


def test_typed_image_url_is_image_field_not_link():
    """[역할] ★피커 없이 '타이핑'한 이미지 URL(.jpg)도 이미지 필드로 잡는다(링크로 오인 금지).
    pixiv 처럼 이미지 URL 과 작품 링크가 같은 id 를 공유해도, .jpg 는 <img>(src)로 가야 한다."""
    dom = lxml_html.fromstring("""
    <html><body><ul>
      <li class="card"><a class="art" href="https://site/artworks/146686478">
        <img src="https://i.pximg.net/thumb/146686478_p0_250.jpg"></a>
        <div class="t">First Art</div></li>
      <li class="card"><a class="art" href="https://site/artworks/222">
        <img src="https://i.pximg.net/thumb/222_p0_250.jpg"></a>
        <div class="t">Second Art</div></li>
    </ul></body></html>""")
    # 타이핑: 제목 + 이미지URL(다른 사이즈 변종 .jpg) + 작품링크 — kinds 없음
    values = ["First Art",
              "https://i.pximg.net/c/480x960/146686478_p0_master1200.jpg",
              "https://site/artworks/146686478"]
    rec, sig, matched, err = locate_by_example(dom, values)   # kinds=None (타이핑)
    assert err is None, err
    by = {v: (node, attr) for v, node, nm, attr in matched}
    img_node, img_attr = by[values[1]]
    assert img_attr == "src" and img_node is not None and img_node.tag == "img", \
        "타이핑한 .jpg 는 링크가 아니라 이미지(src)로 잡혀야 함"
    # 작품 링크는 링크로
    assert by[values[2]][1] == "href"


def test_img_value_remote_vs_localized_vs_relative():
    """[역할] 이미지 값 정규화: 원격 http 는 그대로, Save-As 로컬화 경로는 사이트 URL 에 붙이지 않고
    스냅샷 폴더 기준 로컬 파일로, 그 외 사이트-상대경로는 base 로 절대화. (재현 시 URL mangling 버그 방지)"""
    from engine import _img_value
    import os
    base = "https://www.yahoo.co.jp/"
    lb = os.path.join("output", "saved")
    # 원격은 그대로
    assert _img_value("https://cdn/x.jpg", base, lb) == "https://cdn/x.jpg"
    # 로컬화(_files) 상대경로 → 사이트 URL 이 아니라 스냅샷 폴더 기준 로컬 경로
    got = _img_value("./output_yahoo_1_files/G6mABC", base, lb)
    assert "yahoo.co.jp" not in got and got.endswith(os.path.join("output_yahoo_1_files", "G6mABC"))
    # 사이트-상대경로(로컬화 아님) → base 로 절대화
    assert _img_value("/img/logo.png", base, lb) == "https://www.yahoo.co.jp/img/logo.png"
    # data: 는 값 없음
    assert _img_value("data:image/gif;base64,AAAA", base, lb) == "data:image/gif;base64,AAAA"


def test_find_record_image_handles_float_dims():
    """[역할] width/height 가 소수('90'x'57.02')여도 면적 계산이 깨지지 않는다(야후 실측)."""
    dom = lxml_html.fromstring(
        '<div class="c"><img src="/i/small.jpg" width="40" height="40">'
        '<img src="/i/big.jpg" width="90" height="57.02727272727273"></div>')
    node = _find_record_image(dom, hint="")
    assert node is not None and node.get("src").endswith("big.jpg"), "소수 치수 img(90x57)를 더 크게 봐야 함"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

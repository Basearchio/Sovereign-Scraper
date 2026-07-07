# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/picker.py
PURPOSE: '시각적 요소 피커'(에드블록 스타일) — headed 브라우저로 로컬 HTML(Save-As 스냅샷)을 열고,
         사용자가 마우스로 클릭한 요소의 '보이는 값'을 수집한다. 그 값들은 곧 엔진의 '예시 값'이므로,
         타이핑 대신 클릭으로 select_by_example 을 태우는 입력기 역할(엔진/파이프라인은 무변경).
         우리 차별점(내 크롬 세션으로 받은 Save-As 스냅샷)을 그대로 살려, 로그인/안티봇 사이트도 커버.
DEPENDENCY: playwright(headed). 브라우저가 필요하므로 자동 테스트 대상은 순수 헬퍼(picks_to_example)뿐.

  · 클릭      = 보이는 텍스트   (예: 가격 클릭 → "9,900")
  · Alt+클릭  = 링크(href)      (가장 가까운 <a>)
  · Shift+클릭= 이미지(src)
  · 피커 DOM = 엔진 DOM 계약: '엔진이 파싱할 바로 그 HTML 파일'을 file:// 로 띄운다(값이 정확히 일치).
"""
from __future__ import annotations

import pathlib

# 페이지에 주입하는 피커 오버레이(hover 하이라이트 + 클릭 캡처 + 플로팅 툴바 + 완료 플래그).
# window._pick(rec) 로 파이썬에 실시간 통보하고, 최종 목록은 window.__picks 로도 읽는다.
_PICKER_JS = r"""
() => {
  if (window.__pickerInit) return; window.__pickerInit = true;
  window.__picks = []; window.__pickDone = false;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();

  const hl = document.createElement('div');
  hl.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;'
    + 'border:2px solid #e11;background:rgba(238,17,17,.12);display:none;border-radius:2px';
  document.documentElement.appendChild(hl);

  const bar = document.createElement('div');
  bar.id = '__pickbar';
  bar.style.cssText = 'position:fixed;z-index:2147483647;top:10px;right:10px;width:320px;'
    + 'background:#111;color:#fff;font:13px/1.45 sans-serif;padding:12px 14px;border-radius:10px;'
    + 'box-shadow:0 6px 22px rgba(0,0,0,.45)';
  bar.innerHTML = '<div style="font-weight:700;margin-bottom:4px">🖱 요소 피커</div>'
    + '<div style="opacity:.75;font-size:12px">클릭=텍스트 · Alt+클릭=링크 · Shift+클릭=이미지</div>'
    + '<ol id="__pl" style="margin:8px 0;padding-left:18px;max-height:40vh;overflow:auto"></ol>'
    + '<button id="__done" style="background:#2ea043;color:#fff;border:0;padding:6px 12px;'
    + 'border-radius:6px;cursor:pointer;font-weight:600">완료</button> '
    + '<button id="__undo" style="background:#444;color:#fff;border:0;padding:6px 12px;'
    + 'border-radius:6px;cursor:pointer">되돌리기</button>';
  document.documentElement.appendChild(bar);
  const list = bar.querySelector('#__pl');

  document.addEventListener('mousemove', e => {
    const el = e.target;
    if (!el || bar.contains(el)) { hl.style.display = 'none'; return; }
    const r = el.getBoundingClientRect();
    hl.style.display = 'block';
    hl.style.left = r.left + 'px'; hl.style.top = r.top + 'px';
    hl.style.width = r.width + 'px'; hl.style.height = r.height + 'px';
  }, true);

  document.addEventListener('click', e => {
    const el = e.target;
    if (!el || bar.contains(el)) return;   // 툴바 클릭은 통과
    e.preventDefault(); e.stopPropagation();
    let kind = 'text', value = norm(el.innerText || el.textContent);
    if (e.altKey) { const a = el.closest('a'); kind = 'link'; value = a ? a.href : ''; }
    else if (e.shiftKey) {
      let img = el.tagName === 'IMG' ? el : null;
      if (!img) {   // 컨테이너 클릭이면 '보이는 크기가 가장 큰' img 로(1px 스페이서/아이콘 회피)
        const cand = Array.from(el.querySelectorAll('img'));
        const area = i => { const r = i.getBoundingClientRect(); return r.width * r.height; };
        cand.sort((a, b) => area(b) - area(a));
        img = cand[0] || null;
      }
      kind = 'image';
      value = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';
    }
    if (!value) return;
    const rec = { kind: kind, value: value, tag: el.tagName.toLowerCase() };
    window.__picks.push(rec);
    const li = document.createElement('li');
    li.textContent = kind + ': ' + (value.length > 42 ? value.slice(0, 42) + '…' : value);
    list.appendChild(li);
    try { window._pick(rec); } catch (_) {}
  }, true);

  bar.querySelector('#__done').addEventListener('click', () => { window.__pickDone = true; });
  bar.querySelector('#__undo').addEventListener('click', () => {
    window.__picks.pop();
    if (list.lastChild) list.removeChild(list.lastChild);
  });
}
"""


def script_free_copy(html_path):
    """[순수] 저장 HTML 의 <script>(+ 자동 새로고침 meta)를 모두 제거한 사본을 '같은 폴더'에 만들고
    그 경로(pathlib.Path)를 돌려준다. 같은 폴더라 `_files/` 상대 리소스(CSS/이미지)는 그대로 로드된다.
    이유: 픽커는 오버레이 주입 때문에 브라우저 JS 를 켜야 하는데, 그러면 '저장 페이지 자신의 JS'가
    재부팅해 냉동된 DOM(Gmail 받은편지함 등)을 '일시적 오류/로그인' 페이지로 갈아치운다(실측: JS 켜면
    tr.zA 0개·title '일시적인 오류', 끄면 100개). script 만 걷어내면 그 하이재킹을 막고 DOM 이 그대로 남는다.
    (엔진은 원본을 lxml 로 정적 파싱하므로 값은 여전히 일치 — 스크립트는 보이는 값이 없다.)"""
    from lxml import html as _lh
    p = pathlib.Path(html_path)
    # 명시적 UTF-8 파싱: Save-As 스냅샷은 UTF-8. charset 선언이 없는 파일도 한글이 깨지지 않게.
    doc = _lh.parse(str(p), _lh.HTMLParser(encoding="utf-8")).getroot()
    for s in doc.xpath("//script"):
        s.getparent().remove(s)
    for m in doc.xpath("//meta[@http-equiv]"):
        if (m.get("http-equiv") or "").lower() == "refresh":
            m.getparent().remove(m)
    # UTF-8 로 직렬화하므로 charset 선언이 없으면 넣어 준다(브라우저가 한글을 잘못 디코딩하지 않게).
    head = doc.find(".//head")
    if head is not None and not any(
            m.get("charset") or "charset" in (m.get("content") or "").lower()
            for m in head.findall(".//meta")):
        meta = _lh.Element("meta")
        meta.set("charset", "utf-8")
        head.insert(0, meta)
    out = p.with_name(p.stem + ".__pick__" + p.suffix)
    out.write_bytes(_lh.tostring(doc, encoding="utf-8"))
    return out


def picks_to_example(picks) -> str:
    """[순수] 피커가 모은 값들을 select_by_example 이 받는 '@#' 구분 예시 문자열로.
    빈 값은 버리고, 앞뒤 공백 정리. (테스트 대상 — 브라우저 불필요.)"""
    vals = [str(p.get("value") or "").strip() for p in (picks or [])]
    return "@#".join(v for v in vals if v)


def picks_kinds(picks) -> list:
    """[순수] picks_to_example 와 '똑같은 필터(빈 값 제외)'로 정렬된 kind 리스트.
    → @# 로 쪼갠 값들과 1:1 로 대응한다. kind: 'text' | 'link' | 'image'.
    이미지 필드는 URL 매칭이 아니라 '구조로' <img> 를 잡아야 하므로 엔진까지 이 종류를 전달한다."""
    out = []
    for p in (picks or []):
        if str(p.get("value") or "").strip():
            out.append(str(p.get("kind") or "text"))
    return out


def pick_from_html(html_path, log=print, timeout_s: int = 900):
    """[사용처] cli --pick(로컬 Save-As 스냅샷). headed 브라우저로 file:// 를 열고 사용자가 클릭한
    요소 값들을 [{kind, value, tag}, ...] 로 반환. '완료' 누르면 종료(최대 timeout_s 대기).
    playwright 미설치/실패 시 RuntimeError(호출부가 안내)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("playwright 필요: pip install playwright && python -m playwright install chromium") from e

    # 저장 페이지의 JS 하이재킹 방지: <script> 걷어낸 사본을 띄운다(같은 폴더라 _files/ 리소스 유지).
    pick_file = script_free_copy(html_path)
    url = pick_file.resolve().as_uri()   # file:///... (스크립트 제거본 — 값/DOM 은 원본과 동일)
    picks = []

    def _pick(source, rec):        # 클릭 순간 CLI 로 실시간 에코(사용자 '찍힘' 피드백)
        picks.append(rec)
        log(f"  ✓ 담음 [{len(picks)}] {rec.get('kind')}: {str(rec.get('value'))[:50]!r}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        # 남은 외부 네트워크(폰트/추적/잔여 스크립트)는 차단 — 로컬 file:// 리소스만 로드(빠르고 안전).
        page.route("**/*", lambda route: route.abort()
                   if route.request.url.startswith(("http://", "https://")) else route.continue_())
        page.expose_binding("_pick", _pick)
        page.goto(url, wait_until="domcontentloaded")
        page.evaluate(_PICKER_JS)   # body 존재 후 주입(브라우저 JS 는 켜져 있어 오버레이 정상)
        log("  ▶ 브라우저에서 원하는 값들을 클릭하고 '완료'를 누르세요...")
        try:
            page.wait_for_function("window.__pickDone === true", timeout=timeout_s * 1000)
            picks[:] = page.evaluate("window.__picks") or picks   # 최종 목록으로 확정
        except Exception:
            pass
        browser.close()
    try:
        pick_file.unlink()      # 임시 사본 정리(실패해도 무방)
    except Exception:
        pass
    return picks


if __name__ == "__main__":   # 수동 스모크: python crawlers/picker.py output/saved/output_bilibili_1.html
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # _internal
    from i18n import t
    if len(sys.argv) < 2:
        print(t("사용: python crawlers/picker.py <저장된_HTML_경로>"))
        sys.exit(1)
    got = pick_from_html(sys.argv[1])
    print("\n■ " + t("수집된 예시 문자열(@# 구분):"))
    print("   " + picks_to_example(got))

# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/picker.py
PURPOSE: '시각적 요소 피커'(에드블록 스타일) — headed 브라우저로 로컬 HTML(Save-As 스냅샷)을 열고,
         사용자가 마우스로 클릭한 요소의 '보이는 값'을 수집한다. 그 값들은 곧 엔진의 '예시 값'이므로,
         타이핑 대신 클릭으로 select_by_example 을 태우는 입력기 역할(엔진/파이프라인은 무변경).
         우리 차별점(내 크롬 세션으로 받은 Save-As 스냅샷)을 그대로 살려, 로그인/안티봇 사이트도 커버.
DEPENDENCY: playwright(headed) + structure(leaf, 반복 구조 탐지 재사용) + i18n(leaf, 로그 문구 번역
            — __main__ 자기부트스트랩과 충돌 안 나게 함수 안에서 지연 임포트). 브라우저가 필요하므로
            자동 테스트 대상은 순수 헬퍼(picks_to_example/detect_repeating_fields 등)뿐.

  · 클릭      = 보이는 텍스트   (예: 가격 클릭 → "9,900")
  · Alt+클릭  = 링크(href)      (가장 가까운 <a>)
  · Shift+클릭= 이미지(src)
  · 피커 DOM = 엔진 DOM 계약: '엔진이 파싱할 바로 그 HTML 파일'을 file:// 로 띄운다(값이 정확히 일치).
  · 읽기모드 = CSS 가 깨져도(구글류 확장자 없는 리소스 등) 내용을 보게 하는 탈출구. 레시피/사전
    지식 없이 '지금 이 페이지의 반복 구조'만 보고 자주 반복되는 자리를 번호(#1,#2…)로 표시한다
    (detect_repeating_fields/_annotate_repeating_fields) — 어떤 반복형 사이트에도 동일하게 적용.
"""
from __future__ import annotations

import os
import pathlib

# 페이지에 주입하는 피커 오버레이(hover 하이라이트 + 클릭 캡처 + 플로팅 툴바 + 완료 플래그).
# window._pick(rec) 로 파이썬에 실시간 통보하고, 최종 목록은 window.__picks 로도 읽는다.
# 툴바 문구는 이 JS 안에서 t()를 직접 부를 수 없으므로(브라우저 런타임 ≠ 파이썬), pick_from_html
# 이 t()로 미리 번역한 라벨 dict 를 page.evaluate(_PICKER_JS, labels) 의 인자 L 로 주입한다.
_PICKER_JS = r"""
(L) => {
  if (window.__pickerInit) return; window.__pickerInit = true;
  window.__picks = []; window.__pickDone = false;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();

  const hl = document.createElement('div');
  hl.id = '__pickhl';
  hl.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;'
    + 'border:2px solid #e11;background:rgba(238,17,17,.12);display:none;border-radius:2px';
  document.documentElement.appendChild(hl);

  // '읽기 모드': 저장 스냅샷 CSS 일부가 file:// 재오픈 시 안 먹으면(구글류 확장자 없는 리소스 등,
  // 실측 확인됨) 원래 여러 개였던 항목들이 박스 구분 없이 한 덩어리로 붙어 보인다. 원본 모양을
  // 복원하려 하지 않고, 아예 모든 요소를 강제로 한 줄씩 분리해 '내용이라도' 확실히 클릭 가능하게
  // 만드는 탈출구(형식 포기, 내용 우선). DOM 자체는 안 건드리므로 구조 경로 기반 추출은 그대로 유지.
  // ★첫 시도 실측 실패: 모든 요소를 display:block 하면, 원래 display:none/닫힌 메뉴/스크린리더
  // 전용 텍스트 등 '원래 안 보이던' 요소까지 전부 화면에 펼쳐져 문서 높이가 수십만px 로 폭발 →
  // 진짜 내용은 화면 밖 저 아래로 밀려나고 맨 위 로고 하나만 보이는 것처럼 됨. 켜기 '전' 레이아웃
  // 기준으로 '이미 화면에 크기가 있던(0×0 이 아닌)' 요소만 펼치고, 원래 안 보이던 건 계속 숨긴다.
  const READER_CSS = document.createElement('style');
  READER_CSS.id = '__readerCss';
  READER_CSS.textContent = `
    /* ★실사용자 확인된 회귀: 'html.__reader-mode .__reader-show'(공백=자손 결합자)는 <html> 이
       __reader-show 를 '자기 자신'에게 갖는 경우엔 안 먹는다(자기 자신은 자기 자손이 될 수 없음).
       그래서 문서 전체는 펼쳐져도 스크롤을 쥔 <html> 자체의 원래 overflow:hidden(Gmail 앱쉘용)이
       안 풀려 스크롤이 완전히 막혔었다 — html 자신이 해당하는 경우(콤마로 병기)도 함께 지정. */
    html.__reader-mode.__reader-show, html.__reader-mode .__reader-show {
      all: revert !important;
      overflow: visible !important;
      display: block !important;
      white-space: pre-wrap !important;
      word-break: break-word !important;
      padding: 2px 6px !important;
      margin: 0 !important;
      border-bottom: 1px solid rgba(160,160,160,.4) !important;
      color: #eaeaea !important;
      background: #1b1b1b !important;
      font: 13px/1.5 -apple-system, sans-serif !important;
      position: static !important;
      float: none !important;
    }
    html.__reader-mode img.__reader-show { display: inline-block !important; max-width: 90px !important; max-height: 70px !important; }
    html.__reader-mode a.__reader-show { color: #7cc4ff !important; text-decoration: underline !important; }
    html.__reader-mode .__reader-hide { display: none !important; }
    /* 내용이 아예 없는 요소(추적용 빈 <a> 등)가 실제 텍스트를 가진 요소 위에 겹쳐 클릭을
       가로채는 경우가 실사용자 확인됨(Gmail) → 클릭을 통과시켜 뒤/옆의 진짜 대상이 잡히게 함. */
    html.__reader-mode .__reader-empty { pointer-events: none !important; }
    /* 레시피·사전 지식 없이, 지금 이 페이지의 '반복 구조'만 보고 파이썬이 미리 찾아둔 후보
       필드(data-__field=N, _annotate_repeating_fields 가 심음)를 번호로 표시 — "제목 제목 제목"
       처럼 반복되는 자리를 사용자가 한눈에 알아보게(다른 메일/게시판 사이트에도 동일 적용). */
    html.__reader-mode [data-__field] { outline: 2px solid #4ea1ff !important; outline-offset: -1px !important; }
    html.__reader-mode [data-__field]::before {
      content: '#' attr(data-__field) !important;
      display: inline-block !important;
      background: #4ea1ff !important;
      color: #04264d !important;
      font: 700 11px/1.4 monospace !important;
      padding: 0 4px !important;
      margin: 0 4px 0 0 !important;
      border-radius: 3px !important;
    }
    html.__reader-mode body { background: #1b1b1b !important; }
  `;
  document.head.appendChild(READER_CSS);

  function enterReaderMode() {
    // 리셋 '전' 크기를 기준으로 원래 보이던 요소/안 보이던 요소를 나눠 표시해둔다(리셋 후엔
    // 전부 강제로 보이게 되므로 미리 판정해야 함).
    // ★실사용자 확인된 회귀: Gmail 처럼 요소가 수만 개인 DOM 에서 '읽기(rect)→쓰기(class)'를
    // 한 요소씩 번갈아 하면 매 반복마다 강제 리플로우가 걸려(레이아웃 스래싱) 페이지가 몇 초~
    // 수십 초씩 멎어버린다 — 그동안의 클릭은 브라우저가 못 받아 '피커가 안 먹는다'로 보였고,
    // 화면도 처리 도중 상태로 멈춰 최상단 몇 개(건너뛰기 링크 등)만 보이는 것처럼 됐다.
    // 모든 요소의 rect 를 먼저 다 읽고, 그다음에 class 를 몰아서 쓰면(읽기·쓰기 단계 분리)
    // 리플로우가 한 번만 일어나 훨씬 빠르다.
    const els = Array.from(document.querySelectorAll('*')).filter(el =>
      !el.closest('#__pickbar') && el.id !== '__pickhl' && el.id !== '__readerCss');
    // 읽기 단계(전부 먼저) — innerText 는 textContent 와 달리 '실제 화면에 보이는 글자만' 치므로
    // 안 보이는 스크린리더 전용 텍스트가 섞여 '비어있지 않다'고 오판되는 걸 막는다(실측: 호버용
    // 빈 <div>(공백 하나)가 innerText 기준으론 비어있는데 textContent 기준으론 안 비어있어서
    // __reader-empty 판정을 피해가며 실제 링크 위에 계속 겹쳐 클릭을 가로챈 사례 확인).
    const rects = els.map(el => el.getBoundingClientRect());
    const texts = els.map(el => (el.innerText || '').trim());
    els.forEach((el, i) => {                                    // 쓰기 단계(그 다음에 몰아서)
      el.classList.remove('__reader-show', '__reader-hide', '__reader-empty');  // 재토글 초기화
      const r = rects[i];
      el.classList.add(r.width > 0 || r.height > 0 ? '__reader-show' : '__reader-hide');
      // 이미지 캡처(Shift+클릭)는 텍스트가 없어도 정상 대상이므로 제외.
      if (!texts[i] && el.tagName !== 'IMG' && !el.querySelector('img')) {
        el.classList.add('__reader-empty');
      }
    });
    document.documentElement.classList.add('__reader-mode');
  }

  const bar = document.createElement('div');
  bar.id = '__pickbar';
  bar.style.cssText = 'position:fixed;z-index:2147483647;top:10px;right:10px;width:320px;'
    + 'background:#111;color:#fff;font:13px/1.45 sans-serif;padding:12px 14px;border-radius:10px;'
    + 'box-shadow:0 6px 22px rgba(0,0,0,.45)';
  bar.innerHTML = `<div style="font-weight:700;margin-bottom:4px">🖱 ${L.title}</div>`
    + `<div style="opacity:.75;font-size:12px">${L.desc1}</div>`
    + `<div style="opacity:.75;font-size:12px;margin-top:2px">${L.desc2}</div>`
    + '<ol id="__pl" style="margin:8px 0;padding-left:18px;max-height:40vh;overflow:auto"></ol>'
    + `<button id="__done" style="background:#2ea043;color:#fff;border:0;padding:6px 12px;`
    + `border-radius:6px;cursor:pointer;font-weight:600">${L.done}</button> `
    + `<button id="__undo" style="background:#444;color:#fff;border:0;padding:6px 12px;`
    + `border-radius:6px;cursor:pointer">${L.undo}</button> `
    + `<button id="__reader" title="${L.readerTitle}"`
    + ` style="background:#444;color:#fff;border:0;padding:6px 12px;`
    + `border-radius:6px;cursor:pointer">${L.reader}</button>`;
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
    // 저장 스냅샷의 일부 CSS(특히 확장자 없는 구글류 리소스)가 file:// 재오픈 시 적용 안 되면,
    // 원래는 여러 개의 작은 항목이던 영역이 박스 구분 없이 한 덩어리로 붙어 보인다 → 클릭하면
    // 의도한 항목이 아니라 그 덩어리 전체(예: 사이드바 라벨 목록 전체)를 담게 된다. 길이로 그런
    // '뭉친 값'을 즉시 표시해 사용자가 그 자리에서 '되돌리기' 하도록 돕는다(완벽 복원 대신 조기경고).
    const big = kind === 'text' && value.length > 120;
    const rec = { kind: kind, value: value, tag: el.tagName.toLowerCase(), big: big };
    window.__picks.push(rec);
    const li = document.createElement('li');
    li.textContent = (big ? '⚠ ' : '') + kind + ': ' + (value.length > 42 ? value.slice(0, 42) + '…' : value);
    if (big) { li.style.color = '#ffb84d'; li.title = L.bigWarn; }
    list.appendChild(li);
    try { window._pick(rec); } catch (_) {}
  }, true);

  bar.querySelector('#__done').addEventListener('click', () => { window.__pickDone = true; });
  bar.querySelector('#__undo').addEventListener('click', () => {
    if (!window.__picks.length) return;
    window.__picks.pop();
    if (list.lastChild) list.removeChild(list.lastChild);
    try { window._unpick(window.__picks.length); } catch (_) {}   // 터미널에 '되돌림' 즉시 에코
  });
  bar.querySelector('#__reader').addEventListener('click', () => {
    const on = !document.documentElement.classList.contains('__reader-mode');
    if (on) { enterReaderMode(); }
    else { document.documentElement.classList.remove('__reader-mode'); }
    bar.querySelector('#__reader').textContent = on ? L.readerOff : L.reader;
  });
}
"""


def script_free_copy(html_path):
    """[순수] 저장 HTML 의 <script>(+ <iframe> + 자동 새로고침 meta)를 모두 제거한 사본을 '같은
    폴더'에 만들고 그 경로(pathlib.Path)를 돌려준다. 같은 폴더라 `_files/` 상대 리소스(CSS/이미지)는
    그대로 로드된다.
    이유: 픽커는 오버레이 주입 때문에 브라우저 JS 를 켜야 하는데, 그러면 '저장 페이지 자신의 JS'가
    재부팅해 냉동된 DOM(Gmail 받은편지함 등)을 '일시적 오류/로그인' 페이지로 갈아치운다(실측: JS 켜면
    tr.zA 0개·title '일시적인 오류', 끄면 100개). script 만 걷어내면 그 하이재킹을 막고 DOM 이 그대로 남는다.
    (엔진은 원본을 lxml 로 정적 파싱하므로 값은 여전히 일치 — 스크립트는 보이는 값이 없다.)
    ★실사용자 확인된 회귀: <script> 만 지우고 <iframe> 은 남겨뒀더니, Gmail 이 iframe(app.html,
    m=_b,_tp 등 저장된 모듈 로더) 안에서 '진짜 살아있는 세션'인 것처럼 계속 모듈을 초기화하려다
    실패(gapi 미정의·postMessage 오류 등)를 반복하며 화면·픽커 동작을 방해했다. script 와 똑같은
    이유로 iframe 도 통째로 제거해야 한다."""
    from lxml import html as _lh
    p = pathlib.Path(html_path)
    # 명시적 UTF-8 파싱: Save-As 스냅샷은 UTF-8. charset 선언이 없는 파일도 한글이 깨지지 않게.
    doc = _lh.parse(str(p), _lh.HTMLParser(encoding="utf-8")).getroot()
    for s in doc.xpath("//script | //iframe"):
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


def _leaf_paths(row):
    """[순수] row 안의 '리프'(자식 요소가 없고 텍스트가 있는) 노드들의 자식-인덱스 경로 목록
    (문서 순서). 레시피/사전 지식 없이 '지금 이 페이지'만 보고 후보를 뽑기 위한 최소 표현 —
    지금 이 순간의 같은 DOM 안에서만 쓰므로 rel_path/follow_path(자가치유용, class 앵커 등)
    같은 정교함은 불필요하고, 반복 형제 사이에서는 단순 자식 인덱스로 충분히 안정적이다."""
    from structure import _children, _norm
    out = []

    def walk(node, path):
        kids = _children(node)
        if not kids:
            if _norm(node.text_content()):
                out.append(list(path))
            return
        for i, c in enumerate(kids):
            walk(c, path + [i])

    walk(row, [])
    return out


def _resolve_path(row, path):
    """[순수] _leaf_paths 가 만든 자식-인덱스 경로를 row 에 적용해 노드를 찾는다(없으면 None)."""
    from structure import _children
    node = row
    for i in path:
        kids = _children(node)
        if i >= len(kids):
            return None
        node = kids[i]
    return node


def detect_repeating_fields(dom, max_rows: int = 60, sample_size: int = 20,
                            min_hit_rate: float = 0.6):
    """[순수] 레시피/사전 지식 없이 '지금 이 페이지의 반복 구조'만 보고, 거의 모든 반복 행에
    일관되게 텍스트가 있는 자리를 찾는다(엔진의 calibrate 와 같은 find_repeating_rows 를 쓰되,
    특정 필드 유형을 매칭하는 게 아니라 '반복되는 모든 리프 위치'를 후보로 봄).

    [사용처] 읽기모드가 "제목/발신자처럼 보이는 자리"를 사용자가 알아보게 번호 라벨을 붙이는
    용도(_annotate_repeating_fields). 다른 사이트에도 동일 로직이 그대로 적용된다(구조 반복만
    보므로 Gmail 전용 지식 없음).

    Returns: (rows, field_paths) — 반복 행 목록(최대 max_rows개)과 채택된 자식-인덱스 경로 목록
    (문서 순서 = 표시될 번호 순서). 반복 구조가 약하면(행 3개 미만) ([], [])."""
    from structure import find_repeating_rows, _norm
    rows, _sig = find_repeating_rows(dom)
    if not rows or len(rows) < 3:
        return [], []
    rows = rows[:max_rows]
    # 참고 행: 후보가 가장 많이 나오는 행을 기준으로(첫 행에 선택적 필드 하나가 빠진 경우 대비).
    ref = max(rows[:5], key=lambda r: len(_leaf_paths(r)))
    candidates = _leaf_paths(ref)
    sample = rows[:sample_size]
    good = []
    for path in candidates:
        hits = sum(1 for r in sample
                  if (n := _resolve_path(r, path)) is not None and _norm(n.text_content()))
        if hits / len(sample) >= min_hit_rate:
            good.append(path)
    return rows, good


def _annotate_repeating_fields(html_file: pathlib.Path) -> pathlib.Path:
    """[사용처] pick_from_html — 읽기모드가 '자주 반복되는 구조'를 미리 찾아 번호로 보여줄 수
    있도록, 채택된 후보 필드의 실제 위치마다(모든 반복 행에 걸쳐) data-__field=N 속성을 직접
    심어 같은 파일에 덮어쓴다. 순수 마킹(속성 추가)만 하므로 값/구조는 안 바뀜 — 엔진 추출과
    무관. 반복 구조가 없으면 그대로 둔다(실패해도 조용히 원본 유지)."""
    from lxml import html as _lh
    try:
        doc = _lh.parse(str(html_file), _lh.HTMLParser(encoding="utf-8")).getroot()
    except Exception:
        return html_file
    rows, good = detect_repeating_fields(doc)
    if not good:
        return html_file
    for row in rows:
        for field_no, path in enumerate(good, 1):
            node = _resolve_path(row, path)
            if node is not None:
                node.set("data-__field", str(field_no))
    html_file.write_bytes(_lh.tostring(doc, encoding="utf-8"))
    return html_file


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


def _local_stylesheet_paths(html_file: pathlib.Path) -> set:
    """[순수] html_file 안의 <link rel=stylesheet href=...>(로컬 상대경로만) 를 절대경로 문자열
    집합으로. 크롬 'Webpage, Complete' 저장분은 리소스 파일명이 원본 URL 쿼리 그대로(예: rs=AA2Yr...)라
    확장자가 없는 경우가 있다 — file:// 로 다시 열면 브라우저가 MIME 을 못 알아내 text/plain 으로 서빙,
    '이건 CSS 가 아니다'로 판단해 스타일 적용을 거부한다(document.styleSheets 의 해당 항목이 cssRules
    접근 시 에러 — 실측 확인됨). 이 경로들만 나중에 명시적으로 text/css 로 응답해 우회한다."""
    from lxml import html as _lh
    try:
        doc = _lh.parse(str(html_file), _lh.HTMLParser(encoding="utf-8")).getroot()
    except Exception:
        return set()
    base_dir = html_file.parent
    out = set()
    for link in doc.xpath("//link[@rel='stylesheet']"):
        href = (link.get("href") or "").strip()
        if not href or href.startswith(("http://", "https://", "data:", "//")):
            continue
        out.add(os.path.normcase(os.path.abspath(str(base_dir / href))))
    return out


def _file_url_to_path(url: str) -> str:
    """[순수] file:// URL → 로컬 경로 문자열(윈도우 드라이브 문자 포함). 비교용으로 normcase."""
    from urllib.parse import urlparse, unquote
    p = unquote(urlparse(url).path)
    if len(p) > 2 and p[0] == "/" and p[2] == ":":   # /C:/... → C:/...
        p = p[1:]
    return os.path.normcase(os.path.abspath(p))


def pick_from_html(html_path, log=print, timeout_s: int = 900):
    """[사용처] cli --pick(로컬 Save-As 스냅샷). headed 브라우저로 file:// 를 열고 사용자가 클릭한
    요소 값들을 [{kind, value, tag}, ...] 로 반환. '완료' 누르면 종료(최대 timeout_s 대기).
    playwright 미설치/실패 시 RuntimeError(호출부가 안내)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("playwright 필요: pip install playwright && python -m playwright install chromium") from e
    from i18n import t     # 지연 임포트: __main__ 직접 실행 시 자기부트스트랩(sys.path.insert)보다
                            # 먼저 모듈 최상단에서 import 되면 깨지므로, 실제로 필요한 이 시점에 임포트.

    # 저장 페이지의 JS 하이재킹 방지: <script> 걷어낸 사본을 띄운다(같은 폴더라 _files/ 리소스 유지).
    pick_file = script_free_copy(html_path)
    pick_file = _annotate_repeating_fields(pick_file)   # 읽기모드용 반복 필드 번호 마킹(레시피 불필요)
    url = pick_file.resolve().as_uri()   # file:///... (스크립트 제거본 — 값/DOM 은 원본과 동일)
    css_paths = _local_stylesheet_paths(pick_file)   # MIME 보정이 필요한 로컬 스타일시트 경로들
    picks = []

    def _pick(source, rec):        # 클릭 순간 CLI 로 실시간 에코(사용자 '찍힘' 피드백)
        picks.append(rec)
        log("  ✓ " + ("⚠ " if rec.get('big') else "") +
            t("담음 [{n}] {kind}: {v}", n=len(picks), kind=rec.get('kind'),
              v=repr(str(rec.get('value'))[:50])))
        if rec.get('big'):
            log("    " + t("값이 유난히 깁니다 — 여러 항목이 뭉쳤을 수 있어요. "
                          "'되돌리기'로 지우고 더 안쪽 요소를 클릭해보세요."))

    def _unpick(source, remaining):   # '되돌리기' 클릭 순간 CLI 로 실시간 에코(안 지운 것처럼 보이는 것 방지)
        del picks[remaining:]         # 브라우저 window.__picks 와 길이를 맞춤(파이썬 쪽 목록도 진짜로 줄임)
        log("  ↩ " + t("되돌림 → 남은 값 {n}개", n=remaining))

    def _route(route):
        req_url = route.request.url
        if req_url.startswith(("http://", "https://")):
            # 남은 외부 네트워크(폰트/추적/잔여 스크립트)는 차단 — 로컬 file:// 리소스만 로드(빠르고 안전).
            route.abort()
            return
        if req_url.startswith("file://") and _file_url_to_path(req_url) in css_paths:
            try:
                route.fulfill(path=_file_url_to_path(req_url), content_type="text/css")
                return
            except Exception:
                pass   # 실패하면 평범하게 계속(최소 스타일 없이라도 데이터는 살아있음)
        route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.route("**/*", _route)
        page.expose_binding("_pick", _pick)
        page.expose_binding("_unpick", _unpick)
        page.goto(url, wait_until="domcontentloaded")
        # 툴바 문구는 브라우저 JS 안에서 t()를 못 부르니, 여기서 미리 번역해 인자로 넘긴다.
        labels = {
            "title": t("요소 피커"),
            "desc1": t("클릭=텍스트 · Alt+클릭=링크 · Shift+클릭=이미지"),
            "desc2": t("화면이 안 보이면 → 읽기모드 · 읽기모드에서도 안 보이면 → 휠로 스크롤"),
            "done": t("완료"),
            "undo": t("되돌리기"),
            "reader": t("읽기모드"),
            "readerOff": t("읽기모드 끄기"),
            "readerTitle": t("화면이 깨져 보이면: 모양을 포기하고 내용만 한 줄씩 분리해서 보여줍니다. "
                            "자주 반복되는 자리는 파란 테두리+번호(#1,#2…)로 표시됩니다."),
            "bigWarn": t("값이 유난히 깁니다 — 여러 항목이 뭉쳤을 수 있어요."),
        }
        page.evaluate(_PICKER_JS, labels)   # body 존재 후 주입(브라우저 JS 는 켜져 있어 오버레이 정상)
        log("  ▶ " + t("브라우저에서 원하는 값들을 클릭하고 '완료'를 누르세요..."))
        try:
            page.wait_for_function("window.__pickDone === true", timeout=timeout_s * 1000)
        except Exception:
            pass   # 타임아웃/창 닫힘 등 — 아래에서 그 시점까지의 window.__picks 는 그래도 회수 시도
        try:
            # '완료' 대기가 실패해도 이 동기화는 별도로 시도한다 — _pick/_unpick 실시간 에코로
            # picks 는 이미 거의 맞지만, '되돌리기'가 이 시점 이후 마지막 클릭 하나만 브라우저에
            # 반영되고 아직 _unpick 콜백이 안 돌았을 수도 있는 미세한 순간차를 최종적으로 봉합.
            picks[:] = page.evaluate("window.__picks") or picks
        except Exception:
            pass   # 브라우저가 이미 닫혔다면 _pick/_unpick 로 이미 반영된 picks 를 그대로 신뢰
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

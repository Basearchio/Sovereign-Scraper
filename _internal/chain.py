# -*- coding: utf-8 -*-
"""
MODULE_NAME: chain.py
PURPOSE: 체인 크롤링(목록 CSV → 링크 열 → 각 상세페이지) 컨트롤러. 1차 수집한 목록 CSV 의 '링크
         열'을 따라 각 상세페이지를 단일 레코드로 2차 수집해 '별도 상세 CSV' 로 저장한다. 레시피가
         있으면 입력 없이 재현, 없으면 학습해 레시피로 저장. URL 정련(by-example)·iframe 인라인·
         본문/CSS 필드 지정·랜덤 대기 포함.
DEPENDENCY: engine(SelfHealingEngine/row_sig/load_dom), core.schema(Schema), loader(DOM 획득+가변 상태),
  output(save_csv), cli(대화형 학습 헬퍼 select_by_example).

[계층 규율] cli 와 '동료(peer) 컨트롤러'다: chain 은 cli.select_by_example 만 import 하고(DOM 획득·저장은
  loader/output leaf 에서 직접), cli.main 은 run_chain_crawl 을 '지연(lazy) import' 해 순환을 끊는다.
  '가변 상태'(LAST_LOAD_METHOD/RENDER_REQUIRED)는 loader 가 실행 중 갱신하므로 반드시 loader.<이름> 으로
  '실시간' 참조한다(값 복사 금지).

[검증된 주요 사이트 및 케이스]
- incruit 목록 CSV → 공고 상세 체인(본문 iframe 인라인, 이미지 공고 미디어 폴백). 계층번호 P-k.
- URL 정련: 링크 1개를 고친 예시로 꼬리(&src=..)/괄호 제거 규칙 추론 → 열 전체 적용.

[테스트/운영 교훈]
- '독립된 여러 페이지' 배치이므로 단일 추출은 스키마 고정(engine._extract_single) — 오염 방지(#20).
- 상세 요청 간 랜덤 대기(_delay_bounds)로 특정 사이트 과부하/차단 방지.
- 행동 계약은 tests/test_chain_golden.py 가 고정(URL 정련·고정스키마·미디어 폴백).
"""
import os
import sys

from engine import SelfHealingEngine, row_sig, load_dom
from core.schema import Schema
import cli
# 경로 규칙은 leaf(paths), 감사로그는 leaf(runlog)에서 직접 — 나머지 실행 헬퍼는 cli(동료 컨트롤러).
from paths import chain_recipe_path_for, chain_csv_path_for, chain_recipe_glob
# append_runlog 는 record_run 이 감싸지만 테스트가 chain 재-export 를 고정하므로 유지.
from runlog import append_runlog, resolve_batch, record_run  # noqa: F401
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)
from cli import select_by_example
from loader import load_or_die, _warn_if_spa   # DOM 획득은 loader.py leaf 에서 직접(cli 우회). v5.0 탈결합
import loader   # 가변 상태(LAST_LOAD_METHOD/RENDER_REQUIRED)는 loader.<이름> 으로 실시간 참조
# CSV 저장 + 저장방식 결정 규칙은 output.py leaf 에서 직접(cli 갓-모듈 우회, cli 와 규칙 공유).
from output import save_csv, resolve_save_mode


def _read_csv_rows(path):
    """CSV 를 (컬럼목록, [행dict, ...]) 로 읽는다. Excel 한글 대응 utf-8-sig."""
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        cols = list(r.fieldnames or [])
        rows = list(r)
    return cols, rows


def _guess_url_col(cols):
    """URL 이 담겼을 법한 컬럼명 추정(우선순위: *_url > url/링크 > 'url' 포함)."""
    for c in cols:
        if c.endswith("_url"):
            return c
    for c in cols:
        if c.lower() == "url" or c == "링크":
            return c
    for c in cols:
        if "url" in c.lower():
            return c
    return None


def _derive_url_cleaner(full: str, clean: str):
    """원본 URL 1개(full)와 사용자가 정련한 값(clean)을 비교해, 열 전체에 적용할
    정련 함수와 설명을 만든다.

    규칙 감지(사용자가 '지운 부분'을 그대로 재현):
      · clean 이 full 의 '연속 부분 문자열'이면 → 앞/뒤로 지운 리터럴을 전 행에서 제거.
        (꼬리 제거 / 괄호 등 '감싸기' 제거 / 앞부분 제거 를 모두 커버)
      · 지운 꼬리가 쿼리(?..=.. / &..=..) 형태면 → 값이 행마다 달라도 되도록
        '그 파라미터 이름' 기준 제거로 업그레이드.
    반환: (cleaner(u)->str, 설명|None). 설명이 None 이면 규칙 감지 실패(원본 유지).
    """
    full, clean = (full or "").strip(), (clean or "").strip()
    if not clean or clean == full:
        return (lambda u: (u or "").strip()), "정련 없음(원본 그대로)"
    idx = full.find(clean)
    if idx < 0:
        return (lambda u: (u or "").strip()), None   # 부분문자열 아님 → 감지 실패
    prefix = full[:idx]                    # 앞에서 지운 리터럴 (예: '(' 또는 'link: ')
    suffix = full[idx + len(clean):]       # 뒤에서 지운 리터럴 (예: ')' 또는 '&src=..')

    # 꼬리가 쿼리 파라미터면 '이름 기준' 제거로 업그레이드(값이 행마다 달라도 처리).
    drop_params = None
    if suffix and suffix[0] in "?&":
        from urllib.parse import parse_qsl
        names = [k for k, _ in parse_qsl(suffix.lstrip("?&"), keep_blank_values=True)]
        if names:
            drop_params = set(names)

    def cleaner(u):
        u = (u or "").strip()
        if not u:
            return u
        if prefix and u.startswith(prefix):     # 1) 앞 리터럴 제거 (urlsplit 전에)
            u = u[len(prefix):]
        if drop_params is not None:             # 2a) 꼬리=쿼리 → 파라미터 이름 기준 제거
            from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
            s = urlsplit(u)
            q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
                 if k not in drop_params]
            u = urlunsplit((s.scheme, s.netloc, s.path, urlencode(q), s.fragment))
        elif suffix and u.endswith(suffix):     # 2b) 꼬리 리터럴 제거
            u = u[:len(u) - len(suffix)]
        return u.strip()

    bits = []
    if prefix:
        bits.append(f"앞 {prefix!r} 제거")
    if drop_params is not None:
        bits.append(f"쿼리 파라미터 {sorted(drop_params)} 제거")
    elif suffix:
        bits.append(f"뒤 {suffix!r} 제거")
    return cleaner, " + ".join(bits) if bits else "정련 없음"


_AD_IFRAME_HOSTS = ("doubleclick", "googlesyndication", "google-analytics",
                    "googletagmanager", "facebook.", "adservice", "criteo")


def _inline_iframes(dom, base_url, limit=3):
    """상세페이지의 <iframe> 내용을 바깥 DOM 에 인라인한다(사이트 하드코딩 없음).

    incruit 처럼 공고 본문이 iframe(예: jobpostcont.asp) 안에 있는 사이트는, 바깥
    페이지만 보면 본문이 '빈 껍데기'다. iframe src 를 직접 받아 그 <body> 를 iframe
    노드 자리에 붙여, by-example/CSS 셀렉터가 본문을 실제로 찾게 한다.
    반환: 인라인한 iframe 개수.
    """
    from urllib.parse import urljoin
    n = 0
    for ifr in list(dom.iter("iframe"))[:max(0, limit)]:
        src = (ifr.get("src") or "").strip()
        if not src:
            continue
        url = urljoin(base_url, src)
        if not url.startswith(("http://", "https://")):
            continue
        if any(h in url for h in _AD_IFRAME_HOSTS):   # 광고/추적 프레임 제외
            continue
        try:
            sub = load_dom(url)
        except Exception:
            continue
        body = sub.find(".//body")
        node = body if body is not None else sub
        node.tag = "div"                 # iframe 자식으로 붙이기 좋게 div 로
        node.set("data-inlined-iframe", "1")   # 본문 경계 표시(anchor→본문 컨테이너 탐색용)
        for ch in list(ifr):
            ifr.remove(ch)
        ifr.append(node)                 # 다른 트리의 노드를 이 트리로 이동(reparent)
        n += 1
    return n


def _find_by_css(dom, sel):
    """아주 단순한 CSS 셀렉터로 첫 노드를 찾는다(문서 순서).
    지원: tag / .class / tag.class / #id / tag#id  (클래스/아이디 각 1개)."""
    sel = (sel or "").strip()
    elid = None
    if "#" in sel:
        base, elid = sel.split("#", 1)
        elid = elid.strip() or None
    else:
        base = sel
    base = base.strip()
    tag = cls = None
    if "." in base:
        t, rest = base.split(".", 1)
        tag = t.strip() or None
        cls = (rest.split(".")[0]).strip() or None
    elif base:
        tag = base
    for e in dom.iter():
        if not isinstance(e.tag, str):
            continue
        if tag and e.tag != tag:
            continue
        if elid and e.get("id") != elid:
            continue
        if cls and not (e.get("class") and cls in e.get("class").split()):
            continue
        return e
    return None


def _build_detail_schema_by_css(eng, dom, spec):
    """'css:' 모드 — CSS 셀렉터로 상세 필드를 직접 지정해 단일 레코드 스키마 생성.
    spec 예)  상세=div#content_job @# 급여=strong.pay @# 원문=a.more@href
      · name= 생략하면 f1,f2.. 로 자동 명명.  · 셀렉터 뒤 @attr 면 그 속성값 추출.
    """
    parts = [p.strip() for p in spec.split("@#") if p.strip()]
    sels = []
    for i, p in enumerate(parts, 1):
        if "=" in p:
            name, sel = p.split("=", 1)
            name, sel = name.strip(), sel.strip()
        else:
            name, sel = f"f{i}", p.strip()
        attr = None
        if "@" in sel:
            sel, attr = sel.rsplit("@", 1)
            sel, attr = sel.strip(), attr.strip()
        node = _find_by_css(dom, sel)
        if node is None:
            print("  ✗ " + t("셀렉터 매칭 실패: {sel} → 건너뜀", sel=repr(sel)))
            continue
        raw = node.get(attr) if attr else (node.text_content() or "")
        preview = " ".join(raw.split())[:70]
        print(f"  ✓ {name} ← {sel}{('@' + attr) if attr else ''}  = \"{preview}"
              f"{'…' if len(' '.join(raw.split())) > 70 else ''}\"")
        sels.append((name, node, attr))
    if not sels:
        print("[" + t("에러") + "] " + t("셀렉터로 매칭된 필드가 없습니다."))
        sys.exit(3)
    # 문서 루트를 단일 레코드로 삼아, 필드 위치를 '구조 경로'로 저장(페이지마다 재현).
    eng.build_schema_from_selection(
        [dom], row_sig(dom), sels, dom=dom, single=True, link_split=False)
    print("  · " + t("필드: {f}", f=[n for n, _, _ in sels]))


def _locate_body_container(dom, line):
    """본문에서 '보이는 한 줄'(line)을 담은 컨테이너(=본문 전체)를 찾는다.

    ① 그 문구를 담은 '가장 작은' 요소(anchor)를 찾고, ② 위로 올라가며
       - iframe 인라인 경계(data-inlined-iframe)가 있으면 그걸 본문으로(incruit 등),
       - 없으면 '페이지 전체로 번지기 직전의 가장 큰 블록'을 본문으로 고른다.
    반환: 컨테이너 노드 | None.
    """
    ns = lambda s: " ".join((s or "").split())
    target = ns(line)
    if not target:
        return None

    def _smallest_containing(tgt):
        best, best_len = None, None
        for e in dom.iter():
            if not isinstance(e.tag, str) or e.tag in ("script", "style"):
                continue
            txt = ns(e.text_content())
            if tgt in txt and (best_len is None or len(txt) < best_len):
                best, best_len = e, len(txt)
        return best

    anchor = _smallest_containing(target)
    if anchor is None:                       # 앞머리 기호(- • *) 차이 흡수해 재시도
        stripped = target.lstrip("-•*·▪◦ \t")
        if stripped and stripped != target:
            anchor = _smallest_containing(stripped)
    if anchor is None:
        return None

    chain, p = [], anchor                    # anchor → ... → root
    while p is not None:
        chain.append(p)
        p = p.getparent()
    for a in chain:                          # ① iframe 인라인 본문 경계 우선
        if a.get("data-inlined-iframe"):
            return a
    root = chain[-1]                         # ② 폴백: 전체의 70% 넘기 직전까지 확장
    root_len = len(ns(root.text_content())) or 1
    chosen = anchor
    for a in chain:
        if a.tag in ("body", "html"):
            break
        if len(ns(a.text_content())) <= 0.7 * root_len:
            chosen = a
        else:
            break
    return chosen


def _build_detail_schema_by_anchor(eng, dom, line, name="본문"):
    """'body:'/'본문:' 모드 — 본문 한 줄만 주면 그 줄이 든 컨테이너 전체를 필드로."""
    node = _locate_body_container(dom, line)
    if node is None:
        print("[" + t("에러") + "] " + t("그 문구를 페이지에서 찾지 못했습니다: {line}", line=repr(line)))
        print("  · " + t("상세 본문에서 '실제로 보이는' 한 줄을 그대로 붙여넣어 주세요."))
        sys.exit(3)
    cls = (node.get("class") or "").split()
    tag_desc = node.tag + (f"#{node.get('id')}" if node.get("id")
                           else (f".{cls[0]}" if cls else ""))
    full = " ".join((node.text_content() or "").split())
    print("  ✓ " + t("본문 컨테이너 식별: <{tag}>  ({n}자)", tag=tag_desc, n=len(full)))
    print(f"     = \"{full[:70]}{'…' if len(full) > 70 else ''}\"")
    eng.build_schema_from_selection(
        [dom], row_sig(dom), [(name, node, None)], dom=dom, single=True,
        link_split=False)
    print("  · " + t("필드: {f}", f=[name]))


def _delay_bounds(n):
    """--delay 의 '한 숫자'(평균 대기 초)를 그 주위 ±50% 랜덤 범위로 변환.
    (요청마다 값이 달라 규칙적 패턴을 피한다.)"""
    try:
        n = max(0.0, float(n))
    except Exception:
        n = 15.0
    return n * 0.5, n * 1.5


DELAY_HINT = (
    "  · --delay(요청 간 평균 대기, 초) 추천 — 상황 보고 알아서 판단하세요:\n"
    "      소량 테스트  5    |   일반 수집   10\n"
    "      대형/보수    15   |   차단 겪음   25      (기본 15 = 대형 사이트 기준)\n"
    "    ※ 준 값 주위로 ±50% 자동 랜덤. 빨리 하려면 낮게(예: --delay 5)."
)


def _find_chain_recipes(csv_target):
    """이 목록 CSV 에 딸린 체인 레시피들: [(url_col, path), ...] (url_col 은 레시피 meta 에서)."""
    import glob
    out = []
    for p in sorted(glob.glob(chain_recipe_glob(csv_target))):
        try:
            meta = Schema.read_recipe_meta(p)
        except Exception:
            continue
        if meta.get("chain") == "1":
            out.append((meta.get("url_col", ""), p))
    return out


def run_chain_crawl(target, args):
    """목록 CSV → 링크 열의 각 상세페이지를 크롤링해 '별도 상세 CSV' 로 저장.
    레시피가 있으면 입력 없이 재현(replay), 없으면 이번에 학습해 레시피로 저장한다."""
    import time
    import random
    cols, csv_rows = _read_csv_rows(target)
    if not csv_rows:
        print("[" + t("에러") + "] " + t("CSV 에 데이터 행이 없습니다."))
        sys.exit(1)
    print("\n■ " + t("CSV 체인 모드: {target}  ({n}행)", target=target, n=len(csv_rows)))
    print("  · " + t("컬럼: {cols}", cols=', '.join(cols)))

    # ② URL 컬럼 결정 (미지정 시: 저장된 체인 레시피가 하나면 그걸로 자동 재현)
    url_col = args.url_col
    saved = _find_chain_recipes(target)
    if url_col and url_col not in cols:
        print("[" + t("경고") + "] " + t("지정한 컬럼 '{c}' 이 CSV 에 없습니다.", c=url_col))
        url_col = None
    if not url_col and saved and not args.rediscover:
        if len(saved) == 1:
            url_col = saved[0][0]
            print("  · " + t("저장된 체인 레시피 발견 → URL 컬럼 '{c}' 자동 사용", c=url_col))
        else:
            print("  · " + t("저장된 체인 레시피 여러 개 — --url-col 로 지정하세요:"))
            for c, p in saved:
                print(f"      --url-col {c}")
    if not url_col:
        guess = _guess_url_col(cols)
        prompt = "\n" + t("URL 이 담긴 컬럼명을 입력하세요")
        prompt += t(" (Enter={g}): ", g=guess) if guess else ": "
        url_col = input(prompt).strip() or (guess or "")
    if url_col not in cols:
        print("[" + t("에러") + "] " + t("컬럼 '{c}' 을 CSV 에서 찾을 수 없습니다. 종료.", c=url_col))
        sys.exit(1)

    raw = [(row.get(url_col) or "").strip() for row in csv_rows]
    nonempty = [u for u in raw if u]
    if not nonempty:
        print("[" + t("에러") + "] " + t("'{c}' 컬럼에 URL 이 없습니다.", c=url_col))
        sys.exit(1)
    sample = nonempty[0]

    # 재현 여부: 이 (CSV, url_col) 레시피가 있고 --rediscover 아니면 입력 없이 재현.
    recipe_path = chain_recipe_path_for(target, url_col)
    reproduce = os.path.exists(recipe_path) and not args.rediscover
    eng = SelfHealingEngine(None, verbose=True)
    parse_method, ex = "chain", ""
    repro_render = False

    if reproduce:
        loaded_schema, _u, _lm, _w, _p = Schema.from_csv_recipe(recipe_path)
        meta = Schema.read_recipe_meta(recipe_path)
        eng.schema = loaded_schema
        clean_ex = meta.get("clean_url", "")
        repro_render = (_lm == "render")
        parse_method = "chain-recipe"
        cleaner, _desc = _derive_url_cleaner(sample, clean_ex)
        print("■ " + t("체인 레시피 재현: {p}", p=recipe_path))
        print("  · " + t("필드={f}  URL컬럼={c}  로드방식={lm}  (정련: {clean})",
                        f=list(loaded_schema.fields), c=url_col, lm=_lm, clean=(_desc or t("없음"))))
    else:
        # ③ URL 정련(선택): 1행 URL 을 보여주고 사용자가 고친 형태로 규칙을 도출
        print("\n  · " + t("예시 URL(1행): {u}", u=sample))
        clean_ex = args.clean_url
        if clean_ex is None:
            print("  · " + t("이 URL 을 '깔끔하게' 정련하려면 원하는 형태로 붙여넣으세요."))
            print("    " + t("(예: 괄호/꼬리 파라미터 제거 → 열 전체에 동일 적용). 그대로면 Enter."))
            clean_ex = input("  " + t("정련 예시(Enter=원본 그대로): ")).strip()
        cleaner, desc = _derive_url_cleaner(sample, clean_ex)
        if clean_ex and desc is None:
            print("  · [" + t("경고") + "] " + t("정련 규칙 감지 실패('{ex}' 이 원본의 부분문자열 아님) → 원본 그대로.", ex=clean_ex))
        elif clean_ex:
            print("  · " + t("정련 규칙: {desc}", desc=desc))
            print("  · " + t("정련 후 예시: {u}", u=cleaner(sample)))

    detail_urls = [cleaner(u) if u else "" for u in raw]   # 행 순서 유지
    first = cleaner(sample)
    dom0, used_dom0 = None, True   # 학습 때만 dom0 재사용(재현은 매 URL 새로 로드)

    if not reproduce:
        # ④ 첫 상세페이지 → 단일 레코드 스키마 (by-example / 본문 / CSS)
        print("\n[1] " + t("첫 상세페이지 로드: {u}", u=first))
        dom0 = load_or_die(first, wait=args.wait)
        n_if = _inline_iframes(dom0, first)
        if n_if:
            print("  · " + t("iframe {n}개 본문을 DOM 에 인라인(예: 공고 본문이 iframe 안)", n=n_if))
        _warn_if_spa(dom0)
        print("\n[2] " + t("이 상세페이지에서 뽑을 필드를 지정하세요. 세 가지 방법:"))
        print("  " + t("(A) 보이는 값 by-example:   회사명@#3,000만원@#2026-07-15 마감"))
        print("  " + t("(B) 본문 한 줄로 통째:       본문: LLM/Agentic AI에 대한 이해 및 AI API 활용 경험"))
        print("      · " + t("그 줄이 든 '본문 컨테이너 전체'를 끌어온다(여러 줄 붙여넣기 불필요)."))
        print("  " + t("(C) CSS 셀렉터로 지정:      css: 상세=div#content_job @# 급여=strong.pay"))
        ex = input("\n" + t("값 입력: ")).strip()
        if not ex:
            print(t("입력 없음 — 종료."))
            sys.exit(0)
        low = ex.lower()
        if low.startswith("css:"):
            print("\n■ " + t("CSS 셀렉터로 필드 지정"))
            _build_detail_schema_by_css(eng, dom0, ex[4:].strip())
        elif low.startswith("body:") or ex.startswith("본문:"):
            print("\n■ " + t("본문 한 줄 → 컨테이너 전체 추출"))
            _build_detail_schema_by_anchor(eng, dom0, ex.split(":", 1)[1].strip())
        else:
            dom0 = select_by_example(eng, dom0, ex, llm_name=True, target=first,
                                     wait=args.wait, single=True)
        used_dom0 = False   # 첫 URL 은 학습에 쓴 dom0 재사용(재요청 안 함)

    # ⑤ 정련된 모든 URL 순회 → 상세 추출 → 별도 상세 CSV
    fields = list(eng.schema.fields.keys())
    limit = args.limit if (args.limit and args.limit > 0) else None
    force_render = loader.RENDER_REQUIRED or repro_render
    dmin, dmax = _delay_bounds(args.delay)
    lim = t(", 최대 {n}개", n=limit) if limit else ""
    print("\n[3] " + t("상세페이지 순회 추출 (필드={fields}{lim}, 요청간 대기 약 {d}s → {dmin}~{dmax}s 랜덤)",
                     fields=fields, lim=lim, d=f"{float(args.delay):g}",
                     dmin=f"{dmin:g}", dmax=f"{dmax:g}"))
    print(t(DELAY_HINT))
    out_rows, seen, n = [], set(), 0
    for i, u in enumerate(detail_urls, 1):
        if not u or u in seen:
            continue
        seen.add(u)
        if limit and n >= limit:
            print("  · " + t("--limit {n} 도달 → 중단", n=limit))
            break
        n += 1
        if u == first and not used_dom0:
            dom, used_dom0 = dom0, True          # 학습에 쓴 dom 재사용(재요청 안 함)
        else:
            wait_s = random.uniform(dmin, dmax)  # 랜덤 대기 — 특정 사이트 과부하/차단 방지
            print("       " + t("… {s}s 대기 후 요청", s=f"{wait_s:.1f}"))
            time.sleep(wait_s)
            try:
                dom = load_or_die(u, wait=args.wait, force_render=force_render)
                _inline_iframes(dom, u)           # 본문 iframe 도 동일하게 인라인
            except SystemExit:
                raise
            except Exception as e:
                print(f"  {i:>3}. " + t("로드 실패 → 건너뜀 ({e})", e=e))
                continue
        recs = eng.extract(dom)
        rec = recs[0] if recs else {}
        out = {url_col: u}
        out.update({k: rec.get(k) for k in fields})
        out_rows.append(out)
        filled = sum(1 for k in fields if rec.get(k))
        print(f"  {i:>3}. " + t("채움 {filled}/{total}  {u}", filled=filled, total=len(fields), u=u))

    if not out_rows:
        print("\n[" + t("결과 없음") + "] " + t("추출된 상세 레코드가 없습니다."))
        sys.exit(3)
    valid = any(any(r.get(k) for k in fields) for r in out_rows)

    # 저장 방식/회차 결정 — 규칙은 output.resolve_save_mode/runlog.resolve_batch 단일 출처(cli 와 공유).
    save_mode = resolve_save_mode(args.mode, recipe_path, args.no_dedup)
    batch = resolve_batch(args.batch)

    # 별도 상세 CSV 저장(레시피와 같은 코어로 '한 쌍'). 회차 포함.
    out_path = (args.csv if (args.csv and args.csv != "AUTO")
                else chain_csv_path_for(target, url_col))
    added, updated = save_csv(out_path, out_rows, [url_col] + fields,
                              mode=save_mode, url_field=url_col, batch=batch)
    upd = t(", 갱신 {u}건", u=updated) if updated else ""
    print("\n=== " + t("체인 크롤링 완료: {n}건 추출", n=len(out_rows)) + " ===")
    print("■ " + t("상세 CSV: {csv}  [{mode}] 회차={batch} (추가 {added}건{upd})",
                  csv=out_path, mode=save_mode, batch=batch, added=added, upd=upd))

    # ⑥ 체인 레시피 저장/갱신 (다음 실행·replay 가 입력 없이 재현) — 정상일 때만.
    if valid:
        try:
            eng.schema.save_csv_recipe(
                recipe_path, url=target, load_method=loader.LAST_LOAD_METHOD,
                wait=args.wait,
                extra_meta={"chain": "1", "url_col": url_col, "clean_url": clean_ex or "",
                            "save_mode": save_mode})
            print("■ " + t("체인 레시피 {verb}: {p}",
                          verb=(t("재현확인") if reproduce else t("저장")), p=recipe_path))
        except Exception as e:
            print("[" + t("경고") + "] " + t("체인 레시피 저장 실패: {e}", e=e))

    # ⑦ 실행 기록 — _runs.csv append(잠금/실패 안내 포함). target=목록CSV, url_col 기록 → 부모-자식 번호(P-k).
    record_run(target, "success" if valid else "fail",
               loader.LAST_LOAD_METHOD, parse_method, ex, fields,
               len(out_rows), out_path, recipe_path if valid else "",
               url_col=url_col, batch=batch, save_mode=save_mode)

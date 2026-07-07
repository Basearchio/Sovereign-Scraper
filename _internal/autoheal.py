# -*- coding: utf-8 -*-
"""
MODULE_NAME: autoheal.py
PURPOSE: 자동 재학습(심층 힐) + 실패 진단 저널 — 값싼 방법이 다 실패했을 때의 최후 사다리.
         (v5.0 분할: cli 에서 이관) 라이브 사이트엔 save_as 1회만(탐지 회피), 무거운 전체-HTML LLM 분석은
         '로컬 파일'에만 수행. 설정 AUTO_HEAL ON 일 때만 LLM 을 쓰고, 뚫린 경위는 heal_knowledge 저널에
         개선 브리핑(fix_prompt)+HTML 샘플로 남겨 '값싼 휴리스틱' 자체를 개발자가 개선하게 한다.

  · try_auto_heal        : 추출 단계 폴백(save_as dom → recalibrate → 재추출 → 가드 통과 시 채택, 실패 시 롤백)
  · _heal_missing_at_learning : 학습 단계 폴백(요청 필드 누락을 LLM 으로 회복 + 저널)
  · _auto_heal           : save_as 로 로컬 HTML 1회 확보 → try_auto_heal → 저널
  · _auto_heal_enabled / _ask_load_method / _record_heal_case : 설정·UX·저널 헬퍼
DEPENDENCY: 성공 가드=guards, dedup 키=dedup, DOM 조각=engine._row_html, LLM=llm_locators,
  save_as=crawlers.chrome, 경로/사이트명=paths, 저널=heal_knowledge, 설정 플래그=services.llm_service.
  cli 를 import 하지 않는다(cli→autoheal 단방향, 순환 차단).
"""
from __future__ import annotations

import os
import sys

from guards import _run_is_valid, _semantic_ok
from dedup import _choose_url_field
from engine import _row_html
from llm_locators import improvement_brief, discover_structure as _discover_impl
from crawlers.chrome import chrome_save_as_fetch
from paths import RECIPE_DIR, _site_label, saved_html_path_for
import heal_knowledge
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)


def try_auto_heal(eng, heal_dom):
    """자동 재학습 최후 폴백(값싼 방법이 다 실패한 뒤). heal_dom 은 save_as 로 받은 '로컬 HTML'의
    dom(라이브 무접촉·탐지 회피). 기존 필드명/예시를 보존해 recalibrate → 재추출 → ①빈값 가드 +
    ②형태검증 을 통과해야만 성공. 실패면 후보 스키마를 폐기(롤백)해 좋은 레시피를 보호한다.
    Returns: (recovered: bool, rows, url_field, new_schema|None)."""
    if eng.schema is None:
        return False, [], None, None
    old_schema = eng.schema
    names = list(old_schema.fields.keys())
    examples = {n: (old_schema.fields[n].get("example", "") if isinstance(old_schema.fields[n], dict)
                    else "") for n in names}
    new_schema = eng.recalibrate(heal_dom, names, examples)   # engine 은 훅만 호출(LLM-free)
    if new_schema is None:
        return False, [], None, None
    fields = list(new_schema.fields.keys())
    rows = eng.extract(heal_dom) or []
    ok = _run_is_valid(rows, fields) and _semantic_ok(rows, new_schema)[0]
    if not ok:
        eng.schema = old_schema          # 후보 폐기 → 기존 레시피 보호
        eng._persist()                   # 캐시도 원복(cache_path 없으면 no-op)
        return False, [], None, None
    url_field = _choose_url_field(rows, fields)
    return True, rows, url_field, new_schema


def _auto_heal_enabled():
    """설정(.env AUTO_HEAL) 여부. LLM 계층을 통해 읽음. 없거나 오류면 False(안전=기존 동작)."""
    try:
        from services import llm_service
        return llm_service.get_flag("AUTO_HEAL")
    except Exception:
        return False


def _ask_load_method(args, default="chrome"):
    """재학습으로 레시피가 나온 뒤 '앞으로 이 사이트 로드 방식'을 고정. 비대화(replay=--batch 또는
    비TTY)면 감지된 방식(save_as=chrome) 자동, 대화형이면 물어본다(사용자 요구: save_as vs auto)."""
    if args.batch is not None or not sys.stdin.isatty():
        return default
    print("\n[" + t("로드 방식") + "] " + t("재학습으로 레시피가 나왔습니다. 앞으로 이 사이트를 어떻게 로드할까요?"))
    print("  1) save_as " + t("(실제 크롬 — 안티봇/무거운 SPA 안전, 사람 개입 최소)") + "  " + t("[기본]"))
    print("  2) auto    " + t("(정적/렌더 자동 — 빠르지만 차단되면 다시 재학습 유도)"))
    return "auto" if input("  " + t("번호(Enter=1): ")).strip() == "2" else "chrome"


def _record_heal_case(target, heal_dom, eng, new_schema, rows):
    """실패 진단 저널 기록: 문제 HTML 샘플 + 필드 위치 + fix_prompt(개선 브리핑). 사용자가 이 저널을
    Claude 에게 붙여넣어 값싼 휴리스틱을 개선하도록(개선 후 heal_knowledge.resolve 로 기록·삭제)."""
    sample_nodes = eng._match_rows(heal_dom)
    sample = sample_nodes[0] if sample_nodes else None
    html_sample = _row_html(sample, 2000) if sample is not None else ""
    first = rows[0] if rows else {}
    findings = [(n, str(first.get(n, fs.get("example", ""))),
                 f"{fs.get('css') or fs.get('tag')}, path={fs.get('path')}")
                for n, fs in new_schema.fields.items()]
    fix_prompt = improvement_brief(
        html_sample, findings,
        engine_hint="정적/구조/휴리스틱/_relocate 가 모두 실패하고 save_as+전체 HTML LLM 으로만 해결됨")
    heal_knowledge.record({
        "site": _site_label(target), "url": target,
        "field": "|".join(new_schema.fields.keys()), "source": "full_llm",
        "fields": [{"name": n, "tag": fs.get("tag"), "class_token": fs.get("cls"),
                    "path": fs.get("path"), "example": fs.get("example", "")}
                   for n, fs in new_schema.fields.items()],
        "html_sample": html_sample, "fix_prompt": fix_prompt or "",
    })
    print("  · " + t("실패 진단 저널 기록: {p}", p=os.path.join(RECIPE_DIR, '_heal_hints.json'))
          + (t("  (fix_prompt 포함 — 설정에서 개선에 활용)") if fix_prompt else ""))


def _heal_missing_at_learning(target, dom, rec, dropped, existing_names):
    """(3c) 학습 단계에서 값싼 방법(+3a 카드 broaden, +_relocate)으로도 못 잡은 '요청 필드'를,
    로컬 HTML+LLM(discover_structure)으로 마지막 시도하고, '왜 값싼 휴리스틱이 놓쳤는지'를
    heal_knowledge 저널에 개선 브리핑(fix_prompt)+HTML 샘플로 남긴다.

    - AUTO_HEAL(설정) ON 일 때만 LLM 사용(OFF 면 '값싼 방법까지만' 안내 후 종료 — LLM 비용 0).
    - 회복 노드는 '기존 레코드 rec 의 자손'인 것만 채택(다른 레코드 침범 방지, 행별 추출 재현 보장).
    dropped: [(value, is_url), ...]. 반환: 회복된 [(name, node, attr, value), ...]."""
    if not dropped:
        return []
    if not _auto_heal_enabled():
        print("     · " + t("(심층 재학습 OFF → 값싼 방법까지만 분석했습니다. 설정에서 켜면 LLM 이 전체 HTML 로 시도)"))
        return []
    print("\n  [" + t("학습 자동 재학습") + "] " + t("못 잡은 요청 필드를 로컬 HTML+LLM 으로 분석합니다(라이브 재접속 없음)."))
    used = set(existing_names)
    names = []
    for i, (v, is_url) in enumerate(dropped):
        base = "링크" if is_url else f"필드{i + 1}"
        n, j = base, 2
        while n in used:
            n, j = f"{base}_{j}", j + 1
        used.add(n)
        names.append(n)
    examples = {n: v for n, (v, _u) in zip(names, dropped)}
    recovered = []
    try:
        result = _discover_impl(dom, names, examples)
    except Exception as e:
        result, _ = None, print("     · " + t("(LLM 분석 생략: {e})", e=e))
    inside = {id(x) for x in rec.iter()}
    if result:
        _s, _sig, sels, err = result
        for (n, node), (v, is_url) in zip(sels or [], dropped):
            if node is not None and id(node) in inside:
                recovered.append((n, node, "href" if is_url else None, v))
                print("     ✓ " + t("LLM 회복: \"{v}\" → <{tag}>", v=v[:30], tag=node.tag))
    rec_names = {rn for rn, _, _, _ in recovered}
    try:
        html_sample = _row_html(rec, 2000)
        findings = [(n, v, "값싼 방법(셀렉터/구조경로/시그니처/휴리스틱/_relocate/카드broaden) 실패"
                     + (" → LLM 회복" if n in rec_names else " → 미해결"))
                    for n, (v, _u) in zip(names, dropped)]
        fix_prompt = improvement_brief(
            html_sample, findings,
            engine_hint="학습 단계에서 요청 필드를 값싼 방법으로 못 잡음(형제 가지/속성/비정형 위치 의심)")
        heal_knowledge.record({
            "site": _site_label(target), "url": target,
            "field": "|".join(names), "source": "learning_miss",
            "fields": [{"name": n, "example": v, "recovered": n in rec_names}
                       for n, (v, _u) in zip(names, dropped)],
            "html_sample": html_sample, "fix_prompt": fix_prompt or "",
        })
        print("     · " + t("실패 진단 저널 기록: {p}", p=os.path.join(RECIPE_DIR, '_heal_hints.json'))
              + t(" (개선 후 heal_knowledge.resolve 로 정리)"))
    except Exception as e:
        print("     · " + t("(지식 저널 기록 생략: {e})", e=e))
    return recovered


def _auto_heal(eng, target, args):
    """설정 ON 시 최후 폴백. save_as 로 로컬 HTML 1회 확보 → try_auto_heal. 성공 시 지식 저널 기록 후
    (True, rows, fields, url_field), 실패 시 (False, [], [], None). 라이브는 save_as 1회뿐(재fetch 없음)."""
    print("\n[" + t("자동 재학습") + "] " + t("값싼 방법 실패 → save_as 로 HTML 을 받아 전체 구조를 LLM 으로 분석합니다 (라이브 재접속 없이 실크롬 1회, 탐지 회피)."))
    load_wait = 10.0 + max(0, args.wait or 0)
    heal_dom = chrome_save_as_fetch(target, saved_html_path_for(target),
                                    log=print, load_wait=load_wait)
    if heal_dom is None:
        print("  · " + t("save_as 실패 → 재학습 불가."))
        return False, [], [], None
    ok, rows, url_field, new_schema = try_auto_heal(eng, heal_dom)
    if not ok:
        print("  · " + t("전체 HTML 분석으로도 유효한 구조를 못 찾음 → 기존 레시피 보호."))
        return False, [], [], None
    fields = list(new_schema.fields.keys())
    print("  · " + t("재학습 성공 → 필드={f}, {n}건", f=fields, n=len(rows)))
    try:
        _record_heal_case(target, heal_dom, eng, new_schema, rows)
    except Exception as e:
        print("  · " + t("(지식 저널 기록 생략: {e})", e=e))
    return True, rows, fields, url_field

# -*- coding: utf-8 -*-
"""
MODULE_NAME: start.py
PURPOSE: 사람이 쓰는 '메뉴 런처'. 플래그를 외울 필요 없이 번호만 고르면 기존 진입점(cli.py/replay.py)을
         그대로 실행한다. 속(로직)은 기존과 100% 동일 — 이 파일은 얇은 디스패처일 뿐이다.
         메뉴는 MENU 리스트라 항목 추가가 한 줄(라벨, 함수) → 별개 프로그램도 5·6…으로 쉽게 확장.
DEPENDENCY: 표준 라이브러리만. 각 항목은 subprocess 로 기존 스크립트를 띄운다(격리 = replay 방식과 동일).
            LLM 설정만 예외로 .env 를 직접 읽고/쓴다(설정 파일 편집이라 인프로세스가 자연스러움).

사용:
  python start.py        # 메뉴 표시(대화형)
  (더블클릭용: start.bat)

[확장하는 법]
  MENU 끝에 ("내 기능 이름", 내_함수) 를 추가하면 자동으로 다음 번호가 붙는다.
  외부 프로그램이면:  ("내 프로그램", lambda: _run([sys.executable, "myprog.py"]))
"""
import os as _os, sys as _sys
# 내부 모듈은 _internal/ 폴더에 있다 → import 전에 검색 경로에 추가(배포 시 루트를 깔끔하게).
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_internal"))
import bootstrap  # 첫 실행: 가상환경(.venv) 안내·자동설치 후 venv 로 재실행
if __name__ == "__main__":
    bootstrap.ensure_env()

import os
import sys
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import crawl_config   # 레시피 기본 저장/로드 방식(설정에서 읽고 여기서 바꿈)
import i18n           # 다국어(한국어 소스 + 언어 오버레이). 미번역은 한국어로 폴백.
from i18n import t

HERE = os.path.dirname(os.path.abspath(__file__))
INTERNAL = os.path.join(HERE, "_internal")     # 내부 모듈/도구 폴더
CLI = os.path.join(HERE, "cli.py")             # front(파워유저용)
REPLAY = os.path.join(HERE, "replay.py")       # front
CAP = os.path.join(INTERNAL, "capabilities.py")   # back(내부 도구)
DOCTOR = os.path.join(INTERNAL, "doctor.py")      # back
ENV_PATH = os.path.join(HERE, ".env")


def _run(cmd):
    """기존 스크립트를 현재 콘솔에 그대로 붙여 실행(입력/출력 상속 → 대화형 프롬프트 정상 동작)."""
    print()
    try:
        subprocess.run(cmd, cwd=HERE)
    except KeyboardInterrupt:
        print("\n[" + t("중단") + "]")
    print()


# ────────────────────────── 메뉴 동작 ──────────────────────────
# start 는 '런처'다: 크롤 대화형 안내(로드/저장 방식·주소·재학습)는 전부 cli._interactive_setup 한 곳.
# (예전엔 start 에도 같은 안내를 뒀다가 cli 와 분기가 갈려 'start 경로에선 안 뜬다'는 혼란을 낳았다.)
def action_crawl():
    """크롤링 — 인자 없이 cli 를 띄우면 cli 가 로드/저장 방식→주소→(있으면)재학습까지 안내한다."""
    _run([sys.executable, CLI])


def action_chain():
    """체인 크롤링 — 목록 CSV 안의 링크 열을 따라 상세페이지 크롤링. 내부적으로 cli.py <csv>."""
    print("· " + t("'목록 CSV' 경로를 입력하세요(그 안의 링크 열을 따라 상세페이지를 크롤링)."))
    path = input("  " + t("목록 CSV 경로 (빈칸=취소): ")).strip().strip('"')
    if not path:
        return
    if not path.lower().endswith(".csv"):
        print("  " + t("⚠ .csv 가 아닙니다. 일반 페이지면 '1. 크롤링'을 쓰세요."))
        return
    _run([sys.executable, CLI, path])


def action_export():
    """레시피 공유하기 — 개인정보 마스킹해 recipes/shared/outbox/ 로. 내부적으로 replay.py --export-recipe."""
    print("· " + t("내 성공 레시피 목록을 보여준 뒤, 고른 번호만 '마스킹'해 recipes/shared/outbox/ 에 저장합니다."))
    _run([sys.executable, REPLAY, "--export-recipe"])


def action_replay():
    """과거 작업 다시하기(replay) — 과거 성공한 크롤링을 골라 다시 실행(배치). 내부적으로 replay.py."""
    print("· " + t("과거 성공한 크롤링을 번호로 골라 다시 실행합니다(레시피 자동 로드)."))
    _run([sys.executable, REPLAY])


def action_capabilities():
    """역량 매트릭스 — output/·recipes/ 를 읽어 사이트별 '가져온 필드' 표. 로컬은 사이트명, 공개본은 마스킹."""
    print("· " + t("output/·recipes/ 만 읽어 사이트별 '가져온 필드' 표를 만듭니다(크롤 안 함)."))
    _run([sys.executable, CAP])                       # 로컬(실제 사이트명) 화면 출력
    ans = input("  " + t("공개용(사이트명→카테고리 마스킹)으로 docs/capabilities.md 저장할까요? [y/N]: ")).strip().lower()
    if ans in ("y", "yes", "ㅇ"):
        _run([sys.executable, CAP, "--mask", "-o", os.path.join(INTERNAL, "docs", "capabilities.md")])


# ────────────────────────── 레시피 (받은 것 읽어들이기 / 내 것 공유하기) ──────────────────────────
# inbox=남에게 받은 레시피 / outbox=내가 공유할(마스킹) 레시피 (recipes/shared/ 아래 분리).
# ★공유 레시피는 '파일 이식'이 아니라 '검증된 필드맵 안내서'다: 받으면 → 내 URL 로 데려가서 →
#   그대로 적용(검증본 재사용)하거나, 처음부터 새로 만든다. 실행이 _runs.csv 기록+내 레시피를 남겨
#   '받았는데 뭘 할지 모르는' 고아 상태를 없앤다.
def action_recipes():
    """레시피 — 받은 것(inbox) 읽어들이기 / 내 것 공유하기(outbox) / 온라인 레지스트리에서 받기."""
    while True:
        print("\n── " + t("레시피 (공유 받기/올리기)") + " ──")
        print("  1. " + t("읽어들이기 (받은 레시피 → 내 URL 에 적용·실행)"))
        print("  2. " + t("공유하기 (내 레시피 마스킹 → outbox → 브라우저 업로드)"))
        print("  3. " + t("온라인에서 찾기 (레지스트리 검색 → inbox 로 받기)"))
        print("  0. " + t("뒤로"))
        sel = input("  " + t("번호: ")).strip().lower()
        if sel in ("0", "", "q", "b"):
            return
        if sel == "1":
            _recipe_read_in()
        elif sel == "2":
            _recipe_share()
        elif sel == "3":
            _recipe_search_online()
        else:
            print("  " + t("⚠ 잘못된 입력"))


def _import_recipe_file(src):
    """[공용] 받은 레시피 1개를 임포트: 매니페스트(사이트·필드) 표시 → 내 URL → 그대로 적용(Enter)/새로 만들기.
    그대로 = 검증본을 내 URL 로 retarget 해 설치 후 실행(결과+_runs 기록). 새로 = 필드만 참고해 처음부터 학습."""
    import paths
    from urllib.parse import urlparse
    from core import recipe_share
    from core.schema import Schema
    try:
        sch, murl, _lm, _w, _pg = Schema.from_csv_recipe(src)
        fields = [n for n in sch.fields if not n.endswith("_url")]
    except Exception as e:
        print("  " + t("레시피를 읽지 못했습니다: {e}", e=e))
        return
    site = urlparse(murl).netloc or os.path.basename(src)
    print("\n  ■ " + t("레시피: {name}", name=os.path.basename(src)[:-4]))
    print("     " + t("사이트: {site}", site=site))
    print("     " + t("가져오는 필드: {f}", f=(', '.join(fields) or t('(없음)'))))
    if murl:
        # 마스킹으로 검색어는 이미 EXAMPLE 로 지워졌으니, 예시 주소(어느 페이지인지)를 그대로 보여준다.
        print("     " + t("예시 주소: {u}", u=murl))
        if "EXAMPLE" in murl:
            print("       " + t("└ 'EXAMPLE' 자리에 내 검색어/조건을 넣어 아래에 붙여넣으세요."))
    print("  · " + t("적용할 '내 URL'(검색/목록 페이지 주소)을 넣으세요."))
    my_url = input("  " + t("내 URL (빈칸=취소): ")).strip().strip('"')
    if not my_url:
        return
    mode = input("  " + t("그대로 사용할까요? [Enter=검증된 레시피 그대로 적용 / 아무거나 입력=처음부터 새로 만들기]: ")).strip()
    if mode == "":
        dst = paths.recipe_path_for(my_url)
        recipe_share.retarget_recipe(src, my_url, dst)
        print("  ✔ " + t("적용됨 → {p}. 지금 실행합니다(결과·기록 생성).", p=os.path.relpath(dst, HERE)))
        _run([sys.executable, CLI, my_url])
    else:
        print("  · " + t("공유 필드를 참고해 '처음부터' 새로 만듭니다(예시 입력/피커로 지정)."))
        _run([sys.executable, CLI, my_url])   # 공유 레시피 미설치 → cli 가 대화형 학습


def _recipe_read_in():
    """받은 레시피(inbox) 목록 → 번호 선택 → _import_recipe_file 로 적용/새로 만들기."""
    import paths
    inbox = paths.inbox_dir()
    files = sorted(f for f in os.listdir(inbox) if f.lower().endswith(".csv"))
    if not files:
        print("  " + t("받은 레시피가 없습니다."))
        print("  · " + t("'3. 온라인에서 찾기'로 받거나, 공유받은 .csv 를 이 폴더에 넣으세요:"))
        print(f"    {os.path.relpath(inbox, HERE)}")
        return
    print("\n  ── " + t("받은 레시피 (inbox)") + " ──   " + t("※ 파일명 = 사이트_필드…"))
    for i, f in enumerate(files, 1):
        print(f"    {i}. {f[:-4]}")
    sel = input("  " + t("읽어들일 번호(빈칸=취소): ")).strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(files)):
        return
    _import_recipe_file(os.path.join(inbox, files[int(sel) - 1]))


def _recipe_search_online():
    """레지스트리 검색 → 선택 → inbox 로 다운로드 → (선택) 바로 읽어들이기."""
    import paths
    from core import recipe_registry as reg
    raw, _web = reg.resolve_registry(_read_env())
    if not reg.is_configured(raw):
        print("  " + t("⚠ 공유 레지스트리 주소가 아직 설정되지 않았습니다."))
        print("     " + t(".env 에 RECIPE_REGISTRY_RAW / RECIPE_REGISTRY_WEB 를 넣으세요(.env.example 참고)."))
        return
    print("  · " + t("공유 레시피 목록을 불러오는 중..."))
    entries = reg.fetch_index(raw)
    if not entries:
        print("  " + t("아직 공유된 레시피가 없습니다(또는 레지스트리 접속 실패 — 주소/네트워크 확인)."))
        return
    q = input("  " + t("검색어(사이트/카테고리/필드 · 빈칸=전체 {n}개): ", n=len(entries))).strip()
    hits = reg.search(entries, q)
    if not hits:
        print("  " + t("일치하는 레시피가 없습니다."))
        return
    for i, e in enumerate(hits, 1):
        print(f"    {i}. [{e.get('site','')}] {e.get('desc') or e.get('id')}"
              + "  · " + t("필드={f}", f=', '.join(e.get('fields', []) or []))
              + (('  · ' + e['category']) if e.get('category') else ''))
    sel = input("  " + t("받을 번호(빈칸=취소): ")).strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(hits)):
        return
    try:
        src = reg.download_recipe(hits[int(sel) - 1], raw, paths.inbox_dir())
    except Exception as ex:
        print("  " + t("다운로드 실패: {e}", e=ex))
        return
    print("  ✔ " + t("받음 → recipes/shared/inbox/{name}", name=os.path.basename(src)))
    if input("  " + t("지금 읽어들일까요? [Y/n]: ")).strip().lower() in ("", "y", "yes", "ㅇ"):
        _import_recipe_file(src)


def _recipe_share():
    """내 레시피를 마스킹해 outbox 로 export(자기설명 이름) 후, repo 업로드 페이지를 브라우저로 열어 PR 제출."""
    from core import recipe_registry as reg
    _raw, web = reg.resolve_registry(_read_env())
    print("  · " + t("내 성공 레시피를 마스킹해 recipes/shared/outbox/ 로 뽑습니다(개인정보 검수 필수)."))
    print("    " + t("이름은 Enter=기본(사이트_필드…) 또는 직접 입력(예: 구글_이메일제목_이메일내용)."))
    action_export()
    url = reg.share_page_url(web)
    print("\n  · " + t("검수한 recipes/shared/outbox/*.csv 를 올릴 '업로드 페이지'를 브라우저로 엽니다."))
    print("    " + t("(파일을 끌어다 놓고 'Propose changes'로 PR 제출 → 관리자가 검토 후 반영.)"))
    if input("  " + t("브라우저로 열까요? [{url}] [Y/n]: ", url=url)).strip().lower() in ("", "y", "yes", "ㅇ"):
        import webbrowser
        webbrowser.open(url)


# ────────────────────────── 4. LLM 설정(.env 직접 편집) ──────────────────────────
# (라벨, base_url, 기본 model, api_key 필요여부)
_LLM_PRESETS = [
    ("로컬 LM Studio (기본, 키 불필요)", "http://localhost:1234/v1", "local-model", False),
    ("OpenAI",        "https://api.openai.com/v1",    "gpt-4o-mini",                  True),
    ("OpenRouter",    "https://openrouter.ai/api/v1", "qwen/qwen-2.5-72b-instruct",   True),
    ("직접 입력",     "",                              "",                             True),
]


AUTO_HEAL_KEY = "AUTO_HEAL"   # 심층 재학습(값싼 방법 실패 시 save_as+전체 HTML LLM) on/off


def _read_env(path=ENV_PATH):
    d = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return d


def _set_env(updates, path=ENV_PATH):
    """.env 의 '일부 키'만 갱신하고 나머지 키는 보존한다(전체 덮어쓰기 금지 — 토글이 LLM 키를 날리는
    사고 방지). 파일 없으면 생성."""
    cur = _read_env(path)
    for k, v in updates.items():
        cur[k] = "" if v is None else str(v)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 설정 (start.py 가 생성/갱신). .env 는 .gitignore 됩니다 — 커밋되지 않음.\n")
        for k, v in cur.items():
            f.write(f"{k}={v}\n")


def _write_env(base, model, key, path=ENV_PATH):
    _set_env({"LLM_BASE_URL": base, "LLM_MODEL": model, "LLM_API_KEY": key}, path)


def _auto_heal_on(path=ENV_PATH):
    return (_read_env(path).get(AUTO_HEAL_KEY, "") or "").strip().lower() in (
        "1", "true", "on", "yes", "y")


def _toggle_auto_heal(path=ENV_PATH):
    on = not _auto_heal_on(path)
    _set_env({AUTO_HEAL_KEY: "1" if on else "0"}, path)
    return on


def _mask_key(k):
    k = k or ""
    return (k[:4] + "…" + k[-2:]) if len(k) > 6 else (t("(설정됨)") if k else t("(없음)"))


def action_recipe_defaults():
    """레시피 기본 설정 — 명시 지정이 없을 때의 기본 저장/로드 방식(대화형 [기본]·비대화 폴백).
    이미 만든 레시피의 재현(replay)은 저장값을 지키고, 이 기본값은 '새로/대화형' 실행의 기준이 된다."""
    _labels = {"history": "추가하기(중복허용)", "append": "중복제외추가",
               "overwrite": "덮어쓰기", "upsert": "키 갱신"}
    while True:
        sm, lm = crawl_config.default_save_mode(), crawl_config.default_load_method()
        print("\n── " + t("레시피 기본 설정") + " ──")
        print("  " + t("기본 저장 방식 : {m}  ({label})", m=sm, label=t(_labels.get(sm, sm))))
        print("  " + t("기본 로드 방식 : {m}  (auto=정적/렌더 자동 · save_as=처음부터 실크롬)", m=lm))
        print("  1. " + t("기본 저장 방식 바꾸기"))
        print("  2. " + t("기본 로드 방식 바꾸기"))
        print("  0. " + t("뒤로"))
        sel = input("  " + t("번호: ")).strip().lower()
        if sel in ("0", "", "q", "b"):
            return
        if sel == "1":
            print("  " + t("1) 추가하기(history)  2) 중복제외추가(append)  3) 덮어쓰기(overwrite)  4) 키갱신(upsert)"))
            m = {"1": "history", "2": "append", "3": "overwrite", "4": "upsert"}.get(
                input("  " + t("번호: ")).strip())
            if m:
                _set_env({crawl_config.SAVE_MODE_KEY: m})
                print("  ✔ " + t("기본 저장 방식 = {m} ({label})", m=m, label=t(_labels[m])))
        elif sel == "2":
            print("  1) auto  2) save_as")
            m = {"1": "auto", "2": "save_as"}.get(input("  " + t("번호: ")).strip())
            if m:
                _set_env({crawl_config.LOAD_METHOD_KEY: m})
                print("  ✔ " + t("기본 로드 방식 = {m}", m=m))
        else:
            print("  " + t("⚠ 잘못된 입력"))


def action_settings():
    """설정 — LLM 공급자 · 레시피 기본값 · (개발자용) 정합성 점검·역량 매트릭스. 뒤 둘은 읽기 전용 진단 도구라
    일반 사용자 메뉴에 노출하지 않고 설정 안에 숨겨 둔다."""
    while True:
        print("\n── " + t("설정") + " ──")
        print("  1. " + t("LLM 공급자 설정 (.env — 로컬/클라우드)"))
        print("  2. " + t("레시피 기본 설정 (기본 저장/로드 방식)"))
        print("  · " + t("개발자용(읽기 전용)") + " ·")
        print("  3. " + t("정합성 점검 (doctor — 파일 수정 안 함)"))
        print("  4. " + t("역량 매트릭스 (가져온 필드 표 · 공개용 마스킹)"))
        print("  5. 언어 / Language (" + t("현재: {lang}", lang=i18n.current_lang()) + ")")
        print("  0. " + t("뒤로"))
        sel = input("  " + t("번호: ")).strip().lower()
        if sel in ("0", "", "q", "b"):
            return
        if sel == "1":
            action_llm_config()
        elif sel == "2":
            action_recipe_defaults()
        elif sel == "5":
            _toggle_lang()
        elif sel == "3":
            _run([sys.executable, DOCTOR])
        elif sel == "4":
            action_capabilities()
        else:
            print("  " + t("⚠ 잘못된 입력"))


def _toggle_lang():
    """언어를 지원 목록에서 순환(ko↔en)해 .env 에 저장 + 즉시 반영. 설정 메뉴에서 호출."""
    order = list(i18n.SUPPORTED)
    cur = i18n.current_lang()
    nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else i18n.DEFAULT_LANG
    _set_env({i18n.LANG_KEY: nxt})
    i18n.set_lang(nxt)
    print("  ✔ " + t("언어/Language → {lang}", lang=nxt))


def action_llm_config():
    """설정(LLM) — 현재 .env 를 보여주고, 프리셋/직접입력으로 공급자를 바꾼다. 연결 테스트 제공."""
    while True:
        cur = _read_env()
        print("\n── " + t("현재 LLM 설정(.env)") + " ──")
        print(f"  BASE_URL : {cur.get('LLM_BASE_URL', t('(미설정 → 기본 로컬 LM Studio)'))}")
        print(f"  MODEL    : {cur.get('LLM_MODEL', t('(미설정)'))}")
        print(f"  API_KEY  : {_mask_key(cur.get('LLM_API_KEY', ''))}")
        print("  " + t("심층 재학습(전체 HTML LLM 분석): {s}", s=('ON' if _auto_heal_on() else 'OFF')))
        print("    " + t("⚠ 페이지 전체 HTML 을 LLM 에 보내는 방식이라 토큰을 많이 씁니다 — "
                        "클라우드 LLM(유료)이면 비용에 유의하세요."))
        print("\n  " + t("공급자 선택:"))
        for i, (label, _b, _m, _k) in enumerate(_LLM_PRESETS, 1):
            print(f"    {i}. " + t(label))
        print("    d. " + t("심층 재학습 켜기/끄기"))
        print("    t. " + t("현재 설정으로 연결 테스트"))
        print("    0. " + t("뒤로"))
        sel = input("  " + t("번호: ")).strip().lower()
        if sel in ("0", "", "q", "b"):
            return
        if sel == "d":
            on = _toggle_auto_heal()
            print("  ✔ " + t("심층 재학습: ") + (t("ON — 값싼 방법 실패 시 save_as 후 전체 HTML 을 LLM 으로 분석")
                                        if on else t("OFF — 값싼 방법까지만(비용/호출 없음)")))
            continue
        if sel == "t":
            print("  " + t("(새 프로세스로 .env 를 다시 읽어 테스트합니다)"))
            _run([sys.executable, os.path.join(INTERNAL, "services", "llm_service.py")])
            continue
        if not sel.isdigit() or not (1 <= int(sel) <= len(_LLM_PRESETS)):
            print("  " + t("⚠ 잘못된 입력"))
            continue
        label, base_d, model_d, need_key = _LLM_PRESETS[int(sel) - 1]
        base = input("  BASE_URL [" + (base_d or t("필수")) + "]: ").strip() or base_d
        if not base:
            print("  " + t("⚠ BASE_URL 은 필수입니다."))
            continue
        model = input("  MODEL [" + (model_d or t("필수")) + "]: ").strip() or model_d
        key = ""
        if need_key:
            key = input("  " + t("API_KEY (로컬이면 빈칸): ")).strip()
        _write_env(base, model, key)
        print("  ✔ " + t("저장됨 → {p}  ({label})", p=ENV_PATH, label=label))
        print("    " + t("'t' 로 연결을 테스트하거나, 0 으로 돌아가세요."))


# ────────────────────────── 메뉴 등록(여기에 6·7… 추가) ──────────────────────────
MENU = [
    ("크롤링 (URL/HTML 한 페이지·목록)", action_crawl),
    ("체인 크롤링 (목록 CSV → 상세페이지)", action_chain),
    ("과거 작업 다시하기 (저장된 작업 다시 실행)", action_replay),
    ("레시피 (받은 것 읽어들이기 · 내 것 공유)", action_recipes),
    ("설정 (LLM · 레시피 기본값 · 개발자 도구)", action_settings),
]


def show_help():
    """고급 사용법(명령줄 옵션) — 메뉴가 감춘 파워유저 기능. 메뉴에서 'help' 로 부른다.
    (메뉴만으로도 다 되지만, 익숙해지면 옵션으로 페이지 수·저장 방식·체인 등을 세밀히 제어.)"""
    print("\n" + "=" * 60)
    print("  " + t("고급 사용법 (명령줄 옵션)"))
    print("  " + t("메뉴로 다 되지만, 익숙해지면 아래 옵션으로 더 세밀하게 제어할 수 있어요."))
    print("=" * 60)
    print("\n■ " + t("크롤링") + "   python cli.py \"<URL>\" [" + t("옵션") + "]")
    print("  --example \"" + t("값1@#값2") + "\"   " + t("화면에서 본 값을 주면 대화형 없이 바로 추출"))
    print("  --pages N              " + t("최대 N페이지까지 순회 (기본 1페이지)"))
    print("  --scroll               " + t("무한스크롤: 브라우저로 스크롤해 로드(끝나면 조기 종료)"))
    print("  --scroll-seconds N     " + t("스크롤 지속 시간(초, 기본 15) — 끝이 없는 피드 대비"))
    print("  --chrome               " + t("내 진짜 크롬 Save As 로 강제 로드(안티봇·무거운 SPA)"))
    print("  --wait N               " + t("느린 SPA 렌더 추가 대기 N초 (예: 30)"))
    print("  --mode M               " + t("저장 방식: append/history/overwrite/upsert"))
    print("  --rediscover           " + t("기존 레시피를 무시하고 처음부터 다시 학습"))
    print("  --no-images            " + t("이미지 파일은 안 받고 URL 열만 유지"))
    print("\n■ " + t("체인 크롤링") + "   python cli.py \"" + t("목록.csv") + "\" [" + t("옵션") + "]   " + t("(목록의 링크 → 상세페이지)"))
    print("  --url-col " + t("이름") + "         " + t("링크가 든 열 이름 (예: 직무_url)"))
    print("  --clean-url \"...\"      " + t("1행 URL 정련 예시(지운 부분을 열 전체에 적용)"))
    print("  --limit N              " + t("상세페이지 N개까지만 (테스트용)"))
    print("  --delay N              " + t("상세 요청 간 평균 N초 대기 (기본 15, ±50% 랜덤)"))
    print("\n■ " + t("과거 작업 다시하기 · 공유") + "   python replay.py [옵션]")
    print("  (" + t("인자 없음") + ")            " + t("목록을 보고 번호를 입력"))
    print("  1 3  /  all            " + t("특정 번호 / 전부 재현(스케줄러용)"))
    print("  --list                 " + t("목록만 출력"))
    print("  --export-recipe 1 3    " + t("고른 레시피를 마스킹해 공유용(outbox)으로"))
    print("\n" + t("전체 옵션 보기: python cli.py --help"))
    print(t("정기 실행(스케줄러): 윈도우 작업 스케줄러에 'replay.py all' 등록"))
    input("\n  " + t("Enter 로 메뉴로 돌아가기..."))


def main():
    while True:
        print("\n" + "=" * 52)
        print("  " + t("Sovereign-Scraper — 메뉴  (데이터 주권을 위한 자가 치유형 웹 스크래퍼)"))
        print("=" * 52)
        for i, (label, _fn) in enumerate(MENU, 1):
            print(f"  {i}. {t(label)}")
        print(f"  0. {t('종료')}")
        print("  " + t("(help = 고급 옵션·명령줄 사용법 보기)"))
        sel = input("\n" + t("선택 번호: ")).strip().lower()
        if sel in ("help", "h", "?", "도움말"):
            show_help()
            continue
        if sel in ("0", "q", "quit", "exit", ""):
            print(t("종료합니다."))
            return
        if not sel.isdigit() or not (1 <= int(sel) <= len(MENU)):
            print(t("⚠ 목록에 있는 번호를 입력하세요."))
            continue
        _label, fn = MENU[int(sel) - 1]
        try:
            fn()
        except KeyboardInterrupt:
            print("\n" + t("[취소]"))


if __name__ == "__main__":
    main()

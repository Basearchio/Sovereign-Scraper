# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/chrome.py
PURPOSE: '진짜 크롬' 수집 전략 — 정적/헤드리스가 안티봇(Akamai/Cloudflare/PerimeterX/DataDome)에
         막힐 때, 사용자의 실제 Chrome 세션(로그인/쿠키)으로 페이지를 받는 최후 경로.
         방식: Save As 완전자동(pywin32 키입력). 과거의 profile 디버그 attach(CDP) 경로는
         Chrome 136+ 의 '기본 프로필 디버그 차단'으로 불가능해져 제거(SRS 운영 교훈 #2).
DEPENDENCY: lxml(필수), Chrome 설치, i18n(leaf, 로그 문구 번역),
            pywin32(win32com/win32gui/win32clipboard). 미설치/실패 시 None → 호출부가 폴백/안내.

[검증된 주요 사이트 및 케이스]
- 쿠팡 등 Akamai/Cloudflare 계열: save_as(Ctrl+S) 경로로 내 세션 HTML 확보(디버그 포트 불필요 →
  Chrome 136+ 의 '기본 프로필 디버그 차단'과 무관).

[테스트/운영 교훈]
- 우회 트릭이 아니라 '평소 브라우저로 다른이름저장' 자동화. 내가 띄운 크롬은 절대 강제종료 안 함.
- Save As 경로는 창 포커스/타이밍에 민감 → 저장창을 '폴링으로 감지'(win32gui #32770)하고, 경로는
  타이핑 대신 '클립보드 Ctrl+V'(한글 IME/글자드롭으로 경로 깨짐 방지). ASCII 경로 권장.
- 저장 완료는 '파일 크기가 안정될 때까지' 확인('Webpage, Complete' 리소스 저장이 느림).
- [계층] engine 을 import 하지 않는다(leaf). engine.load_dom 이 아니라 cli 가 직접 호출/폴백 판단.
"""
from __future__ import annotations

import os

from lxml import html as lxml_html
from i18n import t     # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)


def _find_chrome():
    """시스템에 설치된 진짜 Chrome 실행 파일 경로(없으면 None)."""
    import shutil
    for name in ("chrome", "chrome.exe", "google-chrome", "chromium"):
        p = shutil.which(name)
        if p:
            return p
    cands = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def _foreground_is_dialog() -> bool:
    """현재 맨 앞 창이 표준 Win32 대화상자(#32770)인가 = 저장 대화상자가 떴는가.
    win32gui 미설치/오류면 판단 불가로 False(→ 호출부가 고정대기 폴백)."""
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        return bool(hwnd) and win32gui.GetClassName(hwnd) == "#32770"
    except Exception:
        return False


def _wait_save_dialog(shell, log, tries: int = 3, per_try: float = 6.0) -> bool:
    """Ctrl+S 를 보내고 '저장 대화상자'가 실제로 뜰 때까지 폴링한다.
    안 뜨면 재시도(페이지가 아직 바빠 Ctrl+S 를 못 먹은 경우). win32gui 가 없으면
    감지 불가라, 한 번 Ctrl+S 후 고정 대기하고 True 로 진행(구 동작 폴백)."""
    can_detect = False
    try:
        import win32gui  # noqa: F401
        can_detect = True
    except Exception:
        pass
    for attempt in range(tries):
        shell.SendKeys("^s")
        if not can_detect:                 # 감지 불가 → 옛 방식(고정 대기)
            import time
            time.sleep(2.5)
            return True
        import time
        waited = 0.0
        while waited < per_try:
            time.sleep(0.4)
            waited += 0.4
            if _foreground_is_dialog():
                return True
        if attempt < tries - 1:
            log("  · " + t("저장창이 아직 안 떠서 Ctrl+S 재시도({n}/{tries})...",
                          n=attempt + 2, tries=tries))
    return False


def _is_admin() -> "bool | None":
    """현재 프로세스가 관리자 권한(elevated)으로 실행 중인가. 판단 불가 시 None.

    ★실사용자 확인(2026-07): 일반 권한으로 실행하면 SendKeys(Ctrl+S)가 크롬 창에 '보이지 않게'
    씹혀 저장 대화상자가 절대 안 뜨고, 관리자 권한으로 실행하면 정상 작동함을 재현 확인. 이 환경의
    Windows 입력 격리(UIPI 계열) 정책이 원인으로 추정 — 창 포커스/타이밍 문제가 아니었음."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return None


def _correct_saved_filename(got: str, save_path: str, log=print) -> str:
    """[순수 파일조작] 크롬이 저장한 실제 경로(got)가 의도한 경로(save_path)와 다르면 정정한다.

    ★실사용자 확인된 회귀: 저장창의 파일명 칸에 Alt+N→Ctrl+A→붙여넣기 키 입력 중 일부가 씹히면
    (관리자 권한이 아닐 때 합성 키 입력이 간헐적으로 전달 안 되는 것과 같은 근본 원인 계열), 저장창
    자체는 뜨고 저장도 되지만 크롬의 기본 제안 파일명(예: "av.html")으로 저장돼버린다. 그냥 '성공'
    으로 받아들이면 (a) 레시피가 기대하는 파일명과 달라 다음 실행에서 못 찾고, (b) 다음 replay
    배치 작업이 같은 기본 파일명으로 다시 저장하려다 크롬의 '덮어쓸까요?' 확인창(우리 자동화가
    처리 안 함)에 걸려 멎을 수 있다. → GUI 의존 없는 100% 확실한 파이썬 파일 이동으로 정정한다.
    [반환] 최종적으로 사용할 경로(정정 성공 시 save_path, 실패 시 got 그대로)."""
    if os.path.abspath(got) == os.path.abspath(save_path):
        return got
    from i18n import t
    import shutil
    log("  · " + t("⚠ 예상한 파일명이 아니라 크롬 기본 이름으로 저장된 것 같습니다({name}) — "
                   "파일명 입력 키가 일부 씹혔을 수 있습니다(관리자 권한 문제와 같은 계열). "
                   "올바른 이름으로 정정합니다.", name=os.path.basename(got)))
    got_base = got.rsplit(".", 1)[0]
    base = save_path.rsplit(".", 1)[0]
    try:
        if os.path.exists(save_path):
            os.remove(save_path)
        os.rename(got, save_path)
        got_files = got_base + "_files"
        if os.path.isdir(got_files):
            if os.path.isdir(base + "_files"):
                shutil.rmtree(base + "_files", ignore_errors=True)
            os.rename(got_files, base + "_files")
        return save_path
    except OSError as e:
        log("  · [" + t("저장경고") + f"] {type(e).__name__}: {e} "
            f"({t('정정 실패 — 원래 파일명 그대로 사용')})")
        return got


def _set_clipboard(text: str) -> bool:
    """클립보드에 text 를 넣는다(경로 붙여넣기용). 성공 True."""
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        return True
    except Exception:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return False


def chrome_save_as_fetch(url: str, save_path: str, log=print,
                         load_wait: float = 10.0, save_wait: float = 30.0,
                         new_window: bool = True):
    """[Save As 완전자동] 내 진짜 크롬으로 url 을 열고 Ctrl+S 로 저장 → 그 HTML 의 DOM 반환.

    디버그 포트를 전혀 안 쓰므로 Chrome 136+ 의 '기본 프로필 디버그 차단'과 무관하고,
    평소 쓰는 내 세션(로그인/쿠키)으로 페이지를 받는다. pywin32 로 창 포커스→Ctrl+S→
    경로 입력→Enter 까지 키 입력으로 자동 집행한다(마우스 0번). 실패 시 None.

    네이티브 저장창을 키 입력으로 다루므로 창 포커스/타이밍에 민감하다(가끔 어긋날 수
    있음). save_path 는 ASCII 경로 권장(SendKeys 한글 입력 불안정).
    """
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        log("  · [" + t("저장자동화오류") + "] " + t("pywin32 미설치 (pip install pywin32)"))
        return None
    chrome = _find_chrome()
    if not chrome:
        log("  · [" + t("크롬오류") + "] " + t("chrome.exe 를 찾지 못함"))
        return None
    if _is_admin() is False:
        log("  · " + t("⚠ 관리자 권한이 아닙니다 — 일부 Windows 환경은 이 상태에서 Ctrl+S 입력이 "
                       "크롬에 전달되지 않습니다. 실패하면 관리자 권한으로 다시 실행해 보세요."))
    import subprocess, time, shutil

    save_path = os.path.abspath(save_path)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    base = save_path.rsplit(".", 1)[0]
    # 덮어쓰기 확인창 방지: 기존 파일/리소스폴더 선삭제
    try:
        if os.path.exists(save_path):
            os.remove(save_path)
        for d in (base + "_files", base + "_파일"):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass

    start = time.time()
    # 1) 내 진짜 크롬으로 페이지 열기 (디버그 없음 = 내 세션/쿠키)
    args = [chrome, "--new-window", url] if new_window else [chrome, url]
    subprocess.Popen(args)
    log("  · " + t("내 크롬으로 페이지 여는 중... (로드 대기 {s}s)", s=f"{load_wait:.0f}"))
    time.sleep(load_wait)

    shell = win32com.client.Dispatch("WScript.Shell")
    # 2) 크롬 창 포커스 (+ 잔여 모달 대화상자가 있으면 ESC로 정리)
    try:
        shell.AppActivate("Chrome")
    except Exception:
        pass
    time.sleep(1.0)
    shell.SendKeys("{ESC}")          # 떠 있을 수 있는 잔여 저장창/팝업 정리
    time.sleep(0.3)
    # 3) Ctrl+S → '저장 대화상자가 실제로 뜰 때까지' 폴링(안 뜨면 재시도)
    log("  · " + t("Ctrl+S 전송 → 저장창 대기"))
    if not _wait_save_dialog(shell, log):
        log("  · [" + t("저장자동화오류") + "] " + t("저장 대화상자가 안 떴습니다(페이지 로딩/포커스 문제)."))
        if _is_admin() is False:
            log("    " + t("관리자 권한이 아니라서 Ctrl+S 입력이 크롬에 전달되지 않았을 가능성이 "
                           "높습니다 — 관리자 권한으로 다시 실행해 보세요."))
        else:
            log("    " + t("크롬 창이 맨 앞이었는지 확인하고 다시 시도하세요."))
        return None
    time.sleep(0.5)
    # 4) 파일명 칸을 '명시적으로' 포커스(Alt+N) → 전체선택 → 경로를 '붙여넣기'.
    #    타이핑(SendKeys) 은 한글 IME/특수문자/글자드롭으로 경로가 깨져 '경로 없음'
    #    오류가 나기 쉽다 → 클립보드 Ctrl+V 가 훨씬 안정적. (Alt+N = 로케일 무관 표준
    #    가속키 '파일 이름(N)' — 엉뚱한 컨트롤에 포커스돼 기본파일명이 남는 것 방지.)
    shell.SendKeys("%n")             # Alt+N: 파일 이름 칸 포커스
    time.sleep(0.3)
    shell.SendKeys("^a")             # 기존(기본) 파일명 전체 선택
    time.sleep(0.2)
    if _set_clipboard(save_path):
        shell.SendKeys("^v")         # 경로 붙여넣기(선택 내용 대체) — 타이핑 회피
        time.sleep(0.5)
    else:                            # 클립보드 실패 시 폴백: 직접 타이핑
        shell.SendKeys("{DEL}")
        time.sleep(0.2)
        shell.SendKeys(save_path)
        time.sleep(0.6)
    shell.SendKeys("{ENTER}")

    # 5) 저장 완료 대기 — 정확 경로 우선, 없으면 같은 폴더의 최신 .htm(l) 탐색
    def _saved_file():
        if os.path.exists(save_path):
            return save_path
        d = os.path.dirname(save_path)
        cands = []
        try:
            for fn in os.listdir(d):
                if fn.lower().endswith((".html", ".htm")):
                    fp = os.path.join(d, fn)
                    if os.path.getmtime(fp) >= start:
                        cands.append(fp)
        except Exception:
            pass
        return max(cands, key=os.path.getmtime) if cands else None

    # 저장 대화상자가 뜨고 Enter 까지 눌렀으므로 '저장은 이미 진행 중'이다. 그러니
    # 파일이 '아직 안 나타났을 때'만 save_wait 만큼 기다리고, 일단 파일이 나타나면
    # 'Webpage, Complete'(리소스까지 받아 느림, CNN 등)라도 '크기가 안정될 때까지'
    # 시간제한 없이 기다린다 — 저장은 거의 실패하지 않으므로 고정 컷(옛 30s)으로 느린
    # 페이지를 헛되이 포기하지 않는다. (파일이 끝내 안 나타나면 = 경로 오류 등 진짜
    # 실패 → save_wait 뒤 종료. 저장 파일은 커지기만 하므로 이 루프는 반드시 끝난다:
    #  파일 등장→크기 안정=완료, 또는 미등장→appear_deadline. 무한 대기 불가능.)
    appear_deadline = time.time() + save_wait
    got = None
    prev_size = -1
    while True:
        cand = _saved_file()
        if cand:
            try:
                size = os.path.getsize(cand)
            except OSError:
                size = -1
            if size > 0 and size == prev_size:   # 두 번 연속 같은 크기 = 쓰기 끝
                got = cand
                break
            prev_size = size                     # 아직 커지는 중 → 계속 기다림(무기한)
            time.sleep(0.9)
            continue
        if time.time() > appear_deadline:        # 파일이 끝내 안 나타남 = 진짜 실패
            break
        time.sleep(0.5)
    if not got:
        try:
            shell.SendKeys("{ESC}")   # 멈춘 저장창(경로 오류 등) 닫아 잔존 모달 제거
        except Exception:
            pass
        log("  · [" + t("저장자동화오류") + "] " +
            t("{s}s 안에 저장 파일이 안 보임(저장창 포커스/저장 지연).", s=f"{save_wait:.0f}"))
        log("    " + t("크롬 창이 맨 앞이었는지 확인하고 다시 시도하세요."))
        return None

    # 크롬이 기본 제안 파일명으로 저장해버렸을 수 있음(파일명 입력 키 일부 누락) → 정정.
    got = _correct_saved_filename(got, save_path, log=log)

    try:
        with open(got, "rb") as f:
            content = f.read()   # 로컬 HTML(bytes → lxml 인코딩 자동감지)
    except Exception as e:
        log("  · [" + t("저장읽기오류") + f"] {type(e).__name__}: {e}")
        return None
    # 'Webpage, Complete' 가 만든 리소스 폴더(_files: 이미지·CSS)는 '유지'한다 — 시각적 피커가
    # 그 로컬 리소스로 오프라인 렌더(요청 0건)하기 위함. 엔진 파싱엔 .html 만 쓰지만 삭제하지 않는다.
    log("  · " + t("저장 완료 → {p}", p=got))
    try:
        return lxml_html.fromstring(content)
    except Exception as e:
        log("  · [" + t("파싱오류") + f"] {type(e).__name__}: {e}")
        return None

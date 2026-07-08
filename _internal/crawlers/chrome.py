# -*- coding: utf-8 -*-
"""
MODULE_NAME: crawlers/chrome.py
PURPOSE: '진짜 크롬' 수집 전략 — 정적/헤드리스가 안티봇(Akamai/Cloudflare/PerimeterX/DataDome)에
         막힐 때, 사용자의 실제 Chrome 세션(로그인/쿠키)으로 페이지를 받는 최후 경로.
         두 방식: (1) profile 디버그 attach(CDP), (2) Save As 완전자동(pywin32 키입력).
DEPENDENCY: lxml(필수), Chrome 설치, i18n(leaf, 로그 문구 번역). profile=Playwright(CDP),
            save_as=pywin32(win32com/win32gui/win32clipboard). 미설치/실패 시 모두 None → 호출부(cli)가 폴백/안내.

[검증된 주요 사이트 및 케이스]
- 쿠팡 등 Akamai/Cloudflare 계열: save_as(Ctrl+S) 경로로 내 세션 HTML 확보(디버그 포트 불필요 →
  Chrome 136+ 의 '기본 프로필 디버그 차단'과 무관).
- profile_fetch: 디버그 포트 attach-first(깜빡임 없이 재사용), 없으면 내 프로필 디버그 실행.

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


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _scrape_open_browser(endpoint, url, wait_ms, scroll, own_tab, log, scroll_seconds=15.0):
    """이미 떠 있는 CDP 엔드포인트(=실제 크롬)에 붙어 url 내용을 받아 HTML 문자열 반환.

    own_tab=True 면 새 탭을 열어 받고 닫는다(사용자 기존 탭 안 건드림 → attach 모드).
    own_tab=False 면 우리가 띄운 전용 크롬이라 그 탭을 그대로 쓴다.
    scroll_seconds: 무한스크롤 시 최대 스크롤 시간(초). 높이 정체 시 조기 종료(dynamic.py 와 동일 정책).
    """
    from playwright.sync_api import sync_playwright
    import time
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = None
        if own_tab:
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        else:
            base = url.split("?")[0]
            for _ in range(40):     # 우리가 띄운 크롬이 연 탭을 찾는다
                pages = [pg for c in browser.contexts for pg in c.pages]
                page = next((pg for pg in pages if base in pg.url), None) \
                    or (pages[0] if pages else None)
                if page and page.url not in ("about:blank", ""):
                    break
                time.sleep(0.25)
            if page is None:
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=wait_ms)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)   # 안티봇 JS·콘텐츠 안정화 대기
        if scroll:
            prev_h = -1
            deadline = time.monotonic() + scroll_seconds
            while time.monotonic() < deadline:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
                h = page.evaluate("document.body.scrollHeight")
                if h == prev_h:
                    break
                prev_h = h
        content = page.content()
        if own_tab:
            try:
                page.close()     # attach 모드: 우리가 연 탭만 닫고 사용자 크롬은 유지
            except Exception:
                pass
        browser.close()         # connect_over_cdp 의 close 는 '연결 해제'(크롬 안 죽임)
    return content


def _default_chrome_user_data():
    """사용자의 진짜 Chrome 프로필(User Data) 디렉터리. 없으면 None."""
    p = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    return p if os.path.isdir(p) else None


def _kill_chrome(log=print):
    """남아 있는(백그라운드 포함) chrome.exe 를 모두 종료. 프로필 잠금 해제용."""
    import subprocess
    try:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                       capture_output=True)
        log("  · " + t("백그라운드 크롬 정리(taskkill)"))
    except Exception as e:
        log("  · " + t("크롬 정리 실패: {e}", e=e))


def chrome_profile_fetch(url: str, port: int = 9222, save_path: str = None,
                         wait_ms: int = 6000, scroll: bool = False,
                         scroll_seconds: float = 15.0, log=print,
                         allow_kill: bool = True):
    """[내 크롬 전용] 사용자의 '진짜 Chrome 프로필'로만 렌더된 DOM 을 받는다.

    별도/전용 프로필은 절대 만들지 않는다. 동작:
      ① attach : 디버그 포트가 이미 열려 있으면(이전 실행이 띄워둠) 거기 붙어 받는다.
      ② 내 프로필 디버그 자동 실행 : 크롬이 완전히 꺼져 있으면 내 실제 프로필을 디버그로
         실행해 받고, 그 크롬은 닫지 않고 둔다(다음엔 ①로 재사용 → 깜빡임 없음).
      · 크롬이 백그라운드로 남아 ②가 위임돼 막히면, allow_kill 일 때 그 잔류 크롬만
        정리하고 한 번 재시도한다. (사용자가 이미 닫은 크롬의 백그라운드 잔재 정리)

    우회 트릭이 아니라, 평소 브라우저로 '다른 이름으로 저장' 하는 동작의 자동화일 뿐.
    save_path 주면 HTML 저장. 실패 시 None. (내가 띄운 크롬은 절대 강제 종료 안 함)
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        log("  · [" + t("크롬오류") + "] " + t("Playwright 미설치 (pip install playwright)"))
        return None

    import subprocess, time
    endpoint = f"http://127.0.0.1:{port}"
    chrome = _find_chrome()
    real = _default_chrome_user_data()

    def _launch_real():
        """내 실제 프로필을 디버그로 실행. '디버그 포트가 열리는지'로만 성공 판정.

        주의: 크롬은 켜질 때 런처 프로세스가 곧장 끝나고 브라우저는 별도 프로세스로
        돈다. 그러니 프로세스 종료(poll)를 실패로 보면 안 되고, 오직 포트가 열렸는지만
        본다. 포트가 끝까지 안 열리면 = (디버그 없이) 기존 크롬에 위임된 것.
        """
        subprocess.Popen([
            chrome, f"--remote-debugging-port={port}",
            f"--user-data-dir={real}",
            "--no-first-run", "--no-default-browser-check", url,
        ])
        deadline = time.time() + 15
        while time.time() < deadline and not _port_open(port):
            time.sleep(0.3)
        return _port_open(port)

    content = None
    try:
        # ① attach-first: 이미 열린 내 디버그 크롬에 연결
        if _port_open(port):
            log("  · " + t("디버그 크롬 감지(:{port}) → 내 크롬 세션에 연결(attach)", port=port))
            content = _scrape_open_browser(endpoint, url, wait_ms, scroll,
                                           own_tab=True, log=log,
                                           scroll_seconds=scroll_seconds)
        elif not chrome:
            log("  · [" + t("크롬오류") + "] " + t("chrome.exe 를 찾지 못함"))
            return None
        elif not real:
            log("  · [" + t("크롬오류") + "] " + t("내 Chrome 프로필(User Data)을 찾지 못함"))
            return None
        else:
            # ② 내 프로필을 디버그로 실행 → 포트 열리면 그 즉시 추출
            log("  · " + t("내 크롬(실제 프로필)을 디버그로 실행(:{port})...", port=port))
            ok = _launch_real()
            if not ok and allow_kill:
                # 포트가 끝내 안 열림 = (디버그 없이) 기존 크롬에 위임된 것 → 정리 후 재시도
                log("  · " + t("디버그 포트 안 열림(기존 크롬에 위임 추정) → 잔류 크롬 정리 후 재시도"))
                _kill_chrome(log)
                time.sleep(3)
                ok = _launch_real()
            if not ok:
                log("  · [" + t("크롬오류") + "] " + t("내 프로필 디버그 실행 실패."))
                log("    " + t("크롬을 '완전히' 종료(작업표시줄/백그라운드 앱 포함) 후 다시 실행하세요."))
                return None
            log("  · " + t("내 크롬 디버그 실행됨 → HTML 추출 (이 크롬은 닫지 않고 둠)"))
            content = _scrape_open_browser(endpoint, url, wait_ms, scroll,
                                           own_tab=False, log=log,
                                           scroll_seconds=scroll_seconds)
    except Exception as e:
        log("  · [" + t("크롬오류") + f"] {type(e).__name__}: {e}")
        content = None
    # 주의: 내가 띄운 크롬은 절대 terminate 하지 않는다(= 내 크롬, 살려둠).

    if not content:
        return None
    dom = lxml_html.fromstring(content)
    if save_path:                 # 저장 실패가 어렵게 받은 DOM 을 날리면 안 됨 → 격리
        try:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            log("  · [" + t("저장경고") + f"] {type(e).__name__}: {e}")
    return dom


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

    # 'Webpage, Complete' 는 리소스까지 받아 마무리가 느리다 → 넉넉히 대기하고,
    # 파일이 보이면 '크기가 안정될 때까지'(쓰기 진행 중일 수 있음) 확인 후 채택.
    deadline = time.time() + save_wait
    got = None
    while time.time() < deadline:
        cand = _saved_file()
        if cand:
            try:
                s1 = os.path.getsize(cand)
                time.sleep(0.9)
                s2 = os.path.getsize(cand)
            except OSError:
                s1, s2 = 0, -1
            if s1 > 0 and s1 == s2:     # 더 안 커지면 쓰기 끝
                got = cand
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

# -*- coding: utf-8 -*-
"""
MODULE_NAME: bootstrap.py
PURPOSE: 첫 실행 부트스트랩(비전공자용) — 진입점(start/cli/replay/capabilities/doctor) 맨 위에서
         ensure_env() 를 부르면, 처음 한 번 '가상환경(.venv) 만들까요?(권장)'를 묻고 그 선택을 기억한다.
         venv 를 쓰면 .venv 생성 + 의존성 자동설치(pip + playwright chromium) 후 venv 파이썬으로 '재실행'한다.
         이후엔 물어보지 않고 자동으로 venv 로 실행된다.
DEPENDENCY: 표준 라이브러리만(첫 실행 시 서드파티가 아직 없으므로). 내부 모듈 import 안 함.

  안전장치:
   · '이미 어떤 venv 안'이면 즉시 return → os.execv 무한루프 방지(우리 .venv 로 재실행된 프로세스 포함).
   · 비대화(스케줄러/서브프로세스, stdin 비-tty)면 묻지 않고 현재 인터프리터로 진행.
   · venv 생성/설치/재실행 중 어디서 실패해도 '경고 후 현재 파이썬으로 계속' → 절대 크래시로 막지 않는다.
   · SHC_NO_BOOTSTRAP=1 이면 완전히 건너뜀(디버깅/CI).
"""
import hashlib
import json
import os
import subprocess
import sys

from i18n import t, set_lang, _read_env_lang  # 다국어: stdlib-only leaf → venv 전에도 안전, 미번역은 한국어 폴백

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 프로젝트 루트(_internal 의 부모)
VENV = os.path.join(HERE, ".venv")
CFG = os.path.join(HERE, ".shc_bootstrap.json")
REQ = os.path.join(HERE, "requirements.txt")


def _venv_python():
    """이 프로젝트 .venv 의 파이썬 실행 경로(윈도우/POSIX)."""
    win = os.path.join(VENV, "Scripts", "python.exe")
    return win if os.name == "nt" else os.path.join(VENV, "bin", "python")


def _in_any_venv():
    """지금 '어떤' 가상환경 안에서 실행 중인가(우리 .venv 로 재실행된 경우 포함)."""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _isatty():
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _load_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(d):
    try:
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _file_hash(p):
    try:
        with open(p, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _set_lang_in_env(lang):
    """루트 .env 에 LANG=<lang> 을 쓴다(다른 키·줄은 보존, 없으면 새로 만듦). 표준 라이브러리만
    (start.py 의 _set_env 는 아직 못 씀 — bootstrap 은 내부 모듈을 안 부르는 leaf 라서 직접 구현)."""
    root_env = os.path.join(HERE, ".env")
    lines, found = [], False
    try:
        with open(root_env, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped \
                        and stripped.split("=", 1)[0].strip() == "LANG":
                    lines.append(f"LANG={lang}\n")
                    found = True
                    continue
                lines.append(line if line.endswith("\n") else line + "\n")
    except FileNotFoundError:
        pass
    if not found:
        lines.append(f"LANG={lang}\n")
    try:
        with open(root_env, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass   # 실패해도 이번 실행은 set_lang() 으로 이미 반영됨 — 다음 실행에 다시 물어볼 뿐


def _ask_language():
    """.env 에 LANG 이 아예 없으면(진짜 첫 실행) 언어부터 물어본다 — venv 질문조차 뭔 말인지 모른 채
    영어로 나오면 비전공자가 당황하므로, 그보다 먼저 배치. 아직 언어를 모르는 시점이라 이 프롬프트
    자체는 한국어/영어를 병기(그 아래부터는 고른 언어로 t() 가 알아서 나옴)."""
    print("\n┌─ 언어 선택 / Language ───────────────────────────")
    print("│ 1) 한국어")
    print("│ 2) English")
    ans = input("└ 번호 / number [Enter=2]: ").strip()
    lang = "ko" if ans == "1" else "en"
    set_lang(lang)              # 이번 실행에 바로 반영(뒤따르는 venv 질문부터 적용)
    _set_lang_in_env(lang)      # 다음 실행부터도 기억
    print()


def _install_deps(vpy):
    """venv 에 의존성 자동설치(pip + playwright 브라우저). 비전공자가 pip 를 몰라도 되게."""
    print("  · " + t("의존성 설치 중(pip)... 처음 한 번, 잠시 걸릴 수 있어요."))
    subprocess.run([vpy, "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=False)
    subprocess.run([vpy, "-m", "pip", "install", "-r", REQ], check=True)
    print("  · " + t("브라우저(Chromium) 설치 중(playwright, 최초 1회 ~150MB)..."))
    # 실패해도 치명적이지 않음(정적 크롤은 동작) → check=False + 안내.
    r = subprocess.run([vpy, "-m", "playwright", "install", "chromium"])
    if r.returncode != 0:
        print("  · [" + t("안내") + "] " + t("Chromium 설치가 완료되지 않았습니다. 렌더링/피커가 필요하면 나중에\n    '.venv 파이썬 -m playwright install chromium' 를 다시 실행하세요."))


def ensure_env(interactive: bool = True):
    """진입점 최상단에서 호출. 필요하면 venv 준비 후 그 파이썬으로 현재 프로세스를 재실행한다."""
    if _in_any_venv() or os.environ.get("SHC_NO_BOOTSTRAP") == "1":
        return
    if interactive and _isatty() and not _read_env_lang():
        _ask_language()    # .env 에 LANG 이 아예 없으면(진짜 첫 실행) venv 질문보다 먼저 언어부터
    cfg = _load_cfg()
    if "use_venv" not in cfg:                     # 첫 실행
        if not (interactive and _isatty()):
            return                                # 비대화 → 결정 미루고 현재 파이썬으로
        print("\n┌─ " + t("처음 실행 설정") + " ─────────────────────────────")
        print("│ " + t("가상환경(.venv)을 만들어 필요한 것들을 자동 설치할까요? (권장)"))
        print("│  · " + t("권장: 다른 파이썬 프로그램과 안 섞이고, 설치가 자동입니다."))
        print("│  · " + t("아니오: 지금 파이썬 그대로 사용(필요 패키지는 직접 설치)."))
        ans = input("└ " + t("가상환경을 사용하시겠어요? [Y/n]: ")).strip().lower()
        cfg["use_venv"] = ans in ("", "y", "yes", "ㅇ", "예", "네")
        _save_cfg(cfg)
        print("  · " + t("선택 기억됨({choice}) — 바꾸려면 {cfg} 삭제.",
                        choice=(t("가상환경 사용") if cfg['use_venv'] else t("현재 파이썬 사용")),
                        cfg=os.path.basename(CFG)) + "\n")
    if not cfg.get("use_venv"):
        return
    try:
        created = not os.path.exists(_venv_python())
        if created:
            print("  · " + t("가상환경(.venv) 생성 중..."))
            subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
        req_hash = _file_hash(REQ)
        if created or cfg.get("deps_hash") != req_hash:   # 최초/의존성 변경 시에만 설치
            _install_deps(_venv_python())
            cfg["deps_hash"] = req_hash
            _save_cfg(cfg)
    except Exception as e:
        print("  · [" + t("부트스트랩 경고") + "] " + t("가상환경 준비 실패: {e}\n    현재 파이썬으로 계속합니다(필요 패키지가 없으면 오류가 날 수 있어요).", e=e))
        return
    vpy = _venv_python()
    try:
        print("  · " + t("가상환경으로 전환하여 실행합니다...") + "\n")
        sys.stdout.flush()
        os.execv(vpy, [vpy] + sys.argv)           # 프로세스를 venv 파이썬으로 교체(재실행)
    except Exception as e:
        print("  · [" + t("부트스트랩 경고") + "] " + t("가상환경 재실행 실패: {e} → 현재 파이썬으로 계속", e=e))

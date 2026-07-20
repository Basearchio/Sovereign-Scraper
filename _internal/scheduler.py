# -*- coding: utf-8 -*-
"""
MODULE_NAME: scheduler.py
PURPOSE: Windows 작업 스케줄러(schtasks.exe) 등록/조회/삭제를 명령어를 외우지 않고 메뉴로 하게 해주는
         '섬' 유틸리티. `replay.py all`(또는 특정 site_no)을 주기 실행하도록 등록해, 지금까지 README/SRS
         부록이 사용자에게 손으로 입력하라고 안내하던 schtasks 명령을 대신 짜준다.
DEPENDENCY: 표준 라이브러리(os/sys/csv/subprocess) + paths(HERE)·i18n(t, leaf) + bootstrap(첫 실행 venv,
         최상위 진입점 공통 관례). cli/engine/chain/core/crawlers/autoheal 등 다른 내부 모듈은 전혀
         참조하지 않는다 — start.py 가 서브프로세스로만 이 파일을 띄우므로(다른 스크립트를 건드리지
         않는 '섬' 구조), 이 파일이 죽거나 바뀌어도 크롤 엔진 자체엔 영향이 없다.
         Windows 전용(schtasks.exe 는 Windows 에만 존재) — 다른 OS 에서는 안내 후 조용히 종료.

[상태 없음 — 이 프로젝트의 '상태파일 없이 결정론' 철학]
등록된 작업 목록을 별도 파일로 추적하지 않는다. 항상 `schtasks /query` 로 실조회하고, 우리가 만든
작업만 이름 접두사(SHC_)로 골라낸다 — 사용자의 다른(우리와 무관한) 예약 작업을 절대 건드리지 않는다.

[v1 범위 — 알려진 한계]
등록은 '로그온 상태에서만 실행'(/it)만 지원한다(README/SRS 부록 E가 이미 문서화한 방식과 동일 —
Save As GUI 자동화가 있는 사이트는 로그온 세션이 필요하기 때문). 로그오프 상태에서도 도는 완전 무인
운영은 Windows 자격 증명(비밀번호) 저장이 필요해 보안 표면이 넓어지므로 v1 에서는 지원하지 않는다
(향후 과제로 문서화).

[테스트/운영 교훈]
- schtasks.exe 실호출은 테스트에서 절대 하지 않는다(LLM 처럼 비결정적/외부 의존 — 심을 모킹).
  명령어 생성(build_*_cmd)과 실행(_run_schtasks)을 분리해 전자만 순수 함수로 테스트한다.
- /tr 값은 '나중에 Task Scheduler 가 다시 파싱할 완전한 명령줄 문자열'이라, 경로마다 따옴표로
  감싸야 한다(공백 포함 경로 대응) — subprocess 자체의 인자 분리와는 별개의 계층.
- (실사용 확인) `schtasks /query /tn X /fo LIST /v` 원문 전체(~28줄)는 정보 과다라 목록 화면엔
  부적합 — 이름/시작일/시작 시각/다음 실행 4가지만 요약해서 보여주고 정렬한다(get_task_summary).
  값(Start Time 등)은 로케일 포맷(한국어 Windows 실측: '오후 3:17:00')이지만, **헤더 라벨 자체는
  실측 결과 로케일과 무관하게 영어로 고정**이라(`/fo CSV /v`, 헤더+데이터를 함께 받아 zip) 하드
  코딩된 열 인덱스 대신 헤더 이름으로 안전하게 찾는다 — 혹시 다른 Windows 버전에서 순서가
  달라져도 밀리지 않는다. `Task To Run` 값 안에 이스케이프 안 된 따옴표가 섞여 나오는 걸 실측
  확인했는데, `csv.reader` 가 이를 견디고 뒤 컬럼(Start Time/Start Date)을 밀지 않고 정확히
  파싱함을 실제 등록된 작업으로 검증했다(표준 csv 모듈이 malformed quote 에 관대하기 때문).
"""
import bootstrap  # 첫 실행: 가상환경(.venv) 안내·자동설치 후 venv 로 재실행
if __name__ == "__main__":
    bootstrap.ensure_env()

import csv
import datetime
import io
import os
import re
import subprocess
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths            # leaf: 프로젝트 루트(HERE)만 재사용(경로 계산 중복 방지)
from i18n import t       # leaf: 다국어(미번역은 한국어 폴백)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPLAY_PATH = os.path.join(paths.HERE, "replay.py")
TASK_PREFIX = "SHC_"   # 우리가 만든 작업만 식별(다른 예약 작업을 절대 건드리지 않기 위한 안전장치)


# ---------------------------------------------------------------------------
# 순수 함수 — 명령어 조립(테스트가 실제 schtasks.exe 없이 검증하는 부분)
# ---------------------------------------------------------------------------
def _task_name(label: str) -> str:
    """사용자가 입력한 라벨을 안전한 작업 이름으로("<접두사><영숫자/-/_>", 최대 200자)."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (label or "").strip())
    safe = safe.strip("_") or "task"
    return (TASK_PREFIX + safe)[:200]


def _current_user() -> str:
    """/RU(로그온 사용자) 값. DOMAIN\\user 형식이 있으면 그걸, 없으면 사용자명만."""
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    return f"{domain}\\{user}" if domain and user else user


def _parse_hour_interval(raw: str):
    """간격 입력 → 총 분(정수). 두 표기 모두 지원(사용자 선택 편의):
      · 'H:MM' 시:분 표기(예: '50:23' = 50시간 23분 = 3023분, '0:1' = 1분)
      · 시간 분수 표기(Fraction 문법, 예: '3' = 3시간 = 180분, '1/60' = 1분, '1/2' = 30분)
    총 분이 정수가 아니거나(예: '1/90') 0 이하면 무효 → None(호출부가 기본값으로 폴백)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if ":" in raw:
        try:
            h, mi = raw.split(":", 1)
            total = int(h) * 60 + int(mi)
        except (ValueError, TypeError):
            return None
        return total if total > 0 else None
    try:
        minutes = Fraction(raw) * 60
    except (ValueError, ZeroDivisionError):
        return None
    if minutes <= 0 or minutes != int(minutes):
        return None
    return int(minutes)


# ★실측(2026-07-20): 'Repeat: Every' 값 자체가 로케일에 따라 'N Hour(s), M Minute(s)'(영어) 또는
# 'N시간, M분'(한국어)로 나오는 걸 실제 등록된 MINUTE 작업으로 확인(헤더뿐 아니라 '값'도 로케일
# 의존). 시간/분을 '독립적으로' 찾아 어느 한쪽이 없거나 순서가 달라도 안전하게 합산한다.
_HOUR_PART_RE = re.compile(r"(\d+)\s*(?:Hour\(s\)|시간)", re.I)
_MIN_PART_RE = re.compile(r"(\d+)\s*(?:Minute\(s\)|분)", re.I)


def _parse_interval_minutes(repeat_every: str):
    """schtasks 'Repeat: Every' 원문(예: '1 Hour(s), 0 Minute(s)' 또는 '0시간, 1분')에서 총 분
    (정수)을 뽑는다. DAILY/WEEKLY/ONCE 등 '반복 간격' 개념이 없는 스케줄은 이 필드가 없거나
    'N/A' → None(호출부가 '-' 로 표시)."""
    if not repeat_every:
        return None
    hm, mm = _HOUR_PART_RE.search(repeat_every), _MIN_PART_RE.search(repeat_every)
    if not hm and not mm:
        return None
    total = (int(hm.group(1)) if hm else 0) * 60 + (int(mm.group(1)) if mm else 0)
    return total if total > 0 else None


def _format_interval_minutes(total_minutes):
    """총 분 → 사람이 읽는 'N시간 M분' 표시. 분수(예: '3023/60')보다 이게 훨씬 읽기 쉽다."""
    if total_minutes is None:
        return "-"
    h, m = divmod(int(total_minutes), 60)
    if h and m:
        return t("{h}시간 {m}분", h=h, m=m)
    if h:
        return t("{h}시간", h=h)
    return t("{m}분", m=m)


def build_replay_tr(selection: str, python_exe: str = None, replay_path: str = None) -> str:
    """schtasks /tr 값(=예약될 전체 명령줄, Task Scheduler 가 나중에 재파싱) 조립.
    selection: 'all' 또는 site_no 들(예: '3', '1 3 4', '6-1') — replay.py 의 기존 파싱을 그대로
    재사용하므로 여기서 별도 검증하지 않는다(잘못된 번호는 재현 시점에 replay 가 무시하고 알려줌)."""
    py = python_exe or sys.executable
    rp = replay_path or REPLAY_PATH
    sel = (selection or "all").strip() or "all"
    return f'"{py}" "{rp}" {sel}'


def build_create_cmd(name: str, tr_command: str, schedule: str, modifier=None,
                     start_time=None, start_date=None, days=None,
                     logon_only=True, user=None):
    """schtasks /create 인자 리스트(순수 함수, 부작용 없음 — 실행은 _run_schtasks 가 따로 한다).
    schedule: 'HOURLY'|'DAILY'|'WEEKLY'|'ONCE'. modifier: /mo(반복 간격, 예: 3시간마다=3).
    days: WEEKLY 전용 콤마 목록(예: 'MON,WED,FRI'). /f 로 '이미 있으면 덮어쓸지' 프롬프트를 없애
    비대화형으로 만든다(우리가 register_task 호출 '전'에 이미 확인을 받으므로 중복 확인 불필요)."""
    cmd = ["schtasks", "/create", "/tn", name, "/sc", schedule, "/tr", tr_command, "/f"]
    if modifier:
        cmd += ["/mo", str(modifier)]
    if days:
        cmd += ["/d", days]
    if start_time:
        cmd += ["/st", start_time]
    if start_date:
        cmd += ["/sd", start_date]
    if logon_only:
        cmd += ["/it", "/ru", user or _current_user()]
    return cmd


def build_query_all_cmd():
    """전체 작업을 헤더 없는 CSV 로(로케일 무관하게 첫 컬럼=작업명만 신뢰)."""
    return ["schtasks", "/query", "/fo", "CSV", "/nh"]


def build_query_one_cmd(name: str):
    """특정 작업의 '전체 원문' 상세(사람이 읽을 그대로 relay — 로케일별 라벨을 우리가 파싱하지
    않는다). 목록 화면의 요약(4가지만)으로 부족할 때 '더 보기' 용도로만 쓰인다."""
    return ["schtasks", "/query", "/tn", name, "/fo", "LIST", "/v"]


def build_query_one_csv_cmd(name: str):
    """특정 작업의 상세를 CSV(헤더 있음, 파싱은 헤더 '개수'만 스키마 검증에 쓰고 실제 값은 위치
    인덱스로 뽑는다 — get_task_summary 참고). ★실측(2026-07-20): 처음엔 '헤더 라벨은 로케일과
    무관하게 영어로 고정'이라 가정하고 헤더 이름으로 찾았으나, 같은 한국어 Windows에서도 호출
    경로(수동 PowerShell vs 파이썬 subprocess)에 따라 헤더가 한국어로 나오는 경우를 실제로 확인
    했다 — 라벨 텍스트는 못 믿는다. 대신 '열 순서'(스키마)는 schtasks 전체 버전에서 고정이므로
    _QUERY_V_CSV_FIELDS 인덱스로 신뢰한다(개수가 다르면 스키마 자체가 달라진 것으로 보고 None)."""
    return ["schtasks", "/query", "/tn", name, "/fo", "CSV", "/v"]


# schtasks 의 CSV(/v, verbose) 출력 열 '순서'(고정, 실측 확인 — 라벨 텍스트는 로케일에 따라
# 달라질 수 있어도 이 순서 자체는 바뀌지 않는다). 헤더+데이터 '컬럼 개수'만 이 리스트 길이와
# 비교해 스키마 일치를 검증하고, 실제 값은 인덱스로 집는다(헤더 문자열 매칭 없음).
_QUERY_V_CSV_FIELDS = [
    "HostName", "TaskName", "NextRunTime", "Status", "LogonMode", "LastRunTime",
    "LastResult", "Author", "TaskToRun", "StartIn", "Comment", "ScheduledTaskState",
    "IdleTime", "PowerManagement", "RunAsUser", "DeleteIfNotRescheduled",
    "StopIfRunsXHoursAndXMins", "Schedule", "ScheduleType", "StartTime",
    "StartDate", "EndDate", "Days", "Months", "RepeatEvery", "RepeatUntilTime",
    "RepeatUntilDuration", "RepeatStopIfStillRunning",
]
_IDX = {name: i for i, name in enumerate(_QUERY_V_CSV_FIELDS)}


def build_delete_cmd(name: str):
    return ["schtasks", "/delete", "/tn", name, "/f"]


def build_run_cmd(name: str):
    return ["schtasks", "/run", "/tn", name]


# ---------------------------------------------------------------------------
# 실행 계층 — 실제 schtasks.exe 호출(테스트는 runner 를 주입해 이 함수들을 우회)
# ---------------------------------------------------------------------------
def _decode_console_bytes(raw: bytes) -> str:
    """콘솔 프로그램(schtasks.exe) stdout/stderr 원문 바이트를 디코드.
    ★실측(2026-07-20): 콘솔 출력 코드페이지가 '고정값 하나'가 아니라 실행 맥락(어느 터미널에서
    띄웠는지 — 시스템 기본 OEM 코드페이지 vs 그 터미널의 활성 코드페이지가 다를 수 있음)에 따라
    실제로 달라지는 걸 확인했다: 'utf-8' 고정도, 'oem'(시스템 기본 OEM 코드페이지) 고정도 둘 다
    어떤 세션에서는 깨졌다. 그래서 후보를 순서대로 '엄격 디코드'(errors=strict)로 시도해 예외 없이
    통과하는 첫 후보를 채택한다 — 특히 UTF-8은 검증이 엄격해(연속 바이트 규칙) 성공하면 진짜
    UTF-8일 확률이 매우 높다(오탐 위험이 낮은 '카나리아'). 전부 실패하면 마지막 후보를
    errors='replace' 로 강제 디코드(크래시보다 안전 — 최악이어도 사람이 읽을 텍스트는 나온다)."""
    candidates = ["utf-8"]
    try:
        import ctypes
        cp = ctypes.windll.kernel32.GetConsoleOutputCP() or ctypes.windll.kernel32.GetOEMCP()
        if cp:
            candidates.append(f"cp{cp}")
    except Exception:
        pass
    candidates.append("cp949")   # 한국어 Windows OEM 코드페이지(가장 흔한 실제 사례) 최종 폴백
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode(candidates[-1], errors="replace")


def _run_schtasks(cmd, log=print):
    """schtasks.exe 실행 → (returncode, stdout, stderr). 실패해도 예외를 죽이지 않고 안내로 변환한다
    (bootstrap.ensure_env() 와 같은 철학: 크래시로 막지 않는다). 인코딩은 _decode_console_bytes 가
    여러 후보를 시도해 정하므로, 여기선 바이트 그대로(text=False) 받는다."""
    try:
        r = subprocess.run(cmd, capture_output=True)
        return r.returncode, _decode_console_bytes(r.stdout), _decode_console_bytes(r.stderr)
    except FileNotFoundError:
        log("  · [" + t("스케줄러오류") + "] " +
            t("schtasks.exe 를 찾을 수 없습니다(Windows 전용 기능입니다)."))
        return 1, "", ""
    except Exception as e:
        log("  · [" + t("스케줄러오류") + f"] {type(e).__name__}: {e}")
        return 1, "", str(e)


def list_tasks(prefix: str = TASK_PREFIX, runner=_run_schtasks, log=print):
    """우리(SHC_ 접두사) 작업 이름 목록. CSV 첫 컬럼(작업명)만 신뢰 — 나머지 컬럼은 로케일에 따라
    한국어/영어로 달라지므로 파싱하지 않는다(관례: 원문 그대로 relay, 우리가 재해석 안 함)."""
    rc, out, err = runner(build_query_all_cmd(), log=log)
    if rc != 0:
        return []
    names = []
    for row in csv.reader(io.StringIO(out)):
        if not row:
            continue
        nm = row[0].strip().lstrip("\\")   # Task Scheduler 는 루트 작업에 '\' 를 붙여 표시
        if nm.startswith(prefix):
            names.append(nm)
    return names


def create_task(name, tr_command, schedule, runner=_run_schtasks, log=print, **kw):
    cmd = build_create_cmd(name, tr_command, schedule, **kw)
    rc, out, err = runner(cmd, log=log)
    if rc == 0:
        log("  ✔ " + t("등록됨: {name}", name=name))
        return True
    log("  · [" + t("등록 실패") + "] " + (err.strip() or out.strip() or t("(schtasks 가 이유를 알려주지 않음)")))
    return False


def delete_task(name, runner=_run_schtasks, log=print):
    rc, out, err = runner(build_delete_cmd(name), log=log)
    if rc == 0:
        log("  ✔ " + t("삭제됨: {name}", name=name))
        return True
    log("  · [" + t("삭제 실패") + "] " + (err.strip() or out.strip()))
    return False


def run_task_now(name, runner=_run_schtasks, log=print):
    rc, out, err = runner(build_run_cmd(name), log=log)
    if rc == 0:
        log("  ✔ " + t("지금 실행 요청됨: {name} (백그라운드에서 곧 시작)", name=name))
        return True
    log("  · [" + t("실행 요청 실패") + "] " + (err.strip() or out.strip()))
    return False


def show_task_detail(name, runner=_run_schtasks, log=print):
    """작업 1건의 '전체 원문' 상세를 그대로 보여준다(로케일별 라벨을 우리가 재해석하지 않음).
    목록 화면(_list)에 이미 핵심 요약이 나오므로, 이건 '더 보기' 용도의 보조 기능이다."""
    rc, out, err = runner(build_query_one_cmd(name), log=log)
    if rc != 0:
        log("  · [" + t("조회 실패") + "] " + (err.strip() or out.strip()))
        return
    log(out.strip())


def get_task_summary(name, runner=_run_schtasks, log=print):
    """작업 1건의 핵심 값(다음 실행/시작 시각/시작일/반복 간격)을 CSV '위치 인덱스'로 뽑는다 —
    헤더 라벨 텍스트는 로케일에 따라 달라질 수 있음을 실측으로 확인해 매칭에 쓰지 않는다(열
    '개수'만 스키마 검증에 사용). 조회 실패·스키마 불일치(컬럼 수가 예상과 다름 — 다른 Windows
    버전 등) 시 None → 호출부(_summarize)가 '?' 로 표시하고 그 항목은 정렬에서 맨 뒤로 보낸다."""
    rc, out, err = runner(build_query_one_csv_cmd(name), log=log)
    if rc != 0:
        return None
    rows = [r for r in csv.reader(io.StringIO(out)) if r]
    if len(rows) < 2:
        return None
    data = rows[-1]
    if len(data) != len(_QUERY_V_CSV_FIELDS):
        return None
    return {
        "next_run": data[_IDX["NextRunTime"]].strip(),
        "start_time": data[_IDX["StartTime"]].strip(),
        "start_date": data[_IDX["StartDate"]].strip(),
        "repeat_every": data[_IDX["RepeatEvery"]].strip(),
    }


def _display_label(name: str) -> str:
    """작업 이름(SHC_접두사+밑줄)을 사람이 읽기 좋은 라벨로. 등록 때 공백→밑줄 변환은 되돌릴 수
    없는 손실 변환이라(원래 라벨에 진짜 밑줄이 있었을 수도 있음) 완벽한 역변환은 아니지만, 표시
    편의로는 충분하다(예: 'SHC_러시아_뉴스' → '러시아 뉴스')."""
    base = name[len(TASK_PREFIX):] if name.startswith(TASK_PREFIX) else name
    return base.replace("_", " ") or name


def _parse_start_dt(date_str, time_str):
    """Start Date/Start Time 문자열을 정렬용 datetime 으로. 실측(이 프로젝트가 검증한 한국어
    Windows): 날짜='2026-07-20'(ISO), 시각='오후 3:17:00'(한국어 오전/오후). 다른 로케일·Windows
    버전에서 형식이 달라 파싱이 실패해도 예외를 던지지 않고 None(그 항목은 정렬에서 맨 뒤로 —
    잘못된 순서보다 '모른다'는 정직한 처리가 안전하다)."""
    date_str, time_str = (date_str or "").strip(), (time_str or "").strip()
    if not date_str:
        return None
    ampm = None
    for kr, en in (("오전", "AM"), ("오후", "PM")):
        if kr in time_str:
            ampm, time_str = en, time_str.replace(kr, "").strip()
            break
    if not ampm:
        m = re.search(r"\b(AM|PM)\b", time_str, re.I)
        if m:
            ampm = m.group(1).upper()
            time_str = (time_str[:m.start()] + time_str[m.end():]).strip()
    try:
        y, mo, d = (int(x) for x in date_str.split("-"))
        h, mi, s = ((time_str.split(":") + ["0", "0", "0"])[:3])
        h, mi, s = int(h), int(mi), int(s)
        if ampm:
            h = h % 12
            if ampm == "PM":
                h += 12
        return datetime.datetime(y, mo, d, h, mi, s)
    except (ValueError, TypeError):
        return None


def _summarize(names, runner=_run_schtasks, log=print):
    """이름 목록 → [{name, label, start_date, start_time, next_run, interval}, …], Start Date+
    Start Time 기준 오름차순 정렬(요청: '이름·시작일·예약시간·다음 실행시간·간격(시간)' 표시, 시작일·
    시각 기준 정렬). 파싱 실패 항목(_sort=None)은 맨 뒤로 몰아 정렬 자체가 죽지 않게 한다."""
    items = []
    for n in names:
        info = get_task_summary(n, runner=runner, log=log) or {}
        sd, st = info.get("start_date", ""), info.get("start_time", "")
        items.append({
            "name": n, "label": _display_label(n),
            "start_date": sd, "start_time": st,
            "next_run": info.get("next_run", ""),
            "interval": _format_interval_minutes(_parse_interval_minutes(info.get("repeat_every", ""))),
            "_sort": _parse_start_dt(sd, st),
        })
    items.sort(key=lambda it: (it["_sort"] is None, it["_sort"] or datetime.datetime.min))
    return items


# ---------------------------------------------------------------------------
# 인터랙티브 메뉴
# ---------------------------------------------------------------------------
_DAY_MAP = {"월": "MON", "화": "TUE", "수": "WED", "목": "THU",
           "금": "FRI", "토": "SAT", "일": "SUN"}


def _pick_selection():
    """예약할 대상 번호. '전체(all)'를 쉬운 기본값(Enter 한 번)으로 두지 않는다 — 레시피가 여러 개
    (실사용 20개 이상) 쌓인 사용자는 그중 하나쯤은 정기 수집을 원치 않을 확률이 높으므로(사용자
    피드백), 매번 replay.py --list 로 목록을 보여주고 번호를 '직접' 입력받는다. 빈 입력은 취소로
    처리(호출부 _register 가 등록을 진행하지 않음) — 'all' 을 정말 원하면 타이핑은 여전히 가능."""
    print("\n  " + t("예약할 사이트를 아래 목록에서 고르세요."))
    subprocess.run([sys.executable, REPLAY_PATH, "--list"], cwd=paths.HERE)
    sel = input("\n  " + t("예약할 번호 (예: 3 / 1,3,4 / 6-1, 전체를 원하면 all, Enter=취소): ")).strip()
    return sel or None


def _pick_schedule():
    """빈도 + 필요한 세부값만 순서대로 물어 (schedule, kwargs) 반환. 날짜/시각은 그대로 통과시키고
    schtasks 자체의 에러 메시지로 사용자가 형식을 고치게 한다(우리가 로케일별 형식을 검증하지 않음).
    1번(기본) 간격은 '시:분'(예: 50:23=50시간23분) 또는 시간 분수(예: 1/60=1분, 3=3시간) 둘 다
    받는다 — 60분 단위로 나눠떨어지면 HOURLY, 아니면 schtasks 네이티브 MINUTE 타입으로 자동 분기
    (분 단위 반복도 별도 메뉴 없이 같은 입력 한 줄로 처리)."""
    print("\n  " + t("얼마나 자주 실행할까요?"))
    print("  1) " + t("매시간/매분 (예: 3=3시간마다, 50:23=50시간23분마다, 1/60=1분마다)")
          + "  " + t("[기본]"))
    print("  2) " + t("매일 (예: 매일 09:00)"))
    print("  3) " + t("매주 (예: 매주 월요일 09:00)"))
    print("  4) " + t("한 번만 (특정 날짜/시각)"))
    sel = input("  " + t("번호(Enter=1): ")).strip()
    if sel == "2":
        st = input("  " + t("몇 시에 실행할까요? (HH:MM, Enter=09:00): ")).strip() or "09:00"
        return "DAILY", {"start_time": st}
    if sel == "3":
        raw = input("  " + t("무슨 요일에? (예: 월,수,금 / Enter=월): ")).strip() or "월"
        days = ",".join(_DAY_MAP.get(d.strip(), d.strip().upper())
                        for d in raw.split(",") if d.strip())
        st = input("  " + t("몇 시에? (HH:MM, Enter=09:00): ")).strip() or "09:00"
        return "WEEKLY", {"days": days or "MON", "start_time": st}
    if sel == "4":
        sd = input("  " + t("날짜 (예: 2026-08-01, 시스템 형식에 맞춰 조정될 수 있음): ")).strip()
        st = input("  " + t("시각 (HH:MM, Enter=09:00): ")).strip() or "09:00"
        return "ONCE", {"start_date": sd, "start_time": st}
    raw = input("  " + t("간격 (예: 3=3시간마다, 50:23=50시간23분마다, 1/60=1분마다, Enter=3): ")).strip()
    minutes = _parse_hour_interval(raw) if raw else 180
    if minutes is None:
        print("  · " + t("⚠ 인식하지 못한 간격 — 기본 3시간마다로 진행합니다."))
        minutes = 180
    if minutes % 60 == 0:
        return "HOURLY", {"modifier": minutes // 60}
    return "MINUTE", {"modifier": minutes}


def _describe_schedule(schedule, kw):
    """등록 전 확인 화면에 보여줄 사람이 읽는 빈도 설명(HOURLY/MINUTE 은 '간격(시간)'과 같은
    _format_interval_minutes 표기로 통일 — 확인 화면과 조회 화면의 빈도 표기가 어긋나지 않게)."""
    if schedule in ("HOURLY", "MINUTE"):
        total = kw.get("modifier", 0) * (60 if schedule == "HOURLY" else 1)
        return t("{iv}마다", iv=_format_interval_minutes(total))
    if schedule == "DAILY":
        return t("매일 {t}", t=kw.get("start_time", ""))
    if schedule == "WEEKLY":
        return t("매주 {d} {t}", d=kw.get("days", ""), t=kw.get("start_time", ""))
    if schedule == "ONCE":
        return t("{d} {t} (한 번만)", d=kw.get("start_date", ""), t=kw.get("start_time", ""))
    return f"{schedule} {kw}"


def _register():
    print("\n── " + t("예약 등록") + " ──")
    selection = _pick_selection()
    if not selection:
        print("  " + t("번호를 입력하지 않아 취소했습니다."))
        return
    schedule, kw = _pick_schedule()
    default_label = "replay_" + ("all" if selection == "all" else selection.replace(",", "_").replace(" ", "_"))
    label = input("\n  " + t("작업 이름 (Enter={d}): ", d=default_label)).strip() or default_label
    name = _task_name(label)
    tr = build_replay_tr(selection)
    print("\n  " + t("등록 내용:"))
    print(f"    · {t('작업 이름')}: {name}")
    print(f"    · {t('실행 명령')}: {tr}")
    print(f"    · {t('빈도')}: {_describe_schedule(schedule, kw)}")
    print("  · " + t("이 작업은 '로그온 상태에서만' 실행됩니다(비밀번호를 저장하지 않기 위한 안전한 기본값)."))
    if input("\n  " + t("이대로 등록할까요? [Y/n]: ")).strip().lower() in ("", "y", "yes", "ㅇ"):
        create_task(name, tr, schedule, **kw)
    else:
        print("  " + t("취소했습니다."))


def _list():
    print("\n── " + t("등록된 예약(이 프로그램이 만든 것만)") + " ──")
    names = list_tasks()
    if not names:
        print("  " + t("등록된 예약이 없습니다."))
        return
    items = _summarize(names)   # 이름·시작일·예약시간·다음 실행시간·간격(시간) 요약, 시작일/시각 순 정렬
    for i, it in enumerate(items, 1):
        print(f"  {i}. {it['label']}")
        print("      " + t("시작일 {d}  예약시간 {st}  다음 실행시간 {n}  간격(시간) {iv}",
                          d=it["start_date"] or "?", st=it["start_time"] or "?",
                          n=it["next_run"] or "?", iv=it["interval"]))
    sel = input("\n  " + t("전체 원문 상세를 볼 번호(Enter=건너뛰기): ")).strip()
    if sel.isdigit() and 1 <= int(sel) <= len(items):
        print()
        show_task_detail(items[int(sel) - 1]["name"])


def _parse_multi_indices(text, n):
    """'1' / '1,2' / '1 2' → 0-based 인덱스 리스트(유효 범위만, 중복 제거, 등장 순서 유지).
    등록 화면(_pick_selection)이 이미 콤마 다중 입력을 받으므로, 삭제도 같은 표기를 지원한다
    (실사용 확인: 콤마로 여러 개를 한 번에 골랐는데 예전엔 숫자 하나만 받아 조용히 취소됐음)."""
    out = []
    for tok in text.replace(",", " ").split():
        if tok.isdigit():
            i = int(tok) - 1
            if 0 <= i < n and i not in out:
                out.append(i)
    return out


def _delete():
    print("\n── " + t("예약 삭제") + " ──")
    names = list_tasks()
    if not names:
        print("  " + t("등록된 예약이 없습니다."))
        return
    for i, n in enumerate(names, 1):
        print(f"  {i}. {n}")
    sel = input("\n  " + t("삭제할 번호 (예: 1 또는 1,2, Enter=취소): ")).strip()
    idxs = _parse_multi_indices(sel, len(names))
    if not idxs:
        return
    targets = [names[i] for i in idxs]
    if len(targets) == 1:
        prompt = t("'{name}' 을(를) 정말 삭제할까요? [y/N]: ", name=targets[0])
    else:
        prompt = t("다음 {n}개를 정말 삭제할까요? {names} [y/N]: ", n=len(targets), names=", ".join(targets))
    if input("  " + prompt).strip().lower() in ("y", "yes", "ㅇ"):
        for name in targets:
            delete_task(name)
    else:
        print("  " + t("취소했습니다."))


def main():
    if os.name != "nt":
        print(t("이 기능은 Windows 전용입니다(schtasks.exe 가 없는 환경)."))
        return
    while True:
        print("\n=== " + t("예약 실행 (Windows 작업 스케줄러)") + " ===")
        print("  · " + t("replay.py 재현을 주기적으로 자동 실행하도록 등록/조회/삭제합니다."))
        print("  1. " + t("등록하기"))
        print("  2. " + t("조회하기"))
        print("  3. " + t("삭제하기"))
        print("  0. " + t("뒤로"))
        sel = input("\n  " + t("번호: ")).strip().lower()
        if sel in ("0", "", "q", "b"):
            return
        if sel == "1":
            _register()
        elif sel == "2":
            _list()
        elif sel == "3":
            _delete()
        else:
            print("  " + t("⚠ 잘못된 입력"))


if __name__ == "__main__":
    main()

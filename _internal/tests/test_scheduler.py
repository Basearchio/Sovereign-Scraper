# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_scheduler.py
PURPOSE: scheduler.py(Windows 작업 스케줄러 등록/조회/삭제 '섬')의 계약 — 명령어 조립은 순수 함수로
         검증하고, schtasks.exe 는 절대 실호출하지 않는다(runner 주입으로 모킹). 이름 접두사(SHC_)
         필터가 다른 예약 작업을 건드리지 않는지, /tr 값 조립이 경로를 따옴표로 감싸는지, 실패 시
         예외를 삼키지 않고 안내로 바꾸는지, scheduler.py 가 진짜 '섬'(다른 내부 모듈 미참조)인지도 고정.
DEPENDENCY: 표준 라이브러리만(오프라인, 결정적). schtasks/subprocess 실호출 없음.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scheduler as sch


# --- 순수 명령어 조립 -------------------------------------------------------

def test_parse_multi_indices_accepts_comma_and_space_dedupes_and_ignores_invalid():
    # 실사용 확인: 삭제 화면에서 '1,2' 콤마 다중 입력이 예전엔 조용히 취소됐음(숫자 하나만 허용) —
    # 등록 화면(_pick_selection)과 같은 표기를 지원하도록 수정.
    assert sch._parse_multi_indices("1,2", 3) == [0, 1]
    assert sch._parse_multi_indices("1 2", 3) == [0, 1]
    assert sch._parse_multi_indices("2,2,1", 3) == [1, 0]        # 중복 제거, 등장 순서 유지
    assert sch._parse_multi_indices("1,9,abc", 3) == [0]         # 범위 밖·비숫자 토큰 무시
    assert sch._parse_multi_indices("", 3) == []
    assert sch._parse_multi_indices("0", 3) == []                # 1-based 이므로 0은 무효


def test_task_name_prefixes_and_sanitizes():
    assert sch._task_name("replay all").startswith(sch.TASK_PREFIX)
    assert sch._task_name("a b!@#c") == sch.TASK_PREFIX + "a_b___c"
    assert sch._task_name("") == sch.TASK_PREFIX + "task"   # 빈 라벨 폴백


def test_build_replay_tr_quotes_paths():
    tr = sch.build_replay_tr("all", python_exe="C:/py 3.12/python.exe", replay_path="C:/proj x/replay.py")
    assert tr == '"C:/py 3.12/python.exe" "C:/proj x/replay.py" all'
    # 선택값(번호)도 그대로 뒤에 붙는다(replay.py 의 기존 파싱을 재사용 — 여기서 검증 안 함)
    tr2 = sch.build_replay_tr("1,3,4", python_exe="py", replay_path="r.py")
    assert tr2.endswith(" 1,3,4")


def test_build_replay_tr_defaults_to_all_when_blank():
    assert sch.build_replay_tr("", python_exe="py", replay_path="r.py").endswith(" all")
    assert sch.build_replay_tr(None, python_exe="py", replay_path="r.py").endswith(" all")


def test_build_create_cmd_hourly_includes_logon_only_by_default():
    cmd = sch.build_create_cmd("SHC_x", "cmd here", "HOURLY", modifier=3, user="DOMAIN\\me")
    assert cmd[:8] == ["schtasks", "/create", "/tn", "SHC_x", "/sc", "HOURLY", "/tr", "cmd here"]
    assert "/f" in cmd
    assert "/mo" in cmd and cmd[cmd.index("/mo") + 1] == "3"
    # 기본값이 '로그온 상태에서만 실행'(/it) — 비밀번호 저장 없이 안전한 v1 기본값
    assert "/it" in cmd
    assert "/ru" in cmd and cmd[cmd.index("/ru") + 1] == "DOMAIN\\me"


def test_build_create_cmd_weekly_has_day_flag():
    cmd = sch.build_create_cmd("SHC_w", "cmd", "WEEKLY", days="MON,WED", start_time="09:00", user="u")
    assert "/d" in cmd and cmd[cmd.index("/d") + 1] == "MON,WED"
    assert "/st" in cmd and cmd[cmd.index("/st") + 1] == "09:00"


def test_build_create_cmd_once_has_date_and_time():
    cmd = sch.build_create_cmd("SHC_o", "cmd", "ONCE", start_date="2026-08-01", start_time="09:00", user="u")
    assert "/sd" in cmd and cmd[cmd.index("/sd") + 1] == "2026-08-01"


def test_build_create_cmd_can_disable_logon_only():
    cmd = sch.build_create_cmd("SHC_x", "cmd", "HOURLY", modifier=3, logon_only=False)
    assert "/it" not in cmd and "/ru" not in cmd


def test_build_query_delete_run_cmds():
    assert sch.build_query_all_cmd() == ["schtasks", "/query", "/fo", "CSV", "/nh"]
    assert sch.build_query_one_cmd("SHC_x") == ["schtasks", "/query", "/tn", "SHC_x", "/fo", "LIST", "/v"]
    assert sch.build_query_one_csv_cmd("SHC_x") == ["schtasks", "/query", "/tn", "SHC_x", "/fo", "CSV", "/v"]
    assert sch.build_delete_cmd("SHC_x") == ["schtasks", "/delete", "/tn", "SHC_x", "/f"]
    assert sch.build_run_cmd("SHC_x") == ["schtasks", "/run", "/tn", "SHC_x"]


# --- 간격 파싱/포맷(순수 함수) — 실사용 확인된 두 표기(시:분 / 시간 분수) ------

def test_parse_hour_interval_accepts_hm_notation():
    assert sch._parse_hour_interval("50:23") == 50 * 60 + 23
    assert sch._parse_hour_interval("0:1") == 1


def test_parse_hour_interval_accepts_fraction_notation():
    assert sch._parse_hour_interval("3") == 180
    assert sch._parse_hour_interval("1/60") == 1
    assert sch._parse_hour_interval("1/2") == 30


def test_parse_hour_interval_rejects_non_integer_minutes_and_junk():
    assert sch._parse_hour_interval("1/90") is None    # 40초 — 정수 분 아님
    assert sch._parse_hour_interval("abc") is None
    assert sch._parse_hour_interval("") is None
    assert sch._parse_hour_interval(None) is None
    assert sch._parse_hour_interval("0") is None       # 0 이하는 무효


def test_format_interval_minutes_human_readable():
    assert sch._format_interval_minutes(180) == "3시간"
    assert sch._format_interval_minutes(1) == "1분"
    assert sch._format_interval_minutes(3023) == "50시간 23분"
    assert sch._format_interval_minutes(None) == "-"


def test_parse_interval_minutes_from_schtasks_repeat_every_field():
    assert sch._parse_interval_minutes("1 Hour(s), 0 Minute(s)") == 60
    assert sch._parse_interval_minutes("0 Hour(s), 1 Minute(s)") == 1
    assert sch._parse_interval_minutes("N/A") is None
    assert sch._parse_interval_minutes("") is None


def test_parse_interval_minutes_handles_localized_korean_value():
    """실측(2026-07-20): 'Repeat: Every' '값' 자체가 로케일에 따라 한국어로도 나온다
    ('0시간, 1분') — 영어 전용 정규식만으론 못 잡던 실제 회귀."""
    assert sch._parse_interval_minutes("0시간, 1분") == 1
    assert sch._parse_interval_minutes("1시간, 0분") == 60
    assert sch._parse_interval_minutes("50시간, 23분") == 50 * 60 + 23


def test_pick_schedule_dispatches_hourly_vs_minute():
    """60분 단위로 나눠떨어지면 HOURLY, 아니면 schtasks 네이티브 MINUTE 타입(별도 메뉴 없이 같은
    간격 입력 한 줄로 분기) — _pick_schedule 은 입력을 받으므로 여기선 그 분기 로직만 직접 검증."""
    minutes = sch._parse_hour_interval("1/60")
    assert minutes % 60 != 0   # 1분 → MINUTE 분기 대상
    minutes = sch._parse_hour_interval("3")
    assert minutes % 60 == 0   # 3시간 → HOURLY 분기 대상


# --- 실행 계층(runner 주입으로 schtasks.exe 를 모킹) ------------------------

def _fake_runner(rc, out="", err=""):
    return lambda cmd, log=print: (rc, out, err)


def test_list_tasks_filters_by_prefix_and_ignores_others():
    # 첫 컬럼(작업명)만 신뢰 — 나머지 컬럼(로케일별 라벨)은 무시. 루트 작업의 '\' 접두사도 벗겨낸다.
    csv_out = (
        '"\\SHC_replay_all","2026-08-01 09:00:00","Ready"\r\n'
        '"\\OtherVendorTask","2026-08-01 10:00:00","Ready"\r\n'
        '"\\SHC_replay_3","N/A","Ready"\r\n'
    )
    names = sch.list_tasks(runner=_fake_runner(0, csv_out))
    assert names == ["SHC_replay_all", "SHC_replay_3"]
    assert "OtherVendorTask" not in names   # 우리 것 아닌 작업은 절대 건드리지 않음


# --- get_task_summary/_summarize — 실제 캡처한 원문(따옴표 깨짐 포함)으로 검증 -----

_REAL_CSV_HEADER = (
    '"HostName","TaskName","Next Run Time","Status","Logon Mode","Last Run Time",'
    '"Last Result","Author","Task To Run","Start In","Comment","Scheduled Task State",'
    '"Idle Time","Power Management","Run As User","Delete Task If Not Rescheduled",'
    '"Stop Task If Runs X Hours and X Mins","Schedule","Schedule Type","Start Time",'
    '"Start Date","End Date","Days","Months","Repeat: Every","Repeat: Until: Time",'
    '"Repeat: Until: Duration","Repeat: Stop If Still Running"'
)
# 실제 등록된 작업을 조회해 받은 원문(따옴표가 이스케이프 안 된 Task To Run 필드 포함) — 이 프로젝트가
# 라이브로 캡처·검증한 값 그대로. csv.reader 가 이 malformed quote 를 견디고 뒤 컬럼을 안 미는지 고정.
_REAL_CSV_DATA = (
    '"C1-21","\\SHC_x","2026-07-20 오후 4:17:00","Ready","Interactive only",'
    '"1999-11-30 오전 12:00:00","267011","C1-21\\user",'
    '""C:\\py\\python.exe" "C:\\proj\\replay.py" 26","N/A","N/A","Enabled","Disabled",'
    '"Stop On Battery Mode, No Start On Batteries","user","Disabled","72:00:00",'
    '"Scheduling data is not available in this format.","One Time Only, Hourly ",'
    '"오후 3:17:00","2026-07-20","N/A","N/A","N/A","1 Hour(s), 0 Minute(s)","None",'
    '"Disabled","Disabled"'
)


def test_get_task_summary_parses_real_captured_csv_despite_broken_quotes():
    csv_out = _REAL_CSV_HEADER + "\r\n" + _REAL_CSV_DATA + "\r\n"
    info = sch.get_task_summary("SHC_x", runner=_fake_runner(0, csv_out))
    assert info["start_date"] == "2026-07-20"
    assert "3:17:00" in info["start_time"]
    assert "4:17:00" in info["next_run"]
    assert info["repeat_every"] == "1 Hour(s), 0 Minute(s)"


def test_get_task_summary_returns_none_on_query_failure_or_schema_mismatch():
    assert sch.get_task_summary("SHC_x", runner=_fake_runner(1, "", "error")) is None
    assert sch.get_task_summary("SHC_x", runner=_fake_runner(0, "\"a\",\"b\"\r\n")) is None  # 헤더뿐


def test_summarize_sorts_by_start_date_time_and_puts_unparseable_last():
    def runner(cmd, log=print):
        name = cmd[cmd.index("/tn") + 1]
        if name == "SHC_early":
            data = _REAL_CSV_DATA.replace("2026-07-20", "2026-07-01").replace("오후 3:17:00", "오전 9:00:00")
        elif name == "SHC_late":
            data = _REAL_CSV_DATA   # 2026-07-20 오후 3:17:00
        else:
            data = _REAL_CSV_DATA.replace('"2026-07-20","N/A"', '"","N/A"')  # 시작일 빈값 → 파싱 실패
        return 0, _REAL_CSV_HEADER + "\r\n" + data + "\r\n", ""

    items = sch._summarize(["SHC_late", "SHC_early", "SHC_unknown"], runner=runner)
    assert [it["name"] for it in items] == ["SHC_early", "SHC_late", "SHC_unknown"]
    assert items[0]["interval"] == "1시간"   # Repeat: Every = '1 Hour(s), 0 Minute(s)'


def test_list_tasks_returns_empty_on_query_failure():
    assert sch.list_tasks(runner=_fake_runner(1, "", "error")) == []


def test_create_task_reports_success_and_failure():
    logs = []
    assert sch.create_task("SHC_x", "tr", "HOURLY", modifier=3,
                           runner=_fake_runner(0), log=logs.append) is True
    assert any("SHC_x" in m for m in logs)

    logs.clear()
    assert sch.create_task("SHC_x", "tr", "HOURLY", modifier=3,
                           runner=_fake_runner(1, "", "ERROR: access denied"),
                           log=logs.append) is False
    assert any("access denied" in m for m in logs)


def test_delete_task_reports_success_and_failure():
    logs = []
    assert sch.delete_task("SHC_x", runner=_fake_runner(0), log=logs.append) is True
    logs.clear()
    assert sch.delete_task("SHC_x", runner=_fake_runner(1, "", "not found"), log=logs.append) is False
    assert any("not found" in m for m in logs)


def test_run_task_now_reports_success_and_failure():
    assert sch.run_task_now("SHC_x", runner=_fake_runner(0)) is True
    assert sch.run_task_now("SHC_x", runner=_fake_runner(1)) is False


def test_run_schtasks_missing_binary_does_not_raise():
    """schtasks.exe 가 없는 환경(예: 비-Windows)에서도 예외를 죽이고 (1,'','') 로 우아하게 폴백."""
    def _boom(cmd, capture_output=True):
        raise FileNotFoundError("no schtasks")
    orig = sch.subprocess.run
    sch.subprocess.run = _boom
    try:
        rc, out, err = sch._run_schtasks(["schtasks", "/query"], log=lambda *_: None)
        assert rc == 1
    finally:
        sch.subprocess.run = orig


# --- 콘솔 바이트 디코드(순수 함수) — 실측: 같은 시스템도 세션마다 실제 코드페이지가 달랐다 ------

def test_decode_console_bytes_prefers_valid_utf8():
    assert sch._decode_console_bytes("한글".encode("utf-8")) == "한글"


def test_decode_console_bytes_falls_back_to_cp949_for_non_utf8_bytes():
    # cp949 바이트는 utf-8 로는 디코드 자체가 실패(엄격 검증)하므로 다음 후보로 안전하게 넘어간다.
    raw = "러시아 뉴스".encode("cp949")
    assert sch._decode_console_bytes(raw) == "러시아 뉴스"


def test_decode_console_bytes_never_raises_on_garbage():
    assert isinstance(sch._decode_console_bytes(b"\xff\xfe\x00garbage"), str)


# --- 계층 규율: 진짜 '섬'인지(다른 내부 모듈을 참조하지 않는지) -------------

def test_scheduler_is_isolated_island():
    """scheduler.py 는 paths/i18n/bootstrap(+표준 라이브러리)만 참조한다 — cli/engine/chain/core/
    crawlers/autoheal 등 다른 내부 모듈을 전혀 모른다(섬 구조: start.py 만 서브프로세스로 이 파일을
    띄우고, 이 파일은 아무도 몰라도 된다)."""
    src = open(sch.__file__, encoding="utf-8").read()
    banned = ("cli", "engine", "chain", "core", "crawlers", "autoheal", "guards",
             "dedup", "output", "runlog", "llm_locators", "locators", "structure")
    offenders = []
    for line in src.splitlines():
        s = line.strip()
        m = re.match(r"(?:import|from)\s+([\w.]+)", s)
        if m and m.group(1).split(".")[0] in banned:
            offenders.append(s)
    assert not offenders, "scheduler.py 가 상위/형제 내부 모듈을 import 함(섬 규율 위반):\n" + "\n".join(offenders)


def test_windows_only_guard_returns_without_calling_schtasks():
    """os.name != 'nt' 면 schtasks 호출 없이 안내 후 즉시 반환."""
    called = []
    orig_run = sch.subprocess.run
    sch.subprocess.run = lambda *a, **k: called.append(1) or orig_run(*a, **k)
    orig_name = sch.os.name
    sch.os.name = "posix"
    try:
        sch.main()
    finally:
        sch.os.name = orig_name
        sch.subprocess.run = orig_run
    assert not called, "Windows 아닐 때 schtasks 를 호출하면 안 됨"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

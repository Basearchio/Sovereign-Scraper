"""replay.py — 과거 성공한 크롤링을 골라 다시 재현(배치 실행).

동작:
  · output/_runs.csv(실행 기록)에서 status=success 건을 사이트별 최신으로 모아 보여준다.
  · 번호를 고르면(예: 1,3,4 / all) 각 사이트에 대해 cli.py 를 '주입'해 다시 실행한다.
    (레시피가 이미 있으니 cli 가 예시 입력 없이 자동 재현 → 비대화형)
  · 사실상 cli 바깥에 for 문을 두는 구조 → 윈도우 작업 스케줄러에 묶기 좋다.

사용:
  python replay.py            # 목록 보고 번호 입력(대화형)
  python replay.py 1 3 4      # 1,3,4번 재현(비대화형)
  python replay.py all        # 전부 재현(스케줄러용)
  python replay.py --list     # 목록만 출력
  python replay.py --export-recipe 1 6-1   # 1,6-1 레시피를 '공유용(개인정보 마스킹)'으로
                                           #   recipes/shared/ 에 저장(url 검색어·example 제거)

스케줄러 예) 3시간마다:
  schtasks /create /tn "crawl_replay" /tr "<py> <이경로>\\replay.py all" /sc hourly /mo 3
  (GUI 저장(Save As) 자동화가 있는 사이트는 '로그온 상태에서 실행'으로 등록)
"""
import os as _os, sys as _sys
# 내부 모듈은 _internal/ 폴더에 있다 → import 전에 검색 경로에 추가.
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_internal"))
import bootstrap  # 첫 실행: 가상환경(.venv) 안내·자동설치 후 venv 로 재실행
if __name__ == "__main__":
    bootstrap.ensure_env()

import os
import sys
import csv
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import cli   # site_no 계층 번호(assign_run_numbers)·체인 판별을 cli 와 단일 규칙으로 공유
import paths   # 저장경로 상대↔절대 복원(폴더 이동 대응)
from runlog import next_batch, MODE_LABELS   # 회차(세션 공유)·저장방식 라벨
from i18n import t                            # 다국어: 사용자 출력 번역(미번역은 한국어 폴백)

HERE = os.path.dirname(os.path.abspath(__file__))
RUNLOG = os.path.join(HERE, "output", "_runs.csv")
CLI = os.path.join(HERE, "cli.py")


def _no_sortkey(no):
    """'6-1' → (6,1), '3' → (3,0). 부모별로 묶고 자식 순으로 정렬."""
    no = (no or "").strip()
    if "-" in no:
        a, b = no.split("-", 1)
        return (int(a) if a.isdigit() else 0, int(b) if b.isdigit() else 0)
    return (int(no) if no.isdigit() else 0, 0)


def load_targets():
    """_runs.csv 에서 성공 건을 번호(site_no)별 '최신'으로 모은다.
    번호는 cli.assign_run_numbers 와 동일 규칙(일반=정수, 체인=부모-자식 P-k)."""
    if not os.path.exists(RUNLOG):
        print(t("실행 기록이 없습니다: {p}", p=RUNLOG))
        print(t("먼저 cli.py 로 한 번 크롤링해 레시피/기록을 만드세요."))
        return []
    with open(RUNLOG, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cli.assign_run_numbers(rows)   # 각 행에 site_no(문자열) 부여 — cli 와 동일
    by_no = {}
    for row in rows:
        if (row.get("status") or "success") != "success":
            continue
        no = (row.get("site_no") or "").strip()
        if no:
            by_no[no] = row   # 나중 행(최신)이 덮어씀
    items = []
    for no, r in by_no.items():
        r["_site_no"] = no
        # 저장된 경로를 현재 루트 기준으로 복원(상대저장/폴더 이동 대응). 존재검사·export 가 이걸 쓴다.
        rec = paths.abs_from_root((r.get("recipe_csv") or "").strip())
        r["recipe_csv"] = rec
        if (r.get("result_csv") or "").strip():
            r["result_csv"] = paths.abs_from_root(r["result_csv"].strip())
        r["_has_recipe"] = bool(rec and os.path.exists(rec))
        r["_is_chain"] = cli._is_chain_target(r.get("target", ""))
        items.append(r)
    items.sort(key=lambda r: _no_sortkey(r["_site_no"]))
    return items


def show(items):
    print("=== " + t("재현 가능한 과거 성공 크롤링 (번호 = _runs.csv 의 site_no)") + " ===")
    for r in items:
        mark = "" if r["_has_recipe"] else "  " + t("⚠레시피없음(재학습 필요)")
        kind = ("  [" + t("체인:{col}", col=r.get('url_col', '')) + "]") if r.get("_is_chain") else ""
        mode_lbl = t(MODE_LABELS.get(r.get('save_mode') or 'append', r.get('save_mode') or 'append'))
        print(f"  {r['_site_no']:>4}. {r['target']}{kind}")
        print("      " + t("필드={f} | 로드={lm} | 저장=[{mode}] | 최근={at}",
                          f=r.get('fields', ''), lm=r.get('load_method', ''),
                          mode=mode_lbl, at=r.get('crawled_at', '')) + mark)


def parse_selection(sel, valid_nos):
    """valid_nos: 선택 가능한 site_no(문자열) 집합. 반환 (선택된 번호 리스트, 무시된 토큰).
    번호는 '3' 또는 체인의 '6-1' 형태(문자열)."""
    sel = sel.strip().lower()
    if sel in ("", "q", "quit", "exit"):
        return [], []
    if sel == "all":
        return sorted(valid_nos, key=_no_sortkey), []
    picked, skipped = [], []
    for tok in sel.replace(",", " ").split():
        if tok in valid_nos:
            if tok not in picked:
                picked.append(tok)
        else:
            skipped.append(tok)              # 목록에 없는 번호이거나 형식 불일치
    return picked, skipped


def do_export(picked, by_no):
    """[역할] 고른 번호의 레시피를 '공유용(개인정보 마스킹)'으로 recipes/shared/ 에 저장.
    구조 규칙은 보존, url 검색어·example 스니펫·chain clean_url 만 마스킹(core.recipe_share)."""
    import paths
    from core.recipe_share import sanitize_recipe
    from core.schema import Schema
    outbox = paths.outbox_dir()
    done = 0
    for no in picked:
        r = by_no[no]
        src = (r.get("recipe_csv") or "").strip()
        if not src or not os.path.exists(src):
            print(f"  [{no}] " + t("레시피 파일이 없어 건너뜀"))
            continue
        if r.get("_is_chain"):
            # 체인 target 은 로컬 목록 CSV(해시 파일명) → 깔끔한 기본 라벨: chain_<url_col>_<짧은해시>
            import hashlib
            col = "".join(c if c.isalnum() else "_" for c in (r.get("url_col") or "url"))
            h = hashlib.md5((r.get("target") or "").encode("utf-8")).hexdigest()[:4]
            default_label = f"chain_{col}_{h}"
        else:
            try:
                sch, _u, _lm, _w, _p = Schema.from_csv_recipe(src)
                fields = [n for n in sch.fields if not n.endswith("_url")]
            except Exception:
                fields = []
            default_label = paths.share_label(r["target"], fields)
        # 자기설명 이름: Enter=기본(사이트_필드…) / 직접 입력(예: 구글_이메일제목_이메일내용_이메일시간)
        try:
            typed = input(f"  [{no}] " + t("공유 이름 [Enter={d}]: ", d=default_label)).strip()
        except EOFError:
            typed = ""
        label = "".join(c for c in typed if c.isalnum() or c in "_-") or default_label
        dst = os.path.join(outbox, label + ".csv")
        try:
            s = sanitize_recipe(src, dst)
        except Exception as e:
            print(f"  [{no}] " + t("정제 실패: {e}", e=e))
            continue
        print(f"  [{no}] → recipes/shared/outbox/{label}.csv")
        print(f"        url : {s['orig_url']}")
        print("            → " + t("{u}  (검색어 마스킹)", u=s['masked_url']))
        print("        " + t("example 스니펫 {n}개 제거", n=s['examples_cleared'])
              + (t(", clean_url 마스킹") if s['chain'] else ""))
        done += 1
    print("\n=== " + t("공유용 레시피 {n}개 내보냄 → recipes/shared/outbox/", n=done) + " ===")
    print("⚠ " + t("올리기 전 recipes/shared/outbox/*.csv 를 열어 마스킹 결과를 검토하세요(경로에 남은 특이값 등). 자세한 정제 가이드는 recipes/shared/README.md."))


def main():
    args = [a for a in sys.argv[1:]]
    list_only = "--list" in args or "-l" in args
    export = "--export-recipe" in args or "--export" in args
    args = [a for a in args if a not in ("--list", "-l", "--export-recipe", "--export")]

    items = load_targets()
    if not items:
        return
    show(items)
    if list_only:
        return

    by_no = {r["_site_no"]: r for r in items}
    if export:
        prompt = "\n" + t("공유용으로 내보낼 번호 (예: 1,3 / 6-1 / all / q): ")
    else:
        prompt = "\n" + t("재현할 번호 (예: 1,3,4 / 6-1 / all / q): ")
    sel = " ".join(args) if args else input(prompt)
    picked, skipped = parse_selection(sel, set(by_no))
    if skipped:
        print(t("[무시] 목록에 없는 번호이거나 형식 불일치: {sk}  (선택 가능: {ok})",
                sk=', '.join(skipped), ok=sorted(by_no, key=_no_sortkey)))
    if not picked:
        print(t("취소(유효한 번호 없음)."))
        return

    if export:
        do_export(picked, by_no)
        return

    batch = next_batch()   # 이 replay 세션의 '회차' — 고른 모든 사이트가 공유(시간 대신 회차로 묶임)
    print("\n" + t("총 {n}개 재현 시작... (회차={b})", n=len(picked), b=batch) + "\n")
    ok = fail = 0
    for no in picked:
        r = by_no[no]
        tgt = r["target"]
        print(f"────────── [{no}] {tgt} ──────────")
        if not r["_has_recipe"]:
            print("  " + t("레시피가 없어 비대화형 재현 불가 → 건너뜀 (cli.py 로 예시 재학습 필요)") + "\n")
            fail += 1
            continue
        # cli 에 target 주입 → 레시피 자동 로드 → 입력 없이 재현(비대화형).
        # 체인(목록 CSV)은 어느 링크 열을 따라갈지 --url-col 로 지정해야 재현이 확정된다.
        cmd = [sys.executable, CLI, tgt, "--batch", str(batch)]   # 세션 회차 공유
        if r.get("_is_chain") and r.get("url_col"):
            cmd += ["--url-col", r["url_col"]]
        rc = subprocess.run(cmd).returncode
        if rc == 0:
            ok += 1
        else:
            fail += 1
            print("  " + t("[실패] cli 종료코드 {rc}", rc=rc))
        print()
    print("=== " + t("재현 완료: 성공 {ok} / 실패 {fail} (총 {tot})", ok=ok, fail=fail, tot=len(picked)) + " ===")


if __name__ == "__main__":
    main()

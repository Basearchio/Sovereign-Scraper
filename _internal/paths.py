# -*- coding: utf-8 -*-
"""
MODULE_NAME: paths.py
PURPOSE: 사이트/대상 → 파일 경로 규칙(leaf). 캐시·출력 CSV·저장 HTML·레시피 경로를 사람이 읽기 쉬운
         '사이트라벨_순번'(예: incruit_1)으로 만든다. 순수 문자열/경로 계산 + 레시피 파일 스캔만.
DEPENDENCY: 표준 라이브러리(os/csv/hashlib/urllib.parse)만. (core/schema 등 상위 import 금지 = leaf)

[명명 규칙 — 상태파일 없이 결정론]
- 종류 접두사 + 사이트라벨 + 순번:  output_<label>_<n>.csv / recipes_<label>_<n>.csv /
  saved/output_<label>_<n>.html / cache_<label>_<n>.json.  같은 <label>_<n> = '한 작업의 쌍'.
- 순번은 '상태파일 없이' 정한다: recipes/recipes_<label>_<n>.csv 를 1부터 스캔해
    · 그 레시피 meta.url 이 이 대상과 같으면 → 그 n 재사용(재크롤이 '자기 레시피'를 찾음 = 자가치유 핵심).
    · 비어 있으면 → 그 n 을 신규 배정.  · 다른 대상이 쓰면 → 다음 n.
  ⇒ 같은 URL=항상 같은 파일, 다른 URL=다음 번호. 레시피 파일 자체가 '대장(registry)' 역할.

[검증된 주요 사이트 및 케이스]
- 사이트별 누적(csv_path_for)·레시피(recipe_path_for)·저장본(saved_html_*): 재현/감사의 파일 기준.
- 체인 레시피(chain_recipe_path_for): 목록CSV 이름 + url_col → 자식 레시피(파일명에 'chain' 안 들어감).
- Save As 안정성: saved_html_* 는 ASCII·공백없는 사이트라벨(SendKeys 경로 깨짐 방지).

[테스트/운영 교훈]
- leaf 규율: 내부 상위 모듈(cli/engine/chain/core 등)을 import 하지 않는다(순환 차단). 레시피 url 은
  schema 를 쓰지 않고 stdlib csv 로 meta,url 행만 직접 읽는다.
- 순번은 '레시피 파일 존재'로 판별하므로, 레시피가 저장되기 전(첫 크롤)엔 첫 빈 슬롯을 일관되게 반환한다.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import os
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 프로젝트 루트(_internal 의 부모)
CACHE_DIR = os.path.join(HERE, "cache")
OUTPUT_DIR = os.path.join(HERE, "output")
RECIPE_DIR = os.path.join(HERE, "recipes")
RUNLOG_PATH = os.path.join(OUTPUT_DIR, "_runs.csv")
# 공유 레시피: outbox=내가 남에게 보낼(마스킹) 것 / inbox=남에게 받아 읽어들일 것 (섞이지 않게 분리)
SHARED_DIR = os.path.join(RECIPE_DIR, "shared")
OUTBOX_DIR = os.path.join(SHARED_DIR, "outbox")
INBOX_DIR = os.path.join(SHARED_DIR, "inbox")


def _url_key(target: str) -> str:
    """대상의 '정규 신원'(같은 대상 판별용). http 면 netloc+path+query, 아니면 파일명."""
    if target.startswith(("http://", "https://")):
        u = urlparse(target)
        return f"{u.netloc}{u.path}?{u.query}"
    return os.path.basename(target.replace("\\", "/"))


def _site_key(target: str):
    """(구) 사이트키 — netloc+path 납작화 + md5 10자. 하위호환용으로 유지(cli 가 import).
    현재 파일명 규칙은 _slot 을 쓰지만, 외부에서 참조할 수 있어 시그니처를 보존한다."""
    key = _url_key(target)
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    safe = "".join(c if c.isalnum() else "_" for c in key)[:40]
    return safe, digest


# 복합 TLD(2단 최상위) — 이 경우 사이트 이름은 그 앞 조각. (한국/영연방 등 흔한 것)
_COMPOUND_TLDS = {
    "co.kr", "or.kr", "ne.kr", "go.kr", "re.kr", "pe.kr", "ac.kr", "hs.kr",
    "co.uk", "org.uk", "gov.uk", "ac.uk", "co.jp", "or.jp", "ne.jp",
    "com.au", "net.au", "com.cn", "com.br", "co.in", "co.nz", "co.za",
}


def _site_label(target: str) -> str:
    """사이트의 짧은 이름(등록 도메인 = TLD 앞 이름). 서브도메인/www 는 무시한다.
    예) www.coupang.com→coupang, search.incruit.com→incruit, www.saramin.co.kr→saramin."""
    if target.startswith(("http://", "https://")):
        net = urlparse(target).netloc.split(":")[0].lower()
        parts = [p for p in net.split(".") if p]
        if parts and parts[0] == "www":
            parts = parts[1:]
        if len(parts) >= 3 and ".".join(parts[-2:]) in _COMPOUND_TLDS:
            label = parts[-3]                 # a.b.co.kr → b
        elif len(parts) >= 2:
            label = parts[-2]                 # sub.name.com → name
        else:
            label = parts[0] if parts else "site"
    else:
        base = os.path.basename(target.replace("\\", "/"))
        label = base.split(".")[0] or "site"
    return "".join(c for c in label if c.isalnum()) or "site"


def inbox_dir():
    """남에게 받은 공유 레시피 폴더(없으면 생성). '읽어들이기'가 여기서 목록을 연다."""
    os.makedirs(INBOX_DIR, exist_ok=True)
    return INBOX_DIR


def outbox_dir():
    """내가 공유할(마스킹) 레시피 폴더(없으면 생성). '공유하기'가 여기에 저장한다."""
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    return OUTBOX_DIR


def share_label(target, field_names=None):
    """공유용 자기설명 이름 = <사이트>_<필드1>_<필드2>… (예: google_이메일제목_이메일내용).
    받은 사람이 파일명만 봐도 '무슨 사이트의 무슨 필드'인지 알게 한다. 파일명 안전문자(영숫자·한글·-)만 남긴다."""
    def _safe(s):
        return "".join(c for c in str(s) if c.isalnum() or c == "-")
    parts = [_site_label(target)] + [f for f in (field_names or [])]
    out = "_".join(p for p in (_safe(x) for x in parts) if p)
    return out[:80] or "recipe"


def _read_recipe_url(path: str) -> str:
    """레시피 CSV 의 meta,url 행에서 url 을 읽는다(core 의존 없이 stdlib csv 로)."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if len(row) >= 3 and row[0] == "meta" and row[1] == "url":
                    return row[2]
    except (OSError, csv.Error):
        pass
    return ""


def _slot_index(target: str) -> int:
    """상태파일 없이 이 대상의 순번(1,2,…)을 정한다(모듈 docstring의 규칙).
    갭 안전: 기존 레시피 중 이 URL 과 일치하는 게 있으면 '그 번호'(중간이 지워져 구멍이 나도)를
    재사용하고, 없으면 '최저 빈 번호'를 배정한다 — 낮은 슬롯을 지워도 높은 슬롯이 오인되지 않는다."""
    label = _site_label(target)
    key = _url_key(target)
    prefix = f"recipes_{label}_"
    used = {}                                          # 순번 -> 레시피 경로 (비체인만)
    for p in glob.glob(os.path.join(RECIPE_DIR, prefix + "*.csv")):
        core = os.path.basename(p)[len(prefix):-4]
        if core.isdigit():                             # 체인(1__col)·다른 라벨은 제외
            used[int(core)] = p
    for n in sorted(used):                             # ① 같은 URL 재사용(구멍 있어도 안전)
        if _url_key(_read_recipe_url(used[n])) == key:
            return n
    n = 1                                              # ② 없으면 최저 빈 번호
    while n in used:
        n += 1
    return n


def _slot(target: str):
    """이 대상의 (사이트라벨, 순번). 모든 경로 함수가 이걸로 같은 <label>_<n> 을 공유한다."""
    return _site_label(target), _slot_index(target)


def cache_path_for(target: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    label, n = _slot(target)
    return os.path.join(CACHE_DIR, f"cache_{label}_{n}.json")


def csv_path_for(target: str) -> str:
    """사이트별 CSV 경로 (output/output_<label>_<n>.csv). 사이트/대상마다 따로 누적."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    label, n = _slot(target)
    return os.path.join(OUTPUT_DIR, f"output_{label}_{n}.csv")


def saved_html_path_for(target: str) -> str:
    """이번에 받은 HTML(=new) 저장 경로. 매 실행 덮어씀(항상 '최근 시도').
    Save-As 'Complete' 로 받으며 동반 리소스는 output_<label>_<n>_files/ 에 저장(피커가 이미지·CSS 오프라인
    렌더용으로 '유지'). 예) output/saved/output_incruit_1.html  (ASCII·공백없음 → SendKeys 안정)."""
    d = os.path.join(OUTPUT_DIR, "saved")
    os.makedirs(d, exist_ok=True)
    label, n = _slot(target)
    return os.path.join(d, f"output_{label}_{n}.html")


def saved_html_old_path_for(target: str) -> str:
    """마지막으로 '성공'한 HTML(=old) 보관 경로. 추출이 정상일 때만 new→old 로 승격.
    → 잘 되던 사이트가 실패하면 old(성공)와 new(실패)를 나란히 두고 원인 비교 가능.
    예) output/saved/output_incruit_1.old.html"""
    d = os.path.join(OUTPUT_DIR, "saved")
    os.makedirs(d, exist_ok=True)
    label, n = _slot(target)
    return os.path.join(d, f"output_{label}_{n}.old.html")


def rel_to_root(p: str) -> str:
    """프로젝트 루트(HERE) 안의 '로컬 절대경로'를 루트 기준 상대경로로 바꾼다(데이터 파일 이식성).
    → _runs.csv·결과 CSV 에 상대경로로 저장하면 폴더를 옮겨도 안 깨진다.
    원격 URL(http, '://' 포함)·상대경로·루트 밖 경로는 그대로 둔다."""
    if not p or "://" in p or not os.path.isabs(p):
        return p
    try:
        rp = os.path.relpath(p, HERE)
    except ValueError:      # 다른 드라이브 등 → 상대화 불가
        return p
    return p if rp.startswith("..") else rp


def abs_from_root(p: str):
    """rel_to_root 로 저장된 상대경로를 현재 루트(HERE) 기준 절대경로로 복원.
    ★레거시(옛 위치의 절대경로)가 이동으로 깨졌으면, 저장된 경로에서 프로젝트 폴더명 이후 '꼬리'를
    현재 루트에 다시 붙여 복원 시도 → 폴더를 옮기거나 이름을 바꿔도 재현/존재검사가 살아난다."""
    if not p or "://" in p:
        return p
    if not os.path.isabs(p):
        return os.path.normpath(os.path.join(HERE, p))
    if os.path.exists(p):
        return p
    marker = os.path.basename(HERE)                       # 예: self_healing_crawler
    parts = p.replace("\\", "/").split("/")
    if marker in parts:
        tail = parts[parts.index(marker) + 1:]
        if tail:
            cand = os.path.normpath(os.path.join(HERE, *tail))
            if os.path.exists(cand):
                return cand
    return p


def image_dir_for(target: str, save_mode: str = "", batch=None) -> str:
    """이미지 아카이브 폴더. 저장모드에 맞춰 CSV 와 같은 의미로:
      · history(전량 누적/회차) → images/<label>/run_<batch>/  (회차별 폴더 = 사용자 요청)
      · append/upsert/overwrite → images/<label>/             (dedup 누적 / 덮어쓰기는 호출부가 비움)."""
    base = os.path.join(OUTPUT_DIR, "images", _site_label(target))
    if save_mode == "history" and batch is not None:
        base = os.path.join(base, f"run_{batch}")
    os.makedirs(base, exist_ok=True)
    return base


def recipe_path_for(target: str) -> str:
    """사이트별 CSV 레시피 경로 (recipes/recipes_<label>_<n>.csv). 타격 위치를 기록."""
    os.makedirs(RECIPE_DIR, exist_ok=True)
    label, n = _slot(target)
    return os.path.join(RECIPE_DIR, f"recipes_{label}_{n}.csv")


def _list_core(csv_target: str) -> str:
    """목록 CSV(output_<label>_<n>.csv) → 코어 '<label>_<n>' (종류 접두사 output_/recipes_ 제거)."""
    stem = os.path.splitext(os.path.basename(csv_target.replace("\\", "/")))[0]
    for pre in ("output_", "recipes_"):
        if stem.startswith(pre):
            return stem[len(pre):]
    return stem


def _chain_core(csv_target: str, url_col: str) -> str:
    """체인 자식의 코어 '<label>_<n>__<col>' (목록 코어 + URL 컬럼). 레시피/데이터가 이걸 공유 = 한 쌍."""
    safe_col = "".join(c if c.isalnum() else "_" for c in (url_col or "url"))
    return f"{_list_core(csv_target)}__{safe_col}"


def chain_recipe_path_for(csv_target: str, url_col: str) -> str:
    """체인(목록 CSV → 상세) 레시피 경로: recipes/recipes_<label>_<n>__<col>.csv.
    같은 목록에서 URL 컬럼이 다르면 다른 자식 레시피. 목록의 <label>_<n> 을 물려받아 데이터와 쌍을 이룬다."""
    os.makedirs(RECIPE_DIR, exist_ok=True)
    return os.path.join(RECIPE_DIR, f"recipes_{_chain_core(csv_target, url_col)}.csv")


def chain_csv_path_for(csv_target: str, url_col: str) -> str:
    """체인 상세(자식) 데이터 CSV 경로: output/output_<label>_<n>__<col>.csv.
    레시피(recipes_<label>_<n>__<col>.csv)와 같은 코어 → 한눈에 '한 쌍'."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return os.path.join(OUTPUT_DIR, f"output_{_chain_core(csv_target, url_col)}.csv")


def chain_recipe_glob(csv_target: str) -> str:
    """이 목록 CSV 에 딸린 체인 레시피들의 glob 패턴 (recipes_<label>_<n>__*.csv)."""
    return os.path.join(RECIPE_DIR, f"recipes_{_list_core(csv_target)}__*.csv")

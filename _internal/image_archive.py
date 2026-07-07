# -*- coding: utf-8 -*-
"""
MODULE_NAME: image_archive.py
PURPOSE: '이미지 아카이버' leaf — 추출된 행의 이미지 값(원격 URL 또는 save_as 로컬 경로)을 받아
         로컬 폴더로 사본을 만들고(다운로드/복사), 각 행에 '오프라인 경로'를 채운다. 크롬 save_as 는
         URL 을 버리지만(파일명이 해시), 우리가 직접 받으면 URL↔파일이 정확히 짝지어진다.
         · 확장자 보정: Content-Type → 매직바이트 순(야후 CDN 처럼 URL 에 확장자 없는 경우 대응).
         · dedup: 같은 URL/파일은 한 번만(회차 누적 시 재다운로드 안 함).
DEPENDENCY: 표준 라이브러리만(os/hashlib/shutil/urllib). engine/cli 를 import 하지 않는다(leaf).
            네트워크는 fetch 주입으로 대체 가능 → 오프라인 결정적 테스트.
"""
from __future__ import annotations

import hashlib
import os
import shutil

# 매직바이트 → 확장자 (Content-Type 이 없거나 애매할 때 내용으로 판정)
_MAGIC = [
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"), (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
]
_CTYPE_EXT = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg",
    "image/bmp": ".bmp", "image/x-icon": ".ico", "image/avif": ".avif",
}


def detect_ext(content_type: str = "", data: bytes = b"") -> str:
    """이미지 확장자를 정한다. Content-Type 우선, 없으면 매직바이트, 그래도 모르면 '.img'.
    (야후 quriosity CDN 은 URL 에 확장자가 없어 서버 헤더/내용으로만 판정 가능.)"""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _CTYPE_EXT:
        return _CTYPE_EXT[ct]
    for sig, ext in _MAGIC:
        if data.startswith(sig):
            return ext
    if data[8:12] == b"WEBP" and data[:4] == b"RIFF":
        return ".webp"
    head = data[:64].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return ".svg"
    return ".img"


def _url_ext_hint(url: str) -> str:
    """URL 끝의 흔한 이미지 확장자(있으면). 헤더/내용이 애매할 때 참고."""
    tail = url.split("?")[0].split("#")[0].lower()
    for e in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".avif", ".ico"):
        if tail.endswith(e):
            return ".jpg" if e == ".jpeg" else e
    return ""


def _key(value: str) -> str:
    """URL/경로로부터 안정적인 파일 스템(같은 값=같은 파일 → dedup)."""
    return hashlib.md5(value.encode("utf-8", "ignore")).hexdigest()[:16]


def _default_fetch(url: str, timeout: float = 15.0, max_bytes: int = 12_000_000,
                   referer: str = ""):
    """(content_type, data) 반환. 실패 시 None. 사람처럼 보이는 UA·크기 상한·타임아웃.
    referer: 핫링크 차단 CDN(pixiv i.pximg.net 등)은 원페이지 Referer 가 없으면 403 → 넣어준다."""
    import urllib.request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes + 1)
            if len(data) > max_bytes:
                return None
            return r.headers.get("Content-Type", ""), data
    except Exception:
        return None


def prepare_dir(out_dir: str, overwrite: bool = False):
    """저장 폴더 준비. overwrite=True 면(저장모드 '덮어쓰기') 폴더를 비우고 새로 시작."""
    if overwrite and os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)


def _is_remote(v: str) -> bool:
    return v.startswith(("http://", "https://"))


def archive_images(rows, img_fields, out_dir, fetch=None, log=print, referer=""):
    """행들의 이미지 값을 out_dir 로 아카이빙하고, 각 행에 '<name>_file' 오프라인 경로를 채운다.

    rows: list[dict] (추출 결과, 제자리 수정).
    img_fields: [(url_field, file_field), ...] — url_field 값(원격 URL 또는 로컬 경로)을 저장하고
                file_field 에 오프라인 경로를 기록.
    fetch: url -> (content_type, bytes) | None (주입; 기본 _default_fetch). 로컬 경로 값은 복사.
    referer: 기본 fetch 에 붙일 원페이지 Referer(핫링크 차단 CDN 대응, 예: pixiv).
    반환: (저장수, 스킵/재사용수, 실패수).
    """
    if fetch is None:
        fetch = lambda u: _default_fetch(u, referer=referer)
    os.makedirs(out_dir, exist_ok=True)
    done = {}                       # value -> 저장경로 (같은 URL/경로 한 번만)
    saved = reused = failed = 0
    for row in rows:
        for url_field, file_field in img_fields:
            v = (row.get(url_field) or "").strip()
            if not v or v.startswith("data:"):
                continue
            if v in done:           # 같은 값 이미 처리 → 재사용
                row[file_field] = done[v]
                reused += 1
                continue
            if _is_remote(v):
                got = fetch(v)
                if not got:
                    failed += 1
                    log(f"    · [이미지 실패] {v[:60]}")
                    continue
                ctype, data = got
                ext = _url_ext_hint(v) or detect_ext(ctype, data)
                path = os.path.join(out_dir, _key(v) + ext)
                if not os.path.exists(path):
                    with open(path, "wb") as f:
                        f.write(data)
                    saved += 1
                else:
                    reused += 1
            else:                   # 로컬 경로(save_as) → 확장자 보정하며 복사
                if not os.path.exists(v):
                    failed += 1
                    continue
                with open(v, "rb") as f:
                    head = f.read(64)
                ext = os.path.splitext(v)[1] or _url_ext_hint(v) or detect_ext("", head)
                path = os.path.join(out_dir, _key(v) + ext)
                if not os.path.exists(path):
                    shutil.copyfile(v, path)
                    saved += 1
                else:
                    reused += 1
            done[v] = path
            row[file_field] = path
    return saved, reused, failed

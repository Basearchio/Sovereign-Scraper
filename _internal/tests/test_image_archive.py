# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_image_archive.py
PURPOSE: 이미지 아카이버 leaf 고정 — 원격 URL 다운로드/로컬 복사, 확장자 보정(Content-Type→매직바이트),
         dedup(같은 URL 한 번), 오프라인 경로 기록. ★네트워크는 fetch 주입으로 대체(오프라인 결정적).
DEPENDENCY: 표준 라이브러리만.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import image_archive as ia

_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 20
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def test_detect_ext_content_type_then_magic():
    assert ia.detect_ext("image/png", _JPEG) == ".png"      # Content-Type 우선
    assert ia.detect_ext("", _JPEG) == ".jpg"               # 헤더 없으면 매직바이트
    assert ia.detect_ext("", _PNG) == ".png"
    assert ia.detect_ext("image/webp", b"") == ".webp"
    assert ia.detect_ext("", b"unknownbytes") == ".img"     # 모르면 .img


def test_archive_downloads_and_fixes_missing_extension():
    """야후처럼 URL 에 확장자가 없어도, 헤더/내용으로 .jpg 를 붙여 저장하고 오프라인 경로를 채운다."""
    rows = [{"제목": "A", "이미지": "https://quriosity/G6mABC=="}]   # 확장자 없는 URL
    def fake_fetch(url):
        return "image/jpeg", _JPEG
    with tempfile.TemporaryDirectory() as d:
        saved, reused, failed = ia.archive_images(
            rows, [("이미지", "이미지_file")], d, fetch=fake_fetch, log=lambda *a: None)
        assert (saved, failed) == (1, 0)
        p = rows[0]["이미지_file"]
        assert p.endswith(".jpg") and os.path.exists(p)      # 확장자 보정 + 실제 저장
        assert open(p, "rb").read().startswith(b"\xff\xd8\xff")


def test_dedup_same_url_downloaded_once():
    """여러 행이 같은 이미지 URL 이면 한 번만 받고 나머지는 같은 파일 재사용."""
    calls = []
    def fake_fetch(url):
        calls.append(url)
        return "image/png", _PNG
    rows = [{"이미지": "https://x/same.png"}, {"이미지": "https://x/same.png"},
            {"이미지": "https://x/other.png"}]
    with tempfile.TemporaryDirectory() as d:
        saved, reused, failed = ia.archive_images(
            rows, [("이미지", "이미지_file")], d, fetch=fake_fetch, log=lambda *a: None)
        assert len(calls) == 2                                # 고유 URL 2개만 fetch
        assert saved == 2 and reused == 1
        assert rows[0]["이미지_file"] == rows[1]["이미지_file"]  # 같은 파일 공유


def test_local_path_value_is_copied_with_extension():
    """save_as 로컬 경로(확장자 없는 파일)도 매직바이트로 확장자 붙여 아카이브에 복사."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "G6m_noext")          # 확장자 없는 로컬 저장 파일
        with open(src, "wb") as f:
            f.write(_JPEG)
        rows = [{"이미지": src}]
        out = os.path.join(d, "archive")
        saved, reused, failed = ia.archive_images(
            rows, [("이미지", "이미지_file")], out, fetch=lambda u: None, log=lambda *a: None)
        assert saved == 1 and failed == 0
        assert rows[0]["이미지_file"].endswith(".jpg") and os.path.exists(rows[0]["이미지_file"])


def test_fetch_failure_is_graceful():
    rows = [{"이미지": "https://x/broken.jpg"}]
    with tempfile.TemporaryDirectory() as d:
        saved, reused, failed = ia.archive_images(
            rows, [("이미지", "이미지_file")], d, fetch=lambda u: None, log=lambda *a: None)
        assert (saved, failed) == (0, 1)
        assert "이미지_file" not in rows[0]                    # 실패 시 열 안 채움


def test_prepare_dir_overwrite_clears():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "imgs")
        os.makedirs(out)
        open(os.path.join(out, "old.jpg"), "wb").close()
        ia.prepare_dir(out, overwrite=True)
        assert os.path.isdir(out) and not os.listdir(out)     # 비워짐
        ia.prepare_dir(out, overwrite=False)                  # 유지
        open(os.path.join(out, "keep.jpg"), "wb").close()
        ia.prepare_dir(out, overwrite=False)
        assert os.path.exists(os.path.join(out, "keep.jpg"))


def test_leaf_no_upper_imports():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "image_archive.py"), encoding="utf-8").read()
    for bad in ("import engine", "import cli", "from engine", "from cli", "import locators"):
        assert bad not in src, f"image_archive 가 '{bad}' — leaf 위반"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

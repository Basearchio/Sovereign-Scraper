# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_capabilities.py
PURPOSE: 역량 매트릭스 도구(capabilities.py)의 계약 — '가져온 필드'는 output 컬럼 기준(부기 제외),
         값이 있는 것만 V, --mask 는 사이트명을 카테고리로만 바꾼다(브랜드/URL 비노출).
DEPENDENCY: 표준 라이브러리만(오프라인, 파일만 읽음).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import capabilities as cap


def _write(d):
    with open(os.path.join(d, "recipes_youtube_1.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("kind,name,tag,cls,attr,path,example\n")
        f.write("meta,url,https://www.youtube.com/playlist?list=SECRET,,,,\n")
        f.write("meta,load_method,render,,,,\n")
    with open(os.path.join(d, "output_youtube_1.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("제목,댓글,crawled_at\n")
        f.write("좋은 영상,,2026-01-01\n")
        f.write("또 영상,,2026-01-01\n")   # 댓글 전부 빈값 → 추출 실패


def test_fields_from_output_columns_only_filled():
    with tempfile.TemporaryDirectory() as d:
        _write(d)
        items = cap.collect(recipe_dir=d, output_dir=d)
        assert len(items) == 1
        it = items[0]
        assert it["label"] == "youtube" and it["load"] == "render" and it["records"] == 2
        names = [n for n, _r in it["fields"]]
        assert "crawled_at" not in names          # 부기 컬럼 제외
        assert "제목" in names and "댓글" in names  # output 컬럼이 소스


def test_render_lists_only_got_fields_local_shows_site():
    with tempfile.TemporaryDirectory() as d:
        _write(d)
        md = cap.render(cap.collect(recipe_dir=d, output_dir=d), mask=False)
        assert "제목:V" in md          # 값 있는 필드만 V
        assert "댓글" not in md         # 전부 빈값 → 나열 안 함
        assert "youtube" in md          # 로컬은 실제 사이트명
        assert "SECRET" not in md       # URL/쿼리는 절대 출력 안 함


def test_mask_replaces_site_with_category():
    with tempfile.TemporaryDirectory() as d:
        _write(d)
        md = cap.render(cap.collect(recipe_dir=d, output_dir=d), mask=True)
        assert "동영상 플랫폼" in md
        assert "youtube" not in md      # 마스킹 시 브랜드 비노출


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

# -*- coding: utf-8 -*-
"""tests/test_recipe_folders.py — 공유 레시피 폴더 분리(inbox/outbox)와 자기설명 이름(사이트_필드…).
동기: export/다운로드가 recipes/shared/ 한 곳에 섞여 받은 사람이 혼란 → outbox(내가 보낼)/inbox(내가 받은) 분리."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths


def test_shared_split_inbox_outbox_constants():
    assert paths.SHARED_DIR == os.path.join(paths.RECIPE_DIR, "shared")
    assert os.path.basename(paths.INBOX_DIR) == "inbox"
    assert os.path.basename(paths.OUTBOX_DIR) == "outbox"
    assert os.path.dirname(paths.INBOX_DIR) == paths.SHARED_DIR
    assert os.path.dirname(paths.OUTBOX_DIR) == paths.SHARED_DIR


def test_share_label_site_underscore_fields():
    lbl = paths.share_label("https://mail.google.com/mail/u/0/#inbox",
                            ["이메일제목", "이메일내용", "이메일시간"])
    assert lbl == "google_이메일제목_이메일내용_이메일시간"   # 받은 사람이 파일명만 봐도 앎


def test_share_label_sanitizes_and_handles_empty():
    lbl = paths.share_label("https://www.saramin.co.kr/zf_user/search", ["공고 제목!", "", "경력"])
    assert lbl == "saramin_공고제목_경력"                     # 공백·!·빈 필드 정리
    assert paths.share_label("https://x.com", []) == "x"       # 필드 없으면 사이트만

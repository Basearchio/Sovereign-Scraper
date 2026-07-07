# -*- coding: utf-8 -*-
"""
MODULE_NAME: tests/test_crawlers_chrome.py
PURPOSE: Phase 2 슬라이스3 고정 — '진짜 크롬' 수집(crawlers.chrome)과 안티봇 차단 감지
         (crawlers.base.block_reason)가 engine 에서 분리되고, cli 가 그것을 '위임'하는지(배선)와
         block_reason 의 판정 동작(차단 페이지 감지/정상 페이지 통과)을 확인한다.
DEPENDENCY: lxml(block_reason 판정). 실브라우저/pywin32 미기동(표면·배선만). 네트워크 불필요.

[검증된 주요 사이트 및 케이스]
- block_reason: 'just a moment'(Cloudflare) 류 짧은 차단 페이지 감지, 정상 목록은 통과.
- chrome_*: 실제 Save As/디버그는 실사이트 수동 스모크 영역(키입력·창포커스 의존).

[테스트/운영 교훈]
- block_reason 오탐 방지: 본문이 길면(>800자) 시그니처 단어가 우연히 있어도 차단으로 안 본다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lxml.html as H


def test_chrome_surface():
    """[역할] crawlers.chrome 의 공개 진입점(profile/save_as)이 실재하는지."""
    import crawlers.chrome as chrome
    assert callable(chrome.chrome_profile_fetch)
    assert callable(chrome.chrome_save_as_fetch)


def test_block_reason_detects_blocked_page():
    """[역할] 안티봇 차단 페이지(제목/시그니처)를 사유와 함께 감지."""
    from crawlers.base import block_reason
    dom = H.fromstring("<html><head><title>Just a moment...</title></head>"
                       "<body>Checking your browser (cloudflare)</body></html>")
    assert block_reason(dom), "차단 제목을 감지해야 함"


def test_block_reason_passes_normal_page():
    """[역할] 정상 목록/긴 본문은 차단으로 오탐하지 않음(None)."""
    from crawlers.base import block_reason
    body = "채용공고 " * 300  # 길고 정상적인 본문
    dom = H.fromstring(f"<html><head><title>채용 목록</title></head><body>{body}</body></html>")
    assert block_reason(dom) is None, "정상 페이지는 통과해야 함"
    assert block_reason(None) is None


def test_engine_dropped_chrome_and_block():
    """[역할] engine 이 chrome/block 관심사를 완전히 내려놨는지(중복/혼선 방지)."""
    import engine
    for name in ("chrome_profile_fetch", "chrome_save_as_fetch", "block_reason",
                 "_find_chrome", "_scrape_open_browser", "_BLOCK_TITLE"):
        assert not hasattr(engine, name), f"engine 에 {name} 가 남아있음(이관 누락)"


def test_loader_and_cli_wire_to_crawlers():
    """[역할] 'DOM 획득'(크롬 Save As)은 loader 가, '다음 페이지 차단 감지'는 cli 가 crawlers 에서 배선.
    (v5.0: 안티봇 Save As 전환이 cli→loader.py 로 이관됨.)"""
    import cli
    import loader
    import crawlers.chrome as chrome
    import crawlers.base as base
    assert loader.chrome_save_as_fetch is chrome.chrome_save_as_fetch   # 차단 시 내 크롬 수신 = loader
    assert cli.block_reason is base.block_reason                        # 페이지네이션 차단 감지 = cli


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("PASS", _n)
    print("ok")

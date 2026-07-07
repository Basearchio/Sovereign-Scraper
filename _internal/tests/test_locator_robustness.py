# -*- coding: utf-8 -*-
"""tests/test_locator_robustness.py — 구조 경로(rel_path/follow_path)가 '형제 밀림'에 강한지 골든.
동기: Gmail 대화 메일은 발신처와 제목 사이에 '메시지 개수 뱃지' span 을 끼워 넣어, 절대 index 로만
저장한 제목/날짜가 한 칸씩 밀렸다. 형제-유일 class 앵커 + 팬텀(삽입된) 형제 제거로 밀림을 흡수한다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lxml import html as lh
from structure import rel_path, follow_path


def _row(html):
    return lh.fragment_fromstring(html)


def test_class_anchor_survives_inserted_sibling():
    # 학습(단일): [발신처, 제목, 날짜]  — 제목 span 은 형제 내 유일 class 'su'
    single = _row('<div><span class="se">S</span><span class="su">Subj</span>'
                  '<span class="da">7/1</span></div>')
    p = rel_path(single, single.xpath('.//span[@class="su"]')[0])
    # 추출(대화): 발신처 뒤에 개수 뱃지 span.cnt 가 삽입 → index 는 밀렸지만 class 앵커로 정확
    thread = _row('<div><span class="se">S</span><span class="cnt">2</span>'
                  '<span class="su">RealSubj</span><span class="da">6/1</span></div>')
    got = follow_path(thread, p)
    assert got is not None and got.text == "RealSubj"


def test_phantom_filter_recovers_classless_target():
    # 제목/날짜 span 에 class 가 아예 없는 경우(Gmail 인증코드 대화) — 앵커 불가.
    single = _row('<div><span class="se">S</span><span>Subj</span><span>7/1</span></div>')
    p_subj = rel_path(single, single.xpath('.//span')[1])
    p_date = rel_path(single, single.xpath('.//span')[2])
    # 삽입된 뱃지 span.cnt 는 '학습에 없던 class' → 팬텀으로 제외한 뒤 index → 제목/날짜 정확
    thread = _row('<div><span class="se">S</span><span class="cnt">2</span>'
                  '<span>RealSubj</span><span>6/1</span></div>')
    assert follow_path(thread, p_subj).text == "RealSubj"
    assert follow_path(thread, p_date).text == "6/1"


def test_rel_path_records_anchor_and_sibling_classes():
    row = _row('<div><span class="x">a</span><span class="y">b</span></div>')
    p = rel_path(row, row.xpath('.//span[@class="y"]')[0])
    tag, idx, uniq, sib = p[-1]
    assert (tag, idx) == ("span", 1)
    assert uniq == "y"                       # 형제-유일 class
    assert set(sib) == {"x", "y"}            # 학습 당시 형제 class 집합


def test_rel_path_two_tuple_when_no_classes():
    row = _row('<div><span>a</span><span>b</span></div>')
    assert rel_path(row, row.xpath('.//span')[1]) == [("span", 1)]


def test_backward_compat_plain_index():
    row = _row('<div><span>a</span><span>b</span><span>c</span></div>')
    assert follow_path(row, [("span", 1)]).text == "b"          # 구버전 2-튜플
    assert follow_path(row, [("span", 9)]) is None              # 범위 밖 → None


def test_ambiguous_class_falls_back_to_filtered_index():
    # 같은 class 가 형제에 둘 → 앵커 불가(uniq None). 팬텀 없으면 그냥 index.
    single = _row('<div><span class="a">x</span><span class="a">y</span></div>')
    p = rel_path(single, single.xpath('.//span')[1])
    assert p[-1][2] is None                                     # uniq 없음
    same = _row('<div><span class="a">x</span><span class="a">y</span></div>')
    assert follow_path(same, p).text == "y"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f(); print("PASS", _n)
    print("ok")

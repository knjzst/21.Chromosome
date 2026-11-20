import math

from lowdarts import board as B
from lowdarts.game import X01, checkout, parse_label


def test_scoring_basics():
    assert B.score_point(0, 0).label == "BULL"
    assert B.score_point(0, 10).label == "25"
    assert B.score_point(0, 103).label == "T20"
    assert B.score_point(0, -166).label == "D3"
    assert B.score_point(103, 0).label == "T6"
    assert B.score_point(-60, 0).label == "S11"
    assert B.score_point(0, 175).label == "MISS"


def test_every_sector_centre():
    for n in B.SECTORS:
        x, y = B.polar(130, B.sector_angle(n))
        assert B.score_point(x, y).sector == n


def test_parse_label():
    assert parse_label("t20").score == 60
    assert parse_label("D16").score == 32
    assert parse_label("bull").score == 50
    assert parse_label("25").score == 25
    assert parse_label("miss").score == 0
    assert parse_label("7").score == 7


def test_x01_bust_and_double_out():
    g = X01(["A", "B"], start=40)
    g.throw(parse_label("S20"))
    g.throw(parse_label("S19"))     # 1 left -> bust with double out
    assert g.bust and g.player.score == 40
    g.next_player()
    assert g.player.name == "B"
    g.throw(parse_label("S20"))
    g.throw(parse_label("D10"))
    assert g.winner == "B"


def test_x01_single_finish_is_bust():
    g = X01(["A"], start=20)
    g.throw(parse_label("S20"))
    assert g.bust and g.player.score == 20


def test_correct_and_undo():
    g = X01(["A"], start=501)
    for l in ("T20", "T20", "S1"):
        g.throw(parse_label(l))
    assert g.player.score == 501 - 121
    g.correct(2, parse_label("T20"))
    assert g.player.score == 501 - 180
    g.undo()
    assert g.player.score == 501 - 120 and len(g.turn) == 2


def test_checkout():
    assert checkout(170, 3) == "T20 T20 BULL"
    assert checkout(40, 1) == "D20"
    assert checkout(159, 3) == ""
    assert checkout(1, 3) == ""

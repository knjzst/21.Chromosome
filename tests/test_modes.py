from lowdarts.bot import Bot
from lowdarts.game import parse_label as P
from lowdarts.modes import create


def play(g, labels):
    for l in labels:
        if l == "|":
            g.next_turn()
        else:
            g.throw(P(l))


def test_x01_legs_sets_and_rotation():
    g = create("x01", ["A", "B"], start=101, legs=2)
    play(g, ["T20", "S1", "D20"])          # A checks 101 -> leg 1
    s = g.state()
    assert s["players"][0]["legs"] == 1 and "leg_won" in s["events"]
    g.next_turn()                           # new leg, B starts
    assert g.state()["current"] == 1 and g.state()["players"][0]["score"] == 101
    play(g, ["S1", "S1", "S1", "|", "T20", "S1", "D20"])  # A wins leg 2 -> match
    assert g.state()["winner"] == 0 and "match_won" in g.state()["events"]


def test_x01_double_in_and_master_out():
    g = create("x01", ["A"], start=60, in_mode="double", out_mode="master")
    play(g, ["S20", "D10"])                 # S20 does not open
    assert g.state()["players"][0]["score"] == 40
    play(g, ["|", "T20"])                   # 40 left -> T20 busts (over)
    assert g.state()["bust"]
    play(g, ["|", "S10", "T10"])            # master out with treble
    assert g.state()["winner"] == 0


def test_x01_180_event_and_average():
    g = create("x01", ["A", "B"])
    play(g, ["T20", "T20", "T20"])
    s = g.state()
    assert "180" in s["events"] and s["players"][0]["avg"] == 180.0


def test_cricket_scoring_and_win():
    g = create("cricket", ["A", "B"])
    play(g, ["T20", "T20", "T19", "|", "S1", "S1", "S1", "|"])
    s = g.state()
    assert s["players"][0]["marks"]["20"] == 3 and s["players"][0]["score"] == 60
    assert s["players"][0]["marks"]["19"] == 3
    for t in ("T18", "T17", "T16", "|", "S1", "S1", "S1", "|", "T15", "BULL", "25"):
        g.next_turn() if t == "|" else g.throw(P(t))
    assert g.state()["winner"] == 0


def test_cricket_cutthroat_gives_points_to_opponent():
    g = create("cricket", ["A", "B"], scoring="cutthroat")
    play(g, ["T20", "T20"])
    s = g.state()
    assert s["players"][1]["score"] == 60 and s["players"][0]["score"] == 0


def test_around_the_clock():
    g = create("atc", ["A"])
    for n in range(1, 21):
        g.throw(P(f"S{n}"))
        if g.state()["turn_done"]:
            g.next_turn()
    g.throw(P("25"))
    assert g.state()["winner"] == 0


def test_bobs27():
    g = create("bobs27", ["A"])
    play(g, ["D1", "D1", "S1", "|"])        # +4
    assert g.state()["players"][0]["score"] == 31
    play(g, ["S2", "S2", "S2", "|"])        # -4
    assert g.state()["players"][0]["score"] == 27


def test_shanghai_instant_win():
    g = create("shanghai", ["A", "B"])
    play(g, ["S1", "D1", "T1"])
    assert g.state()["winner"] == 0


def test_correct_and_undo_generic():
    g = create("countup", ["A"])
    play(g, ["S1", "S1", "S1"])
    g.correct(1, P("T20"))
    assert g.state()["players"][0]["score"] == 62
    g.undo()
    assert g.state()["players"][0]["score"] == 61  # last dart removed


def test_bot_levels_are_ordered():
    def avg(level):
        b, scores = Bot(level, seed=3), []
        for _ in range(15):
            g = create("x01", ["B"])
            n = 0
            while not g.finished and n < 500:
                s = g.state()
                g.next_turn() if s["turn_done"] else g.throw(b.next_dart(s))
                n += 1
            scores.append(g.state()["players"][0]["avg"])
        return sum(scores) / len(scores)
    a1, a6, a11 = avg(1), avg(6), avg(11)
    assert 10 < a1 < 35 < a6 < 90 < a11

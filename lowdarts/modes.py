"""Game modes.

Every mode shares the same flow so that the UI, the detector and the sound
system can treat them alike:

    game.throw(hit)      one dart (from the camera, the virtual board or keypad)
    game.next_turn()     darts pulled / "Next" pressed
    game.correct(i, hit) replace dart i of the current turn
    game.undo()          undo the last action
    game.state()         JSON for the UI (includes `events` for sounds/caller)
"""
from __future__ import annotations

import copy
import random

from .board import Hit
from .game import checkout

# --------------------------------------------------------------------------
# base


class BaseGame:
    mode = "base"
    title = "Spiel"
    darts_per_turn = 3

    def __init__(self, players: list[str], max_rounds: int = 0, **_):
        if not players:
            players = ["Spieler 1"]
        self.players = [p.strip() or f"Spieler {i + 1}" for i, p in enumerate(players)]
        self.n = len(self.players)
        self.current = 0
        self.turn: list[Hit] = []
        self.turn_done = False
        self.round = 1
        self.max_rounds = int(max_rounds or 0)
        self.winner: int | None = None
        self.events: list[str] = []
        self.message = ""
        self.darts = [0] * self.n
        self.history: list[dict] = []

    # -- undo machinery ----------------------------------------------------
    def _save(self):
        snap = {k: copy.deepcopy(v) for k, v in self.__dict__.items() if k != "history"}
        self.history.append(snap)
        if len(self.history) > 300:
            self.history.pop(0)

    def undo(self):
        if self.history:
            self.__dict__.update(self.history.pop())
            self.events = ["undo"]

    @property
    def finished(self) -> bool:
        return self.winner is not None

    # -- flow ----------------------------------------------------------------
    def throw(self, hit: Hit):
        if self.finished or self.turn_done:
            return
        self._save()
        self.events = ["dart", hit_event(hit)]
        self.message = ""
        self.turn.append(hit)
        self.darts[self.current] += 1
        self._apply(hit)
        if not self.turn_done and not self.finished and len(self.turn) >= self.darts_per_turn:
            self.turn_done = True
            self._turn_complete()

    def next_turn(self):
        if self.finished:
            return
        self._save()
        self.events = ["next"]
        self.message = ""
        missing = self.darts_per_turn - len(self.turn)
        if missing > 0 and not self.turn_done:
            self.darts[self.current] += missing
            self._turn_complete()
        self._advance()

    def _advance(self):
        self.turn = []
        self.turn_done = False
        self.current = (self.current + 1) % self.n
        if self.current == self._round_starter():
            self.round += 1
            if self.max_rounds and self.round > self.max_rounds:
                self._out_of_rounds()
                return
            self._new_round()

    def correct(self, index: int, hit: Hit):
        if not (0 <= index < len(self.turn)):
            raise IndexError(index)
        darts = list(self.turn)
        darts[index] = hit
        for _ in range(len(self.turn)):
            self.undo()
        for h in darts:
            self.throw(h)
        self.events = ["correct"] + [e for e in self.events if e not in ("dart",)]

    # -- hooks ---------------------------------------------------------------
    def _round_starter(self) -> int:
        return 0

    def _apply(self, hit: Hit):
        raise NotImplementedError

    def _turn_complete(self):
        pass

    def _new_round(self):
        pass

    def _out_of_rounds(self):
        best = max(range(self.n), key=lambda i: self.ranking_key(i))
        self._win(best)

    def ranking_key(self, i):
        return 0

    def _win(self, i: int):
        self.winner = i
        self.turn_done = True
        self.events.append("match_won")
        self.message = f"{self.players[i]} gewinnt!"

    # -- state -----------------------------------------------------------------
    def player_state(self, i: int) -> dict:
        return {}

    def extra_state(self) -> dict:
        return {}

    def state(self) -> dict:
        return {
            "mode": self.mode,
            "title": self.title,
            "round": self.round,
            "max_rounds": self.max_rounds,
            "current": self.current,
            "turn": [h.to_dict() for h in self.turn],
            "turn_done": self.turn_done,
            "winner": self.winner,
            "message": self.message,
            "events": list(self.events),
            "players": [{"name": p, "darts": self.darts[i], **self.player_state(i)}
                        for i, p in enumerate(self.players)],
            **self.extra_state(),
        }


def hit_event(h: Hit) -> str:
    if h.multiplier == 0:
        return "miss"
    if h.sector == 25:
        return "bull" if h.multiplier == 2 else "outer_bull"
    return {1: "single", 2: "double", 3: "triple"}[h.multiplier]


# --------------------------------------------------------------------------
# X01

def _fits(hit: Hit, mode: str) -> bool:
    if mode == "straight":
        return hit.multiplier > 0
    if mode == "double":
        return hit.multiplier == 2
    return hit.multiplier in (2, 3)  # master


_SINGLE_VALUES = set(range(1, 21)) | {25}
_DOUBLE_VALUES = {2 * n for n in range(1, 21)} | {50}
_TRIPLE_VALUES = {3 * n for n in range(1, 21)}


def one_dart_finish(score: int, out_mode: str) -> bool:
    if out_mode == "double":
        return score in _DOUBLE_VALUES
    if out_mode == "master":
        return score in _DOUBLE_VALUES | _TRIPLE_VALUES
    return score in _SINGLE_VALUES | _DOUBLE_VALUES | _TRIPLE_VALUES


class X01(BaseGame):
    mode = "x01"

    def __init__(self, players, start=501, in_mode="straight", out_mode="double",
                 legs=1, sets=1, max_rounds=0, **kw):
        super().__init__(players, max_rounds=max_rounds)
        self.start = int(start)
        self.title = f"{self.start}"
        self.in_mode, self.out_mode = in_mode, out_mode
        self.legs_to_win, self.sets_to_win = max(1, int(legs)), max(1, int(sets))
        self.scores = [self.start] * self.n
        self.opened = [in_mode == "straight"] * self.n
        self.legs = [0] * self.n
        self.sets = [0] * self.n
        self.points = [0] * self.n        # for the 3-dart average
        self.leg_darts = [0] * self.n
        self.first9 = [[0, 0] for _ in range(self.n)]  # points, darts
        self.high = [0] * self.n
        self.tons = [{"60": 0, "100": 0, "140": 0, "180": 0} for _ in range(self.n)]
        self.checkout_tries = [0] * self.n
        self.checkouts = [0] * self.n
        self.best_finish = [0] * self.n
        self.leg_starter = 0
        self.turn_start = self.start
        self.bust = False
        self.leg_over = False

    def _round_starter(self):
        return self.leg_starter

    def _min_left(self):
        return 1 if self.out_mode == "straight" else 2

    def _apply(self, hit):
        i = self.current
        self.leg_darts[i] += 1
        before = self.scores[i]
        if self.opened[i] and one_dart_finish(before, self.out_mode):
            self.checkout_tries[i] += 1
        if not self.opened[i]:
            if _fits(hit, self.in_mode):
                self.opened[i] = True
            else:
                self._count_first9(i, 0)
                return
        new = before - hit.score
        if new < 0 or 0 < new < self._min_left() or (new == 0 and not _fits(hit, self.out_mode)):
            self._bust()
            return
        self.scores[i] = new
        self.points[i] += hit.score
        self._count_first9(i, hit.score)
        if new == 0:
            self._leg_won(i)

    def _count_first9(self, i, pts):
        if self.first9[i][1] < 9 and self.leg_darts[i] <= 9:
            self.first9[i][0] += pts
            self.first9[i][1] += 1

    def _bust(self):
        i = self.current
        self.points[i] -= self.turn_start - self.scores[i]
        self.scores[i] = self.turn_start
        self.bust = True
        self.turn_done = True
        self.events.append("bust")
        self.message = "BUST"

    def _turn_total(self):
        return 0 if self.bust else self.turn_start - self.scores[self.current]

    def _turn_complete(self):
        i = self.current
        t = self._turn_total()
        self.high[i] = max(self.high[i], t)
        for k in ("180", "140", "100", "60"):
            if t >= int(k):
                self.tons[i][k] += 1
                break
        if not self.bust and not self.leg_over:
            ev = score_event(t)
            if ev:
                self.events.append(ev)

    def _leg_won(self, i):
        t = self._turn_total()
        self.checkouts[i] += 1
        self.best_finish[i] = max(self.best_finish[i], t)
        self._turn_complete()
        self.leg_over = True
        self.turn_done = True
        self.legs[i] += 1
        self.events.append("checkout")
        self.message = f"Game shot! {self.players[i]} checkt {t}"
        if self.legs[i] >= self.legs_to_win:
            self.sets[i] += 1
            if self.sets[i] >= self.sets_to_win:
                self._win(i)
                return
            if self.sets_to_win > 1:
                self.events.append("set_won")
                self.legs = [0] * self.n
        self.events.append("leg_won")

    def _advance(self):
        if self.leg_over:
            self.leg_over = False
            self.leg_starter = (self.leg_starter + 1) % self.n
            self.scores = [self.start] * self.n
            self.opened = [self.in_mode == "straight"] * self.n
            self.leg_darts = [0] * self.n
            self.turn = []
            self.turn_done = False
            self.bust = False
            self.round = 1
            self.current = self.leg_starter
            self.turn_start = self.start
            self.events.append("leg_start")
            return
        super()._advance()
        self.bust = False
        self.turn_start = self.scores[self.current] if not self.finished else 0

    def _out_of_rounds(self):
        best = min(range(self.n), key=lambda i: self.scores[i])
        self._win(best)

    def player_state(self, i):
        avg = 3 * self.points[i] / self.darts[i] if self.darts[i] else 0
        f9 = 3 * self.first9[i][0] / self.first9[i][1] if self.first9[i][1] else 0
        co = 100 * self.checkouts[i] / self.checkout_tries[i] if self.checkout_tries[i] else 0
        left = self.scores[i]
        darts_left = 3 - len(self.turn) if i == self.current else 3
        return {"score": left, "legs": self.legs[i], "sets": self.sets[i],
                "avg": round(avg, 1), "first9": round(f9, 1), "high": self.high[i],
                "tons": self.tons[i], "checkout_pct": round(co, 1),
                "best_finish": self.best_finish[i], "opened": self.opened[i],
                "checkout": checkout(left, darts_left, self.out_mode != "straight")
                if self.opened[i] and left <= 170 else ""}

    def extra_state(self):
        return {"bust": self.bust, "turn_total": self._turn_total(),
                "legs_to_win": self.legs_to_win, "sets_to_win": self.sets_to_win,
                "in_mode": self.in_mode, "out_mode": self.out_mode, "start": self.start}


def score_event(t: int) -> str:
    if t == 180:
        return "180"
    if t >= 140:
        return "ton40"
    if t >= 100:
        return "ton"
    if t == 26:
        return "bed_and_breakfast"
    if t == 0:
        return "zero"
    if t < 20:
        return "low"
    return ""


# --------------------------------------------------------------------------
# Cricket / Tactics

class Cricket(BaseGame):
    mode = "cricket"

    def __init__(self, players, variant="cricket", scoring="standard", max_rounds=20, **kw):
        super().__init__(players, max_rounds=max_rounds)
        self.variant, self.scoring = variant, scoring
        if variant == "tactics":
            self.targets = list(range(10, 21)) + [25]
            self.title = "Tactics"
        else:
            self.targets = list(range(15, 21)) + [25]
            self.title = "Cricket"
        if scoring == "cutthroat":
            self.title += " Cut-Throat"
        elif scoring == "noscore":
            self.title += " No Score"
        self.marks = [{t: 0 for t in self.targets} for _ in range(self.n)]
        self.points = [0] * self.n
        self.total_marks = [0] * self.n
        self.turn_marks = 0

    def _closed_by_all_others(self, t):
        return all(self.marks[j][t] >= 3 for j in range(self.n) if j != self.current)

    def _apply(self, hit):
        i = self.current
        t = hit.sector
        if t not in self.marks[i] or hit.multiplier == 0:
            return
        m = hit.multiplier
        self.total_marks[i] += m
        self.turn_marks += m
        had = self.marks[i][t]
        need = max(0, 3 - had)
        self.marks[i][t] = min(3, had + m)
        extra = m - need if m > need else 0
        if had < 3 <= self.marks[i][t]:
            self.events.append("closed")
        if extra and self.scoring != "noscore" and not self._closed_by_all_others(t):
            pts = extra * t
            if self.scoring == "cutthroat":
                for j in range(self.n):
                    if j != i and self.marks[j][t] < 3:
                        self.points[j] += pts
            else:
                self.points[i] += pts
        self._check_win()

    def _check_win(self):
        i = self.current
        if any(v < 3 for v in self.marks[i].values()):
            return
        others = [self.points[j] for j in range(self.n) if j != i]
        if self.scoring == "cutthroat":
            ok = all(self.points[i] <= p for p in others)
        elif self.scoring == "noscore":
            ok = True
        else:
            ok = all(self.points[i] >= p for p in others)
        if ok:
            self._win(i)

    def _turn_complete(self):
        if self.turn_marks >= 9:
            self.events.append("white_horse" if len({h.sector for h in self.turn}) == 3 else "nine_marks")
        elif self.turn_marks >= 5:
            self.events.append("ton")
        elif self.turn_marks == 0:
            self.events.append("zero")

    def _advance(self):
        self.turn_marks = 0
        super()._advance()

    def ranking_key(self, i):
        closed = sum(v >= 3 for v in self.marks[i].values())
        pts = -self.points[i] if self.scoring == "cutthroat" else self.points[i]
        return (pts, closed, sum(self.marks[i].values()))

    def player_state(self, i):
        rounds = max(1, self.darts[i] / 3)
        return {"marks": {str(k): v for k, v in self.marks[i].items()},
                "score": self.points[i], "mpr": round(self.total_marks[i] / rounds, 2)
                if self.darts[i] else 0.0}

    def extra_state(self):
        return {"targets": self.targets, "scoring": self.scoring,
                "open_targets": [t for t in self.targets
                                 if not all(self.marks[j][t] >= 3 for j in range(self.n))]}


# --------------------------------------------------------------------------
# practice & party

ORDER_UP = list(range(1, 21)) + [25]


class AroundTheClock(BaseGame):
    mode = "atc"
    title = "Around the Clock"

    def __init__(self, players, ring="any", order="up", hits_needed=1, **kw):
        super().__init__(players)
        self.ring = ring
        seq = list(range(1, 21))
        if order == "down":
            seq = seq[::-1]
        elif order == "random":
            random.shuffle(seq)
        self.seq = seq + [25]
        self.hits_needed = max(1, int(hits_needed))
        self.pos = [0] * self.n
        self.hit_count = [0] * self.n
        self.hits = [0] * self.n

    def target(self, i):
        return self.seq[min(self.pos[i], len(self.seq) - 1)]

    def _counts(self, hit):
        if hit.multiplier == 0:
            return False
        if hit.sector == 25:
            return True
        return {"any": True, "single": hit.multiplier == 1, "double": hit.multiplier == 2,
                "triple": hit.multiplier == 3}[self.ring]

    def _apply(self, hit):
        i = self.current
        if hit.sector == self.target(i) and self._counts(hit):
            self.hits[i] += 1
            self.hit_count[i] += 1
            self.events.append("hit")
            if self.hit_count[i] >= self.hits_needed:
                self.hit_count[i] = 0
                self.pos[i] += 1
                if self.pos[i] >= len(self.seq):
                    self._win(i)

    def ranking_key(self, i):
        return (self.pos[i], -self.darts[i])

    def player_state(self, i):
        done = self.pos[i] >= len(self.seq)
        return {"target": None if done else self.target(i), "progress": self.pos[i],
                "total": len(self.seq), "score": self.pos[i],
                "hit_rate": round(100 * self.hits[i] / self.darts[i], 1) if self.darts[i] else 0}

    def extra_state(self):
        return {"sequence": self.seq, "ring": self.ring}


class Bobs27(BaseGame):
    mode = "bobs27"
    title = "Bob's 27"

    def __init__(self, players, allow_negative=False, **kw):
        super().__init__(players, max_rounds=21)
        self.allow_negative = bool(allow_negative)
        self.scores = [27] * self.n
        self.out = [False] * self.n
        self.turn_hits = 0

    def target(self):
        return 25 if self.round >= 21 else self.round

    def _apply(self, hit):
        t = self.target()
        if hit.sector == t and hit.multiplier == 2:
            self.turn_hits += 1
            self.scores[self.current] += 2 * t
            self.events.append("hit")

    def _turn_complete(self):
        i = self.current
        if self.turn_hits == 0:
            self.scores[i] -= 2 * self.target()
            self.events.append("zero")
            if self.scores[i] <= 0 and not self.allow_negative:
                self.out[i] = True
                self.events.append("knocked_out")
        elif self.turn_hits == 3:
            self.events.append("ton40")

    def _advance(self):
        self.turn_hits = 0
        if all(self.out):
            self._out_of_rounds()
            return
        super()._advance()
        guard = 0
        while not self.finished and self.out[self.current] and guard < self.n:
            self.turn, self.turn_done = [], False
            super()._advance()
            guard += 1

    def ranking_key(self, i):
        return self.scores[i]

    def player_state(self, i):
        return {"score": self.scores[i], "out": self.out[i]}

    def extra_state(self):
        t = self.target()
        return {"target": t, "target_label": "BULL" if t == 25 else f"D{t}"}


class CountUp(BaseGame):
    mode = "countup"
    title = "Count Up"

    def __init__(self, players, rounds=8, **kw):
        super().__init__(players, max_rounds=int(rounds))
        self.scores = [0] * self.n
        self.turn_pts = 0

    def _apply(self, hit):
        self.scores[self.current] += hit.score
        self.turn_pts += hit.score

    def _turn_complete(self):
        ev = score_event(self.turn_pts)
        if ev:
            self.events.append(ev)

    def _advance(self):
        self.turn_pts = 0
        super()._advance()

    def ranking_key(self, i):
        return self.scores[i]

    def player_state(self, i):
        return {"score": self.scores[i],
                "avg": round(3 * self.scores[i] / self.darts[i], 1) if self.darts[i] else 0}


class Shanghai(BaseGame):
    mode = "shanghai"
    title = "Shanghai"

    def __init__(self, players, rounds=7, **kw):
        super().__init__(players, max_rounds=int(rounds))
        self.scores = [0] * self.n
        self.turn_mults: set[int] = set()

    def _apply(self, hit):
        if hit.sector == self.round and hit.multiplier:
            self.scores[self.current] += hit.score
            self.turn_mults.add(hit.multiplier)
            self.events.append("hit")
            if self.turn_mults == {1, 2, 3}:
                self.events.append("shanghai")
                self._win(self.current)

    def _advance(self):
        self.turn_mults = set()
        super()._advance()

    def ranking_key(self, i):
        return self.scores[i]

    def player_state(self, i):
        return {"score": self.scores[i]}

    def extra_state(self):
        return {"target": self.round}


MODES = {
    "x01": X01, "cricket": Cricket, "atc": AroundTheClock,
    "bobs27": Bobs27, "countup": CountUp, "shanghai": Shanghai,
}


def create(mode: str, players: list[str], **opts) -> BaseGame:
    cls = MODES.get(mode)
    if cls is None:
        raise KeyError(f"unknown mode {mode}")
    return cls(players, **opts)

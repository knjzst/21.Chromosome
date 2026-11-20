"""X01 game logic (301/501/..., optional double-in/out, undo, corrections)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .board import Hit


def parse_label(label: str) -> Hit:
    """'T20', 'D16', 'S5', '20', '25', 'BULL', 'MISS' -> Hit."""
    s = label.strip().upper()
    if s in ("MISS", "M", "0", "S0"):
        return Hit(0, 0)
    if s in ("BULL", "DB", "D25", "50"):
        return Hit(25, 2)
    if s in ("25", "SB", "S25"):
        return Hit(25, 1)
    mult = 1
    if s[0] in "SDT":
        mult = {"S": 1, "D": 2, "T": 3}[s[0]]
        s = s[1:]
    n = int(s)
    if not (1 <= n <= 20):
        raise ValueError(label)
    return Hit(n, mult)


@dataclass
class Player:
    name: str
    score: int
    legs: int = 0
    darts_thrown: int = 0
    points_scored: int = 0

    @property
    def average(self) -> float:
        return 3 * self.points_scored / self.darts_thrown if self.darts_thrown else 0.0


@dataclass
class X01:
    players: list[str] = field(default_factory=lambda: ["Spieler 1"])
    start: int = 501
    double_out: bool = True
    double_in: bool = False

    def __post_init__(self):
        self.ps = [Player(n, self.start) for n in self.players]
        self.current = 0
        self.turn: list[Hit] = []
        self.turn_start_score = self.start
        self.opened = [not self.double_in] * len(self.ps)
        self.winner: str | None = None
        self.bust = False
        self.history: list[tuple] = []   # snapshots for undo
        self.message = ""

    # -- helpers ------------------------------------------------------------
    def _snapshot(self):
        p = [(x.score, x.legs, x.darts_thrown, x.points_scored) for x in self.ps]
        return (p, self.current, list(self.turn), self.turn_start_score,
                list(self.opened), self.winner, self.bust, self.message)

    def _restore(self, snap):
        p, self.current, self.turn, self.turn_start_score, self.opened, \
            self.winner, self.bust, self.message = snap
        for pl, (s, l, d, pts) in zip(self.ps, p):
            pl.score, pl.legs, pl.darts_thrown, pl.points_scored = s, l, d, pts

    @property
    def player(self) -> Player:
        return self.ps[self.current]

    @property
    def turn_complete(self) -> bool:
        return self.bust or self.winner is not None or len(self.turn) >= 3

    # -- actions ------------------------------------------------------------
    def throw(self, hit: Hit):
        if self.winner or self.turn_complete:
            return
        self.history.append(self._snapshot())
        p = self.player
        self.turn.append(hit)
        p.darts_thrown += 1
        self.message = ""
        if not self.opened[self.current]:
            if hit.multiplier == 2:
                self.opened[self.current] = True
            else:
                return
        new = p.score - hit.score
        min_left = 2 if self.double_out else 1
        if new < 0 or (0 < new < min_left):
            self._bust()
            return
        if new == 0:
            if self.double_out and hit.multiplier != 2:
                self._bust()
                return
            p.score = 0
            p.points_scored += hit.score
            p.legs += 1
            self.winner = p.name
            self.message = f"{p.name} gewinnt!"
            return
        p.score = new
        p.points_scored += hit.score

    def _bust(self):
        p = self.player
        p.points_scored -= (self.turn_start_score - p.score)
        p.score = self.turn_start_score
        self.bust = True
        self.message = "BUST"

    def next_player(self):
        """Called when darts are pulled (takeout) or manually."""
        if self.winner:
            return
        self.history.append(self._snapshot())
        # missing darts count as thrown (misses)
        if not self.bust:
            self.player.darts_thrown += 3 - len(self.turn)
        self.current = (self.current + 1) % len(self.ps)
        self.turn = []
        self.bust = False
        self.turn_start_score = self.player.score
        self.message = ""

    def correct(self, index: int, hit: Hit):
        """Replace dart `index` of the current turn and re-score the turn."""
        if not (0 <= index < len(self.turn)):
            raise IndexError(index)
        darts = list(self.turn)
        darts[index] = hit
        # rewind to start of turn
        while self.history and (self.turn or self.bust or self.winner):
            self._restore(self.history.pop())
        for h in darts:
            self.throw(h)

    def undo(self):
        if self.history:
            self._restore(self.history.pop())

    def checkout_hint(self) -> str:
        return checkout(self.player.score, 3 - len(self.turn), self.double_out)

    def state(self) -> dict:
        return {
            "mode": f"{self.start}",
            "double_out": self.double_out,
            "players": [{"name": p.name, "score": p.score, "legs": p.legs,
                         "avg": round(p.average, 1)} for p in self.ps],
            "current": self.current,
            "turn": [h.to_dict() for h in self.turn],
            "turn_total": sum(h.score for h in self.turn) if not self.bust else 0,
            "bust": self.bust,
            "winner": self.winner,
            "message": self.message,
            "checkout": self.checkout_hint() if not self.winner else "",
        }


# --------------------------------------------------------------------------
_SINGLES = [(f"S{n}", n) for n in range(1, 21)] + [("25", 25)]
_DOUBLES = [(f"D{n}", 2 * n) for n in range(1, 21)] + [("BULL", 50)]
_TRIPLES = [(f"T{n}", 3 * n) for n in range(1, 21)]
_ANY = sorted(_TRIPLES + _SINGLES + _DOUBLES, key=lambda t: -t[1])


def checkout(score: int, darts: int, double_out: bool = True) -> str:
    """Simple checkout suggestion (prefers big first darts, finishing double)."""
    if darts <= 0 or score <= 1 and double_out or score <= 0:
        return ""
    finals = _DOUBLES if double_out else _ANY
    pref = ["D20", "D16", "D18", "D12", "D10", "D8", "BULL"]
    finals = sorted(finals, key=lambda f: pref.index(f[0]) if f[0] in pref else 99)
    for f, v in finals:
        if v == score:
            return f
    if darts >= 2:
        for a, va in _ANY:
            for f, v in finals:
                if va + v == score:
                    return f"{a} {f}"
    if darts >= 3:
        for a, va in _ANY:
            for b, vb in _ANY:
                for f, v in finals:
                    if va + vb + v == score:
                        return f"{a} {b} {f}"
    return ""

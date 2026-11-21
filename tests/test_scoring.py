"""Scoring-Tests: python -m pytest tests/ bzw. python tests/test_scoring.py"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chromosome.config import Config
from chromosome.scoring import score_point


def cfg():
    return Config(Path(__file__).resolve().parent.parent / "config.toml")


def test_bull():
    assert score_point(0, 0, cfg()).label == "BULL"
    assert score_point(10, 0, cfg()).label == "25"


def test_t20_oben():
    s = score_point(0, 103, cfg())
    assert s.label == "T20" and s.value == 60


def test_d3_unten():
    s = score_point(0, -166, cfg())
    assert s.label == "D3" and s.value == 6


def test_s6_rechts():
    s = score_point(130, 0, cfg())
    assert s.label == "6" and s.value == 6


def test_s11_links():
    s = score_point(-130, 0, cfg())
    assert s.label == "11"


def test_miss():
    assert score_point(0, 200, cfg()).label == "MISS"


def test_segmentgrenze_20_1():
    # 9° rechts von oben = Grenze 20/1; knapp darunter noch 20, knapp darüber 1
    r = 130.0
    for deg, exp in [(8.9, "20"), (9.1, "1"), (-8.9, "20"), (-9.1, "5")]:
        a = math.radians(deg)
        s = score_point(r * math.sin(a), r * math.cos(a), cfg())
        assert s.label == exp, f"{deg}°: {s.label} != {exp}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK  {name}")

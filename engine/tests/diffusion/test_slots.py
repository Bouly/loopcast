"""Placement des créneaux : fenêtres, écart minimal, répartition, déterminisme."""

import random

from loopcast.diffusion.settings import intersect, parse_windows
from loopcast.diffusion.slots import Span, free_spans, nearest, place, rng_for

WINDOWS = parse_windows(["07:30-09:00", "12:00-14:00", "18:00-22:30"])


def inside(m: int, windows) -> bool:
    return any(s <= m <= e for s, e in windows)


def test_one_slot_per_window_first():
    slots = place(free_spans(WINDOWS), 3, 180, rng_for("phone-1:tiktok", "2026-11-16"))
    assert len(slots) == 3
    assert [next(i for i, (s, e) in enumerate(WINDOWS) if s <= m <= e) for m in slots] == [0, 1, 2]


def test_two_slots_go_to_the_roomiest_windows():
    slots = place(free_spans(WINDOWS), 2, 180, random.Random(1))
    assert all(inside(m, WINDOWS[1:]) for m in slots)        # midi et soir, pas le matin (le plus court)


def test_min_gap_and_windows_hold_for_any_seed():
    for seed in range(300):
        for n in range(1, 6):
            slots = place(free_spans(WINDOWS), n, 180, random.Random(seed), jitter=40)
            assert all(inside(m, WINDOWS) for m in slots)
            assert all(b - a >= 180 for a, b in zip(slots, slots[1:]))
            assert len(slots) == min(n, 4)                     # 5 posts espacés de 3 h ne tiennent pas


def test_same_seed_same_slots_other_day_other_slots():
    a = place(free_spans(WINDOWS), 3, 180, rng_for("phone-1:tiktok", "2026-11-16"))
    b = place(free_spans(WINDOWS), 3, 180, rng_for("phone-1:tiktok", "2026-11-16"))
    c = place(free_spans(WINDOWS), 3, 180, rng_for("phone-1:tiktok", "2026-11-17"))
    d = place(free_spans(WINDOWS), 3, 180, rng_for("phone-2:tiktok", "2026-11-16"))
    assert a == b and a != c and a != d


def test_jitter_is_bounded():
    for seed in range(50):
        m = place([Span(720, 840)], 1, 180, random.Random(seed), jitter=20)[0]
        assert 760 <= m <= 800                                  # 13:00 ± 20 min


def test_free_spans_respect_past_and_existing_posts():
    spans = free_spans(WINDOWS, not_before=12 * 60 + 30, taken=[19 * 60], gap=180)
    # midi après 12:30 ; le soir seulement à 3 h de 19:00 ou plus (22:00-22:30)
    assert [(s.start, s.end) for s in spans] == [(750, 840), (1320, 1350)]
    assert free_spans(WINDOWS, not_before=23 * 60) == []


def test_existing_posts_count_for_the_spread():
    spans = free_spans(WINDOWS, taken=[13 * 60], gap=180)
    slots = place(spans, 1, 180, random.Random(3), load={1: 1})
    assert inside(slots[0], [WINDOWS[2]])                      # le soir, pas un 2e à midi


def test_nearest_prefers_later():
    spans = [Span(100, 200), Span(400, 500)]
    assert nearest(spans, 150) == 150
    assert nearest(spans, 300) == 400                           # à égale distance : après
    assert nearest(spans, 260) == 200
    assert nearest([], 10) is None


def test_human_windows_intersection():
    human = parse_windows(["09:00-21:00"])
    assert intersect(WINDOWS, human) == [(720, 840), (1080, 1260)]

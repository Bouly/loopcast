"""Créneaux de publication d'une journée : où placer n posts, de façon déterministe et testable.

Tout est en minutes depuis minuit, heure locale du compte. Le principe :
1. les plages libres = créneaux du réglage, privés du passé et du voisinage (± écart minimal) des posts
   déjà prévus ;
2. répartition : un post par créneau d'abord (matin, midi, soir), puis là où il reste le plus de place ;
3. placement : au milieu de sa part de créneau, avec un léger décalage aléatoire tiré d'un générateur
   seedé par (compte, date), puis ajusté pour garantir l'écart minimal.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

_INF = 10 ** 9


@dataclass(frozen=True)
class Span:
    start: int
    end: int            # inclus
    group: int = 0      # le créneau du réglage d'où vient cette plage (pour répartir matin / midi / soir)

    @property
    def length(self) -> int:
        return self.end - self.start


def free_spans(windows: list[tuple[int, int]], *, not_before: int | None = None, taken: list[int] = (),
               gap: int = 0) -> list[Span]:
    """Les plages où un nouveau post peut aller : dans `windows`, pas avant `not_before`, et à au moins
    `gap` minutes de chaque post de `taken`."""
    spans = [Span(s, e, i) for i, (s, e) in enumerate(sorted(windows))]
    if not_before is not None:
        spans = [Span(max(s.start, not_before), s.end, s.group) for s in spans if s.end >= not_before]
    for t in taken:
        if gap <= 0:
            continue
        lo, hi = t - gap, t + gap                    # interdit : ]lo, hi[
        out = []
        for s in spans:
            if s.end <= lo or s.start >= hi:
                out.append(s)
                continue
            if s.start <= lo:
                out.append(Span(s.start, lo, s.group))
            if s.end >= hi:
                out.append(Span(hi, s.end, s.group))
        spans = out
    return sorted(spans, key=lambda s: (s.start, s.end))


def group_load(windows: list[tuple[int, int]], minutes: list[int]) -> dict[int, int]:
    """Combien de posts déjà prévus dans chaque créneau du réglage (le plus proche si hors créneau)."""
    load: dict[int, int] = {}
    ordered = sorted(windows)
    for m in minutes:
        if not ordered:
            break
        best = min(range(len(ordered)), key=lambda i: 0 if ordered[i][0] <= m <= ordered[i][1]
                   else min(abs(m - ordered[i][0]), abs(m - ordered[i][1])))
        load[best] = load.get(best, 0) + 1
    return load


def place(spans: list[Span], n: int, gap: int, rng: random.Random, jitter: int = 20,
          load: dict[int, int] | None = None) -> list[int]:
    """Jusqu'à `n` minutes dans `spans`, espacées d'au moins `gap`. Moins si ça ne tient pas."""
    spans = sorted(spans, key=lambda s: (s.start, s.end))
    if n <= 0 or not spans:
        return []
    load = dict(load or {})
    counts = [0] * len(spans)
    for _ in range(n):
        order = sorted(range(len(spans)), key=lambda j: (
            load.get(spans[j].group, 0),                          # le créneau le moins chargé d'abord
            -(spans[j].length / (counts[j] + 1)),                 # puis celui où il reste le plus de place
            -j,                                                   # à égalité, le plus tard (le soir)
        ))
        for j in order:
            counts[j] += 1
            if _earliest(spans, counts, gap) is not None:
                load[spans[j].group] = load.get(spans[j].group, 0) + 1
                break
            counts[j] -= 1
        else:
            break                                                 # plus rien ne tient

    slots = [(j, i) for j in range(len(spans)) for i in range(counts[j])]
    if not slots:
        return []
    earliest = _earliest(spans, counts, gap)
    latest = _latest(spans, counts, gap)
    out: list[int] = []
    prev = -_INF
    for s, (j, i) in enumerate(slots):
        span, k = spans[j], counts[j]
        share = span.length / k
        spread = min(float(jitter), share / 2)
        ideal = round(span.start + (i + 0.5) * share + rng.uniform(-spread, spread))
        lo = max(earliest[s], prev + gap)
        t = min(max(ideal, lo), latest[s])
        out.append(t)
        prev = t
    return out


def _earliest(spans: list[Span], counts: list[int], gap: int) -> list[int] | None:
    out, prev = [], -_INF
    for j, k in enumerate(counts):
        for _ in range(k):
            t = max(spans[j].start, prev + gap)
            if t > spans[j].end:
                return None
            out.append(t)
            prev = t
    return out


def _latest(spans: list[Span], counts: list[int], gap: int) -> list[int]:
    out, nxt = [], _INF
    for j in reversed(range(len(counts))):
        for _ in range(counts[j]):
            t = min(spans[j].end, nxt - gap)
            out.append(t)
            nxt = t
    return list(reversed(out))


def nearest(spans: list[Span], minute: int) -> int | None:
    """Le point libre le plus proche de `minute`, de préférence après."""
    best: tuple[int, int, int] | None = None
    for s in spans:
        if s.start <= minute <= s.end:
            return minute
        cand = s.start if s.start > minute else s.end
        key = (abs(cand - minute), 0 if cand > minute else 1, cand)
        if best is None or key < best:
            best = key
    return best[2] if best else None


def rng_for(account_id: str, day_iso: str) -> random.Random:
    """Générateur seedé par (compte, date) : la même journée donne toujours les mêmes créneaux."""
    return random.Random(f"loopcast:{account_id}:{day_iso}")

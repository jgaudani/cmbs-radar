"""Scores every live loan with one set of assumptions: the scoring job
writes the result, the api computes it in memory for scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import engine
from .assumptions import Assumptions
from .load import Loader


@dataclass(slots=True)
class Scored:
    score: engine.Score
    prev_period: engine.Score | None = None  # None for a loan's first report
    changes: list[str] = field(default_factory=list)
    group: engine.Group | None = None  # split loan held by several trusts


def score_universe(ld: Loader, a: Assumptions, trusts: list[str] | None = None) -> list[Scored]:
    out: list[Scored] = []
    keys: list[str] = []
    for t in trusts if trusts is not None else ld.trusts():
        for h in ld.trust(t):
            s = Scored(score=engine.score_latest(h, a))
            if len(h.observations) >= 2:
                s.prev_period = engine.score_at(h, len(h.observations) - 2, a)
                s.changes = engine.changes(s.prev_period, s.score, a)
            s.score.whole_loan_key = engine.whole_loan_key(h, s.score)
            out.append(s)
            keys.append(s.score.whole_loan_key)
    # Split loans: one primary row per whole loan across trusts.
    groups = engine.consolidate_groups([s.score for s in out], keys)
    for s in out:
        s.group = groups.get(s.score.whole_loan_key)
    return out

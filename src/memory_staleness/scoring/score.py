"""The staleness scorer.

## Why the score does not include retrieval frequency

The project spec sketched the formula as ``age x volatility x retrieval frequency``. That is
not what this module implements, and the difference is deliberate.

Multiplying retrieval into the score collapses the two outcomes the tool exists to tell
apart. A memory that is very old, very volatile, and *never retrieved* would score near
zero — so it could never reach the "high staleness, never retrieved, safe to forget" branch,
because the low retrieval term is what made the score low in the first place. The branch
would be unreachable by construction.

So the two quantities are kept orthogonal:

- **score** answers *"how likely is this fact to have gone stale?"* — a function of age,
  fact-type volatility, and supersession. Nothing else.
- **retrieval_component** answers *"how exposed are we if it has?"* — a function of how much
  the memory is actually used.

The verdict is the product of the two questions, not of the two numbers. This keeps
``FORGET`` reachable and keeps the score meaningful on its own, which matters because a
reviewer will want to sort by it.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from memory_staleness.types import (
    MemoryEntry,
    StalenessScore,
    Supersession,
    Verdict,
)
from memory_staleness.volatility import VolatilityTable, load_table

REVERIFY_THRESHOLD = 0.5
"""Staleness at or above which a memory is actionable.

0.5 is exactly one half-life by construction, which makes the threshold interpretable: "this
fact is as old as the age at which we assume even odds of staleness for its type." Tunable,
and the tuning is visible in the manifest rather than buried in a magic number.
"""

SUPERSESSION_WEIGHT = 0.6
"""How much of the remaining headroom a newer same-claim entry contributes.

Applied as ``score + (1 - score) * weight`` so supersession can never push a score past 1.0
and never *lowers* one. A newer entry about the same subject and predicate is strong evidence
the older one has been overtaken even when the two do not visibly disagree — which is the
precise case contradiction-based invalidation cannot see.
"""

_RETRIEVAL_SATURATION = 10.0
"""Retrievals at which exposure is ~0.5.

Exposure saturates rather than growing linearly: the difference between 0 and 5 retrievals is
meaningful, the difference between 500 and 505 is not.
"""


def age_component(age_days: float | None, half_life_days: float | None) -> float:
    """Staleness contributed by age alone, in ``[0, 1]``.

    Returns ``1 - 2 ** (-age / half_life)``, so the value is 0.5 at exactly one half-life and
    approaches 1.0 asymptotically. Immutable fact types (``half_life_days is None``) return
    0.0 at any age — a date of birth does not become more doubtful because it is old.
    """
    if age_days is None or half_life_days is None:
        return 0.0
    if age_days <= 0.0:
        return 0.0
    return 1.0 - 2.0 ** (-age_days / half_life_days)


def _retrieval_component(entry: MemoryEntry) -> float:
    """Exposure in ``[0, 1]``: how much damage a wrong answer here would do."""
    if entry.retrieval_count <= 0:
        return 0.0
    return entry.retrieval_count / (entry.retrieval_count + _RETRIEVAL_SATURATION)


def find_supersessions(entries: tuple[MemoryEntry, ...]) -> dict[str, Supersession]:
    """Map each memory_id to the newest entry that supersedes it, if any.

    Two entries supersede when they share a ``claim_key`` — the same subject and predicate —
    and one was written later. Whether their objects *contradict* is recorded but does not
    gate detection: the no-contradiction case is the one this project targets, and requiring
    disagreement here would reduce the tool to what Zep and Mem0 already do.

    Entries without a write timestamp cannot participate in either direction; there is no way
    to know which came first.
    """
    by_claim: dict[tuple[str, str], list[MemoryEntry]] = defaultdict(list)
    for entry in entries:
        if entry.provenance.written_at is not None:
            by_claim[entry.claim_key].append(entry)

    found: dict[str, Supersession] = {}
    for group in by_claim.values():
        if len(group) < 2:
            continue
        # Sorted by write time, then by id so that identical timestamps resolve deterministically
        # rather than by whatever order the adapter happened to yield.
        ordered = sorted(group, key=lambda e: (e.provenance.written_at, e.memory_id))
        newest = ordered[-1]
        for older in ordered[:-1]:
            found[older.memory_id] = Supersession(
                superseded_by=newest.memory_id,
                newer_written_at=newest.provenance.written_at,
                contradicts=older.object_.strip().lower() != newest.object_.strip().lower(),
            )
    return found


def score_entry(
    entry: MemoryEntry,
    *,
    as_of: dt.datetime,
    table: VolatilityTable,
    supersession: Supersession | None = None,
) -> StalenessScore:
    """Score one memory. Pure: no I/O, no clock read, no randomness."""
    exposure = _retrieval_component(entry)

    if not entry.provenance.assessable:
        # No write timestamp means no age, which means no staleness estimate. Reported as an
        # admission rather than folded into a default, because a store full of CANNOT_ASSESS
        # is itself the finding — it says the provenance is not being captured upstream.
        return StalenessScore(
            memory_id=entry.memory_id,
            verdict=Verdict.CANNOT_ASSESS,
            score=0.0,
            age_days=None,
            half_life_days=None,
            age_component=0.0,
            retrieval_component=exposure,
            supersession=supersession,
            reasons=("no write timestamp in provenance; age cannot be computed",),
        )

    age = entry.age_days(as_of)
    half_life = table.half_life(entry.fact_type)
    base = age_component(age, half_life)

    reasons: list[str] = []
    if half_life is None:
        reasons.append(
            f"fact type {entry.fact_type.value!r} does not decay with time; age contributes nothing"
        )
    else:
        reasons.append(
            f"{age:.0f}d old against a {half_life:.0f}d half-life for "
            f"{entry.fact_type.value!r} -> {base:.2f}"
        )

    score = base
    if supersession is not None:
        score = score + (1.0 - score) * SUPERSESSION_WEIGHT
        if supersession.contradicts:
            reasons.append(
                f"superseded by {supersession.superseded_by}, which visibly contradicts it "
                "(a contradiction detector would also catch this)"
            )
        else:
            reasons.append(
                f"superseded by {supersession.superseded_by} with no visible contradiction "
                "(the case contradiction detectors miss)"
            )

    score = min(1.0, max(0.0, score))

    if score < REVERIFY_THRESHOLD:
        verdict = Verdict.FRESH
    elif entry.retrieval_count > 0:
        verdict = Verdict.REVERIFY
        reasons.append(f"still retrieved ({entry.retrieval_count}x): confidently wrong and in use")
    else:
        verdict = Verdict.FORGET
        reasons.append("never retrieved: safe to forget rather than re-verify")

    return StalenessScore(
        memory_id=entry.memory_id,
        verdict=verdict,
        score=score,
        age_days=age,
        half_life_days=half_life,
        age_component=base,
        retrieval_component=exposure,
        supersession=supersession,
        reasons=tuple(reasons),
    )


def score_store(
    entries: tuple[MemoryEntry, ...],
    *,
    as_of: dt.datetime,
    table: VolatilityTable | None = None,
) -> tuple[StalenessScore, ...]:
    """Score every entry, detecting supersession across the whole set first.

    Results are returned in ``memory_id`` order rather than input order, so two audits of the
    same store produce byte-identical output regardless of how the adapter iterated.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    table = table or load_table()
    supersessions = find_supersessions(entries)
    scores = [
        score_entry(
            entry, as_of=as_of, table=table, supersession=supersessions.get(entry.memory_id)
        )
        for entry in entries
    ]
    return tuple(sorted(scores, key=lambda s: s.memory_id))


__all__ = [
    "REVERIFY_THRESHOLD",
    "SUPERSESSION_WEIGHT",
    "age_component",
    "find_supersessions",
    "score_entry",
    "score_store",
]

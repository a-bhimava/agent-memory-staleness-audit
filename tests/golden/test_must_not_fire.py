"""Specificity controls.

A staleness auditor that flags everything has perfect recall and zero worth. False staleness
is the failure mode that makes the tool unusable fastest — flagging a durable fact as expired
teaches a user to ignore the tool, and an ignored auditor is strictly worse than none, because
it costs review time and buys nothing.

So specificity is tested as hard as sensitivity, and these controls must stay clean.
"""

from __future__ import annotations

import pytest

from memory_staleness.scoring import score_entry
from memory_staleness.synth.generate import CaseKind
from memory_staleness.types import FactType, Verdict
from tests.conftest import make_entry


def test_recent_memories_do_not_fire(store, table, now):
    for case in store.cases:
        if case.kind is not CaseKind.CONTROL_FRESH:
            continue
        result = score_entry(case.entry, as_of=now, table=table)
        assert result.verdict is Verdict.FRESH, f"{case.entry.memory_id} fired on a fresh memory"


@pytest.mark.parametrize("age_days", [1000, 7000, 40000])
def test_immutable_facts_never_fire_at_any_age(age_days: float, table, now):
    """A date of birth does not become doubtful because it is old.

    This is the control an age-only scorer fails, and the reason the volatility table is the
    load-bearing part of the design rather than a nicety.
    """
    entry = make_entry(
        fact_type=FactType.DATE_OF_BIRTH,
        predicate="born_on",
        object_="1990-04-02",
        days_ago=age_days,
        retrieval_count=25,
    )
    result = score_entry(entry, as_of=now, table=table)
    assert result.verdict is Verdict.FRESH
    assert result.score == 0.0
    assert result.half_life_days is None


def test_missing_provenance_is_an_admission_not_a_guess(table, now):
    """CANNOT_ASSESS must be its own outcome. Defaulting it to FRESH would hide a store that
    is not capturing provenance at all; defaulting it to REVERIFY would flood the report."""
    result = score_entry(make_entry(days_ago=None, retrieval_count=9), as_of=now, table=table)
    assert result.verdict is Verdict.CANNOT_ASSESS
    assert result.age_days is None
    assert result.score == 0.0
    assert any("no write timestamp" in r for r in result.reasons)


def test_supersession_never_lowers_a_score(table, now):
    """The boost is applied to remaining headroom, so it is monotone by construction."""
    from memory_staleness.types import Supersession

    entry = make_entry(days_ago=300, retrieval_count=1)
    plain = score_entry(entry, as_of=now, table=table)
    boosted = score_entry(
        entry,
        as_of=now,
        table=table,
        supersession=Supersession(
            superseded_by="newer",
            newer_written_at=now,
            contradicts=False,
        ),
    )
    assert boosted.score >= plain.score
    assert boosted.score <= 1.0


def test_a_brand_new_memory_scores_zero(table, now):
    result = score_entry(make_entry(days_ago=0), as_of=now, table=table)
    assert result.score == 0.0


def test_score_never_leaves_the_unit_interval(store, table, now):
    for case in store.cases:
        result = score_entry(case.entry, as_of=now, table=table)
        assert 0.0 <= result.score <= 1.0
        assert 0.0 <= result.age_component <= 1.0
        assert 0.0 <= result.retrieval_component <= 1.0


def test_every_finding_carries_a_reason(store, table, now):
    """A score with no explanation cannot be argued with, and the failure this tool must
    avoid above all others is being confidently wrong about confident wrongness."""
    for case in store.cases:
        result = score_entry(case.entry, as_of=now, table=table)
        assert result.reasons, f"{case.entry.memory_id} produced a verdict with no reasoning"

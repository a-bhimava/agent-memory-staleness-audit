"""The four invariants documented in memory_staleness.types."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from memory_staleness.types import (
    FactType,
    FrozenDict,
    MemoryEntry,
    Provenance,
    StalenessScore,
    Verdict,
)
from tests.conftest import make_entry


def test_entries_are_immutable():
    entry = make_entry()
    with pytest.raises(ValidationError):
        entry.memory_id = "other"


def test_frozendict_blocks_the_mutable_field_hole():
    """model_config frozen=True freezes attribute assignment, not the objects attributes
    point at. Without FrozenDict, entry.extra["x"] = 1 would silently mutate evidence."""
    entry = make_entry()
    with pytest.raises(TypeError):
        entry.extra["injected"] = True  # type: ignore[index]


def test_age_is_derived_not_stored():
    """Invariant 2: storing age would let a record carry an age disagreeing with its own
    timestamp — the exact bug class this tool detects elsewhere."""
    assert "age_days" not in MemoryEntry.model_fields
    entry = make_entry(days_ago=10)
    assert entry.age_days(dt.datetime(2026, 8, 21, 12, 0, tzinfo=dt.UTC)) == pytest.approx(10.0)


def test_missing_provenance_is_representable_and_flagged():
    """Invariant 3: absence of provenance is load-bearing, not a defaulted zero."""
    assert Provenance().assessable is False
    assert make_entry(days_ago=None).age_days(dt.datetime.now(dt.UTC)) is None


def test_naive_timestamps_are_rejected_at_the_boundary():
    """Invariant 4: a naive datetime in a staleness calculation is an off-by-hours error
    waiting for a daylight-saving boundary."""
    with pytest.raises(ValidationError):
        Provenance(written_at=dt.datetime(2026, 1, 1))


def test_claim_key_is_case_and_whitespace_insensitive():
    a = make_entry(subject="Alice", predicate="Works_At")
    b = make_entry(subject=" alice ", predicate="works_at")
    assert a.claim_key == b.claim_key


def test_score_is_bounded():
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            StalenessScore(
                memory_id="m",
                verdict=Verdict.FRESH,
                score=bad,
                age_days=1.0,
                half_life_days=1.0,
                age_component=0.0,
                retrieval_component=0.0,
            )


def test_every_fact_type_is_a_plain_string_value():
    """FactType values are the keys in table.yaml; a non-str value would silently fail lookup."""
    for member in FactType:
        assert isinstance(member.value, str) and member.value == member.value.strip()


def test_frozendict_equality_and_hashing():
    assert FrozenDict({"a": 1}) == FrozenDict({"a": 1}) == {"a": 1}
    assert hash(FrozenDict({"a": 1, "b": 2})) == hash(FrozenDict({"b": 2, "a": 1}))

"""Shared fixtures.

Session-scoped because every object here is frozen, so sharing one instance across the whole
run is safe and keeps the suite fast.
"""

from __future__ import annotations

import datetime as dt

import pytest

from memory_staleness.synth import generate_store
from memory_staleness.synth.generate import REFERENCE_NOW, SyntheticStore
from memory_staleness.types import FactType, MemoryEntry, Provenance
from memory_staleness.volatility import VolatilityTable, load_table


@pytest.fixture(scope="session")
def table() -> VolatilityTable:
    """The shipped volatility table."""
    return load_table()


@pytest.fixture(scope="session")
def now() -> dt.datetime:
    """The generator's fixed clock. Tests must never read the wall clock."""
    return REFERENCE_NOW


@pytest.fixture(scope="session")
def store() -> SyntheticStore:
    """A balanced known-answer corpus: 6 of each case kind."""
    return generate_store(n_per_kind=6)


def make_entry(
    memory_id: str = "m1",
    *,
    subject: str = "alice",
    predicate: str = "works_at",
    object_: str = "Acme",
    fact_type: FactType = FactType.EMPLOYER,
    days_ago: float | None = 100.0,
    retrieval_count: int = 0,
    as_of: dt.datetime = REFERENCE_NOW,
) -> MemoryEntry:
    """Factory for one-off entries.

    ``days_ago=None`` produces an entry with no provenance, which is the CANNOT_ASSESS path.
    """
    written = None if days_ago is None else as_of - dt.timedelta(days=days_ago)
    return MemoryEntry(
        memory_id=memory_id,
        subject=subject,
        predicate=predicate,
        object=object_,
        fact_type=fact_type,
        provenance=Provenance(source=None if written is None else "test", written_at=written),
        retrieval_count=retrieval_count,
    )

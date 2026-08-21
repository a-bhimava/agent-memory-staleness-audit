"""The volatility table is data a reviewer signs off on, so it is validated like data."""

from __future__ import annotations

import pytest

from memory_staleness.types import FactType
from memory_staleness.volatility import load_table
from memory_staleness.volatility.loader import SCHEMA, UnknownFactTypeError
from memory_staleness.volatility.loader import load_table as _load


def test_table_declares_its_schema_version(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text("schema: wrong@9\nfact_types: {}\n")
    with pytest.raises(ValueError, match=SCHEMA):
        _load(bad)


def test_unknown_fact_type_is_fatal_not_ignored(tmp_path):
    """Falling through to the default half-life on a typo would mean every score for that
    type is computed against an assumption nobody checked."""
    bad = tmp_path / "t.yaml"
    bad.write_text(f"schema: {SCHEMA}\nfact_types:\n  employeer:\n    half_life_days: 1\n")
    with pytest.raises(UnknownFactTypeError, match="employeer"):
        _load(bad)


def test_every_row_states_its_basis(table):
    """A half-life with no stated basis cannot be argued with, so it cannot be reviewed."""
    for entry in table.entries:
        assert entry.basis.strip(), f"{entry.fact_type.value} has no basis recorded"


def test_immutable_types_have_no_half_life(table):
    for fact_type in (FactType.DATE_OF_BIRTH, FactType.BIRTHPLACE, FactType.IMMUTABLE_IDENTIFIER):
        assert table.half_life(fact_type) is None
        assert table.entry_for(fact_type).immutable


def test_volatile_types_are_ordered_sensibly(table):
    """Sanity ordering. Not a claim about the world, but a guard against an edit that swaps
    two rows and inverts the model without any test noticing."""
    assert table.half_life(FactType.ACCOUNT_BALANCE) < table.half_life(FactType.PROJECT_STATUS)
    assert table.half_life(FactType.PROJECT_STATUS) < table.half_life(FactType.JOB_TITLE)
    assert table.half_life(FactType.JOB_TITLE) < table.half_life(FactType.EMPLOYER)
    assert table.half_life(FactType.EMPLOYER) < table.half_life(FactType.RESIDENCE_CITY)


def test_unlisted_types_fall_back_to_the_documented_default(table):
    entry = table.entry_for(FactType.UNCLASSIFIED)
    assert entry.half_life_days == table.default_half_life_days
    assert entry.basis == table.default_basis


def test_table_records_the_digest_of_the_file_it_came_from(table):
    """Changing a half-life changes every score in an audit, so a result that does not name
    its table is not reproducible."""
    assert table.source_sha256.startswith("sha256:")
    assert load_table().source_sha256 == table.source_sha256

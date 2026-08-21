"""The three invariants documented in memory_staleness.ids."""

from __future__ import annotations

import datetime as dt
import math

import pytest

from memory_staleness.ids import (
    canonical_json,
    content_id,
    derive_seed,
    portable_json,
    sha256_bytes,
)


def test_canonical_json_sorts_keys_regardless_of_insertion_order():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_floats_are_hex_in_hash_form_and_decimal_on_the_wire():
    value = {"x": 0.1 + 0.2}
    assert "0x1." in canonical_json(value)
    assert "0.30000000000000004" in portable_json(value)


def test_float_precision_survives_the_hash_form():
    """The reason floats are hex: decimal rounding would collide these two."""
    assert canonical_json(0.1 + 0.2) != canonical_json(0.3)


def test_signed_zero_is_normalized():
    assert canonical_json(-0.0) == canonical_json(0.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_rejected(bad: float):
    """Not left to json.dumps: NaN would otherwise serialize as the literal string "nan",
    a garbage value that looks like data."""
    assert not math.isfinite(bad)
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json(bad)


def test_datetimes_normalize_across_timezones():
    """Same instant, different offsets, one hash. Otherwise two adapters exporting the same
    memory in different timezones would produce different ids for it."""
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    assert canonical_json(dt.datetime(2026, 1, 1, 5, 30, tzinfo=ist)) == canonical_json(
        dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.UTC)
    )


def test_naive_datetimes_are_rejected():
    """Guessing a timezone inside a hash function makes an off-by-hours error permanent."""
    with pytest.raises(ValueError, match="naive datetime"):
        canonical_json(dt.datetime(2026, 1, 1))


def test_bool_does_not_collapse_into_int():
    assert canonical_json(True) != canonical_json(1)


def test_content_id_and_sha256_are_tagged_by_algorithm():
    assert content_id({"a": 1}).startswith("blake2b128:")
    assert sha256_bytes(b"x").startswith("sha256:")


def test_derive_seed_is_deterministic_and_path_dependent():
    assert derive_seed(1729, "a", 1) == derive_seed(1729, "a", 1)
    assert derive_seed(1729, "a", 1) != derive_seed(1729, "a", 2)
    assert derive_seed(1729, "a", 1) != derive_seed(1730, "a", 1)


def test_derive_seed_parts_cannot_be_confused_by_concatenation():
    """The unit separator exists so ("ab","c") and ("a","bc") stay distinct."""
    assert derive_seed(1729, "ab", "c") != derive_seed(1729, "a", "bc")


def test_derive_seed_fits_63_bits():
    for i in range(200):
        assert 0 <= derive_seed(1729, "x", i) < (1 << 63)
